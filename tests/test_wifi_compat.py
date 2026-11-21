from pathlib import Path
import tempfile
import unittest

from device.wifi_compat import configure


class WifiCompatTests(unittest.TestCase):
    def test_preserves_factory_loader_backup_and_restores_driver_default(self):
        original = b'#!/bin/sh\ninsmod cfg80211.ko\n\tinsmod aic8800_fdrv.ko\nrkwifi_server start &\n'
        with tempfile.TemporaryDirectory() as folder:
            loader, backup = Path(folder) / 'loader.sh', Path(folder) / 'backup.sh'
            loader.write_bytes(original)
            self.assertTrue(configure(loader, backup, True))
            self.assertIn(b'insmod aic8800_fdrv.ko he_on=0', loader.read_bytes())
            self.assertEqual(backup.read_bytes(), original)
            self.assertFalse(configure(loader, backup, True))
            self.assertTrue(configure(loader, backup, False))
            self.assertEqual(loader.read_bytes(), original)
            self.assertEqual(backup.read_bytes(), original)

    def test_unknown_loader_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            loader, backup = Path(folder) / 'loader.sh', Path(folder) / 'backup.sh'
            loader.write_text('custom_wifi_manager\n', encoding='ascii')
            with self.assertRaises(RuntimeError):
                configure(loader, backup, True)
            self.assertEqual(loader.read_text(), 'custom_wifi_manager\n')
            self.assertFalse(backup.exists())


if __name__ == '__main__':
    unittest.main()
