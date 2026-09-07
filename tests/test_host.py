"""Host recovery regression cases ported from Hypertile, MIT."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from remote_desktops import host as s, mac_display

IDENTITY = "12345678-1234-1234-1234-123456789ABC"

MODE = {"resolution": "1920x1080", "hidpi": True, "refresh": 60}

OLD = {"resolution": "2560x1440", "hidpi": False, "refresh": 60}

BUILTIN = "AAAAAAAA-1234-1234-1234-123456789ABC"

PANEL = {"resolution": "1728x1117", "hidpi": True, "refresh": "ProMotion"}

def computer(adapter="external"):
    display = {"adapter": adapter}
    if adapter != "external":
        display.update(uuid=IDENTITY, mode=MODE, require_ac=True)
    return {"host": "laptop.example", "pairing_uuid": IDENTITY, "title": "Laptop - Moonlight",
            "ssh": {"user": "tester"}, "profiles": {"desktop": {"stream_resolution": "2560x1440", "display": display}}}

class Host:
    def __init__(self, adapter="betterdisplay"):
        self.display = computer(adapter)["profiles"]["desktop"]["display"]
        self.current = {"mode": copy.deepcopy(OLD), "output": "1"}
        self.calls = []
        self.error = None
        self.fail_field = None
        self.before_change = None
        self.ac_power = True
        self.topology = {"lid_closed": True, "display_id": "5"}

    def probe(self, pairing=True):
        if self.error:
            raise ValueError(self.error)
        return {"current": copy.deepcopy(self.current), "identity": {"UUID": IDENTITY, "displayID": self.topology["display_id"]},
                "ac_power": self.ac_power, "modes": [MODE, OLD], "topology": copy.deepcopy(self.topology)}

    def remote(self, operation):
        return self.probe(False)

    def change(self, field, expected, value):
        if self.before_change:
            self.before_change(field, expected, value)
        if field == self.fail_field:
            raise ValueError("injected host failure")
        if self.current[field] != expected:
            raise ValueError("restore-conflict")
        self.calls.append((field, copy.deepcopy(value)))
        self.current[field] = copy.deepcopy(value)

class MainHost(Host):
    """Two physical panels with independent modes and one Sunshine output."""
    def __init__(self):
        super().__init__()
        self.display["follow_main"] = True
        self.identity = IDENTITY
        self.panels = {IDENTITY: copy.deepcopy(OLD), BUILTIN: copy.deepcopy(PANEL)}
        self.available = {IDENTITY, BUILTIN}
        self.refreshes = 0

    def switch(self, identity, lid_closed):
        self.panels[self.identity] = copy.deepcopy(self.current["mode"])
        self.identity = identity
        self.current["mode"] = copy.deepcopy(self.panels[identity])
        self.topology = {"lid_closed": lid_closed, "display_id": "5" if identity == IDENTITY else "1",
                         "display_uuid": identity}

    def probe(self, pairing=True):
        observed = super().probe(pairing)
        observed["identity"]["UUID"] = self.identity
        return observed

    def remote(self, operation, **values):
        if operation == "refresh":
            if values["expected_identity"] != self.identity or values["expected"] != self.current:
                raise ValueError("display-topology-changed")
            self.refreshes += 1
            return {}
        return self.probe(False)

    def change(self, field, expected, value, **guards):
        if guards.get("expected_identity", self.identity) != self.identity:
            raise ValueError("display-topology-changed")
        super().change(field, expected, value)
        self.panels[self.identity] = copy.deepcopy(self.current["mode"])

    def for_display(self, identity):
        owner = self
        class Pinned:
            def remote(self, operation):
                if identity not in owner.available:
                    raise ValueError("display-missing")
                result = owner.probe(False)
                result["current"]["mode"] = copy.deepcopy(owner.panels[identity])
                result["identity"] = {"UUID": identity, "displayID": "5" if identity == IDENTITY else "1"}
                result["topology"].update(display_uuid=identity, display_id=result["identity"]["displayID"])
                return result

            def change(self, field, expected, value):
                assert field == "mode"
                if owner.panels[identity] != expected:
                    raise ValueError("restore-conflict")
                owner.panels[identity] = copy.deepcopy(value)
                if owner.identity == identity:
                    owner.current["mode"] = copy.deepcopy(value)
                owner.calls.append(("restore-mode", identity))
        return Pinned()

class RecoveryTests(unittest.TestCase):
    def test_duplicate_window_titles_are_rejected_for_stable_launcher_matching(self):
        first, second = computer(), computer()
        second["pairing_uuid"] = BUILTIN
        self.config.write_text(json.dumps({"version": 1, "computers": {"one": first, "two": second}}))
        with self.assertRaisesRegex(ValueError, "window titles must be unique"):
            s.configuration(self.config)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = self.root / "computers.json"
        self.host = Host("external")


    def test_original_and_intent_are_durable_before_every_write(self):
        host = Host()
        record = {}
        saved = []
        def persist():
            saved.append(copy.deepcopy(record))
        def before(field, expected, value):
            self.assertEqual(saved[-1]["journal"][field]["original"], expected)
            self.assertEqual(saved[-1]["journal"][field]["applied"], value)
        host.before_change = before
        s.prepare(record, host, persist)
        self.assertEqual(record["journal"]["mode"]["original"], OLD)
        host.before_change = None
        s.prepare(record, host, persist)  # Reconnect keeps the first baseline.
        self.assertEqual(len(host.calls), 2)
        self.assertTrue(s.restore(record, host, persist))
        self.assertEqual(host.current["mode"], OLD)

    def test_partial_prepare_rolls_back_only_changes_that_happened(self):
        host, record = Host(), {}
        host.fail_field = "mode"
        with self.assertRaises(ValueError):
            s.prepare(record, host, lambda: None)
        host.fail_field = None
        self.assertTrue(s.restore(record, host, lambda: None))
        self.assertEqual(host.current, {"mode": OLD, "output": "1"})
        self.assertEqual([field for field, _ in host.calls], ["output", "output"])

    def test_crash_after_apply_recovers_intent_without_rebaselining(self):
        host, record = Host(), {}
        record["journal"] = {"mode": {"original": OLD, "applied": MODE, "phase": "intent"}}
        host.current = {"mode": copy.deepcopy(MODE), "output": "5"}
        s.prepare(record, host, lambda: None)
        self.assertEqual(record["journal"]["mode"]["original"], OLD)
        self.assertFalse(host.calls)
        self.assertTrue(s.restore(record, host, lambda: None))

    def test_manual_changes_preserved_and_conflict_persisted(self):
        host, record = Host(), {}
        s.prepare(record, host, lambda: None)
        manual = {"resolution": "1280x720", "hidpi": True, "refresh": 60}
        host.current["mode"] = manual
        self.assertFalse(s.restore(record, host, lambda: None))
        self.assertEqual(host.current["mode"], manual)
        self.assertEqual(record["journal"]["mode"]["phase"], "conflict")
        self.assertEqual(host.current["output"], "1")

    def test_lid_recovery_tracks_new_numeric_id_for_same_display(self):
        host, record = Host(), {}
        s.prepare(record, host, lambda: None)
        host.topology = {"lid_closed": False, "display_id": "7"}
        record["display_recovery"] = {"current": copy.deepcopy(host.current), "topology": copy.deepcopy(host.topology)}
        s.prepare(record, host, lambda: None)
        self.assertEqual(host.current["output"], "7")
        self.assertEqual(record["journal"]["output"]["original"], "1")
        self.assertEqual(record["journal"]["output"]["applied"], "7")
        self.assertTrue(s.restore(record, host, lambda: None))
        self.assertEqual(host.current["output"], "1")

    def test_lid_recovery_rejects_changes_after_it_was_requested(self):
        for change in ("mode", "topology"):
            with self.subTest(change=change):
                host, record = Host(), {}
                s.prepare(record, host, lambda: None)
                host.topology["lid_closed"] = False
                host.current["mode"] = {"resolution": "6144x2560", "hidpi": False, "refresh": 60}
                record["display_recovery"] = {"current": copy.deepcopy(host.current), "topology": copy.deepcopy(host.topology)}
                if change == "mode":
                    host.current["mode"] = {"resolution": "1280x720", "hidpi": False, "refresh": 60}
                else:
                    host.topology["lid_closed"] = True
                calls = len(host.calls)
                with self.assertRaises(ValueError):
                    s.prepare(record, host, lambda: None)
                self.assertEqual(len(host.calls), calls)

    def test_main_screen_switch_restores_only_the_old_panel(self):
        host, record = MainHost(), {}
        s.prepare(record, host, lambda: None)
        self.assertEqual(record["journal"]["mode"]["display_uuid"], IDENTITY)
        host.switch(BUILTIN, False)
        self.recover_main(host, record)
        self.assertEqual(host.current, {"mode": PANEL, "output": "1"})
        self.assertEqual(host.panels[IDENTITY], OLD)
        self.assertNotIn("mode", record["journal"])
        self.assertEqual(record["journal"]["output"]["original"], "1")
        # Simulate the durable record being loaded after a controller restart.
        record = json.loads(json.dumps(record))
        host.switch(IDENTITY, True)
        self.recover_main(host, record)
        self.assertEqual(host.current, {"mode": MODE, "output": "5"})
        self.assertTrue(s.restore(record, host, lambda: None))
        self.assertEqual(host.current, {"mode": OLD, "output": "1"})
        self.assertEqual(host.panels[BUILTIN], PANEL)

    def test_unplugged_mode_restore_does_not_target_the_builtin_panel(self):
        host, record = MainHost(), {}
        s.prepare(record, host, lambda: None)
        host.switch(BUILTIN, False)
        host.available.remove(IDENTITY)
        self.recover_main(host, record)
        self.assertEqual(host.current, {"mode": PANEL, "output": "1"})
        self.assertEqual(record["journal"]["mode"]["phase"], "unavailable")
        self.assertFalse(s.restore(record, host, lambda: None))
        host.available.add(IDENTITY)
        self.assertTrue(s.restore(record, host, lambda: None))
        self.assertEqual(host.panels[IDENTITY], OLD)
        self.assertEqual(host.panels[BUILTIN], PANEL)

    def test_main_screen_does_not_require_or_apply_external_mode(self):
        host = MainHost()
        host.switch(BUILTIN, False)
        profile = computer("betterdisplay")["profiles"]["desktop"]
        profile["display"]["follow_main"] = True
        native = s.Host(computer("betterdisplay"), profile)
        native.remote = lambda *_: {**host.probe(False), "modes": [PANEL]}
        native.probe(pairing=False)  # A 16:9 mode is absent from this panel.
        record = {}
        s.prepare(record, host, lambda: None)
        self.assertEqual(host.current["mode"], PANEL)
        self.assertEqual(host.calls, [])
        self.assertEqual(host.refreshes, 1)
        self.assertTrue(s.same_setting("mode", PANEL, PANEL.copy()))
        self.assertFalse(s.same_setting("mode", PANEL, {**PANEL, "refresh": 60}))

    def test_main_screen_switch_replays_after_output_write_crash(self):
        host, record = MainHost(), {}
        s.prepare(record, host, lambda: None)
        host.switch(BUILTIN, False)
        health = host.probe(False)
        record["display_recovery"] = {"current": health["current"], "topology": health["topology"]}
        # Crash after the output write, before the readback/phase update.
        saved = []
        def persist():
            saved[:] = [copy.deepcopy(record)]
        change = host.change
        def crash(field, expected, value, **guards):
            change(field, expected, value, **guards)
            if field == "output":
                raise RuntimeError("crash")
        host.change = crash
        with self.assertRaisesRegex(RuntimeError, "crash"):
            s.prepare(record, host, persist)
        host.change = change
        record = saved[0]
        s.prepare(record, host, lambda: None)
        self.assertEqual(record["journal"]["output"]["original"], "1")
        self.assertEqual(host.current, {"mode": PANEL, "output": "1"})
        self.assertTrue(s.restore(record, host, lambda: None))

    def test_native_profile_needs_no_betterdisplay_uuid_or_mode(self):
        c = computer()
        c["platform"] = "macos"
        c["profiles"]["desktop"]["display"] = {"adapter": "macos"}
        self.config.write_text(json.dumps({"version": 1, "computers": {"laptop": c}}))
        s.configuration(self.config)
        h = s.Host(c, c["profiles"]["desktop"])
        observed = {"identity": {"UUID": BUILTIN, "displayID": "1"}, "current": {"mode": PANEL, "output": "1"},
                    "modes": [], "ac_power": True, "topology": {"lid_closed": False, "display_id": "1"}}
        h.remote = Mock(return_value=observed)
        record = {}
        s.prepare(record, h, lambda: None)
        self.assertEqual(record["journal"], {})
        self.assertFalse(any(call.args[0] == "change" for call in h.remote.call_args_list))
        self.assertEqual(h.remote.call_args.args[0], "refresh")

    def test_native_adapter_never_invokes_betterdisplay_or_changes_mode(self):
        directory = self.root / ".config/sunshine"
        directory.mkdir(parents=True)
        (directory / "sunshine_state.json").write_text(json.dumps({"root": {"uniqueid": IDENTITY}}))
        (directory / "sunshine.conf").write_text("output_name = 1\n")
        request = {"adapter": "macos", "pairing_uuid": IDENTITY, "operation": "probe"}
        def run(argv):
            self.assertNotIn(mac_display.BETTER, argv)
            return "AC Power" if argv[0] == "/usr/bin/pmset" else '"AppleClamshellState" = No'
        with patch.object(Path, "home", return_value=self.root), \
             patch.object(mac_display, "native_display", return_value=({"UUID": BUILTIN, "displayID": "1"}, PANEL, "3456x2234")), \
             patch.object(mac_display, "run", side_effect=run), \
             patch.object(mac_display, "restart_sunshine") as restart:
            result = mac_display.display(request)
            self.assertEqual(result["current"]["mode"], PANEL)
            self.assertEqual(result["render_resolution"], "3456x2234")
            with self.assertRaisesRegex(ValueError, "preserves the host mode"):
                mac_display.display({**request, "operation": "change", "field": "mode", "expected": PANEL, "value": MODE})
            restart.assert_not_called()

    def test_mac_main_identity_race_is_rejected_before_writing(self):
        directory = self.root / ".config/sunshine"
        directory.mkdir(parents=True)
        (directory / "sunshine_state.json").write_text(json.dumps({"root": {"uniqueid": IDENTITY}}))
        graphics = Mock()
        graphics.CGMainDisplayID.return_value = 1
        with patch.object(Path, "home", return_value=self.root), \
             patch.object(mac_display.ctypes, "CDLL", return_value=graphics), \
             patch.object(mac_display, "run", return_value=json.dumps({"UUID": BUILTIN, "displayID": "1"})) as run, \
             patch.object(mac_display, "restart_sunshine") as restart:
            with self.assertRaisesRegex(ValueError, "display-topology-changed"):
                mac_display.display({"pairing_uuid": IDENTITY, "display_uuid": IDENTITY, "follow_main": True,
                                     "expected_identity": IDENTITY, "operation": "change", "field": "mode",
                                     "expected": OLD, "value": MODE})
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][1], "get")
            restart.assert_not_called()

    def test_nominal_refresh_tolerance_does_not_hide_other_mode_changes(self):
        actual = {**MODE, "refresh": 59.95}
        self.assertTrue(s.same_setting("mode", MODE, actual))
        self.assertFalse(s.same_setting("mode", MODE, {**actual, "refresh": 50}))
        self.assertFalse(s.same_setting("mode", MODE, {**actual, "hidpi": False}))
        host = Host()
        host.current = {"mode": actual, "output": "5"}
        record = {"journal": {"mode": {"original": OLD, "applied": MODE, "phase": "intent"}}}
        s.prepare(record, host, lambda: None)
        self.assertTrue(s.restore(record, host, lambda: None))

    def test_invalid_configuration_rejected(self):
        for edit in (lambda c: c.update(host="-oProxyCommand=evil"),
                     lambda c: c.update(pairing_uuid="localhost"),
                     lambda c: c["profiles"]["desktop"].update(stream_resolution="1920x1080;touch /tmp/bad")):
            value = computer()
            edit(value)
            self.config.write_text(json.dumps({"version": 1, "computers": {"laptop": value}}))
            with self.assertRaises(ValueError):
                s.configuration(self.config)

    def test_fit_window_profiles_validate_and_need_a_resolved_size(self):
        c = computer()
        c["profiles"]["desktop"]["stream_resolution"] = "auto"
        self.config.write_text(json.dumps({"version": 1, "computers": {"laptop": c}}))
        s.configuration(self.config)
        with self.assertRaisesRegex(ValueError, "resolution-required"):
            s.stream_argv(c, c["profiles"]["desktop"])
        args = s.stream_argv(c, c["profiles"]["desktop"], "6120x2506")
        self.assertEqual(args[args.index("--resolution") + 1], "6120x2506")
        for bad in ("6120x2506;touch /tmp/bad", "auto", "100x100"):
            with self.assertRaises(ValueError):
                s.stream_argv(c, c["profiles"]["desktop"], bad)
        # A fixed profile ignores the daemon's fitted size unless it asks for one.
        fixed = computer()
        self.assertIn("2560x1440", s.stream_argv(fixed, fixed["profiles"]["desktop"]))
        with self.assertRaises(ValueError):
            s.resolution("auto")

    def test_existing_windows_display_needs_no_ssh_and_never_prepares_host(self):
        c = computer()
        c["platform"] = "windows"
        del c["ssh"]
        profile = c["profiles"]["desktop"]
        profile["stream_resolution"] = "1920x1080"
        host = s.Host(c, profile)
        with patch.object(s.windows_display, "powershell", side_effect=AssertionError("SSH called")):
            self.assertEqual(host.probe(pairing=False)["restoration"], "externally-managed")
            record = {}
            s.prepare(record, host, lambda: self.fail("unexpected host state write"))
            self.assertEqual(record, {})
        argv = s.stream_argv(c, profile)
        self.assertEqual(argv[argv.index("--resolution") + 1], "1920x1080")
        self.assertIn("--no-game-optimization", argv)

    def test_sunshine_matching_needs_no_ssh_and_never_prepares_host(self):
        c = computer()
        c["platform"] = "windows"
        del c["ssh"]
        profile = c["profiles"]["desktop"]
        profile["stream_resolution"] = "1920x1080"
        profile["display"] = {"adapter": "sunshine"}
        s.configuration_value({"version": 1, "computers": {"laptop": c}})
        host = s.Host(c, profile)
        with patch.object(s.windows_display, "powershell", side_effect=AssertionError("SSH called")):
            self.assertEqual(host.probe(pairing=False)["restoration"], "sunshine")
            record = {}
            s.prepare(record, host, lambda: self.fail("unexpected host state write"))
            self.assertEqual(record, {})
            self.assertTrue(s.restore(record, host, lambda: self.fail("unexpected write")))
            self.assertFalse(host.probe(pairing=False)["host_display"]["verified"])
        argv = s.stream_argv(c, profile)
        self.assertEqual(argv[argv.index("--resolution") + 1], "1920x1080")
        self.assertIn("--game-optimization", argv)

    def test_virtual_display_mode_management_is_opt_in_and_verified_separately(self):
        from remote_desktops import virtual_display as v, sunshine_display as sd
        c = computer()
        c.update(platform="windows", ssh={"alias": "work-laptop"})
        profile = c["profiles"]["desktop"]
        profile["display"] = {"adapter": "virtual", "output": "{11111111-2222-3333-4444-555555555555}"}
        self.config.write_text(json.dumps({"version": 1, "computers": {"laptop": c}}))
        s.configuration(self.config)
        for bad in ({"adapter": "virtual", "settings": "relative.xml"}, {"adapter": "virtual", "settings": "C:\\a'b.xml"}):
            profile["display"] = bad
            with self.assertRaises(ValueError):
                s.configuration_value({"version": 1, "computers": {"laptop": c}})
        profile["display"] = {"adapter": "virtual", "output": "{11111111-2222-3333-4444-555555555555}"}
        host = s.Host(c, profile)
        record = {"stream_resolution": "2474x1646"}
        with patch.object(sd, "snapshot", return_value={"offset": 100, "created": "stamp"}), patch.object(v, "sync") as sync:
            s.prepare(record, host, lambda: None)
            sync.assert_not_called()
            self.assertFalse(record["resolved"]["host_display"]["verified"])
            profile["display"]["sync_modes"] = True
            s.prepare(record, host, lambda: None)
            sync.assert_called_once_with("work-laptop", "2474x1646", v.SETTINGS, profile.get("fps", 60))
        self.assertTrue(s.restore(record, host, lambda: None))
        # Configuring mode management does not turn a failed update into success.
        with patch.object(sd, "snapshot"), patch.object(v, "sync", side_effect=ValueError("driver reload failed")):
            with self.assertRaisesRegex(ValueError, "driver reload failed"):
                s.prepare(record, host, lambda: None)
        del c["ssh"]
        with patch.object(v.windows_display, "powershell") as ps:
            with self.assertRaisesRegex(ValueError, "display-verification-required"):
                host.probe(pairing=False)
            ps.assert_not_called()
        with patch.object(v.windows_display, "powershell", return_value={"ok": True, "result": {"changed": False, "modes": ["2218x1246"]}}):
            with self.assertRaisesRegex(ValueError, "mode-missing"):
                v.sync("work-laptop", "2474x1646")
        with self.assertRaises(ValueError):
            v.sync("work-laptop", "2474x1646;evil")

    def test_virtual_refit_requests_sunshine_resolution_switching(self):
        c = computer()
        c["platform"] = "windows"
        profile = c["profiles"]["desktop"]
        for adapter in ("virtual", "sunshine", "windows", "external"):
            profile["display"] = {"adapter": adapter}
            for fitted in (None, "2474x1646"):
                with self.subTest(adapter=adapter, fitted=fitted):
                    args = s.stream_argv(c, profile, fitted)
                    self.assertEqual(args[args.index("--resolution") + 1], fitted or profile["stream_resolution"])
                    self.assertEqual("--game-optimization" in args, adapter in ("virtual", "sunshine"))
                    self.assertEqual("--no-game-optimization" in args, adapter not in ("virtual", "sunshine"))
                    self.assertIn("--no-quit-after", args)

    def test_cli_never_requests_host_app_termination(self):
        c = computer()
        args = s.stream_argv(c, c["profiles"]["desktop"])
        self.assertIn("--no-quit-after", args)
        self.assertNotIn("--quit-after", args)
        self.assertEqual(args[-2], IDENTITY)


    def test_mac_host_identity_checked_before_display_reads_or_changes(self):
        directory = self.root / ".config/sunshine"
        directory.mkdir(parents=True)
        (directory / "sunshine_state.json").write_text(json.dumps({"root": {"uniqueid": "other-host"}}))
        with patch.object(Path, "home", return_value=self.root), patch.object(mac_display, "run") as run:
            with self.assertRaisesRegex(ValueError, "host-identity-mismatch"):
                mac_display.display({"pairing_uuid": IDENTITY, "display_uuid": IDENTITY, "operation": "probe"})
            run.assert_not_called()

    def test_mac_uuid_queries_exclude_default_display_group(self):
        directory = self.root / ".config/sunshine"
        directory.mkdir(parents=True)
        (directory / "sunshine_state.json").write_text(json.dumps({"root": {"uniqueid": IDENTITY}}))
        # Stop just after resolving the identifier; this assertion prevents the
        # live BetterDisplay behavior where UUID-only queries include a group.
        def run(argv):
            self.assertIn("-type=Display", argv)
            self.assertIn("-UUID=" + IDENTITY, argv)
            raise ValueError("sentinel")
        with patch.object(Path, "home", return_value=self.root), patch.object(mac_display, "run", side_effect=run), \
             patch.object(mac_display.ctypes, "CDLL", return_value=Mock()):
            with self.assertRaisesRegex(ValueError, "display-missing"):
                mac_display.display({"pairing_uuid": IDENTITY, "display_uuid": IDENTITY, "operation": "probe"})

    def test_mac_mode_changes_refresh_sunshine_cached_pointer_scale(self):
        directory = self.root / ".config/sunshine"
        directory.mkdir(parents=True)
        (directory / "sunshine_state.json").write_text(json.dumps({"root": {"uniqueid": IDENTITY}}))
        (directory / "sunshine.conf").write_text("output_name = 4\n")
        for hidpi in (True, False):
            with self.subTest(original_hidpi=hidpi):
                mode = {"resolution": "1920x1080", "hidpi": hidpi, "refresh": 60}
                before = mode.copy()
                target = {**mode, "hidpi": not hidpi}
                sunshine = {"running": True, "scale": .5 if hidpi else 1, "restarts": 0}
                def command(argv):
                    if argv[0] == "/usr/bin/open":
                        sunshine.update(running=True, scale=.5 if mode["hidpi"] else 1,
                                        restarts=sunshine["restarts"] + 1)
                        return ""
                    if argv[1] == "get":
                        return {"-identifiers": json.dumps({"UUID": IDENTITY, "displayID": "4"}),
                                "-resolution": mode["resolution"], "-hiDPI": "on" if mode["hidpi"] else "off",
                                "-refreshRate": str(mode["refresh"]) + "Hz"}[argv[-1]]
                    values = dict(arg.split("=", 1) for arg in argv[2:])
                    mode.update(resolution=values["-resolution"], hidpi=values["-hiDPI"] == "on",
                                refresh=float(values["-refreshRate"]))
                    return ""
                def process(argv, **kwargs):
                    if argv[0] == "/usr/bin/pkill":
                        sunshine["running"] = False
                    return subprocess.CompletedProcess(argv, 0 if sunshine["running"] else 1)
                graphics = Mock()
                graphics.CGDisplayIsActive.return_value = 1
                with patch.object(Path, "home", return_value=self.root), \
                     patch.object(mac_display.ctypes, "CDLL", return_value=graphics), \
                     patch.object(mac_display, "run", side_effect=command), \
                     patch.object(mac_display.subprocess, "run", side_effect=process):
                    mac_display.display({"pairing_uuid": IDENTITY, "display_uuid": IDENTITY, "operation": "change",
                                         "field": "mode", "expected": before, "value": target})
                self.assertEqual(mode, target)
                self.assertEqual(sunshine["scale"], .5 if target["hidpi"] else 1)
                self.assertEqual(sunshine["restarts"], 1)
                self.assertEqual((directory / "sunshine.conf").read_text(), "output_name = 4\n")

    def recover_main(self, host, record):
        health = host.probe(False)
        record["display_recovery"] = {"current": health["current"], "topology": health["topology"]}
        s.prepare(record, host, lambda: None)
