"""Read-only deployment preflight. Does not contact Qwen or modify the board."""
import importlib.metadata
import os
from pathlib import Path
import platform
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    failed = []

    def check(name, probe):
        try:
            detail = probe()
            print(f'PASS {name}: {detail}')
        except Exception as exc:
            # Exception class only: never include credentials or request bodies.
            failed.append(name)
            print(f'FAIL {name} ({type(exc).__name__}); see deployment guide')

    def interpreter():
        assert platform.system() == 'Windows'
        assert sys.version_info[:2] == (3, 11)
        assert sys.maxsize > 2**32
        return f'Windows x64 / Python {platform.python_version()}'

    def dependencies():
        from packaging.requirements import Requirement
        for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            required = Requirement(line.strip())
            assert importlib.metadata.version(required.name) in required.specifier, required.name
        for conflict in ('opencv-python', 'opencv-contrib-python', 'opencv-contrib-python-headless'):
            try:
                importlib.metadata.version(conflict)
            except importlib.metadata.PackageNotFoundError:
                continue
            raise RuntimeError('Multiple OpenCV distributions installed')
        return 'requirements.txt matches installed versions'

    def cuda():
        import torch
        assert torch.cuda.is_available()
        assert torch.version.cuda == '12.6'
        assert torch.ones(4, device='cuda').sum().item() == 4
        return f'{torch.cuda.get_device_name(0)} / torch {torch.__version__}'

    def vision_files():
        from vision import UPSTREAM, WALKGUIDE_REVISION
        actual = subprocess.check_output(['git', '-C', str(UPSTREAM), 'rev-parse', 'HEAD'],
                                         text=True, stderr=subprocess.DEVNULL).strip()
        assert actual == WALKGUIDE_REVISION
        for mode in ('indoor', 'outdoor'):
            folder = UPSTREAM / ('model-' + mode)
            assert (folder / 'config.json').is_file()
            assert any(p.is_file() and p.stat().st_size > 1024 * 1024
                       for p in (folder / 'pytorch_model.bin', folder / 'model.safetensors'))
        return f'WalkGuide {actual[:7]} / both model files present (run check-vision.py to infer)'

    def voice():
        from vosk import SetLogLevel
        from wake import WakeDetector
        from aec import EchoCanceller
        SetLogLevel(-1)
        detector = WakeDetector()
        detector.reset()
        echo = EchoCanceller()
        echo.close()
        return 'local keyword/ASR models and SpeexDSP load successfully'

    def prompts():
        from speech import PROMPTS
        for name in PROMPTS:
            with wave.open(str(ROOT / '.local/prompts' / (name + '.wav'))) as source:
                assert source.getnframes() > 0 and source.getsampwidth() == 2
        return f'{len(PROMPTS)} local speech prompts'

    def api_key():
        config = {}
        path = ROOT / '.env'
        if path.exists():
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                name, separator, value = line.partition('=')
                if separator and not name.lstrip().startswith('#'):
                    config[name.strip()] = value.strip().strip('"').strip("'")
        key = os.environ.get('DASHSCOPE_API_KEY', config.get('DASHSCOPE_API_KEY', ''))
        assert key and key != 'replace_with_your_beijing_api_key'
        return 'key present; cloud authentication/quota NOT tested'

    for name, probe in [('interpreter', interpreter), ('dependencies', dependencies),
                        ('CUDA', cuda), ('vision files', vision_files), ('voice/AEC', voice),
                        ('prompts', prompts), ('Qwen configuration', api_key)]:
        check(name, probe)
    print('READY for device tests' if not failed else 'NOT READY: ' + ', '.join(failed))
    return int(bool(failed))


if __name__ == '__main__':
    raise SystemExit(main())
