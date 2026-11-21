import time
import unittest
from unittest.mock import patch

from app import create_app
from runtime import Runtime
from speech import Speech


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.speech = Speech(self.runtime)
        self.session = self.speech.connect()
        self.speech.pending.clear()

    def test_sleeping_ignores_commands_and_wake_changes_mode(self):
        self.speech.handle("切换室外模式")
        self.assertEqual(self.runtime.mode, "indoor")
        self.speech.handle("你好小静")
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

    def test_stale_frame_not_sent_to_qwen(self):
        self.speech.handle("你好小镜")
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


if __name__ == "__main__":
    unittest.main()
