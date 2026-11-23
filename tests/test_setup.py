"""Installer must stop before touching an existing environment or configuration."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from backend.paths import ROOT


@unittest.skipUnless(os.name == 'nt', 'Windows installer')
class SetupTests(unittest.TestCase):
    def run_installer(self, root, *args):
        return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                               '-File', str(root / 'scripts/setup-backend.ps1'), *args],
                              capture_output=True, timeout=30)

    def test_plan_is_read_only_and_failures_preserve_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            shutil.copyfile(ROOT / 'scripts/setup-backend.ps1', root / 'scripts/setup-backend.ps1')
            config = root / '.env'
            config.write_text('AI_BACKEND=qwen\n', encoding='utf-8')
            before = sorted(p.relative_to(root).as_posix() for p in root.rglob('*'))
            plan = self.run_installer(root, '-Plan')
            self.assertEqual(plan.returncode, 0, plan.stderr.decode(errors='replace'))
            self.assertEqual(before, sorted(p.relative_to(root).as_posix() for p in root.rglob('*')))
            missing = self.run_installer(root, '-Stage', 'Assets')
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn(b'Environment first', missing.stderr)
            (root / '.venv').mkdir()
            marker = root / '.venv/keep.txt'
            marker.write_text('existing environment content', encoding='utf-8')
            partial = self.run_installer(root, '-Stage', 'Environment')
            self.assertNotEqual(partial.returncode, 0)
            self.assertIn(b'will not be overwritten', partial.stderr)
            self.assertEqual(marker.read_text(encoding='utf-8'), 'existing environment content')
            self.assertEqual(config.read_text(encoding='utf-8'), 'AI_BACKEND=qwen\n')
