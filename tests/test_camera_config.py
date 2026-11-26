import configparser
from pathlib import Path
import tempfile
import unittest

from device.camera_config import configure


class CameraConfigTests(unittest.TestCase):
    def test_video_only_profile_preserves_sensor_settings_and_original(self):
        factory = ('[audio.0]\nenable=1\n[video.source]\nenable_jpeg=1\n'
                   '[video.0]\nwidth=3040\nheight=1710\n'
                   '[isp.0.adjustment]\nfps=20\n[isp]\nircut_open_gpio=36\n'
                   '[isp.0.exposure]\nauto_exposure_enabled=1\n')
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'factory.ini', Path(tmp) / 'camera.ini'
            source.write_text(factory)
            configure(source, target)
            first = target.read_text()
            configure(source, target)
            self.assertEqual(target.read_text(), first)
            self.assertEqual(source.read_text(), factory)
            config = configparser.ConfigParser()
            config.read(target)
            self.assertEqual(config['audio.0']['enable'], '0')
            self.assertEqual(config['video.source']['enable_jpeg'], '0')
            self.assertEqual(config['video.source']['enable_venc_1'], '0')
            self.assertEqual(config['video.source']['enable_rtsp'], '1')
            self.assertEqual(config['video.0']['output_data_type'], 'H.264')
            self.assertEqual(config['video.0']['width'], '1280')
            self.assertEqual(config['video.0']['dst_frame_rate_num'], '15')
            self.assertEqual(config['storage.0']['enable'], '0')
            self.assertEqual(config['isp']['ircut_open_gpio'], '36')
            self.assertEqual(config['isp.0.exposure']['auto_exposure_enabled'], '1')

    def test_wrong_factory_leaves_existing_output_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'factory.ini', Path(tmp) / 'camera.ini'
            source.write_text('[other]\nvalue=1\n')
            target.write_text('existing profile')
            with self.assertRaises(ValueError):
                configure(source, target)
            self.assertEqual(target.read_text(), 'existing profile')
