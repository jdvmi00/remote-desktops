"""Host policy safety and transport tests; no real host, service, or sleep calls."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from remote_desktops import host_power, linux_power_host as power


class HostPowerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.root = self.home / '.local/share/remote-desktops/host-power'
        self.runtime = self.home / 'runtime/remote-desktops-host-power'
        self.hypr = self.home / '.config/hypr/hyprland.lua'
        self.hypr.parent.mkdir(parents=True)
        self.hypr.write_text('-- my desktop\nrequire("user")\n')
        self.home_patch = patch.object(Path, 'home', return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        self.loc_patch = patch.object(power, 'locations', return_value=(self.root, self.runtime))
        self.loc_patch.start()
        self.addCleanup(self.loc_patch.stop)
        self.compositor_patch = patch.object(power, 'hyprland_command', return_value=['hyprctl'])
        self.compositor_patch.start()
        self.addCleanup(self.compositor_patch.stop)
        self.request = {'operation': 'configure', 'policy': 'ac',
                        'pairing_uuid': '11111111-2222-3333-4444-555555555555', 'source': '# helper\n'}
        self.observed = {'installed': False, 'supported': True, 'policy': 'off', 'stream_workers': 0,
                         'binary_hash': 'abc', 'active': False, 'running': False}

    def test_ssh_discovers_one_compositor_and_rejects_ambiguous_sessions(self):
        self.compositor_patch.stop()
        with patch.dict(os.environ, {}, clear=True), patch.object(power, 'run') as run:
            run.return_value = json.dumps([{'instance': 'example_123'}])
            self.assertEqual(power.hyprland_command(), ['hyprctl', '-i', 'example_123'])
            run.assert_called_once_with(['hyprctl', 'instances', '-j'])
            for instances in ([], [{'instance': 'one'}, {'instance': 'two'}]):
                run.return_value = json.dumps(instances)
                with self.assertRaisesRegex(ValueError, 'session-ambiguous'):
                    power.hyprland_command()
            run.return_value = '[{"instance": "-bad"}]'
            with self.assertRaisesRegex(ValueError, 'session-unavailable'):
                power.hyprland_command()

    def test_existing_compositor_environment_is_used(self):
        self.compositor_patch.stop()
        with patch.dict(os.environ, {'HYPRLAND_INSTANCE_SIGNATURE': 'current'}), patch.object(power, 'run') as run:
            self.assertEqual(power.hyprland_command(), ['hyprctl'])
            run.assert_not_called()

    def fake_process(self, pid=10, workers=2):
        proc = self.home / 'proc'
        base = proc / str(pid)
        (base / 'task').mkdir(parents=True, exist_ok=True)
        (base / 'stat').write_text(str(pid) + ' (a name (with brackets)) S ' + '0 ' * 18 + '12345 0\n')
        binary = self.home / 'sunshine'
        binary.touch()
        (base / 'exe').symlink_to(binary)
        for n, name in enumerate(['other'] + ['session::video'] * workers):
            task = base / 'task' / str(n)
            task.mkdir()
            (task / 'comm').write_text(name + '\n')
        return proc, binary

    def test_live_workers_and_process_identity(self):
        proc, binary = self.fake_process()
        self.assertEqual(power.stream_count(10, binary, proc), 2)
        self.assertEqual(power.process_start(10, proc), '12345')
        with self.assertRaisesRegex(ValueError, 'process-changed'):
            power.stream_count(10, self.home / 'different', proc)
        self.assertEqual(power.stream_count(10, binary, proc), 2)
        (proc / '10/task/1/comm').write_text('stopped\n')
        (proc / '10/task/2/comm').write_text('stopped\n')
        self.assertEqual(power.stream_count(10, binary, proc), 0)

    def test_ac_power_unknown_battery_and_external_power(self):
        root = self.home / 'power'
        root.mkdir()
        self.assertFalse(power.on_ac(root))
        battery = root / 'BAT0'
        battery.mkdir()
        (battery / 'type').write_text('Battery')
        (battery / 'status').write_text('Discharging')
        self.assertFalse(power.on_ac(root))
        adapter = root / 'AC'
        adapter.mkdir()
        (adapter / 'type').write_text('Mains')
        (adapter / 'online').write_text('1')
        self.assertTrue(power.on_ac(root))
        (adapter / 'online').write_text('0')
        (battery / 'status').write_text('Full')
        self.assertFalse(power.on_ac(root))
        (adapter / 'online').unlink()
        self.assertFalse(power.on_ac(root))

    def test_dead_or_expired_lease_never_bypasses_lid(self):
        proc, _ = self.fake_process(workers=0)
        self.runtime.mkdir(parents=True)
        value = {'version': 1, 'pid': 10, 'start': '12345', 'heartbeat': 100}
        power.write(self.runtime / 'lease.json', json.dumps(value))
        self.assertTrue(power.lease_valid(self.runtime, proc, now=103))
        self.assertFalse(power.lease_valid(self.runtime, proc, now=107))
        self.assertFalse(power.lease_valid(self.runtime, proc, now=99))
        value['start'] = 'recycled-pid'
        power.write(self.runtime / 'lease.json', json.dumps(value))
        self.assertFalse(power.lease_valid(self.runtime, proc, now=103))
        with patch.object(power, 'lease_valid', return_value=False), patch.object(power, 'run') as run:
            power.lid_close()
            run.assert_called_once()
        with patch.object(power, 'lease_valid', return_value=True), patch.object(power, 'run') as run:
            power.lid_close()
            run.assert_not_called()

    def test_hold_releases_lease_on_parent_eof(self):
        fake_input = type('Input', (), {'buffer': io.BytesIO(), 'fileno': lambda self: 0})()
        with patch.object(power.sys, 'stdin', fake_input), patch.object(power.select, 'select', return_value=([0], [], [])), \
                patch.object(power.os, 'read', return_value=b''):
            power.hold(self.runtime)
        self.assertFalse((self.runtime / 'lease.json').exists())

    def test_hold_releases_lease_when_parent_stops_heartbeats(self):
        fake_input = type('Input', (), {'buffer': io.BytesIO()})()
        with patch.object(power.sys, 'stdin', fake_input), patch.object(power.select, 'select', return_value=([], [], [])):
            power.hold(self.runtime)
        self.assertFalse((self.runtime / 'lease.json').exists())

    def test_policy_requires_a_stream_and_ac_when_selected(self):
        for policy in ('off', 'ac', 'always'):
            self.assertFalse(power.eligible(0, policy, True))
        self.assertFalse(power.eligible(1, 'off', True))
        self.assertFalse(power.eligible(1, 'ac', False))
        self.assertTrue(power.eligible(2, 'ac', True))
        self.assertTrue(power.eligible(1, 'always', False))

    def test_unresponsive_or_wrong_host_releases_observation(self):
        state = self.home / '.config/sunshine/sunshine_state.json'
        state.parent.mkdir(parents=True)
        identity = self.request['pairing_uuid']
        state.write_text(json.dumps({'root': {'uniqueid': identity}}))
        config = {'pairing_uuid': identity, 'binary_hash': 'abc'}
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = ('<root><uniqueid>' + identity + '</uniqueid></root>').encode()
        with patch.object(power, 'binary_hash', return_value='abc'), patch.object(power, 'run', return_value='10'), \
                patch.object(power.http.client, 'HTTPConnection', return_value=connection), \
                patch.object(power, 'stream_count', return_value=6), patch.object(power, 'on_ac', return_value=True):
            self.assertEqual(power.observation(config), (6, True))
            response.read.return_value = b'<root><uniqueid>wrong-host</uniqueid></root>'
            with self.assertRaisesRegex(ValueError, 'server-identity-changed'):
                power.observation(config)
            connection.request.side_effect = TimeoutError('stopped process')
            with self.assertRaises(TimeoutError):
                power.observation(config)
        self.assertEqual(connection.close.call_count, 3)

    def test_watcher_holds_until_last_client_and_releases_on_unknown_state(self):
        self.root.mkdir(parents=True)
        (self.root / 'policy.json').write_text(json.dumps({'version': 1, 'policy': 'ac'}))
        for samples in ([(2, True), (1, True), (0, True)], [(1, True), (1, False)],
                        [(1, True), ValueError('Sunshine replaced')]):
            child = MagicMock()
            child.poll.return_value = None
            with patch.object(power, 'observation', side_effect=samples), \
                    patch.object(power.subprocess, 'Popen', return_value=child) as spawn, \
                    patch.object(power, 'lease_valid', return_value=True), \
                    patch.object(power.signal, 'signal'), \
                    patch.object(power.time, 'sleep', side_effect=[None] * (len(samples) - 1) + [KeyboardInterrupt]):
                with self.assertRaises(KeyboardInterrupt):
                    power.watch()
            self.assertEqual(spawn.call_count, 1)
            self.assertIn('--what=sleep:idle:handle-lid-switch', spawn.call_args.args[0])
            child.stdin.close.assert_called_once()
            child.wait.assert_called_once()

    def test_install_and_disable_preserve_user_configuration(self):
        before = self.hypr.read_text()
        with patch.object(power, 'inspect', return_value=self.observed), patch.object(power, 'run', return_value='') as run, \
                patch.object(power.subprocess, 'run'):
            power.configure(self.request)
            self.assertIn(['systemd-run', '--user', '--wait', '--pipe', '--collect', '--quiet',
                           'systemd-inhibit', '--what=sleep:idle:handle-lid-switch', '--mode=block', '/usr/bin/true'],
                          [c.args[0] for c in run.call_args_list])
            self.assertIn('o.rebind(', self.hypr.read_text())
            self.assertIn(before, self.hypr.read_text())
            self.assertEqual(json.loads((self.root / 'policy.json').read_text())['policy'], 'ac')
            self.request['policy'] = 'off'
            power.configure(self.request)
        self.assertEqual(self.hypr.read_text().strip(), before.strip())

    def test_active_clients_unknown_build_and_custom_binding_refuse_install(self):
        before = self.hypr.read_bytes()
        for update, message in [({'stream_workers': 2}, 'streams-active'), ({'supported': False}, 'unsupported-sunshine')]:
            observed = dict(self.observed, **update)
            with patch.object(power, 'inspect', return_value=observed), self.assertRaisesRegex(ValueError, message):
                power.configure(self.request)
            self.assertEqual(self.hypr.read_bytes(), before)
        self.hypr.write_text('o.bind("switch:on:Lid Switch", nil, "custom")\n')
        with patch.object(power, 'inspect', return_value=self.observed), self.assertRaisesRegex(ValueError, 'custom-lid-binding'):
            power.configure(self.request)

    def test_configuration_failure_restores_files_and_previous_service(self):
        before = self.hypr.read_bytes()
        self.root.mkdir(parents=True)
        original = {'policy': 'always'}
        (self.root / 'policy.json').write_text(json.dumps(original))
        with patch.object(power, 'inspect', return_value=self.observed), \
                patch.object(power, 'run', side_effect=['', '', 'syntax error']), patch.object(power.subprocess, 'run') as commands:
            with self.assertRaisesRegex(ValueError, 'hyprland-config-error'):
                power.configure(self.request)
        self.assertEqual(self.hypr.read_bytes(), before)
        self.assertEqual(json.loads((self.root / 'policy.json').read_text()), original)
        self.assertFalse((self.root / 'host.py').exists())
        self.assertIn(['systemctl', '--user', 'start', power.UNIT], [c.args[0] for c in commands.call_args_list])

    def test_malformed_managed_block_and_symlink_refused(self):
        for text in [power.BEGIN, power.END, power.END + '\n' + power.BEGIN]:
            with self.assertRaises(ValueError):
                power.lid_config(text)
        other = self.home / 'other'
        other.write_text('unchanged')
        self.hypr.unlink()
        self.hypr.symlink_to(other)
        with patch.object(power, 'inspect', return_value=self.observed), patch.object(power, 'run') as run, \
                self.assertRaisesRegex(ValueError, 'symlink-refused'):
            power.configure(self.request)
        run.assert_not_called()
        self.assertEqual(other.read_text(), 'unchanged')

    def test_rollback_preserves_a_concurrent_user_edit(self):
        def command(argv, **kwargs):
            if argv == ['hyprctl', 'configerrors']:
                self.hypr.write_text('-- user edited during setup\n')
                return 'configuration error'
            return ''
        with patch.object(power, 'inspect', return_value=self.observed), patch.object(power, 'run', side_effect=command), \
                patch.object(power.subprocess, 'run'):
            with self.assertRaisesRegex(ValueError, 'restore-conflict'):
                power.configure(self.request)
        self.assertEqual(self.hypr.read_text(), '-- user edited during setup\n')

    def test_ssh_transport_checks_alias_platform_and_redacts_errors(self):
        computer = {'platform': 'linux', 'ssh': {'alias': '-oProxyCommand=bad'}, 'pairing_uuid': self.request['pairing_uuid']}
        with self.assertRaisesRegex(ValueError, 'ssh-required'):
            host_power.remote(computer, 'status')
        computer['ssh']['alias'] = 'test-host'
        computer['platform'] = 'windows'
        with self.assertRaisesRegex(ValueError, 'requires-linux'):
            host_power.remote(computer, 'status')
        computer['platform'] = 'linux'
        reply = subprocess.CompletedProcess([], 0, json.dumps({'ok': True, 'result': {'policy': 'ac'}}), '')
        with patch.object(host_power.subprocess, 'run', return_value=reply) as run:
            self.assertEqual(host_power.remote(computer, 'status'), {'policy': 'ac'})
            argv = run.call_args.args[0]
            self.assertIn('StrictHostKeyChecking=yes', argv)
            self.assertEqual(argv[-2:], ['test-host', 'python3 -'])
        reply = subprocess.CompletedProcess([], 1, '', 'secret diagnostic')
        with patch.object(host_power.subprocess, 'run', return_value=reply), self.assertRaisesRegex(ValueError, '^host-power-ssh-failed:'):
            host_power.remote(computer, 'status')


if __name__ == '__main__':
    unittest.main()
