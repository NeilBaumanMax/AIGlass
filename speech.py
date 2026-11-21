import audioop
import base64
from collections import deque
import json
import logging
import math
from pathlib import Path
import re
import threading
import time
import uuid

import qwen

ROOT = Path(__file__).resolve().parent
WAKE = re.compile(r"你好[小晓筱][镜境静靖径]")
LOOK = re.compile(r"^(?:请帮我|帮我|请|麻烦你)?(?:看看|看一下|看一看|看当前画面|描述(?:一下)?(?:当前|眼前的)?画面)")
MODE = re.compile(r"^(?:切换(?:到)?|打开|进入)(室内|室外)(?:模式|走廊|通道)?$")
PROMPTS = {
    "ready": "眼镜音频已连接，请说你好小镜",
    "wake": "我在，请说",
    "indoor": "已切换室内模式",
    "outdoor": "已切换室外模式",
    "sleep": "对话结束",
    "no_frame": "当前摄像头没有画面",
    "error": "对话暂时不可用，请稍后重试",
    "obstacle": "前方有障碍",
    "stairs": "前方疑似台阶",
    "unclear": "前方路面看不清",
}


class Speech:
    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = threading.RLock()
        self.session = ""
        self.seq = -1
        self.seen = self.mic_seen = 0.0
        self.mic_dbfs = -90
        self.awake_until = 0.0
        self.busy = False
        self.playing = False
        self.generation = 0
        self.history = []
        self.model = self.recognizer = None
        self.utterance = bytearray()
        self.pending = deque(maxlen=4)
        self.active = None
        self.serial = 0
        self.prompts = {}
        for name in PROMPTS:
            path = ROOT / ".local" / "prompts" / (name + ".wav")
            if path.exists():
                self.prompts[name] = path.read_bytes()
        self.runtime.on_alert = self.alert

    def connect(self):
        with self.lock:
            self.session = uuid.uuid4().hex
            self.seq = -1
            self.seen = time.monotonic()
            self.mic_seen = 0
            self.awake_until = 0
            self.playing = self.busy = False
            self.generation += 1
            self.history.clear()
            self.pending.clear()
            self.active = None
            self.recognizer = None
            self.utterance.clear()
            self.runtime.emit("status", "眼镜音频客户端已连接")
            self.prompt("ready")
            return self.session

    def snapshot(self):
        with self.lock:
            online = time.monotonic() - self.seen < 4
            return {"online": online, "microphone": time.monotonic() - self.mic_seen < 2,
                    "mic_dbfs": self.mic_dbfs if online else None,
                    "awake": online and self.awake_until > time.monotonic(),
                    "busy": online and self.busy, "playing": online and self.playing}

    def prompt(self, name, urgent=False):
        self.enqueue(PROMPTS[name], self.prompts.get(name, b""), urgent)

    def enqueue(self, text, wav, urgent=False):
        with self.lock:
            self.serial += 1
            item = {"id": self.serial, "text": text, "wav": base64.b64encode(wav).decode(),
                    "expires": time.monotonic() + (8 if urgent else 45)}
            if urgent:
                self.pending.clear()
                self.active = item
            else:
                self.pending.append(item)

    def alert(self, text):
        name = {"前方有障碍": "obstacle", "前方疑似台阶": "stairs",
                "前方路面看不清": "unclear"}.get(text)
        if name:
            with self.lock:
                self.generation += 1
                self.busy = False
                self.prompt(name, urgent=True)

    def poll(self, session, playing, done, error=""):
        with self.lock:
            if session != self.session:
                raise ValueError("设备会话已失效")
            now = time.monotonic()
            if now - self.seen > 5:
                raise ValueError("设备连接已超时，请重新握手")
            self.seen = now
            self.playing = bool(playing)
            if self.active and self.active["id"] == done:
                self.runtime.emit("status", ("播放失败 " + error) if error else "已播放 · " + self.active["text"])
                self.active = None
                if self.awake_until:
                    self.awake_until = now + 20
            if self.active and self.active["expires"] < now:
                self.active = None
            while self.active is None and self.pending:
                item = self.pending.popleft()
                if item["expires"] >= now:
                    self.active = item
            return self.active

    def ingest(self, session, seq, pcm, muted=False):
        from vosk import KaldiRecognizer, Model

        with self.lock:
            now = time.monotonic()
            if session != self.session or now - self.seen > 5:
                raise ValueError("设备会话已失效")
            if seq <= self.seq:
                return
            gap = seq != self.seq + 1 or now - self.mic_seen > 1.5
            self.seq, self.mic_seen = seq, now
            pcm = audioop.bias(pcm, 2, -audioop.avg(pcm, 2))
            rms = audioop.rms(pcm, 2)
            self.mic_dbfs = max(-90, round(20 * math.log10(rms / 32768))) if rms else -90
            if muted or self.playing or self.active or self.busy:
                self.recognizer = None
                self.utterance.clear()
                return
            if self.model is None:
                self.model = Model(str(ROOT / "models/vosk-model-small-cn-0.22"))
            if self.recognizer is None or gap:
                self.recognizer = KaldiRecognizer(self.model, 16000)
                self.utterance.clear()
            if self.awake_until and now > self.awake_until:
                self.awake_until = 0
                self.history.clear()
                self.runtime.emit("dialog", "对话超时，等待唤醒")
            self.utterance.extend(pcm)
            complete = self.recognizer.AcceptWaveform(pcm)
            if complete or len(self.utterance) > 32000 * 12:
                result = self.recognizer.Result() if complete else self.recognizer.FinalResult()
                text = json.loads(result).get("text", "").replace(" ", "")
                audio = bytes(self.utterance)
                self.utterance.clear()
                self.recognizer = None
                if text:
                    self.handle(text, audio)

    def handle(self, text, pcm=b""):
        with self.lock:
            match = WAKE.search(text)
            if match:
                self.awake_until = time.monotonic() + 20
                self.runtime.emit("dialog", "唤醒词已识别 · " + text)
                text = text[match.end():].strip("，。！, .!")
                if not text:
                    self.prompt("wake")
                    return
            elif time.monotonic() > self.awake_until:
                return
            self.awake_until = time.monotonic() + 20
            self.runtime.emit("dialog", "你 · " + text)
            if text in {"结束对话", "退出对话"}:
                self.awake_until = 0
                self.history.clear()
                self.generation += 1
                self.prompt("sleep", urgent=True)
                return
            mode = MODE.fullmatch(text)
            if mode:
                target = "indoor" if mode[1] == "室内" else "outdoor"
                self.runtime.set_mode(target)
                self.runtime.emit("dialog", "小镜 · " + PROMPTS[target])
                self.prompt(target)
                return
            frame = self.runtime.current_frame() if LOOK.match(text) else None
            if LOOK.match(text) and frame is None:
                self.runtime.emit("dialog", "小镜 · 当前摄像头没有画面")
                self.prompt("no_frame")
                return
            self.busy = True
            generation = self.generation
            history = list(self.history)
            threading.Thread(target=self._answer, args=(text, pcm, frame, history, generation), daemon=True).start()

    def _answer(self, text, pcm, frame, history, generation):
        try:
            answer, wav = qwen.ask(text, history, frame, pcm or None)
            with self.lock:
                if generation != self.generation or time.monotonic() - self.seen > 4:
                    return
                self.history.extend([{"role": "user", "content": text},
                                     {"role": "assistant", "content": answer}])
                self.history = self.history[-8:]
                self.runtime.emit("dialog", "小镜 · " + (answer or "语音回复"))
                self.enqueue(answer or "语音回复", wav)
                self.awake_until = time.monotonic() + 20
        except Exception as exc:
            logging.warning("Qwen request failed (%s)", type(exc).__name__)
            with self.lock:
                if generation == self.generation:
                    self.runtime.emit("dialog", "千问请求失败，请检查网络和百炼配置")
                    self.prompt("error")
        finally:
            with self.lock:
                if generation == self.generation:
                    self.busy = False
