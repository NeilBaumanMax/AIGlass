"""Local phoneme-based keyword spotting for 'Hi, Edith'."""
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / 'models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20'


class WakeDetector:
    def __init__(self):
        import sherpa_onnx
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
        self.reset()

    def reset(self):
        self.stream = self.detector.create_stream()

    def accept(self, pcm):
        self.stream.accept_waveform(16000, np.frombuffer(pcm, '<i2').astype(np.float32) / 32768)
        found = False
        while self.detector.is_ready(self.stream):
            self.detector.decode_stream(self.stream)
            if self.detector.get_result(self.stream):
                found = True
                self.detector.reset_stream(self.stream)
        return found
