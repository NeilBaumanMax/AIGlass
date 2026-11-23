"""Read local configuration without replacing explicit process environment."""
import os

from .paths import ROOT


def load_env(path=None):
    path = path if path is not None else ROOT / '.env'
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        key, separator, value = line.partition('=')
        if separator and key.strip() and not key.lstrip().startswith('#'):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
