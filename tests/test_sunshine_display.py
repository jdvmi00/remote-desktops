"""Synthetic launch evidence; no real SSH host or display is used."""
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from remote_desktops import sunshine_display as sd

UUID = '11111111-2222-3333-4444-555555555555'
OUTPUT = '{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}'


class SunshineDisplayTests(unittest.TestCase):
    def setUp(self):
        self.host = SimpleNamespace(computer={'ssh': {'alias': 'fake-pc'}, 'pairing_uuid': UUID},
                                    display={'adapter': 'virtual', 'output': OUTPUT})
        self.record = {'stream_resolution': '1102x1246', 'resolved': {},
                       'display_observation': {'offset': 100, 'created': '1', 'started': time.time()}}
        self.reply = {'ok': True, 'options': {'output_name': OUTPUT, 'dd_configuration_option': 'ensure_only_display',
                                             'dd_resolution_option': 'auto'}, 'created': '1', 'offset': 200,
                      'text': 'Using the following configuration:\n' + json.dumps({'device_id': OUTPUT, 'resolution': {'width': 1102, 'height': 1246}}) + '\nInfo: Desktop resolution [1102x1246]\n'}

    def test_fresh_matching_capture_verifies_host_resolution(self):
        with patch.object(sd.windows_display, 'powershell', return_value=self.reply) as remote:
            sd.health(self.record, self.host)
        observed = self.record['resolved']['host_display']
        self.assertTrue(observed['verified'])
        self.assertEqual(observed['resolution'], '1102x1246')
        self.assertIn('$offset=100', remote.call_args.args[1])

    def test_missing_selected_display_is_rejected_even_when_fallback_size_matches(self):
        self.reply['text'] += f'Error: Device "{OUTPUT}" is not available in the system!\n'
        with patch.object(sd.windows_display, 'powershell', return_value=self.reply):
            with self.assertRaisesRegex(ValueError, 'capture-display-unavailable'):
                sd.health(self.record, self.host)
        self.assertFalse(self.record['resolved']['host_display']['verified'])

    def test_wrong_resolution_revokes_previous_verification(self):
        self.record['resolved']['host_display'] = {'verified': True}
        self.reply['text'] = self.reply['text'].replace('1102x1246', '6144x2560')
        with patch.object(sd.windows_display, 'powershell', return_value=self.reply):
            with self.assertRaisesRegex(ValueError, 'display-resolution-mismatch'):
                sd.health(self.record, self.host)
        self.assertFalse(self.record['resolved']['host_display']['verified'])

    def test_capture_size_without_selected_identity_does_not_verify(self):
        self.reply['text'] = 'Info: Desktop resolution [1102x1246]\n'
        with patch.object(sd.windows_display, 'powershell', return_value=self.reply):
            sd.health(self.record, self.host)
            self.assertFalse(self.record['resolved']['host_display']['verified'])
            self.record['display_observation']['started'] -= 31
            with self.assertRaisesRegex(ValueError, 'display-unverified'):
                sd.health(self.record, self.host)

    def test_log_rotation_and_changed_output_are_rejected(self):
        for field, value, error in [('created', 'new-log', 'display-verification-lost'),
                                     ('options', {**self.reply['options'], 'output_name': '{' + UUID + '}'}, 'capture-display-changed')]:
            with self.subTest(field=field), patch.object(sd.windows_display, 'powershell', return_value={**self.reply, field: value}):
                with self.assertRaisesRegex(ValueError, error):
                    sd.health(self.record, self.host)

    def test_invalid_sunshine_resolution_setting_is_rejected(self):
        self.reply['options']['dd_resolution_option'] = 'automatic'
        with patch.object(sd.windows_display, 'powershell', return_value=self.reply):
            with self.assertRaisesRegex(ValueError, 'display-configuration-required'):
                sd.snapshot(self.host)

    def test_begin_excludes_preexisting_log_and_clears_old_verification(self):
        self.record['resolved']['host_display'] = {'verified': True}
        with patch.object(sd.windows_display, 'powershell', return_value=self.reply) as remote:
            sd.begin(self.record, self.host, lambda: None)
        self.assertEqual(self.record['display_observation']['offset'], 200)
        self.assertFalse(self.record['resolved']['host_display']['verified'])
        self.assertIn('$offset=-1', remote.call_args.args[1])

    def test_unreachable_host_revokes_verification(self):
        self.record['resolved']['host_display'] = {'verified': True}
        with patch.object(sd.windows_display, 'powershell', side_effect=ValueError('host-unreachable')):
            with self.assertRaisesRegex(ValueError, 'host-unreachable'):
                sd.health(self.record, self.host)
        self.assertFalse(self.record['resolved']['host_display']['verified'])

    def test_long_session_log_bound_revokes_verification_without_advancing_cursor(self):
        for update in ({'text': 'x' * 65537}, {'offset': 100 + 131073}, {'offset': 99}):
            with self.subTest(update=list(update)):
                self.record['resolved']['host_display'] = {'verified': True}
                with patch.object(sd.windows_display, 'powershell', return_value={**self.reply, **update}):
                    with self.assertRaisesRegex(ValueError, 'display-verification-lost'):
                        sd.health(self.record, self.host)
                self.assertFalse(self.record['resolved']['host_display']['verified'])
                self.assertEqual(self.record['display_observation']['offset'], 100)

    def test_later_launch_cannot_reuse_an_earlier_matching_capture(self):
        self.reply['text'] += 'Using the following configuration:\n' + json.dumps({
            'device_id': '{' + UUID + '}', 'resolution': {'width': 1102, 'height': 1246}})
        self.reply['text'] += '\nDesktop resolution [1102x1246]'
        with patch.object(sd.windows_display, 'powershell', return_value=self.reply):
            with self.assertRaisesRegex(ValueError, 'capture-display-changed'):
                sd.health(self.record, self.host)

    def test_partial_launch_does_not_reuse_previous_capture(self):
        self.reply['text'] += 'Using the following configuration:\n{'
        with patch.object(sd.windows_display, 'powershell', return_value=self.reply):
            sd.health(self.record, self.host)
        self.assertFalse(self.record['resolved']['host_display']['verified'])
