import base64
import io
import json
import os
import unittest
from unittest.mock import Mock, patch
import wave

import qwen


class QwenTests(unittest.TestCase):
    def request(self, **kwargs):
        response = Mock(ok=True)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        pcm = bytes(4800)
        response.iter_lines.return_value = [
            b'data: ' + json.dumps({"choices": [{"delta": {
                "content": "测试回复", "audio": {"data": base64.b64encode(pcm).decode()}
            }}]}).encode(),
            b'data: [DONE]',
        ]
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-only-key"}), \
                patch("qwen.requests.post", return_value=response) as post:
            text, audio = qwen.ask("测试指令", [], **kwargs)
        self.assertEqual(text, "测试回复")
        with wave.open(io.BytesIO(audio)) as wav:
            self.assertEqual(wav.getframerate(), 24000)
            self.assertEqual(wav.readframes(wav.getnframes()), pcm)
        return post.call_args.kwargs["json"]["messages"][-1]["content"]

    def test_look_uses_image_and_transcript_without_audio_modality(self):
        content = self.request(frame=b"test-jpeg", pcm=bytes(3200))
        self.assertEqual([item["type"] for item in content], ["text", "image_url"])

    def test_normal_question_uses_audio_without_an_image(self):
        content = self.request(pcm=bytes(3200))
        self.assertEqual([item["type"] for item in content], ["text", "input_audio"])
        data = base64.b64decode(content[1]["input_audio"]["data"].split(",", 1)[1])
        with wave.open(io.BytesIO(data)) as wav:
            self.assertEqual(wav.getframerate(), 16000)


if __name__ == "__main__":
    unittest.main()
