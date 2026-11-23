"""Offline simulated recognition -> real speech scheduler -> local WAV preview.

Does not open a camera, contact a server, load models, or play on a device.
The logical clock runs without sleeping; playback acknowledgements are simulated.
"""
import argparse
import audioop
import base64
import io
import json
from pathlib import Path
import sys
import threading
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from guidance import CUES, FRESH_SECONDS
from runtime import Runtime
from speech import Speech

SCENES = [
    (0, 12, None), (12, 20, 'left'), (20, 34, 'obstacle'),
    (34, 38, 'stairs'), (38, 43, 'stop'), (43, 47, None), (47, 57, 'right'),
]
RATE = 16000


def pcm16(wav):
    with wave.open(io.BytesIO(wav)) as source:
        width, channels, rate = source.getsampwidth(), source.getnchannels(), source.getframerate()
        assert source.getcomptype() == 'NONE', 'PCM WAV required'
        pcm = source.readframes(source.getnframes())
    if width == 1:
        pcm = audioop.bias(pcm, 1, -128)
    pcm = audioop.lin2lin(pcm, width, 2)
    if channels == 2:
        pcm = audioop.tomono(pcm, 2, .5, .5)
    elif channels != 1:
        raise ValueError('Only mono/stereo prompts are supported')
    return audioop.ratecv(pcm, 2, 1, rate, RATE, None)[0]


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/guidance-demo')
    args = parser.parse_args()
    clock = [100.0]
    attempts, clips, commands = [], [], []
    current = None
    sequence = 0
    cancellation = threading.Event()
    interrupted_at = None

    # No environment file is loaded, and no AI client is created for this test.
    with patch.dict('os.environ', {'AI_BACKEND': 'qwen'}), patch('time.monotonic', side_effect=lambda: clock[0]):
        runtime = Runtime()
        runtime.engine_state = 'ready'
        speech = Speech(runtime)
        required = {cue.prompt for cue in CUES.values()} | {'vision_demo', 'sleep'}
        missing = sorted(name for name in required if not speech.prompts.get(name))
        if missing:
            raise SystemExit('Run ./scripts/make-prompts.ps1 first. Missing: ' + ', '.join(missing))
        session = speech.connect()
        speech.pending.clear()  # Simulate only visual scenarios, not boot/wake prompts.

        def deliver(alert):
            result = speech.alert(alert)
            attempts.append({'at': round(clock[0] - 100, 1), 'kind': alert.kind,
                             'text': alert.cue.text, 'repeated': alert.repeated,
                             'interrupts': alert.interrupts, 'result': result})
            return result

        runtime.on_alert = deliver
        for tick in range(571):
            elapsed = tick / 10
            clock[0] = 100 + elapsed
            if tick == 180:
                speech.busy = True
                speech.awake_until = clock[0] + 8
                speech.agent_cancel = cancellation
            kind = next((kind for start, end, kind in SCENES if start <= elapsed < end), None)
            if kind:
                sequence += 1
                runtime.guidance.observe(kind, sequence, clock[0])
            # Device polling is emulated locally; no HTTP requests or microphone data.
            speech.seen = clock[0]
            runtime.dispatch_guidance()
            if cancellation.is_set() and interrupted_at is None:
                interrupted_at = elapsed
            finished = bool(current and elapsed >= current['end'])
            command = speech.poll(session, bool(current and not finished),
                                  current['id'] if finished else None)
            if (command['id'] if command else None) != (current['id'] if current else None):
                if current:
                    seconds = min(elapsed, current['end']) - current['start']
                    clips.append(current['pcm'][:round(seconds * RATE) * 2])
                    current['record']['played_seconds'] = round(seconds, 2)
                    current['record']['interrupted'] = not finished
                current = None
                if command:
                    pcm = pcm16(base64.b64decode(command['wav']))
                    record = {'at': elapsed, 'text': command['text'],
                              'kind': command['_visual'].kind if command.get('_visual') else 'dialog_status'}
                    commands.append(record)
                    current = {'id': command['id'], 'start': elapsed,
                               'end': elapsed + len(pcm) / (RATE * 2), 'pcm': pcm, 'record': record}
        if current:
            seconds = min(57, current['end']) - current['start']
            clips.append(current['pcm'][:round(seconds * RATE) * 2])
            current['record'].update(played_seconds=round(seconds, 2), interrupted=57 < current['end'])

    accepted = [item for item in attempts if item['result'] == 'accepted']
    kinds = [item['kind'] for item in accepted]
    assert kinds == ['waiting', 'restored', 'left', 'obstacle', 'obstacle', 'stairs',
                     'stop', 'lost', 'restored', 'right'], kinds
    assert 20.2 <= interrupted_at < 21, interrupted_at
    obstacles = [item for item in accepted if item['kind'] == 'obstacle']
    assert obstacles[1]['at'] - obstacles[0]['at'] >= 8
    assert obstacles[1]['repeated'] and not obstacles[1]['interrupts']
    assert any(item['kind'] == 'obstacle' and item['result'] == 'deferred' for item in attempts)
    assert not any(item['kind'] in {'left', 'right'} and 18 <= item['at'] < 47 for item in accepted)
    assert not runtime.snapshot()['video_online'] and runtime.snapshot()['frame'] is None

    args.output.mkdir(parents=True, exist_ok=True)
    # Short preview: keep actual played portions; compress gaps to 0.45 seconds.
    intro = pcm16(speech.prompts['vision_demo'])
    with wave.open(str(args.output / 'preview.wav'), 'wb') as output:
        output.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        output.writeframes((b'\0' * round(.45 * RATE) * 2).join([intro] + clips))
    report = {'input': 'SIMULATION ONLY: scripted recognition labels; no camera evidence',
              'playback': 'local scheduler with simulated device acknowledgements, not a speaker test',
              'preview': 'preview.wav has compressed gaps; report times use the 57-second logical clock',
              'scenes': [{'start': start, 'end': end, 'kind': kind} for start, end, kind in SCENES],
              'fresh_seconds': FRESH_SECONDS, 'cues': {key: vars(cue) for key, cue in CUES.items()},
              'simulated_ai_started_at': 18, 'simulated_ai_cancelled_at': interrupted_at,
              'attempts': attempts, 'playback_commands': commands, 'passed': True}
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'simulation': True,
                      'accepted': [{'at': item['at'], 'kind': item['kind']} for item in accepted],
                      'report': str(args.output / 'report.json'), 'preview': str(args.output / 'preview.wav')},
                     ensure_ascii=False))


if __name__ == '__main__':
    run()
