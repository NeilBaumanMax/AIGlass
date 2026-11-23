"""Deployment entrypoints and resources must survive a different working directory."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend.config import load_env
from backend.paths import ROOT


class DeploymentLayoutTests(unittest.TestCase):
    def test_launchers_and_flask_resources_outside_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, str(ROOT / 'app.py'), '--help'], cwd=folder,
                                    capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertIn(b'--test-video', result.stdout)
            code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                    "from backend.app import create_app; from backend.runtime import Runtime; "
                    "c=create_app(Runtime()).test_client(); "
                    "assert c.get('/').status_code==200; "
                    "assert c.get('/static/console.js').status_code==200; "
                    "assert not c.get('/api/status').json['video_online']")
            result = subprocess.run([sys.executable, '-c', code, str(ROOT)], cwd=folder,
                                    capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))

    def test_env_quotes_bom_and_existing_override(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'EDITH_LAYOUT_TEST': 'process'}):
            path = Path(folder) / '.env'
            path.write_text('# comment\nEDITH_LAYOUT_TEST="file"\nEDITH_LAYOUT_NEW=\'value\'\n', encoding='utf-8-sig')
            load_env(path)
            self.assertEqual(os.environ['EDITH_LAYOUT_TEST'], 'process')
            self.assertEqual(os.environ['EDITH_LAYOUT_NEW'], 'value')
