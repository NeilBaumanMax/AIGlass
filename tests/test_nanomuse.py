import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import requests

from backend.nanomuse import NanoMuse, Cancelled, NanoMuseError
from backend.runtime import Runtime
from backend.speech import Speech, PROMPTS


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
        with patch('backend.nanomuse.time.sleep'):
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
        with patch('backend.nanomuse.time.sleep'), self.assertRaises(Cancelled):
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
        self.speech.prompts = {name: b'test-wav' for name in PROMPTS}
        self.speech.connect()
        self.speech.pending.clear()
        self.agent = self.speech.agent = Mock()
        self.agent.snapshot.return_value = {'provider': 'nanomuse', 'approval': None}
        self.speech.handle('嗨，Edith')
        self.speech.agent_cancel = threading.Event()

    def test_phone_page_does_not_require_glasses_camera(self):
        with patch('backend.speech.threading.Thread') as thread:
            self.speech.handle('看看手机页面并读出来')
        args = thread.call_args.kwargs['args']
        self.assertIsNone(args[2])
        self.assertNotIn('当前摄像头没有画面', [item['text'] for item in self.speech.pending])

    def test_computer_view_is_distinct_from_camera_view(self):
        with patch('backend.speech.threading.Thread') as thread:
            self.speech.handle('看看电脑')
        self.assertIsNone(thread.call_args.kwargs['args'][2])
        self.runtime.current_frame = Mock(return_value=b'fresh-camera-jpeg')
        with patch('backend.speech.threading.Thread') as thread:
            self.speech.handle('看看眼前的电脑')
        self.assertEqual(thread.call_args.kwargs['args'][2], b'fresh-camera-jpeg')

    def test_nanomuse_answer_uses_tts_without_direct_chat(self):
        self.agent.ask.return_value = '手机页面的实际结果'
        with patch('backend.qwen.ask') as direct, patch('backend.tts.synthesize', return_value=b'wav') as synth:
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
        with patch('backend.speech.threading.Thread') as thread:
            self.speech.handle('确认执行')
        self.assertEqual(thread.call_args.kwargs['args'], ('a1', True, generation))

    def test_urgent_walkguide_alert_cancels_phone_task(self):
        self.speech.alert('前方有障碍')
        self.assertTrue(self.speech.agent_cancel.is_set())
        self.assertEqual(self.speech.active['text'], PROMPTS['obstacle'])

    def test_microphone_disconnect_requests_cancel(self):
        self.speech.seen = time.monotonic() - 6
        self.speech._agent_event({'stage': 'heartbeat'}, self.speech.generation)
        self.assertTrue(self.speech.agent_cancel.is_set())

    def test_tts_failure_does_not_run_phone_task_again(self):
        self.agent.ask.return_value = '已完成的真实结果'
        with patch('backend.tts.synthesize', side_effect=RuntimeError('tts unavailable')):
            self.speech._answer('读页面', b'', None, [], self.speech.generation)
        self.agent.ask.assert_called_once()
        self.assertTrue(any(e['text'] == 'Edith · 已完成的真实结果' for e in self.runtime.events))

    def start_answer(self, text):
        with patch('backend.speech.threading.Thread') as thread:
            self.speech.handle(text)
        return thread.call_args.kwargs['args']

    def test_old_cancelled_worker_cannot_clear_new_tasks_busy_state(self):
        first = self.start_answer('第一项任务')
        second = self.start_answer('第二项任务')
        self.assertTrue(first[-1].is_set())
        self.agent.ask.side_effect = Cancelled()
        self.speech._answer(*first)
        self.speech.pending.clear()
        self.speech.active = None
        with patch('backend.speech.time.monotonic', return_value=self.speech.awake_until + 20) as clock:
            self.speech.seen = clock.return_value
            self.assertIsNone(self.speech.poll(self.speech.session, False, None))
            self.assertTrue(self.speech.snapshot()['awake'])
            self.assertIsNone(self.speech.snapshot()['idle_remaining'])
        self.assertTrue(self.speech.busy)
        self.assertFalse(second[-1].is_set())

    def test_reply_in_tts_cannot_leak_into_replacement_task(self):
        first = self.start_answer('第一项任务')
        self.agent.ask.return_value = '旧任务结果'
        def synthesize(_):
            self.start_answer('第二项任务')
            return b'old-wav'
        with patch('backend.tts.synthesize', side_effect=synthesize):
            self.speech._answer(*first)
        self.assertTrue(self.speech.busy)
        self.assertNotIn('旧任务结果', [p['text'] for p in self.speech.pending])
        self.assertFalse(self.speech.history)

    def test_rewake_cancels_task_and_prioritizes_ack_over_old_audio(self):
        args = self.start_answer('读页面')
        self.speech.poll(self.speech.session, False, None)
        self.speech.enqueue('旧播报', b'old-wav')
        self.agent.snapshot.return_value['approval'] = {'approval_id': 'a1'}
        with patch('backend.speech.threading.Thread') as thread:
            self.speech.handle('嗨，Edith')
        thread.assert_not_called()
        self.assertTrue(args[-1].is_set())
        self.assertFalse(self.speech.busy)
        self.assertEqual(self.speech.poll(self.speech.session, False, None)['text'], '我在，请说')
        self.assertFalse(self.speech.pending)
        self.agent.approve.assert_not_called()

    def test_long_task_and_tts_wait_until_playback_then_start_eight_seconds(self):
        clock = [100.0]
        speech = self.speech
        speech.pending.clear()
        speech.active = None
        def poll_at(now, playing=False, done=None):
            clock[0] = now
            speech.seen = now
            return speech.poll(speech.session, playing, done)
        def wait_task(*_):
            for now in (109, 130, 160):
                command = poll_at(now)
                if command:
                    self.assertNotEqual(command['text'], '对话结束')
                    poll_at(now, done=command['id'])
                self.assertTrue(speech.snapshot()['awake'])
                self.assertIsNone(speech.snapshot()['idle_remaining'])
            return '任务结果'
        def wait_tts(_):
            poll_at(180)
            self.assertTrue(speech.busy)
            return b'wav'
        self.agent.ask.side_effect = wait_task
        with patch('backend.speech.time.monotonic', side_effect=lambda: clock[0]):
            speech.seen = 100
            speech.awake_until = 108
            args = self.start_answer('耗时任务')
            with patch('backend.tts.synthesize', side_effect=wait_tts):
                speech._answer(*args)
            answer = poll_at(180)
            self.assertEqual(answer['text'], '任务结果')
            poll_at(195, playing=True)
            self.assertIsNone(speech.snapshot()['idle_remaining'])
            poll_at(200, done=answer['id'])
            self.assertEqual(speech.snapshot()['idle_remaining'], 8)
            self.assertIsNone(poll_at(207))
            self.assertEqual(poll_at(208)['text'], '对话结束')

    def test_confirmation_is_accepted_after_idle_deadline_during_task(self):
        self.speech.pending.clear()
        self.speech.active = None
        self.speech.awake_until = time.monotonic() - 20
        self.speech.busy = True
        self.agent.snapshot.return_value['approval'] = {'approval_id': 'a1'}
        with patch('backend.speech.threading.Thread') as thread:
            self.speech.handle('确认执行')
        self.assertEqual(thread.call_args.kwargs['args'], ('a1', True, self.speech.generation))

    def test_wait_notice_is_rate_limited_and_does_not_overlap_approval(self):
        with patch('backend.speech.time.monotonic', return_value=100):
            self.speech.seen = 100
            self.speech.awake_until = 108
            args = self.start_answer('耗时任务')
        self.assertEqual(self.speech.pending[-1]['text'], '正在处理，请稍候')
        self.speech.active = None
        self.speech.pending.clear()
        for now, expected in ((129, 0), (130, 1), (131, 1)):
            with patch('backend.speech.time.monotonic', return_value=now):
                self.speech.seen = now
                self.speech._agent_event({'stage': 'heartbeat'}, args[-2])
            self.assertEqual(len(self.speech.pending), expected)
        self.assertEqual(self.speech.pending[-1]['text'], '任务仍在执行，请稍候')
        self.speech.pending.clear()
        self.agent.snapshot.return_value['approval'] = {'approval_id': 'a1'}
        with patch('backend.speech.time.monotonic', return_value=170):
            self.speech.seen = 170
            self.speech._agent_event({'stage': 'heartbeat'}, args[-2])
        self.assertFalse(self.speech.pending)

    def test_cancel_during_tts_discards_answer_even_without_generation_change(self):
        args = self.start_answer('读页面')
        self.agent.ask.return_value = '旧任务结果'
        def synthesize(_):
            args[-1].set()
            return b'old-wav'
        with patch('backend.tts.synthesize', side_effect=synthesize):
            self.speech._answer(*args)
        self.assertNotIn('旧任务结果', [p['text'] for p in self.speech.pending])

    def test_old_worker_error_cannot_play_over_new_wake(self):
        args = self.start_answer('读页面')
        def ask(*_):
            self.speech.handle('嗨，Edith')
            raise NanoMuseError('旧任务报错')
        self.agent.ask.side_effect = ask
        self.speech._answer(*args)
        self.assertEqual(self.speech.poll(self.speech.session, False, None)['text'], '我在，请说')
        self.assertFalse(self.speech.pending)
