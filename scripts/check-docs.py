"""Check repository Markdown file links without internet or local secrets."""
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def main():
    names = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z', '--cached', '--others',
                                     '--exclude-standard']).decode('utf-8').split('\0')
    errors, checked, documents = [], 0, 0
    for name in sorted(set(names)):
        path = ROOT / name
        if not name.endswith('.md') or not path.is_file():
            continue
        documents += 1
        source = re.sub(r'```[\s\S]*?```', '', path.read_text(encoding='utf-8'))
        for match in re.finditer(r'\]\(([^)]+)\)', source):
            url = match.group(1).strip().strip('<>')
            if urlsplit(url).scheme or url.startswith(('#', '//')):
                continue
            target = unquote(url.split('#')[0])
            if target:
                checked += 1
                if not (path.parent / target).exists():
                    errors.append(f'{name}: {target}')
    for error in errors:
        print('BROKEN', error)
    print(f'{documents} documents / {checked} local file links / {len(errors)} broken')
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
