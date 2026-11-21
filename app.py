import argparse
import base64
import io
import ipaddress
import json
import logging
import os
import threading
import time
import wave
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request
from PIL import Image

from vision import Vision

ROOT = Path(__file__).resolve().parent
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024
vision_lock = threading.Lock()
speech_lock = threading.Lock()
vision = speech_model = None
board_lock = threading.Lock()
board_frame = None
board_time = 0.0
board_configured = False


def watch_camera(address):
    import cv2

    global board_frame, board_time
    url = f"rtsp://{address}/live/0"
    while True:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3500, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3500,
        ])
        try:
            while cap.isOpened():
                ok, pixels = cap.read()
                if not ok:
                    break
                h, w = pixels.shape[:2]
                scale = min(1, 960 / max(h, w))
                small = cv2.resize(pixels, (int(w * scale), int(h * scale)))
                ok, jpg = cv2.imencode(".jpg", small)
                if ok:
                    with board_lock:
                        board_frame, board_time = jpg.tobytes(), time.monotonic()
        finally:
            cap.release()
            with board_lock:
                board_frame, board_time = None, 0.0
        time.sleep(2)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    with board_lock:
        online = board_frame is not None and time.monotonic() - board_time < 4
    return jsonify(online=online, configured=board_configured,
                   qwen=bool(os.getenv("DASHSCOPE_API_KEY")))


@app.get("/api/glasses.jpg")
def glasses():
    with board_lock:
        if board_frame is None or time.monotonic() - board_time >= 4:
            return "眼镜视频未连接", 503
        return Response(board_frame, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/vision")
def analyze():
    global vision
    mode = request.args.get("mode", "")
    if mode not in {"indoor", "outdoor"}:
        return "请选择室内或室外模式", 400
    try:
        with Image.open(io.BytesIO(request.get_data()), formats=["JPEG"]) as f:
            if max(f.size) > 960:
                return "画面长边不能超过 960 像素", 400
            frame = f.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError):
        return "无法解码 JPEG", 400
    if not vision_lock.acquire(blocking=False):
        return "正在处理上一帧", 429
    start = time.monotonic()
    try:
        if vision is None:
            vision = Vision()
        result, event = vision.analyze(frame, mode)
        output = io.BytesIO()
        result.save(output, format="JPEG", quality=84)
        return jsonify(image=base64.b64encode(output.getvalue()).decode(), event=event,
                       device=str(vision.device), ms=round(1000 * (time.monotonic() - start)))
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        app.logger.exception("Vision unavailable")
        return f"WalkGuide 无法推理，请检查依赖和 {mode} 权重。{type(exc).__name__}", 503
    finally:
        vision_lock.release()


@app.post("/api/listen")
def listen():
    global speech_model
    data = request.get_data()
    if not data or len(data) % 2 or len(data) > 32000 * 16:
        return "需要 16 kHz 单声道 PCM16 语音片段", 400
    try:
        from vosk import KaldiRecognizer, Model

        with speech_lock:
            if speech_model is None:
                speech_model = Model(str(ROOT / "models/vosk-model-small-cn-0.22"))
        recognizer = KaldiRecognizer(speech_model, 16000)
        recognizer.AcceptWaveform(data)
        return jsonify(text=json.loads(recognizer.FinalResult())["text"].replace(" ", ""))
    except Exception as exc:  # Vosk raises a generic Exception when loading fails.
        app.logger.warning("Local speech unavailable: %s", type(exc).__name__)
        return "本地中文语音模型未就绪，可在网页输入指令", 503


@app.post("/api/chat")
def chat():
    import requests

    key = os.getenv("DASHSCOPE_API_KEY")
    if not key:
        return "尚未配置北京地域 DASHSCOPE_API_KEY", 503
    body = request.get_json()
    question = str(body.get("text", "")).strip()[:2000]
    if not question:
        return "请输入问题", 400
    content = [{"type": "text", "text": question}]
    if body.get("look"):
        image = body.get("frame", "")
        if not image.startswith("data:image/jpeg;base64,"):
            return "当前没有可用画面", 400
        content.append({"type": "image_url", "image_url": {"url": image}})
    messages = [{"role": "system", "content": "你是视障眼镜助手小镜。用简短自然的中文回答。仅描述可见信息，无法判断时说明。"}]
    for entry in body.get("history", [])[-8:]:
        if entry.get("role") in {"user", "assistant"}:
            messages.append({"role": entry["role"], "content": str(entry.get("content", ""))[:2000]})
    messages.append({"role": "user", "content": content})
    try:
        with requests.post(
            os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": os.getenv("QWEN_MODEL", "qwen3-omni-flash"), "messages": messages,
                  "stream": True, "modalities": ["text", "audio"],
                  "audio": {"voice": "Cherry", "format": "wav"}, "enable_thinking": False},
            timeout=(8, 60), stream=True,
        ) as reply:
            if not reply.ok:
                return f"百炼请求失败（HTTP {reply.status_code}），请检查北京地域密钥、模型权限和额度", 502
            words, transcript, audio = [], [], []
            for line in reply.iter_lines():
                if not line.startswith(b"data:"):
                    continue
                payload = line[5:].strip()
                if payload == b"[DONE]":
                    break
                chunk = json.loads(payload)
                if "error" in chunk:
                    return "千问生成中断，请重试", 502
                choices = chunk.get("choices")
                if choices:
                    delta = choices[0].get("delta", {})
                    words.append(delta.get("content") or "")
                    sound = delta.get("audio") or {}
                    transcript.append(sound.get("transcript") or "")
                    audio.append(sound.get("data") or "")
            answer = "".join(words) or "".join(transcript)
            pcm = base64.b64decode("".join(audio))
            if not answer and not pcm:
                return "千问未返回内容", 502
            wav = io.BytesIO()
            if pcm:
                with wave.open(wav, "wb") as output:
                    output.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                    output.writeframes(pcm)
            return jsonify(text=answer, audio=base64.b64encode(wav.getvalue()).decode())
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return "未收到有效的百炼回复，请检查网络及配置", 502


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--glasses", type=ipaddress.IPv4Address, help="眼镜的 Wi-Fi IPv4 地址")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    if args.glasses:
        board_configured = True
        threading.Thread(target=watch_camera, args=(args.glasses,), daemon=True).start()
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    print(f"打开 http://127.0.0.1:{args.port}", flush=True)
    app.run(host="127.0.0.1", port=args.port, threaded=True)
