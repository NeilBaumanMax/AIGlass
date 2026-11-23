"""Voice transport to the real nanoMuse desktop agent, never a second agent loop."""
import base64
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlparse
import uuid

import requests

ROOT = Path(__file__).resolve().parent
TERMINAL = {"completed", "cancelled", "failed", "interrupted"}


class NanoMuseError(RuntimeError):
    pass


class Cancelled(NanoMuseError):
    pass


class NanoMuse:
    def __init__(self, url=None, token_file=None, state_file=None, monitor=True):
        self.url = (url or os.getenv("NANOMUSE_BRIDGE_URL", "http://127.0.0.1:18765")).rstrip("/")
        parsed = urlparse(self.url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("nanoMuse 接口必须是本机 http://127.0.0.1:端口")
        self.token_file = Path(token_file or os.getenv("EDITH_BRIDGE_TOKEN_FILE", ROOT / ".local/nanomuse-token"))
        self.state_file = Path(state_file or ROOT / ".local/nanomuse-turn.json")
        self.conversation = str(uuid.uuid4())
        self.known_conversations = set()
        self.serial = threading.Lock()
        self.lock = threading.RLock()
        self.current = None
        self.approval = None
        self.state = {"provider": "nanomuse", "online": False, "phase": "disconnected", "devices": []}
        if monitor:
            threading.Thread(target=self._monitor, daemon=True).start()

    def _http(self, method, path, data=None):
        try:
            token = self.token_file.read_text(encoding="utf-8").strip()
        except OSError:
            raise NanoMuseError("nanoMuse 尚未配置眼镜接入") from None
        if len(token) < 32:
            raise NanoMuseError("nanoMuse 接入令牌无效")
        # Ignore system proxies for the local authenticated bridge.
        with requests.Session() as session:
            session.trust_env = False
            response = session.request(method, self.url + path,
                headers={"Authorization": "Bearer " + token},
                **({"params": data} if method == "GET" else {"json": data}), timeout=(2, 8))
            if not response.ok:
                raise NanoMuseError("nanoMuse 接口不可用（HTTP %s）" % response.status_code)
            return response.json()

    def _monitor(self):
        while True:
            try:
                status = self._http("GET", "/v1/status")
                if status.get("protocol") != 1:
                    raise NanoMuseError("nanoMuse 接口版本不匹配")
                with self.lock:
                    self.state.update(online=True, hub_connected=bool(status.get("hub_connected")),
                                      signed_in=bool(status.get("signed_in")), devices=status.get("devices", []))
                    if self.state["phase"] == "disconnected":
                        self.state["phase"] = "idle"
            except (NanoMuseError, requests.RequestException, ValueError):
                with self.lock:
                    self.state.update(online=False, hub_connected=False, devices=[])
            time.sleep(2)

    def snapshot(self):
        with self.lock:
            return {**self.state, "approval": dict(self.approval) if self.approval else None}

    def reset_conversation(self):
        with self.lock:
            self.conversation = str(uuid.uuid4())

    def _remember(self, identity):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_file.with_suffix(".tmp")
        temp.write_text(json.dumps(identity), encoding="utf-8")
        temp.replace(self.state_file)

    def _settle_previous(self):
        if not self.state_file.exists():
            return
        identity = json.loads(self.state_file.read_text(encoding="utf-8"))
        status = self._http("GET", "/v1/task", identity)
        if status.get("state") == "unknown":
            raise NanoMuseError("上次任务接收状态仍未知，请先在 nanoMuse 核实")
        if status.get("state") not in TERMINAL:
            self._http("POST", "/v1/stop", identity)
            deadline = time.monotonic() + 15
            while status.get("state") not in TERMINAL:
                if time.monotonic() > deadline:
                    raise NanoMuseError("上一项任务尚未确认停止，请在 nanoMuse 查看状态")
                time.sleep(.2)
                status = self._http("GET", "/v1/task", identity)
        self.state_file.unlink(missing_ok=True)

    def approve(self, approval_id, allow):
        with self.lock:
            pending = self.approval
            identity = dict(self.current or {})
            if not pending or pending["approval_id"] != approval_id or not identity or time.monotonic() >= pending["expires"]:
                return False
        result = self._http("POST", "/v1/approve", {**identity, "approval_id": approval_id, "allow": bool(allow)})
        if result.get("ok"):
            with self.lock:
                if self.approval and self.approval["approval_id"] == approval_id:
                    self.approval = None
                    self.state["phase"] = "thinking"
        return bool(result.get("ok"))

    def ask(self, text, frame, on_event, cancel):
        # A new utterance cannot race a still-stopping phone operation.
        if not self.serial.acquire(timeout=20):
            raise NanoMuseError("上一项任务仍在结束，请稍后再试")
        identity = None
        try:
            self._settle_previous()
            if cancel.is_set():
                raise Cancelled()
            with self.lock:
                identity = {"conversation": self.conversation, "turn_id": str(uuid.uuid4())}
                self.current = identity
                self.approval = None
                self.state["phase"] = "thinking"
            self._remember(identity)
            request = {**identity, "new_conversation": identity["conversation"] not in self.known_conversations,
                "text": "你正通过 Edith 眼镜与用户对话。用简短中文回答，通常不超过 150 字。"
                        "用户要求操作手机时，先查看 nanoMuse 设备列表，再委派给手机。"
                        "没有执行结果时不能声称完成。不要推断摄像头外的环境或保证通行安全。"
                        "以下是用户原话：\n" + text}
            if frame:
                request["edith_image"] = base64.b64encode(frame).decode()
            # POST exactly once. A lost response is recovered by read-only status polling.
            try:
                self._http("POST", "/v1/task", request)
            except requests.RequestException:
                pass
            deadline = time.monotonic() + 15 * 60
            stop_at = None
            seen = set()
            while True:
                if time.monotonic() > deadline:
                    cancel.set()
                if cancel.is_set() and stop_at is None:
                    self._http("POST", "/v1/stop", identity)
                    stop_at = time.monotonic()
                    with self.lock:
                        self.state["phase"] = "cancelling"
                        self.approval = None
                status = self._http("GET", "/v1/task", identity)
                on_event({"stage": "heartbeat"})
                state = status.get("state")
                if state in TERMINAL | {"accepted"}:
                    self.known_conversations.add(identity["conversation"])
                if state in TERMINAL:
                    self.state_file.unlink(missing_ok=True)
                    if cancel.is_set() or state == "cancelled":
                        raise Cancelled()
                    if state != "completed":
                        raise NanoMuseError("nanoMuse 任务未完成，请检查桌面端任务记录")
                    return str(status.get("text", "")) or "nanoMuse 没有返回可播报的结果。"
                if state == "unknown":
                    raise NanoMuseError("任务接收状态未知，未自动重发，请检查 nanoMuse")
                if stop_at and time.monotonic() - stop_at > 15:
                    raise NanoMuseError("已请求停止，尚未收到停止确认")
                events = status.get("events", [])
                approval_ids = {e.get("approval_id") for e in events if e.get("stage") == "approval"}
                with self.lock:
                    if self.approval and self.approval["approval_id"] not in approval_ids:
                        self.approval = None
                        self.state["phase"] = "thinking"
                for event in events:
                    # Partial text is cumulative, not a new dialog message; show only final answer.
                    if event.get("stage") == "text":
                        continue
                    fingerprint = json.dumps({k: v for k, v in event.items() if k != "timeout"}, sort_keys=True)
                    if fingerprint in seen or cancel.is_set():
                        continue
                    seen.add(fingerprint)
                    with self.lock:
                        stage = event.get("stage")
                        if stage == "approval":
                            self.approval = {**event, "expires": time.monotonic() + min(float(event.get("timeout", 0)), 180)}
                            self.state["phase"] = "awaiting_approval"
                        elif stage == "approval_result":
                            self.approval = None
                            self.state["phase"] = "thinking"
                        elif stage == "tool" and not self.approval:
                            self.state["phase"] = "executing"
                    on_event(event)
                time.sleep(.2)
        except Cancelled:
            raise
        except (requests.RequestException, ValueError, OSError):
            raise NanoMuseError("nanoMuse 连接中断，任务未重发，请检查桌面端") from None
        finally:
            with self.lock:
                self.current = None
                self.approval = None
                self.state["phase"] = "idle" if not self.state_file.exists() else "uncertain"
            self.serial.release()
