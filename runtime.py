import base64
from collections import deque
import io
import logging
import threading
import time
import uuid

from PIL import Image

from vision import Vision, WALKGUIDE_REVISION


def jpeg(image):
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=82)
    return output.getvalue()


class Runtime:
    """Own video processing independently of viewers and HTTP requests."""

    def __init__(self, source=None, mode="indoor", journal_path=None):
        self.source = source
        self.mode = mode
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.stop = threading.Event()
        self.frame = None
        self.frame_time = 0.0
        self.sequence = 0
        self.pair = None
        self.pair_time = 0.0
        from journal import Journal
        self.journal = Journal(journal_path) if journal_path else None
        self.events = deque(self.journal.read() if self.journal else [], maxlen=500)
        self.auto_source = source is None
        self.engine_state = "loading"
        self.error = ""
        self.device = ""
        self.latency = 0
        self.on_alert = lambda text: None
        self.threads = []

    def emit(self, kind, text):
        with self.lock:
            event = {"id": uuid.uuid4().hex, "kind": kind, "text": text, "time": time.time()}
            self.events.append(event)
            if self.journal:
                self.journal.append(event)

    def clear_dialog(self):
        with self.lock:
            self.events = deque((e for e in self.events if e['kind'] != 'dialog'), maxlen=500)
            if self.journal:
                self.journal.clear_dialog()

    def configure_glasses(self, ip):
        if self.auto_source:
            with self.lock:
                address = f"rtsp://{ip}/live/0"
                if self.source != address:
                    self.disconnect()
                    self.source = address

    def set_mode(self, mode):
        if mode not in {"indoor", "outdoor"}:
            raise ValueError("invalid mode")
        with self.changed:
            self.mode = mode
            self.pair = None
            self.changed.notify_all()

    def ingest(self, image):
        with self.changed:
            self.frame = image.copy()
            self.frame_time = time.monotonic()
            self.sequence += 1
            self.changed.notify_all()

    def disconnect(self):
        with self.lock:
            self.frame = self.pair = None
            self.frame_time = 0

    def current_frame(self):
        with self.lock:
            if self.frame is None or time.monotonic() - self.frame_time > 4:
                return None
            return jpeg(self.frame)

    def snapshot(self):
        with self.lock:
            fresh = self.frame is not None and time.monotonic() - self.frame_time < 4
            return {
                "video_online": fresh, "source": self.source or "未配置",
                "mode": self.mode, "device": self.device, "ms": self.latency,
                "engine_state": self.engine_state,
                "vision_revision": WALKGUIDE_REVISION,
                "error": self.error, "events": list(self.events),
                "frame": self.pair if fresh and time.monotonic() - self.pair_time < 4 else None,
            }

    def start(self):
        for target in (self._capture, self._infer):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)

    def _capture(self):
        import cv2

        while not self.stop.is_set():
            source = self.source
            if not source:
                self.stop.wait(1)
                continue
            is_file = not source.startswith("rtsp://")
            cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG, [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000,
            ])
            try:
                fps = cap.get(cv2.CAP_PROP_FPS)
                interval = 1 / fps if is_file and 0 < fps < 240 else 0
                while cap.isOpened() and not self.stop.is_set() and self.source == source:
                    before = time.monotonic()
                    ok, pixels = cap.read()
                    if not ok:
                        break
                    image = Image.fromarray(cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB))
                    image.thumbnail((960, 960))
                    self.ingest(image)
                    self.stop.wait(max(0, interval - (time.monotonic() - before)))
            finally:
                cap.release()
                self.disconnect()
            if is_file:
                self.emit("status", "测试视频播放结束")
                return
            self.stop.wait(5)

    def _infer(self):
        vision = None
        try:
            vision = Vision()
            if hasattr(vision, 'prepare'):
                vision.prepare()
            with self.lock:
                self.device = str(vision.device)
                self.engine_state = "ready"
        except Exception:
            logging.exception("Vision model loading failed")
            self.engine_state = "error"
            self.error = "视觉模型加载失败，请检查模型文件"
        last = None
        stable = ""
        candidate = None
        count = 0
        previous_at = 0
        while not self.stop.is_set():
            with self.changed:
                self.changed.wait_for(
                    lambda: self.stop.is_set() or
                    (self.frame is not None and (self.sequence, self.mode) != last),
                    timeout=1,
                )
                if self.stop.is_set():
                    return
                if self.frame is None or (self.sequence, self.mode) == last:
                    continue
                image, when = self.frame.copy(), self.frame_time
                seq, mode = self.sequence, self.mode
                if last is None or last[1] != mode or when - previous_at > 4:
                    candidate, stable, count = None, "", 0
                last, previous_at = (seq, mode), when
            started = time.monotonic()
            alert_to_say = ""
            try:
                vision = vision or Vision()
                overlay, event = vision.analyze(image, mode)
                pair = {"sequence": seq, "mode": mode, "raw": base64.b64encode(jpeg(image)).decode(),
                        "overlay": base64.b64encode(jpeg(overlay)).decode(),
                        "width": image.width, "height": image.height,
                        "analysis": getattr(vision, 'analysis', None)}
                with self.lock:
                    if self.mode != mode or time.monotonic() - when > 4 or self.frame is None:
                        continue
                    self.pair = pair
                    self.pair_time = when
                    self.device = str(vision.device)
                    self.latency = round((time.monotonic() - started) * 1000)
                    self.error = ""
                    self.engine_state = "ready"
                    count = count + 1 if event == candidate else 1
                    candidate = event
                    if count >= (5 if event == "前方路面看不清" else 3) and event != stable:
                        stable = event
                        if event:
                            self.emit("alert", event)
                            alert_to_say = event
                if alert_to_say:
                    self.on_alert(alert_to_say)
            except Exception:
                logging.exception("Video inference failed")
                with self.lock:
                    self.error = "视觉处理失败，请检查后端日志"
                    self.pair = None
                self.stop.wait(2)
