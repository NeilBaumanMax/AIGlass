import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import requests

from nanomuse import NanoMuse, Cancelled, NanoMuseError
from runtime import Runtime
from speech import Speech


class NanoMuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = NanoMuse(state_file=Path(self.temp.name) / 'turn.json', monitor=False)

    def test_lost_post_response_queries_result_without_replaying_action(self):
        calls = []
        def http(method, path, body=None):
            calls.append((method, path, body))
            if method == 'POST':
                raise requests.ConnectionError('response lost')
            return {'state': 'completed', 'text': '页面的真实内容'}
        self.client._http = http
        self.assertEqual(self.client.ask('读一下手机页面', None, lambda _: None, threading.Event()), '页面的真实内容')
        self.assertEqual(sum(c[0] == 'POST' for c in calls), 1)
        self.assertFalse(self.client.state_file.exists())

    def test_partial_text_is_not_spoken_as_final_and_approval_is_scoped(self):
        step = 0
        events = []
        def http(method, path, body=None):
            nonlocal step
            if path == '/v1/approve':
                self.assertEqual(body['approval_id'], 'a1')
                self.assertIs(body['allow'], True)
                return {'ok': True}
            if method == 'POST':
                return {'state': 'accepted'}
            step += 1
            return {'state': 'completed', 'text': '完成'} if step > 1 else {
                'state': 'accepted', 'events': [
                    {'stage': 'text', 'text': '还没执行的草稿', 'partial': True},
                    {'stage': 'approval', 'approval_id': 'a1', 'preview': '打开应用', 'timeout': 20}]}
        def event(item):
            events.append(item)
            if item['stage'] == 'approval':
                self.assertFalse(self.client.approve('old-id', True))
                self.assertTrue(self.client.approve('a1', True))
        self.client._http = http
        with patch('nanomuse.time.sleep'):
            self.client.ask('打开应用', None, event, threading.Event())
        self.assertFalse(any(e['stage'] == 'text' for e in events))
        self.assertFalse(self.client.approve('a1', True))

    def test_barge_in_cancels_exact_turn_and_waits_for_terminal(self):
        calls, cancel = [], threading.Event()
        def http(method, path, body=None):
            calls.append((method, path, body))
            if path == '/v1/stop':
                self.assertEqual(body, self.client.current)
                return {'stopped': True}
            if method == 'POST':
                return {'state': 'accepted'}
            if any(c[1] == '/v1/stop' for c in calls):
                return {'state': 'cancelled'}
            return {'state': 'accepted', 'events': [{'stage': 'tool', 'name': 'delegate'}]}
        self.client._http = http
        with patch('nanomuse.time.sleep'), self.assertRaises(Cancelled):
            self.client.ask('打开应用', None, lambda e: cancel.set() if e['stage'] == 'tool' else None, cancel)
        self.assertFalse(self.client.state_file.exists())
        self.assertEqual(sum(c[1] == '/v1/stop' for c in calls), 1)

    def test_uncertain_execution_is_kept_and_never_retried(self):
        def offline(method, path, body=None):
            raise requests.ConnectionError()
        self.client._http = Mock(side_effect=offline)
        with self.assertRaises(NanoMuseError):
            self.client.ask('打开应用', None, lambda _: None, threading.Event())
        self.assertTrue(self.client.state_file.exists())
        self.client._http.reset_mock()
        with self.assertRaises(NanoMuseError):
            self.client.ask('新任务', None, lambda _: None, threading.Event())
        self.assertTrue(all(c.args[0] == 'GET' for c in self.client._http.call_args_list))

    def test_expired_approval_cannot_be_sent(self):
        self.client.current = {'conversation': 'x', 'turn_id': 'y'}
        self.client.approval = {'approval_id': 'a1', 'expires': time.monotonic() - 1}
        self.client._http = Mock()
        self.assertFalse(self.client.approve('a1', True))
        self.client._http.assert_not_called()

    def test_bridge_must_be_local(self):
        for url in ('http://example.com:18765', 'http://127.0.0.1@evil.com', 'http://127.0.0.1:18765/path'):
            with self.assertRaises(ValueError):
                NanoMuse(url=url, monitor=False)


class NanoMuseSpeechTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.speech = Speech(self.runtime)
        self.speech.connect()
        self.speech.pending.clear()
        self.agent = self.speech.agent = Mock()
        self.agent.snapshot.return_value = {'provider': 'nanomuse', 'approval': None}
        self.speech.agent_cancel = threading.Event()
        self.speech.handle('嗨，Edith')

    def test_phone_page_does_not_require_glasses_camera(self):
        with patch('speech.threading.Thread') as thread:
            self.speech.handle('看看手机页面并读出来')
        args = thread.call_args.kwargs['args']
        self.assertIsNone(args[2])
        self.assertNotIn('当前摄像头没有画面', [item['text'] for item in self.speech.pending])

    def test_computer_view_is_distinct_from_camera_view(self):
        with patch('speech.threading.Thread') as thread:
            self.speech.handle('看看电脑')
        self.assertIsNone(thread.call_args.kwargs['args'][2])
        self.runtime.current_frame = Mock(return_value=b'fresh-camera-jpeg')
        with patch('speech.threading.Thread') as thread:
            self.speech.handle('看看眼前的电脑')
        self.assertEqual(thread.call_args.kwargs['args'][2], b'fresh-camera-jpeg')

    def test_nanomuse_answer_uses_tts_without_direct_chat(self):
        self.agent.ask.return_value = '手机页面的实际结果'
        with patch('qwen.ask') as direct, patch('tts.synthesize', return_value=b'wav') as synth:
            self.speech._answer('读手机页面', b'pcm', None, [], self.speech.generation)
        direct.assert_not_called()
        synth.assert_called_once_with('手机页面的实际结果')
        self.assertEqual(self.speech.pending[-1]['text'], '手机页面的实际结果')

    def test_approval_reply_barge_in_preserves_pending_task(self):
        self.agent.snapshot.return_value['approval'] = {'approval_id': 'a1', 'expires': time.monotonic() + 20}
        self.speech.busy = True
        generation = self.speech.generation
        self.speech.interrupt()
        self.assertEqual(self.speech.generation, generation)
        self.assertFalse(self.speech.agent_cancel.is_set())
        self.assertTrue(self.speech.busy)
        with patch('speech.threading.Thread') as thread:
            self.speech.handle('确认执行')
        self.assertEqual(thread.call_args.kwargs['args'], ('a1', True, generation))

    def test_urgent_walkguide_alert_cancels_phone_task(self):
        self.speech.alert('前方有障碍')
        self.assertTrue(self.speech.agent_cancel.is_set())
        self.assertEqual(self.speech.active['text'], '前方有障碍')

    def test_microphone_disconnect_requests_cancel(self):
        self.speech.seen = time.monotonic() - 6
        self.speech._agent_event({'stage': 'heartbeat'}, self.speech.generation)
        self.assertTrue(self.speech.agent_cancel.is_set())

    def test_tts_failure_does_not_run_phone_task_again(self):
        self.agent.ask.return_value = '已完成的真实结果'
        with patch('tts.synthesize', side_effect=RuntimeError('tts unavailable')):
            self.speech._answer('读页面', b'', None, [], self.speech.generation)
        self.agent.ask.assert_called_once()
        self.assertTrue(any(e['text'] == 'Edith · 已完成的真实结果' for e in self.runtime.events))
