"""Deterministic WalkGuide-to-speech policy. No camera, model or cloud dependency."""
from dataclasses import dataclass
import threading
import time

from .vision import DIRECTION_MESSAGES

FRESH_SECONDS = 1.5
STARTUP_NOTICE_SECONDS = 8
RETRY_SECONDS = 1


@dataclass(frozen=True)
class Cue:
    prompt: str
    text: str
    priority: int
    frames: int = 3
    confirm_seconds: float = .2
    repeat_seconds: float = 8


CUES = {
    'stairs': Cue('stairs', '前方疑似台阶', 100),
    'obstacle': Cue('obstacle', '前方有障碍', 90),
    'stop': Cue('direction_stop', '请暂停，前方通道不明确', 80),
    'unclear': Cue('unclear', '前方路面看不清', 70, 5, .8),
    'left': Cue('direction_left', '前方通道偏左', 10, 3, .6, 12),
    'right': Cue('direction_right', '前方通道偏右', 10, 3, .6, 12),
    'straight': Cue('direction_straight', '前方通道向前', 10, 3, .6, 12),
    'waiting': Cue('vision_waiting', '摄像头未连接，视觉提醒未启用', 20),
    'lost': Cue('vision_lost', '画面中断，视觉提醒已暂停', 60),
    'error': Cue('vision_error', '视觉处理异常，提醒已暂停', 60),
    'restored': Cue('vision_restored', '视觉画面已恢复', 20),
}
SCENE_KINDS = {'stairs', 'obstacle', 'stop', 'unclear', 'left', 'right', 'straight'}
MESSAGE_KINDS = {value: key for key, value in DIRECTION_MESSAGES.items()}
MESSAGE_KINDS.update({'前方疑似台阶': 'stairs', '前方有障碍': 'obstacle', '前方路面看不清': 'unclear'})


@dataclass(frozen=True)
class Alert:
    kind: str
    epoch: int
    repeated: bool = False

    @property
    def cue(self):
        return CUES[self.kind]

    @property
    def interrupts(self):
        return self.cue.priority >= 60 and not self.repeated


