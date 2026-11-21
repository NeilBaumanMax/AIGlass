import argparse
import ipaddress
import os

from flask import Flask, jsonify, render_template

from runtime import Runtime


def create_app(runtime):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/status")
    def status():
        snapshot = runtime.snapshot()
        snapshot["qwen"] = bool(os.getenv("DASHSCOPE_API_KEY"))
        return jsonify(snapshot)

    @app.after_request
    def no_cache(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--glasses", type=ipaddress.IPv4Address)
    source.add_argument("--test-video", help="后端测试录像路径，网页显示测试标记")
    parser.add_argument("--mode", choices=["indoor", "outdoor"], default="indoor")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    address = f"rtsp://{args.glasses}/live/0" if args.glasses else args.test_video
    runtime = Runtime(address, args.mode)
    runtime.start()
    try:
        create_app(runtime).run(host="0.0.0.0", port=args.port, threaded=True)
    finally:
        runtime.stop.set()
