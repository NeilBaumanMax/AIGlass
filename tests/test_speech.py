import time
import unittest
from unittest.mock import Mock, patch

from app import create_app
from runtime import Runtime
from speech import Speech
from vision import DIRECTION_MESSAGES
from guidance import CUES


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.speech = Speech(self.runtime)
        self.session = self.speech.connect()
        self.speech.pending.clear()

    def test_sleeping_ignores_commands_and_wake_changes_mode(self):
        self.speech.handle("切换室外模式")
        self.assertEqual(self.runtime.mode, "indoor")
        self.speech.handle("嗨，Edith")
        self.speech.handle("切换室外模式")
        self.assertEqual(self.runtime.mode, "outdoor")
        self.assertTrue(self.speech.snapshot()["awake"])
        self.speech.handle("结束对话")
        self.assertFalse(self.speech.snapshot()["awake"])

    def test_playback_ack_does_not_remove_new_urgent_message(self):
        self.speech.prompt("wake")
        first = self.speech.poll(self.session, False, None)
        self.speech.alert("前方有障碍")
        second = self.speech.poll(self.session, False, first["id"])
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(second["text"], "前方有障碍")
        self.assertIsNone(self.speech.poll(self.session, False, second["id"]))

    def test_reconnect_invalidates_old_session(self):
        old = self.session
        self.speech.connect()
        with self.assertRaises(ValueError):
            self.speech.poll(old, False, None)

    def test_direction_does_not_interrupt_dialog_but_stop_does(self):
        self.speech.handle('嗨，Edith')
        wake = self.speech.poll(self.session, False, None)
        self.speech.alert(DIRECTION_MESSAGES['left'])
        self.assertEqual(self.speech.active['id'], wake['id'])
        self.assertFalse(self.speech.pending)
        self.speech.alert(DIRECTION_MESSAGES['stop'])
        stop = self.speech.poll(self.session, True, wake['id'])
        self.assertNotEqual(stop['id'], wake['id'])
        self.assertEqual(stop['text'], CUES['stop'].text)

    def test_idle_direction_is_spoken_without_waking_dialog(self):
        self.speech.alert(DIRECTION_MESSAGES['right'])
        self.assertEqual(self.speech.poll(self.session, False, None)['text'], CUES['right'].text)
        self.assertFalse(self.speech.snapshot()['awake'])

    def test_stale_frame_not_sent_to_qwen(self):
        self.speech.handle("嗨，Edith")
        with patch("qwen.ask") as ask:
            self.speech.handle("看看当前画面")
            ask.assert_not_called()
        self.assertEqual(self.speech.pending[-1]["text"], "当前摄像头没有画面")

    def test_auth_and_validation(self):
        client = create_app(self.runtime, self.speech, "test-only-token").test_client()
        self.assertEqual(client.post("/device/session").status_code, 401)
        header = {"X-Device-Token": "test-only-token"}
        self.assertEqual(client.post("/device/session", headers=header).status_code, 200)
        self.assertEqual(client.post("/device/audio", headers=header, data=b"1").status_code, 409)
        self.assertEqual(client.post("/device/poll", headers=header, json={"session": "old"}).status_code, 409)

    def test_poll_transfers_audio_only_when_command_changes(self):
        client = create_app(self.runtime, self.speech, "test-only-token").test_client()
        header = {"X-Device-Token": "test-only-token"}
        self.speech.prompt("wake")
        first = client.post("/device/poll", headers=header,
                            json={"session": self.session}).json["command"]
        self.assertIn("wav", first)
        second = client.post("/device/poll", headers=header,
                             json={"session": self.session, "current": first["id"]}).json["command"]
        self.assertEqual(second["id"], first["id"])
        self.assertNotIn("wav", second)
        self.speech.alert("前方有障碍")
        urgent = client.post("/device/poll", headers=header,
                             json={"session": self.session, "current": first["id"]}).json["command"]
        self.assertIn("wav", urgent)
        self.assertNotEqual(urgent["id"], first["id"])

    def test_late_cloud_reply_cannot_overwrite_urgent_alert(self):
        generation = self.speech.generation
        def delayed_reply(*args):
            self.speech.alert("前方有障碍")
            return "已经失效的回复", b"wav"
        with patch("qwen.ask", side_effect=delayed_reply):
            self.speech._answer("问题", b"", None, [], generation)
        self.assertFalse(self.speech.history)
        self.assertFalse(self.speech.pending)
        self.assertEqual(self.speech.active["text"], "前方有障碍")
        self.assertFalse(self.speech.busy)

    def test_eight_second_idle_timeout_starts_after_playback(self):
        self.speech.seen = 100
        with patch("speech.time.monotonic", return_value=100):
            self.speech.handle("嗨，Edith")
            wake = self.speech.poll(self.session, False, None)
        for now in (104, 108):
            with patch("speech.time.monotonic", return_value=now):
                self.speech.poll(self.session, True, None)
                self.assertTrue(self.speech.snapshot()["awake"])
                self.assertIsNone(self.speech.snapshot()["idle_remaining"])
        with patch("speech.time.monotonic", return_value=109):
            self.speech.poll(self.session, False, wake["id"])
            self.assertEqual(self.speech.snapshot()["idle_remaining"], 8)
        with patch("speech.time.monotonic", return_value=113):
            self.assertIsNone(self.speech.poll(self.session, False, None))
            self.assertTrue(self.speech.snapshot()["awake"])
        with patch("speech.time.monotonic", return_value=117):
            timeout = self.speech.poll(self.session, False, None)
            self.assertEqual(timeout["text"], "对话结束")
            self.assertFalse(self.speech.snapshot()["awake"])
            with patch("qwen.ask") as ask:
                self.speech.handle("介绍一下你自己")
                ask.assert_not_called()

    def test_waiting_for_cloud_does_not_expire_dialog(self):
        self.speech.seen = 100
        self.speech.awake_until = 90
        self.speech.busy = True
        with patch("speech.time.monotonic", return_value=100):
            self.assertIsNone(self.speech.poll(self.session, False, None))
            self.assertTrue(self.speech.snapshot()["awake"])
        self.assertEqual(self.speech.awake_until, 90)

    def test_new_partial_speech_extends_wait_but_stale_partial_does_not(self):
        self.speech.seen = self.speech.mic_seen = 100
        self.speech.seq = 0
        self.speech.awake_until = 101
        self.speech.model = object()
        self.speech.recognizer = Mock()
        self.speech.recognizer.AcceptWaveform.return_value = False
        self.speech.recognizer.PartialResult.return_value = '{"partial":"介绍 一下"}'
        with patch("speech.time.monotonic", return_value=100):
            self.speech.ingest(self.session, 1, bytes(6400))
            self.assertEqual(self.speech.awake_until, 108)
        with patch("speech.time.monotonic", return_value=101):
            self.speech.ingest(self.session, 2, bytes(6400))
            self.assertEqual(self.speech.awake_until, 108)

    def test_dedicated_keyword_detector_wakes_without_asr_transcript(self):
        self.speech.seen = self.speech.mic_seen = 100
        self.speech.seq = 0
        self.speech.wake_detector = Mock()
        self.speech.wake_detector.accept.side_effect = [False, True]
        with patch("speech.time.monotonic", return_value=100):
            self.speech.ingest(self.session, 1, bytes(6400))
            self.assertFalse(self.speech.snapshot()["awake"])
        with patch("speech.time.monotonic", return_value=100.2):
            self.speech.ingest(self.session, 2, bytes(6400))
            self.assertTrue(self.speech.snapshot()["awake"])
            self.assertEqual(self.speech.pending[-1]["text"], "我在，请说")
            self.assertIsNone(self.speech.recognizer)

    def test_duplex_speech_interrupts_playback_and_invalidates_pending_answer(self):
        self.speech.seen = self.speech.mic_seen = 100
        self.speech.seq = 0
        self.speech.awake_until = 108
        self.speech.busy = self.speech.playing = True
        self.speech.active = {'id': 99, 'text': 'old answer'}
        self.speech.aec = Mock()
        self.speech.aec.process.return_value = b'\x90\x01\x70\xfe' * 1600
        self.speech.model = object()
        self.speech.recognizer = Mock()
        self.speech.recognizer.AcceptWaveform.return_value = False
        self.speech.recognizer.PartialResult.return_value = '{"partial":"换个 话题"}'
        generation = self.speech.generation
        with patch('speech.time.monotonic', return_value=100):
            self.speech.ingest(self.session, 1, bytes(12800), True, True)
            self.assertIsNotNone(self.speech.active)
        with patch('speech.time.monotonic', return_value=100.2):
            self.speech.ingest(self.session, 2, bytes(12800), True, True)
            self.assertIsNone(self.speech.active)
            self.assertFalse(self.speech.busy)
            self.assertGreater(self.speech.generation, generation)


if __name__ == "__main__":
    unittest.main()
