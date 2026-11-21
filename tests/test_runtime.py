import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image

from app import create_app
from runtime import Runtime


class RuntimeTests(unittest.TestCase):
    def test_read_only_view(self):
        client = create_app(Runtime()).test_client()
        page = client.get("/").data
        for element in (b"<input", b"<textarea", b"<select", b"<video"):
            self.assertNotIn(element, page)
        self.assertEqual(page.count(b'<button'), 1)
        self.assertIn(b'id="clear-dialog"', page)
        self.assertEqual(client.post("/api/vision").status_code, 404)
        self.assertEqual(client.post("/api/chat").status_code, 404)
        self.assertFalse(client.get("/api/status").json["video_online"])

    def test_inference_runs_without_browser_and_deduplicates_frames(self):
        calls = []

        class FakeVision:
            device = "test"

            def analyze(self, image, mode):
                calls.append(mode)
                return image, "前方有障碍"

        runtime = Runtime()
        with patch("runtime.Vision", FakeVision):
            worker = threading.Thread(target=runtime._infer)
            worker.start()
            try:
                for count in range(1, 5):
                    runtime.ingest(Image.new("RGB", (64, 48)))
                    deadline = time.monotonic() + 2
                    while len(calls) < count and time.monotonic() < deadline:
                        time.sleep(.01)
                time.sleep(.05)
                self.assertEqual(len(calls), 4)
                self.assertEqual(len(runtime.snapshot()["events"]), 1)
                runtime.set_mode("outdoor")
                deadline = time.monotonic() + 2
                while calls[-1] != "outdoor" and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(calls[-1], "outdoor")
                runtime.disconnect()
                self.assertIsNone(runtime.snapshot()["frame"])
                self.assertIsNone(runtime.current_frame())
            finally:
                runtime.stop.set()
                with runtime.changed:
                    runtime.changed.notify_all()
                worker.join(3)

    def test_expired_frames_are_hidden(self):
        runtime = Runtime()
        runtime.ingest(Image.new("RGB", (64, 48)))
        runtime.pair = {"sequence": 1}
        runtime.frame_time -= 5
        self.assertIsNone(runtime.snapshot()["frame"])
        self.assertIsNone(runtime.current_frame())

    def test_stalled_inference_hides_old_pair_even_if_capture_is_live(self):
        runtime = Runtime()
        runtime.ingest(Image.new('RGB', (64, 48)))
        runtime.pair = {'sequence': 1}
        runtime.pair_time = time.monotonic() - 5
        self.assertTrue(runtime.snapshot()['video_online'])
        self.assertIsNone(runtime.snapshot()['frame'])


if __name__ == "__main__":
    unittest.main()
