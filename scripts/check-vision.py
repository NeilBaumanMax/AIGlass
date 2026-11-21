"""Offline model/pipeline smoke test; generated inputs are NOT camera evidence."""
import argparse
import json
from pathlib import Path
import sys
import threading
import time

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime import Runtime
from vision import DIRECTION_MESSAGES


def wait_for(probe, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = probe()
        if result:
            return result
        time.sleep(.02)
    raise TimeoutError('Vision check timed out')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, help='Optional dashboard QA fixture, never sent to live server')
    args = parser.parse_args()
    runtime = Runtime('generated-offline-test')
    worker = threading.Thread(target=runtime._infer, daemon=True)
    worker.start()
    checks = []
    try:
        wait_for(lambda: runtime.engine_state != 'loading', 90)
        assert runtime.engine_state == 'ready', runtime.error
        assert runtime.snapshot()['frame'] is None and not runtime.snapshot()['video_online']
        assert runtime.current_frame() is None and not runtime.snapshot()['events']
        for mode in ('indoor', 'outdoor'):
            runtime.set_mode(mode)
            for size in ((640, 480), (960, 540), (540, 960)):
                frame = Image.new('RGB', size, '#304758')
                draw = ImageDraw.Draw(frame)
                draw.polygon([(size[0] // 2, size[1] // 3), (size[0], size[1]), (0, size[1])], fill='#71838e')
                runtime.ingest(frame)
                sequence = runtime.sequence
                snapshot = wait_for(lambda: (s if s['frame'] and s['frame']['sequence'] == sequence
                                              and s['frame']['mode'] == mode else None)
                                    if (s := runtime.snapshot()) else None)
                result = snapshot['frame']
                assert (result['width'], result['height']) == size
                assert result['analysis']['direction'] in DIRECTION_MESSAGES
                assert snapshot['video_online'] and not snapshot['error']
                checks.append({'mode': mode, 'size': size, 'ms': snapshot['ms'],
                               'direction': result['analysis']['direction']})
                if args.snapshot and mode == 'indoor' and size == (640, 480):
                    args.snapshot.parent.mkdir(exist_ok=True, parents=True)
                    args.snapshot.write_text(json.dumps(snapshot), encoding='utf-8')
        runtime.disconnect()
        assert runtime.snapshot()['frame'] is None
        assert not runtime.snapshot()['video_online']
        print(json.dumps({'revision': snapshot['vision_revision'], 'device': snapshot['device'],
                          'input': 'generated test pattern, not real camera', 'checks': checks,
                          'disconnect_clears_output': True}, ensure_ascii=False))
    finally:
        runtime.stop.set()
        with runtime.changed:
            runtime.changed.notify_all()
        worker.join(5)


if __name__ == '__main__':
    main()
