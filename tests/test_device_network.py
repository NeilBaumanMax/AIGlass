import subprocess
import unittest
import urllib.error
from unittest.mock import patch

from device.client import NetworkRecovery, network_failure, error_detail, pin_hotspot_neighbor


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.recovery = NetworkRecovery('http://192.168.137.1:7860')
        self.error = urllib.error.URLError(OSError(113, 'No route to host'))

    def test_broken_neighbor_reassociates_only_after_three_failures_and_cools_down(self):
        replies = [subprocess.CompletedProcess([], 0, 'Connected to hotspot'),
                   subprocess.CompletedProcess([], 0, '192.168.137.1 INCOMPLETE'),
                   subprocess.CompletedProcess([], 0, 'OK')]
        with patch('device.client.subprocess.run', side_effect=replies) as run, \
             patch('device.client.time.monotonic', return_value=100):
            self.assertFalse(self.recovery.failed(self.error))
            self.assertFalse(self.recovery.failed(self.error))
            self.assertTrue(self.recovery.failed(self.error))
            self.assertFalse(self.recovery.failed(self.error))
            self.assertEqual(run.call_count, 3)
            self.assertEqual(run.call_args.args[0], ['wpa_cli', '-i', 'wlan0', 'reassociate'])

    def test_http_session_error_never_resets_wifi(self):
        error = urllib.error.HTTPError('http://local', 409, 'session stale', {}, None)
        with patch('device.client.subprocess.run') as run:
            for _ in range(4):
                self.assertFalse(self.recovery.failed(error))
            run.assert_not_called()
        self.assertFalse(network_failure(error))
        self.assertEqual(error_detail(error), 'HTTP 409')

    def test_server_down_with_reachable_neighbor_does_not_reset_wifi(self):
        replies = [subprocess.CompletedProcess([], 0, 'Connected to hotspot'),
                   subprocess.CompletedProcess([], 0, '192.168.137.1 lladdr 00:00:00:00:00:00 REACHABLE')]
        self.recovery.failures = 2
        with patch('device.client.subprocess.run', side_effect=replies) as run:
            self.assertFalse(self.recovery.failed(urllib.error.URLError(ConnectionRefusedError(111, 'refused'))))
            self.assertEqual(run.call_count, 2)

    def test_disassociated_station_can_reconnect(self):
        self.recovery.failures = 2
        replies = [subprocess.CompletedProcess([], 0, 'Not connected.'),
                   subprocess.CompletedProcess([], 0, ''),
                   subprocess.CompletedProcess([], 0, 'OK')]
        with patch('device.client.subprocess.run', side_effect=replies):
            self.assertTrue(self.recovery.failed(self.error))

    def test_only_verified_hotspot_bssid_is_pinned(self):
        mac = '02:11:22:33:44:55'
        with patch('device.client.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '')) as run:
            self.assertTrue(pin_hotspot_neighbor('http://192.168.137.1:7860', mac, 'Connected to ' + mac))
            self.assertEqual(run.call_args.args[0], ['arp', '-i', 'wlan0', '-s', '192.168.137.1', mac])
            run.reset_mock()
            self.assertFalse(pin_hotspot_neighbor('http://192.168.137.1:7860', mac, 'Connected to 02:11:22:33:44:66'))
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][0], 'ip')

    def test_changed_hotspot_removes_our_stale_pin(self):
        mac = '02:11:22:33:44:55'
        replies = [subprocess.CompletedProcess([], 0, '192.168.137.1 lladdr ' + mac + ' PERMANENT'),
                   subprocess.CompletedProcess([], 0, '')]
        with patch('device.client.subprocess.run', side_effect=replies) as run:
            self.assertFalse(pin_hotspot_neighbor('http://192.168.137.1:7860', mac, 'Not connected.'))
            self.assertEqual(run.call_args.args[0], ['arp', '-i', 'wlan0', '-d', '192.168.137.1'])

    def test_verified_permanent_neighbor_with_repeated_timeouts_recovers(self):
        mac = '02:11:22:33:44:55'
        self.recovery.server_mac = mac
        self.recovery.failures = 2
        replies = [subprocess.CompletedProcess([], 0, 'Connected to ' + mac),
                   subprocess.CompletedProcess([], 0, '192.168.137.1 lladdr ' + mac + ' PERMANENT'),
                   subprocess.CompletedProcess([], 0, 'OK')]
        with patch('device.client.subprocess.run', side_effect=replies):
            self.assertTrue(self.recovery.failed(TimeoutError()))
