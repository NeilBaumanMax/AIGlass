"""Speak nanoMuse's actual answer through Qwen TTS, without another chat model."""
import io
import os
from urllib.parse import urlparse, urlunparse
import wave

import requests


def synthesize(text):
    key = os.getenv("DASHSCOPE_API_KEY")
    if not key:
        raise RuntimeError("百炼语音密钥未配置")
    # Keep each API request below its 600-character input limit.
    chunks = [text[i:i + 500] for i in range(0, min(len(text), 3000), 500)]
    if len(text) > 3000:
        chunks.append("内容较长，其余部分请查看 nanoMuse 记录。")
    frames, parameters = [], None
    for chunk in chunks:
        with requests.post("https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
            headers={"Authorization": "Bearer " + key},
            json={"model": os.getenv("QWEN_TTS_MODEL", "qwen3-tts-flash"),
                  "input": {"text": chunk, "voice": os.getenv("QWEN_TTS_VOICE", "Cherry"), "language_type": "Auto"}},
            timeout=(5, 25)) as response:
            if not response.ok:
                raise RuntimeError("千问语音合成失败 HTTP %s" % response.status_code)
            url = response.json().get("output", {}).get("audio", {}).get("url", "")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not (parsed.hostname or "").endswith(".aliyuncs.com") or parsed.username or parsed.password:
            raise RuntimeError("无效的语音下载地址")
        # Signed OSS URLs may be returned with http; use TLS and never forward the API key.
        with requests.get(urlunparse(parsed._replace(scheme="https")), timeout=(5, 20),
                          allow_redirects=False, stream=True) as audio:
            if audio.status_code != 200:
                raise RuntimeError("语音下载失败")
            data = bytearray()
            for block in audio.iter_content(16384):
                data.extend(block)
                if len(data) > 16 * 1024 * 1024:
                    raise RuntimeError("语音文件过大")
        with wave.open(io.BytesIO(data), "rb") as wav:
            current = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate())
            if current[:2] != (1, 2) or (parameters and current != parameters):
                raise RuntimeError("不支持的语音格式")
            parameters = current
            frames.append(wav.readframes(wav.getnframes()))
    result = io.BytesIO()
    if not parameters:
        raise RuntimeError("语音文本为空")
    with wave.open(result, "wb") as wav:
        wav.setparams((*parameters, 0, "NONE", "not compressed"))
        wav.writeframes(b"".join(frames))
    return result.getvalue()
