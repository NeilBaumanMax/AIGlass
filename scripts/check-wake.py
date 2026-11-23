"""Replay local diagnostic WAVs through the production microphone processing.

Example: python scripts/check-wake.py .local/recording.wav
No network requests or cloud transcription are performed.
"""
import argparse
import audioop
import json
from pathlib import Path
import sys
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.wake import WakeDetector
from backend.aec import EchoCanceller


def check(path, detector):
    detector.reset()
    with wave.open(str(path)) as source:
        if source.getsampwidth() != 2 or source.getframerate() != 16000 or source.getnchannels() not in (1, 2):
            raise ValueError('Expected 16 kHz PCM16 mono or mic/reference stereo')
        channels = source.getnchannels()
        data = source.readframes(source.getnframes())
    aec = EchoCanceller() if channels == 2 else None
    hits = []
    block_size = 6400 * channels
    try:
        for offset in range(0, len(data), block_size):
            pcm = data[offset:offset + block_size].ljust(block_size, b'\0')
            if aec:
                pcm = aec.process(pcm)
            pcm = audioop.bias(pcm, 2, -audioop.avg(pcm, 2))
            pcm = audioop.mul(pcm, 2, min(4.0, 600 / max(audioop.rms(pcm, 2), 1)))
            if detector.accept(pcm):
                hits.append(round(offset / (32000 * channels), 2))
    finally:
        if aec:
            aec.close()
    return {'file': str(path), 'seconds': round(len(data) / (32000 * channels), 2), 'wake_times': hits}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+', type=Path)
    args = parser.parse_args()
    detector = WakeDetector()
    for file in args.files:
        print(json.dumps(check(file, detector), ensure_ascii=False), flush=True)