class Guidance:
    def __init__(self, now=None):
        self.lock = threading.RLock()
        self.started = time.monotonic() if now is None else now
        self.epoch = 0
        self.engine = 'loading'
        self.ever_seen = False
        self.observed_at = None
        self.stable_seen_at = float('-inf')
        self.reset_at = self.started
        self.sequence = -1
        self.candidate = self.stable = None
        self.count = 0
        self.since = self.started
        self.last_sent = {}
        self.last_spoken = None
        self.last_sent_at = float('-inf')
        self.last_attempt = float('-inf')
        self.health_announced = None
        self.needs_recovery = False
        self.delivery = 'waiting'

    def reset(self, now=None):
        """Source/mode boundary: no evidence or queued direction crosses it."""
        with self.lock:
            self.epoch += 1
            self.observed_at = None
            self.stable_seen_at = float('-inf')
            self.reset_at = time.monotonic() if now is None else now
            self.sequence = -1
            self.candidate = self.stable = None
            self.count = 0
            self.last_attempt = float('-inf')
            self.last_sent.clear()

    def reconnect_audio(self, now=None):
        with self.lock:
            self.started = time.monotonic() if now is None else now
            self.health_announced = None
            self.last_sent.clear()
            self.last_attempt = float('-inf')

    def observe(self, kind, sequence, captured_at, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if (kind not in SCENE_KINDS or sequence <= self.sequence or
                    now - captured_at > FRESH_SECONDS or captured_at > now):
                return False
            gap = self.observed_at is None or captured_at - self.observed_at > FRESH_SECONDS
            self.sequence = sequence
            self.observed_at = captured_at
            self.ever_seen = True
            self.engine = 'ready'
            if gap:
                self.stable = None
            if kind != self.candidate or gap:
                self.candidate, self.count, self.since = kind, 1, captured_at
            else:
                self.count += 1
            cue = CUES[kind]
            duration = cue.confirm_seconds
            if self.stable and CUES[self.stable].priority >= 70 and cue.priority < CUES[self.stable].priority:
                duration = max(duration, 1.0)
            if self.count >= cue.frames and captured_at - self.since + 1e-6 >= duration:
                if self.stable != kind:
                    self.last_sent.pop(kind, None)
                self.stable = kind
            if self.stable == kind:
                self.stable_seen_at = captured_at
            return True

    def health(self, now):
        if self.engine == 'error':
            return 'error'
        if self.observed_at is not None and now - self.observed_at <= FRESH_SECONDS:
            return 'ready'
        if self.ever_seen:
            if self.observed_at is None and now - self.reset_at <= FRESH_SECONDS:
                return 'confirming'
            return 'lost'
        return 'loading' if self.engine == 'loading' else 'waiting'

    def valid(self, alert, now=None, playing=False):
        now = time.monotonic() if now is None else now
        with self.lock:
            if alert.epoch != self.epoch:
                return False
            health = self.health(now)
            if alert.kind in SCENE_KINDS:
                if health != 'ready':
                    return False
                # A brief higher-priority warning may finish before a lower one.
                if playing and alert.cue.priority >= 70:
                    return True
                return (alert.kind == self.stable and now - self.stable_seen_at <= FRESH_SECONDS and
                        (alert.cue.priority >= 70 or alert.kind == self.candidate))
            return health == ('ready' if alert.kind == 'restored' else alert.kind)

    def next_alert(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if now - self.last_attempt < RETRY_SECONDS:
                # Escalation must not wait behind an ordinary deferred prompt.
                if not self.stable or not self.last_spoken or CUES[self.stable].priority <= CUES[self.last_spoken].priority:
                    return None
            health = self.health(now)
            if health != 'ready':
                if (health in {'loading', 'confirming'} or
                        (not self.ever_seen and now - self.started < STARTUP_NOTICE_SECONDS) or
                        health == self.health_announced):
                    return None
                kind = health
            else:
                kind = self.stable
                if not kind or not self.valid(Alert(kind, self.epoch), now):
                    return None
                if self.needs_recovery and CUES[kind].priority < 70:
                    kind = 'restored'
            repeated = kind in self.last_sent
            cue = CUES[kind]
            if repeated and now - self.last_sent[kind] < cue.repeat_seconds:
                return None
            escalating = cue.priority >= 70 and (self.last_spoken is None or cue.priority > CUES[self.last_spoken].priority)
            if not escalating and now - self.last_sent_at < (4 if cue.priority <= 20 else 2.5):
                return None
            self.last_attempt = now
            return Alert(kind, self.epoch, repeated)

    def acknowledge(self, alert, result, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if alert.epoch != self.epoch:
                return
            self.delivery = result
            if result != 'accepted':
                return
            self.last_sent[alert.kind] = now
            self.last_spoken, self.last_sent_at = alert.kind, now
            if alert.kind in {'waiting', 'lost', 'error'}:
                self.health_announced = alert.kind
                self.needs_recovery = True
            else:
                self.health_announced = None
                self.needs_recovery = False

    def playback_failed(self, alert):
        with self.lock:
            if alert.epoch == self.epoch:
                self.last_sent.pop(alert.kind, None)
                if self.health_announced == alert.kind:
                    self.health_announced = None
                self.delivery = 'playback_failed'

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            health = self.health(now)
            return {'state': health, 'candidate': self.candidate if health == 'ready' else None,
                    'confirmed': self.stable if health == 'ready' and now - self.stable_seen_at <= FRESH_SECONDS else None,
                    'confirm_frames': self.count if health == 'ready' else 0,
                    'delivery': self.delivery, 'last_spoken': CUES[self.last_spoken].text if self.last_spoken else None,
                    'fresh_seconds': FRESH_SECONDS}
