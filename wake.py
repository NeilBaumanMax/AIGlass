"""Local keyword spotting plus constrained pronunciation matching for Edith."""
import json
from pathlib import Path
import re
import numpy as np

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / 'models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20'
PRONUNCIATIONS = ['嗨 伊 迪 丝', '嗨 伊 迪 斯', '海 伊 迪 丝', '嗨 伊 迪', '[unk]']
PRONUNCIATION = re.compile(r'(?:嗨|海)伊迪(?:丝|斯)?')


class WakeDetector:
    def __init__(self):
        import sherpa_onnx
        from vosk import Model
        if not (MODEL / 'tokens.txt').exists():
            raise FileNotFoundError('Run scripts/install-wake.ps1 first')
        self.detector = sherpa_onnx.KeywordSpotter(
            tokens=str(MODEL / 'tokens.txt'),
            encoder=str(MODEL / 'encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx'),
            decoder=str(MODEL / 'decoder-epoch-13-avg-2-chunk-16-left-64.onnx'),
            joiner=str(MODEL / 'joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx'),
            keywords_file=str(ROOT / 'device/edith-keywords.txt'),
            num_threads=2, keywords_score=1.5, keywords_threshold=.25,
            num_trailing_blanks=1, provider='cpu',
        )
        self.model = Model(str(ROOT / 'models/vosk-model-small-cn-0.22'))
        self.reset()

    def reset(self):
        from vosk import KaldiRecognizer
        self.stream = self.detector.create_stream()
        self.pronunciation = KaldiRecognizer(self.model, 16000, json.dumps(PRONUNCIATIONS, ensure_ascii=False))

    def accept(self, pcm):
        self.stream.accept_waveform(16000, np.frombuffer(pcm, '<i2').astype(np.float32) / 32768)
        found = False
        while self.detector.is_ready(self.stream):
            self.detector.decode_stream(self.stream)
            if self.detector.get_result(self.stream):
                found = True
                self.detector.reset_stream(self.stream)
        complete = self.pronunciation.AcceptWaveform(pcm)
        result = self.pronunciation.Result() if complete else self.pronunciation.PartialResult()
        text = json.loads(result).get('text' if complete else 'partial', '').replace(' ', '')
        # Match the whole greeting + name. Never accept only "Hi", only the
        # name, unknown words, or a broad everyday phrase such as "你的意思".
        # A full partial phrase is sufficient: waiting for a second chunk or
        # final transcript lost three valid calls in the recorded regression.
        if PRONUNCIATION.fullmatch(text):
            found = True
        if found:
            self.reset()
        return found
