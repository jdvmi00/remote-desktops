"""Failure and cancellation tests for the Windows display ownership boundary."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from remote_desktops import windows_display as w

DEVICE = r'\\?\DISPLAY#MTT1337#virtual'
PAIR = '12345678-1234-1234-1234-123456789abc'

class Host:
    display = {'adapter': 'windows', 'device_id': DEVICE}
    def __init__(self):
        self.calls = []
        self.result = {'phase': 'idle', 'owner': '', 'active': [{'id': 'internal'}]}
        self.fail = None
    def remote(self, operation, **values):
        self.calls.append((operation, values.copy()))
        if self.fail:
            raise self.fail
        if operation == 'prepare':
            self.result = {'owner': values['owner'], 'phase': 'preparing', 'active': [{'id': DEVICE}]}
        if operation == 'restore':
            self.result['phase'] = 'restore-pending'
        return copy.deepcopy(self.result)

class WindowsTests(unittest.TestCase):
    def setUp(self):
        self.record = {}
        self.host = Host()
        self.saved = []
    def persist(self):
        self.saved.append(copy.deepcopy(self.record))
    def test_reconnect_keeps_owner_and_advances_sequence(self):
        w.prepare(self.record, self.host, self.persist)
        owner = self.record['journal']['windows']['owner']
        w.prepare(self.record, self.host, self.persist)
        self.assertEqual(self.record['journal']['windows']['owner'], owner)
        self.assertEqual(self.record['journal']['windows']['sequence'], 2)
    def test_timeout_after_prepare_keeps_recovery_identity(self):
        self.host.fail = subprocess.TimeoutExpired('ssh', 35)
        with self.assertRaises(subprocess.TimeoutExpired):
            w.prepare(self.record, self.host, self.persist)
        self.assertEqual(self.saved[0]['journal']['windows']['phase'], 'intent')
        self.host.fail = None
        self.assertFalse(w.restore(self.record, self.host, self.persist))
        self.assertEqual(self.host.calls[-1][0], 'restore')
        self.assertEqual(self.host.calls[-1][1]['sequence'], 2)
    def test_pending_until_physical_readback_and_virtual_is_disabled(self):
        w.prepare(self.record, self.host, self.persist)
        self.assertFalse(w.restore(self.record, self.host, self.persist))
        self.host.result.update(phase='idle', active=[{'id': DEVICE}])
        self.assertFalse(w.restore(self.record, self.host, self.persist))
        self.host.result['active'] = []
        self.assertFalse(w.restore(self.record, self.host, self.persist))
        self.host.result['active'] = [{'id': 'internal'}]
        self.assertTrue(w.restore(self.record, self.host, self.persist))
        self.assertEqual(self.record['journal'], {})
        self.assertEqual([c[0] for c in self.host.calls], ['prepare', 'restore', 'status', 'status', 'status'])
    def test_failed_restore_ack_is_retried_as_restore_not_status(self):
        w.prepare(self.record, self.host, self.persist)
        self.host.fail = ValueError('lost reply')
        with self.assertRaises(ValueError):
            w.restore(self.record, self.host, self.persist)
        self.host.fail = None
        w.restore(self.record, self.host, self.persist)
        self.assertEqual(self.host.calls[-1][0], 'restore')
        self.assertEqual(self.host.calls[-1][1]['sequence'], 3)
    def test_helper_error_prevents_false_restoration_success(self):
        w.prepare(self.record, self.host, self.persist)
        w.restore(self.record, self.host, self.persist)
        self.host.result.update(phase='idle', active=[{'id': 'internal'}], error='identity mismatch')
        self.assertFalse(w.restore(self.record, self.host, self.persist))
    def test_transport_rejects_wrong_pairing_and_shell_alias(self):
        computer = {'ssh': {'alias': 'work-laptop'}, 'pairing_uuid': PAIR}
        with patch.object(w, 'powershell', return_value={'ok': True, 'result': {'pairing_uuid': 'other', 'capture_id': DEVICE}}):
            with self.assertRaisesRegex(ValueError, 'identity'):
                w.remote(computer, self.host.display, 'probe')
        with self.assertRaisesRegex(ValueError, 'alias'):
            w.powershell('-oProxyCommand=bad', '')

class VirtualModeTests(unittest.TestCase):
    def test_reload_failure_is_actionable(self):
        from remote_desktops import virtual_display
        with patch.object(virtual_display.windows_display, "powershell", return_value={"ok": False, "error": "virtual-display-reload-failed: retry"}):
            with self.assertRaisesRegex(ValueError, "virtual-display-reload-failed"):
                virtual_display.sync("fake-pc", "1920x1080", refresh=120)


if __name__ == '__main__':
    unittest.main()
