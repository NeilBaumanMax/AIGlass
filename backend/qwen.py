import base64
import io
import json
import os
import time
import wave

import requests


def wav_bytes(pcm, rate=24000):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        wav.writeframes(pcm)
    return output.getvalue()


def ask(text, history, frame=None, pcm=None):
    key = os.getenv("DASHSCOPE_API_KEY")
    if not key:
        raise RuntimeError("百炼密钥未配置")
    content = [{"type": "text", "text": text}]
    # Qwen3-Omni accepts text plus one non-text modality per request.
    # A look command uses its local transcript with the requested image.
    if pcm and frame is None:
        content.append({"type": "input_audio", "input_audio": {
            "data": "data:audio/wav;base64," + base64.b64encode(wav_bytes(pcm, 16000)).decode(),
            "format": "wav",
        }})
    if frame:
        content.append({"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(frame).decode(),
        }})
    messages = [{"role": "system", "content":
        "你是视障眼镜助手Edith，根据用户的语音问题用简短中文回答，通常不超过80字。"
        "当前原型支持语音对话、切换室内或室外视觉模式，以及用户明确要求看画面时描述所附图像。"
        "尚不支持GPS路线导航或可靠测距，不要宣称具备这些功能。"
        "无图时只能说明本轮未收到画面，不能声称看到环境，也不要说自己完全不能看图。"
        "图像无法确认的距离、通行安全和台阶高差请明确说明。"}]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": content})
    endpoint = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    with requests.post(
        endpoint.rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + key},
        json={"model": os.getenv("QWEN_MODEL", "qwen3-omni-flash"), "messages": messages,
              "stream": True, "modalities": ["text", "audio"],
              "audio": {"voice": "Cherry", "format": "wav"}, "enable_thinking": False},
        stream=True, timeout=(8, 30),
    ) as response:
        if not response.ok:
            raise RuntimeError(f"百炼请求失败 HTTP {response.status_code}")
        words, transcript, audio = [], [], []
        deadline = time.monotonic() + 60
        for line in response.iter_lines():
            if time.monotonic() > deadline:
                raise RuntimeError("千问回答超时")
            if not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if payload == b"[DONE]":
                break
            chunk = json.loads(payload)
            if "error" in chunk:
                raise RuntimeError("千问生成中断")
            if chunk.get("choices"):
                delta = chunk["choices"][0].get("delta", {})
                words.append(delta.get("content") or "")
                sound = delta.get("audio") or {}
                transcript.append(sound.get("transcript") or "")
                audio.append(sound.get("data") or "")
        text = "".join(words) or "".join(transcript)
        pcm = base64.b64decode("".join(audio))
        if not text and not pcm:
            raise RuntimeError("千问返回空结果")
        # API audio chunks carry PCM16 even when the requested container is WAV.
        return text, wav_bytes(pcm) if pcm else b""
