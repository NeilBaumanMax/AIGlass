"""Read-only check of the desktop bridge; never submits a phone task."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.nanomuse import NanoMuse
from backend.config import load_env

load_env()

try:
    client = NanoMuse(monitor=False)
    status = client._http('GET', '/v1/status')
    phones = [d for d in status.get('devices', []) if d.get('kind') == 'phone' and d.get('online')]
    print(json.dumps({'protocol': status.get('protocol'), 'desktop_bridge': 'online',
        'signed_in': bool(status.get('signed_in')), 'hub_connected': bool(status.get('hub_connected')),
        'online_phones': len(phones), 'model_and_phone_actions': 'not tested'}, ensure_ascii=False))
    sys.exit(0 if status.get('protocol') == 1 else 1)
except Exception as exc:
    print('Desktop bridge unavailable:', type(exc).__name__)
    sys.exit(1)
