import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image

from backend.app import create_app
from backend.runtime import Runtime


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
        runtime.on_alert = lambda alert: 'accepted'
        with patch("backend.runtime.Vision", FakeVision):
            worker = threading.Thread(target=runtime._infer)
            worker.start()
            try:
                for count in range(1, 5):
                    runtime.ingest(Image.new("RGB", (64, 48)))
                    deadline = time.monotonic() + 2
                    while (runtime.pair is None or runtime.pair['sequence'] < count) and time.monotonic() < deadline:
                        time.sleep(.01)
                    runtime.dispatch_guidance()
                    time.sleep(.12)
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

    def test_source_change_drops_inflight_old_result(self):
        entered, release, next_entered, next_release = (threading.Event() for _ in range(4))
        calls = []

        class SlowVision:
            device = 'test'

            def analyze(self, image, mode):
                calls.append(mode)
                if len(calls) == 1:
                    entered.set()
                    release.wait(3)
                else:
                    next_entered.set()
                    next_release.wait(3)
                return image, '前方有障碍'

        runtime = Runtime()
        with patch('backend.runtime.Vision', SlowVision):
            worker = threading.Thread(target=runtime._infer)
            worker.start()
            try:
                runtime.ingest(Image.new('RGB', (64, 48)))
                self.assertTrue(entered.wait(2))
                runtime.configure_glasses('192.0.2.10')
                runtime.ingest(Image.new('RGB', (64, 48), 'white'))
                release.set()
                self.assertTrue(next_entered.wait(2))
                self.assertIsNone(runtime.pair)
                self.assertIsNone(runtime.guidance.observed_at)
            finally:
                runtime.stop.set()
                release.set()
                next_release.set()
                with runtime.changed:
                    runtime.changed.notify_all()
                worker.join(3)

    def test_stalled_inference_hides_old_pair_even_if_capture_is_live(self):
        runtime = Runtime()
        runtime.ingest(Image.new('RGB', (64, 48)))
        runtime.pair = {'sequence': 1}
        runtime.pair_time = time.monotonic() - 5
        self.assertTrue(runtime.snapshot()['video_online'])
        self.assertIsNone(runtime.snapshot()['frame'])


if __name__ == "__main__":
    unittest.main()
