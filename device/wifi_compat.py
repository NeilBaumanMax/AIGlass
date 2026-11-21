"""Persist AIC8800 Wi-Fi 6 compatibility choice in the factory module loader.

This only changes the next boot; it does not reload a running driver.
"""
import argparse
from pathlib import Path
import re
import shutil
import stat


def configure(loader, backup, legacy):
    original = loader.read_bytes()
    pattern = rb'(?m)^([ \t]*insmod[ \t]+(?:\S*/)?aic8800_fdrv\.ko)(?:[ \t]+he_on=[01])?([ \t]*\r?)$'
    suffix = b' he_on=0' if legacy else b''
    updated, count = re.subn(pattern, lambda m: m[1] + suffix + m[2], original)
    if not count:
        raise RuntimeError('Unrecognized Wi-Fi loader; no files changed')
    if updated == original:
        return False
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        shutil.copy2(loader, backup)
    temporary = loader.with_name(loader.name + '.aiglass.tmp')
    temporary.write_bytes(updated)
    temporary.chmod(stat.S_IMODE(loader.stat().st_mode))
    temporary.replace(loader)
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['legacy', 'default'])
    args = parser.parse_args()
    changed = configure(Path('/oem/usr/ko/insmod_wifi.sh'),
                        Path('/userdata/aiglass/insmod_wifi.before-compat.sh'),
                        args.mode == 'legacy')
    print(('Updated' if changed else 'Already configured') + '; applies at next boot: ' + args.mode)
