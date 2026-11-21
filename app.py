import argparse
import ipaddress
import os
from pathlib import Path
import secrets
import hmac
import logging
import mimetypes

from flask import Flask, jsonify, render_template, request

from runtime import Runtime


def create_app(runtime, speech=None, token=""):
    mimetypes.init()
    mimetypes.add_type('image/svg+xml', '.svg')
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/status")
    def status():
        snapshot = runtime.snapshot()
        snapshot["qwen"] = bool(os.getenv("DASHSCOPE_API_KEY"))
        if speech:
            snapshot["audio"] = speech.snapshot()
        return jsonify(snapshot)

    @app.before_request
    def authenticate_device():
        if request.path.startswith("/device/"):
            if not token or not hmac.compare_digest(request.headers.get("X-Device-Token", ""), token):
                return "设备认证失败", 401
            if speech is None:
                return "音频服务未启动", 503

    @app.post("/api/dialog/clear")
    def clear_dialog():
        origin = request.headers.get("Origin")
        if (not request.is_json or request.headers.get("Sec-Fetch-Site") == "cross-site" or
                (origin and origin != request.host_url.rstrip('/'))):
            return "仅允许本机页面清空展示记录", 403
        runtime.clear_dialog()
        return jsonify(ok=True)

    @app.post("/device/session")
    def session():
        body = request.get_json(silent=True) or {}
        info = {k: str(body.get(k, ""))[:100] for k in ("os", "ssid", "hostname", "audio_mode")}
        info["ip"] = request.remote_addr
        runtime.configure_glasses(str(ipaddress.ip_address(request.remote_addr)))
        return jsonify(session=speech.connect(info))

    @app.post("/device/audio")
    def audio():
        data = request.get_data()
        try:
            seq = int(request.headers["X-Sequence"])
            if seq < 0 or not data or len(data) % 2 or len(data) > 16000:
                return "无效 PCM16 片段", 400
            speech.ingest(request.headers.get("X-Session"), seq, data,
                          request.headers.get("X-Muted") == "1",
                          request.headers.get("X-Audio-Format") == "mic-reference")
            return "", 204
        except (ValueError, KeyError):
            return "音频会话或序号错误，请重新连接", 409

    @app.post("/device/poll")
    def poll():
        body = request.get_json()
        try:
            command = speech.poll(body["session"], body.get("playing", False),
                                  body.get("done"), str(body.get("error", ""))[:100])
            if command:
                command = {key: value for key, value in command.items() if key != "expires"}
                if body.get("current") == command["id"]:
                    command.pop("wav", None)
            return jsonify(command=command)
        except (ValueError, KeyError):
            return "播放会话失效，请重新连接", 409

    @app.after_request
    def no_cache(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    return app


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() and not key.lstrip().startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    from speech import Speech

    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--glasses", type=ipaddress.IPv4Address)
    source.add_argument("--test-video", help="后端测试录像路径，网页显示测试标记")
    parser.add_argument("--mode", choices=["indoor", "outdoor"], default="indoor")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    address = f"rtsp://{args.glasses}/live/0" if args.glasses else args.test_video
    runtime = Runtime(address, args.mode, root / '.local/events.sqlite3')
    speech = Speech(runtime)
    token_file = root / ".local" / "device-token"
    token_file.parent.mkdir(exist_ok=True)
    if not token_file.exists():
        token_file.write_text(secrets.token_urlsafe(32), encoding="ascii")
    token = token_file.read_text(encoding="ascii").strip()
    runtime.start()
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    try:
        create_app(runtime, speech, token).run(host="0.0.0.0", port=args.port, threaded=True)
    finally:
        runtime.stop.set()
