import audioop
import base64
from collections import deque
import json
import logging
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid

from . import qwen
from .nanomuse import NanoMuse, NanoMuseError, Cancelled
from . import tts
from .guidance import Alert, CUES, MESSAGE_KINDS

from .paths import ROOT
IDLE_SECONDS = 8
WAKE = re.compile(r"(?:嗨|hi)[，,\s]*(?:edith|伊迪丝|伊迪斯)", re.I)
LOOK = re.compile(r"^(?:请帮我|帮我|请|麻烦你)?(?:看看|看一下|看一看|看当前画面|描述(?:一下)?(?:当前|眼前的)?画面)")
MODE = re.compile(r"^(?:切换(?:到)?|打开|进入)(室内|室外)(?:模式|走廊|通道)?$")
PROMPTS = {
    "ready": "Edith 已连接，语音服务已就绪",
    "wake": "我在，请说",
    "indoor": "已切换室内模式",
    "outdoor": "已切换室外模式",
    "sleep": "对话结束",
    "no_frame": "当前摄像头没有画面",
    "error": "对话暂时不可用，请稍后重试",
    "working": "正在处理，请稍候",
    "still_working": "任务仍在执行，请稍候",
    **{cue.prompt: cue.text for cue in CUES.values()},
    "vision_demo": "以下是模拟场景测试，不是实际路况",
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
        self.agent = NanoMuse() if os.getenv("AI_BACKEND", "qwen") == "nanomuse" else None
        self.agent_cancel = None
        self.last_wait_prompt = 0.0
        self.model = self.recognizer = None
        self.utterance = bytearray()
        self.partial = ""
        self.last_voice_at = 0.0
        self.wake_hits = 0
        self.pending = deque(maxlen=4)
        self.active = None
        self.serial = 0
        self.device_info = {}
        self.aec = None
        self.aec_error = ''
        self.voice_hits = 0
        self.barged = False
        self.noise_rms = 10.0
        self.wake_detector = None
        self.wake_error = ''
        self.wake_retry_at = 0.0
        self.prompts = {}
        for name in PROMPTS:
            path = ROOT / ".local" / "prompts" / (name + ".wav")
            if path.exists():
                self.prompts[name] = path.read_bytes()
        self.runtime.on_alert = self.alert

    def connect(self, device_info=None):
        with self.lock:
            self.cancel_agent()
            if self.agent:
                self.agent.reset_conversation()
            self.runtime.guidance.reconnect_audio()
            self.device_info = device_info or {}
            if self.aec:
                self.aec.close()
            self.aec = None
            self.aec_error = ''
            self.voice_hits = 0
            self.barged = False
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
            self.partial = ""
            self.last_voice_at = 0.0
            if self.wake_detector:
                self.wake_detector.reset()
            self.wake_hits = 0
            self.runtime.emit("status", "眼镜音频客户端已连接")
            self.prompt("ready")
            return self.session

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            online = now - self.seen < 4
            occupied = self.busy or self.playing or self.active or self.pending
            awake = bool(online and self.awake_until and (occupied or self.awake_until > now))
            return {"online": online, "microphone": time.monotonic() - self.mic_seen < 2,
                    "mic_dbfs": self.mic_dbfs if online else None,
                    "awake": awake,
                    "agent": self.agent.snapshot() if self.agent else {"provider": "qwen"},
                    "device": self.device_info,
                    "wake_error": self.wake_error,
                    "duplex": bool(self.aec), "aec_error": self.aec_error,
                    "echo": self.aec.metrics if self.aec else {},
                    "heartbeat_age": round(now - self.seen, 1) if self.seen else None,
                    "idle_remaining": math.ceil(max(0, self.awake_until - now)) if awake and not occupied else None,
                    "busy": online and self.busy, "playing": online and self.playing}

    def expire_dialog(self, now):
        if (self.awake_until and now >= self.awake_until and
                not (self.busy or self.playing or self.active or self.pending)):
            # Vosk may hold a stable partial without declaring an endpoint in
            # background noise. Never discard those words at the idle boundary.
            if self.partial and self.recognizer and self.finish_utterance():
                return
            self.awake_until = 0
            self.history.clear()
            if self.agent:
                self.agent.reset_conversation()
            self.recognizer = None
            self.utterance.clear()
            self.partial = ""
            self.last_voice_at = 0.0
            if self.wake_detector:
                self.wake_detector.reset()
            self.generation += 1
            self.runtime.emit("dialog", "8 秒无新指令，对话结束，等待唤醒")
            self.prompt("sleep")

    def prompt(self, name, urgent=False, visual=None):
        self.enqueue(PROMPTS[name], self.prompts.get(name, b""), urgent, visual)

    def enqueue(self, text, wav, urgent=False, visual=None):
        with self.lock:
            self.barged = False
            self.serial += 1
            item = {"id": self.serial, "text": text, "wav": base64.b64encode(wav).decode(),
                    "expires": time.monotonic() + (8 if urgent else 45)}
            if visual:
                item['_visual'] = visual
            if urgent:
                self.pending.clear()
                self.active = item
            else:
                self.pending.append(item)

    def alert(self, alert):
        # String input is retained for existing diagnostics. Runtime uses Alert.
        checked = isinstance(alert, Alert)
        if not checked:
            kind = MESSAGE_KINDS.get(alert)
            if not kind:
                return 'unknown'
            alert = Alert(kind, self.runtime.guidance.epoch)
        with self.lock:
            now = time.monotonic()
            if not self.seen or now - self.seen > 4:
                return 'audio_offline'
            if checked and not self.runtime.guidance.valid(alert, now):
                return 'stale'
            if not self.prompts.get(alert.cue.prompt):
                return 'missing_audio'
            active_visual = self.active.get('_visual') if self.active else None
            if active_visual and not self.runtime.guidance.valid(active_visual, now, playing=True):
                self.active = None
                active_visual = None
            occupied = self.awake_until > now or self.busy or self.playing or self.active or self.pending
            if not alert.interrupts and occupied:
                return 'deferred'
            if active_visual and active_visual.cue.priority >= alert.cue.priority:
                return 'priority_busy'
            if alert.interrupts:
                self.generation += 1
                self.cancel_agent()
                self.busy = False
            self.prompt(alert.cue.prompt, urgent=alert.interrupts, visual=alert if checked else None)
            return 'accepted'

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
                if error and self.active.get('_visual'):
                    self.runtime.guidance.playback_failed(self.active['_visual'])
                self.active = None
                if self.awake_until:
                    self.awake_until = now + IDLE_SECONDS
            if self.active and self.active["expires"] < now:
                self.active = None
            if self.active and self.active.get('_visual') and not self.runtime.guidance.valid(self.active['_visual'], now, playing=True):
                self.active = None
            self.expire_dialog(now)
            while self.active is None and self.pending:
                item = self.pending.popleft()
                if (item["expires"] >= now and
                        (not item.get('_visual') or self.runtime.guidance.valid(item['_visual'], now))):
                    self.active = item
            return self.active

    def ingest(self, session, seq, pcm, muted=False, duplex=False):
        from vosk import KaldiRecognizer, Model

        with self.lock:
            now = time.monotonic()
            if session != self.session or now - self.seen > 5:
                raise ValueError("设备会话已失效")
            if seq <= self.seq:
                return
            gap = seq != self.seq + 1 or now - self.mic_seen > 1.5
            self.seq, self.mic_seen = seq, now
            if duplex:
                if len(pcm) % 1280:
                    raise ValueError('无效的麦克风与参考音频帧')
                try:
                    from .aec import EchoCanceller
                    if self.aec is None or gap:
                        if self.aec:
                            self.aec.close()
                        self.aec = EchoCanceller()
                    pcm = self.aec.process(pcm)
                    self.aec_error = ''
                except (OSError, RuntimeError) as exc:
                    self.aec_error = '回声处理不可用，已退回轮流说话'
                    if self.aec:
                        self.aec.close()
                        self.aec = None
                    pcm = audioop.tomono(pcm, 2, 1, 0)
                    duplex = False
            pcm = audioop.bias(pcm, 2, -audioop.avg(pcm, 2))
            rms = audioop.rms(pcm, 2)
            self.mic_dbfs = max(-90, round(20 * math.log10(rms / 32768))) if rms else -90
            # Waiting for a tool is not speaker playback. Even without AEC,
            # the user must be able to wake/interrupt a silent running task.
            occupied = muted or self.playing or self.active
            interruptible = occupied or self.busy
            # During playback, require residual near-end speech above the
            # measured speaker-only residual before passing it to recognition.
            if not occupied and rms < 100:
                self.noise_rms = .95 * self.noise_rms + .05 * rms
            near_voice = rms >= max(30, self.noise_rms * 2.5)
            self.voice_hits = self.voice_hits + 1 if near_voice else 0
            if (occupied and not duplex) or (duplex and occupied and not self.barged and not near_voice):
                self.recognizer = None
                self.utterance.clear()
                self.partial = ""
                self.last_voice_at = 0.0
                self.wake_hits = 0
                if self.wake_detector:
                    self.wake_detector.reset()
                return
            if self.awake_until and near_voice:
                self.last_voice_at = now
                if self.voice_hits >= 2:
                    self.awake_until = now + IDLE_SECONDS
            self.expire_dialog(now)
            # Limited digital gain for normal conversational volume; never
            # change the codec gain dynamically or amplify a block over 4x.
            pcm = audioop.mul(pcm, 2, min(4.0, 600 / max(rms, 1)))
            # Run the dedicated keyword model before free-form ASR in ALL
            # phases, including listening, tool execution and duplex playback.
            if self.detect_wake(pcm, gap, now) or not self.awake_until:
                return
            if self.model is None:
                self.model = self.wake_detector.model if self.wake_detector else Model(str(ROOT / "models/vosk-model-small-cn-0.22"))
            if self.recognizer is None or gap:
                self.recognizer = KaldiRecognizer(self.model, 16000)
                self.utterance.clear()
                self.partial = ""
                self.wake_hits = 0
            self.utterance.extend(pcm)
            complete = self.recognizer.AcceptWaveform(pcm)
            if not complete:
                partial = json.loads(self.recognizer.PartialResult()).get("partial", "").replace(" ", "")
                if interruptible and not self.barged and self.awake_until and self.voice_hits >= 2 and len(partial) >= 2:
                    self.interrupt()
                if self.awake_until and partial and partial != self.partial:
                    self.awake_until = time.monotonic() + IDLE_SECONDS
                self.partial = partial
            paused = self.partial and self.last_voice_at and now - self.last_voice_at >= 1.0
            if complete or paused or len(self.utterance) > 32000 * 12:
                self.finish_utterance(complete, interruptible)

    def finish_utterance(self, complete=False, interruptible=False):
        result = self.recognizer.Result() if complete else self.recognizer.FinalResult()
        text = json.loads(result).get("text", "").replace(" ", "")
        audio = bytes(self.utterance)
        self.utterance.clear()
        self.recognizer = None
        self.partial = ""
        self.last_voice_at = 0.0
        self.wake_hits = 0
        # Only the finalized transcript is a command, not an unconfirmed partial.
        if text and self.awake_until:
            if interruptible and not self.barged:
                self.interrupt()
            self.awake_until = time.monotonic() + IDLE_SECONDS
            self.handle(text, audio)
            return True
        return False

    def detect_wake(self, pcm, gap, now):
        from .wake import WakeDetector
        if self.wake_detector is None:
            if now < self.wake_retry_at:
                return False
            try:
                self.wake_detector = WakeDetector()
                self.wake_error = ''
            except (OSError, RuntimeError, ImportError):
                self.wake_error = '唤醒模型未就绪'
                self.wake_retry_at = now + 30
                logging.exception('Edith keyword model failed to load')
                return False
        elif gap:
            self.wake_detector.reset()
        if self.wake_detector.accept(pcm):
            self.handle('嗨，Edith')
            return True
        return False

    def cancel_agent(self):
        if self.agent_cancel:
            self.agent_cancel.set()

    def interrupt(self, force=False, announce=True):
        self.barged = True
        # Speaking an approval answer stops the prompt, but must keep its task alive.
        approval = self.agent.snapshot().get("approval") if self.agent else None
        answering = approval and not force
        if not answering:
            self.generation += 1
            self.cancel_agent()
            self.busy = False
        self.playing = False
        self.active = None
        self.pending.clear()
        self.awake_until = time.monotonic() + IDLE_SECONDS
        if announce:
            self.runtime.emit('dialog', '正在听取确认回答' if answering else
                              '检测到插话，已停止播报并请求取消任务' if self.agent else '检测到插话，已停止当前回答')

    def handle(self, text, pcm=b""):
        with self.lock:
            match = WAKE.search(text)
            if match:
                self.interrupt(force=True, announce=False)
                self.recognizer = None
                self.utterance.clear()
                self.partial = ""
                self.last_voice_at = 0.0
                if self.wake_detector:
                    self.wake_detector.reset()
                self.runtime.emit("dialog", "唤醒词已识别 · " + text)
                self.prompt("wake", urgent=True)
                text = text[match.end():].strip("，。！, .!")
                if not text:
                    return
            elif not self.awake_until or (time.monotonic() > self.awake_until and
                    not (self.busy or self.playing or self.active or self.pending)):
                return
            self.awake_until = time.monotonic() + IDLE_SECONDS
            self.runtime.emit("dialog", "你 · " + text)
            if text in {"结束对话", "退出对话"}:
                self.cancel_agent()
                if self.agent:
                    self.agent.reset_conversation()
                self.awake_until = 0
                self.history.clear()
                self.generation += 1
                self.busy = False
                self.prompt("sleep", urgent=True)
                return
            approval = self.agent.snapshot().get("approval") if self.agent else None
            if approval:
                if text in {"确认执行", "允许执行", "同意执行", "取消执行", "拒绝执行"}:
                    allow = text in {"确认执行", "允许执行", "同意执行"}
                    threading.Thread(target=self._approve,
                        args=(approval["approval_id"], allow, self.generation), daemon=True).start()
                    return
                # A different instruction cancels the old task rather than authorizing it.
                self.interrupt(force=True)
            if self.agent and text in {"停一下", "停止", "停止任务", "取消任务"}:
                self.interrupt(force=True)
                return
            if self.busy:
                self.interrupt(force=True)
            command = re.sub(r'^(?:停一下|等一下|先停一下|Edith)[，,。\s]*', '', text)
            mode = MODE.fullmatch(command)
            if mode:
                target = "indoor" if mode[1] == "室内" else "outdoor"
                self.runtime.set_mode(target)
                self.runtime.emit("dialog", "Edith · " + PROMPTS[target])
                self.prompt(target)
                return
            remote_view = re.search(r"手机|电脑|屏幕|显示器|桌面|页面|app|应用", text, re.I)
            camera_view = re.search(r"眼前|摄像头|眼镜.*画面", text)
            look = LOOK.match(text) and not (self.agent and remote_view and not camera_view)
            frame = self.runtime.current_frame() if look else None
            if look and frame is None:
                self.runtime.emit("dialog", "Edith · 当前摄像头没有画面")
                self.prompt("no_frame")
                return
            self.busy = True
            self.cancel_agent()
            # Each worker owns a unique generation. A cancelled worker may
            # finish after its replacement; it must not clear the new busy flag
            # or enqueue stale TTS and start the eight-second idle countdown.
            self.generation += 1
            cancel = threading.Event()
            self.agent_cancel = cancel
            generation = self.generation
            history = list(self.history)
            self.last_wait_prompt = time.monotonic()
            if self.agent and self.prompts.get('working'):
                self.prompt('working')
            threading.Thread(target=self._answer, args=(text, pcm, frame, history, generation, cancel), daemon=True).start()

    def _approve(self, approval_id, allow, generation):
        try:
            with self.lock:
                if generation != self.generation or (self.agent_cancel and self.agent_cancel.is_set()):
                    return
            ok = self.agent.approve(approval_id, allow)
            message = "已确认本次操作" if ok and allow else "已拒绝本次操作" if ok else "确认已失效，请重新下达指令"
        except Exception:
            message = "确认未送达，请检查 nanoMuse 连接"
        with self.lock:
            if generation == self.generation:
                self.runtime.emit("dialog", "Edith · " + message)

    def _agent_event(self, event, generation):
        with self.lock:
            if generation != self.generation or (self.agent_cancel and self.agent_cancel.is_set()):
                return
            if time.monotonic() - self.seen > 5:
                self.cancel_agent()
                return
            if event.get("stage") == "tool":
                self.runtime.emit("agent", "nanoMuse 正在执行 · " + str(event.get("name", "任务")))
            if (event.get('stage') == 'heartbeat' and self.busy and
                    time.monotonic() - self.last_wait_prompt >= 30 and
                    not (self.playing or self.active or self.pending) and
                    not self.agent.snapshot().get('approval') and self.prompts.get('still_working')):
                self.last_wait_prompt = time.monotonic()
                self.prompt('still_working')
            if event.get("stage") == "approval":
                preview = str(event.get("preview", "当前操作"))[:250]
                text = "nanoMuse 需要确认：" + preview + "。请说确认执行，或取消执行。"
                self.runtime.emit("dialog", "Edith · " + text)
                threading.Thread(target=self._approval_prompt,
                    args=(text, event["approval_id"], generation), daemon=True).start()

    def _approval_prompt(self, text, approval_id, generation):
        try:
            wav = tts.synthesize(text)
            with self.lock:
                approval = self.agent.snapshot().get("approval")
                if generation == self.generation and approval and approval["approval_id"] == approval_id:
                    self.enqueue(text, wav)
        except Exception:
            with self.lock:
                if generation == self.generation:
                    self.cancel_agent()
                    self.runtime.emit("dialog", "确认提示播放失败，已请求取消任务")
                    self.prompt("error")

    def _answer(self, text, pcm, frame, history, generation, cancel=None):
        try:
            with self.lock:
                if generation != self.generation or (cancel and cancel.is_set()):
                    return
            if self.agent:
                cancel = cancel or threading.Event()
                answer = self.agent.ask(text, frame, lambda event: self._agent_event(event, generation), cancel)
                with self.lock:
                    if generation != self.generation or cancel.is_set():
                        return
                    self.runtime.emit("dialog", "Edith · " + answer)
                wav = tts.synthesize(answer)
            else:
                answer, wav = qwen.ask(text, history, frame, pcm or None)
            with self.lock:
                if generation != self.generation or (cancel and cancel.is_set()) or time.monotonic() - self.seen > 4:
                    return
                self.history.extend([{"role": "user", "content": text},
                                     {"role": "assistant", "content": answer}])
                self.history = self.history[-8:]
                if not self.agent:
                    self.runtime.emit("dialog", "Edith · " + (answer or "语音回复"))
                self.enqueue(answer or "语音回复", wav)
                self.awake_until = time.monotonic() + IDLE_SECONDS
        except Cancelled:
            pass
        except Exception as exc:
            logging.warning("AI request failed (%s)", type(exc).__name__)
            with self.lock:
                if generation == self.generation:
                    self.runtime.emit("dialog", str(exc) if isinstance(exc, NanoMuseError) else
                                      "nanoMuse 或语音合成失败，请检查桌面端和百炼配置" if self.agent else
                                      "千问请求失败，请检查网络和百炼配置")
                    self.prompt("error")
        finally:
            with self.lock:
                if generation == self.generation:
                    self.busy = False
