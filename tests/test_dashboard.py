import tempfile
from pathlib import Path
import unittest

from app import create_app
from runtime import Runtime


class DashboardTests(unittest.TestCase):
    def test_brand_migration_and_svg_content_type(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'events.sqlite3'
            first = Runtime(journal_path=path)
            first.emit('dialog', '\u5c0f\u955c · 历史回答')
            first.emit('dialog', '\u0045lis · 历史回答')
            first.journal.db.close()
            second = Runtime(journal_path=path)
            client = create_app(second).test_client()
            self.assertEqual(second.events[0]['text'], 'Edith · 历史回答')
            self.assertEqual(second.events[1]['text'], 'Edith · 历史回答')
            self.assertNotIn('\u5c0f\u955c', client.get('/').text)
            with client.get('/static/icons/eyeglass.svg') as response:
                self.assertEqual(response.mimetype, 'image/svg+xml')
            second.journal.db.close()

    def test_history_survives_restart_and_clear_keeps_device_events(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'events.sqlite3'
            first = Runtime(journal_path=path)
            first.emit('dialog', '你 · 测试问题')
            first.emit('status', '设备在线')
            first.journal.db.close()
            second = Runtime(journal_path=path)
            self.assertEqual(len(second.events), 2)
            client = create_app(second).test_client()
            self.assertEqual(client.post('/api/dialog/clear', json={}, headers={'Origin':'https://untrusted.example'}).status_code, 403)
            self.assertEqual(len(second.events), 2)
            self.assertEqual(client.post('/api/dialog/clear', json={}).status_code, 200)
            self.assertEqual([e['kind'] for e in second.events], ['status'])
            self.assertEqual([e['kind'] for e in second.journal.read()], ['status'])
            second.journal.db.close()

    def test_auto_rtsp_discovery_preserves_explicit_test_source(self):
        runtime = Runtime()
        runtime.configure_glasses('192.168.137.54')
        self.assertEqual(runtime.source, 'rtsp://192.168.137.54/live/0')
        explicit = Runtime('test.mp4')
        explicit.configure_glasses('192.168.137.54')
        self.assertEqual(explicit.source, 'test.mp4')
