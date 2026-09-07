"""Exercise the real Rust daemon/CLI/supervisor with isolated fake hosts/clients.

No real compositor, Moonlight configuration, SSH account, or display is used.
"""
import fcntl
import json
import os
from pathlib import Path
import signal
import shlex
import socket
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
BIN = Path(os.environ.get("REMOTE_DESKTOPS_BIN", ROOT / "target/debug/remote-desktops")).resolve()

WORKER = r'''
import fcntl, json, os, sys, time
from pathlib import Path
request=json.load(sys.stdin)
if request['operation']=='validate':
    result=json.loads(Path(request['config']).read_text())['computers']
elif request['operation']=='validate-value':
    result=request['value']['computers']
else:
    path=Path(request['path'])
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        record=json.loads(path.read_text())
        def persist():
            tmp=path.with_suffix('.tmp')
            tmp.write_text(json.dumps(record)); os.replace(tmp,path)
        action=request['operation']
        if action=='probe':
            record['resolved']={'client_version':'6.1.0'}
            result={'argv':['python3','-u',str(Path(__file__).with_name('client.py')),str(path.parent),request.get('stream_resolution') or record['settings'].get('stream_resolution') or ''],'resolved':record['resolved']}
        elif action=='prepare':
            record['journal']={'output':{'original':'1','applied':'2','phase':'intent'}}
            persist()
            (path.parent/'prepared').touch()
            deadline=time.monotonic()+15
            while (path.parent/'hold').exists() and time.monotonic()<deadline:
                time.sleep(.02)
            record['journal']['output']['phase']='applied'
            result={}
        elif action=='restore':
            if not (path.parent/'conflict').exists(): record['journal']={}
            result={'complete':not record['journal']}
        elif action=='release':
            assert request['keep_host_settings'] is True
            record['journal']={}; result={'complete':True}
        elif action=='health':
            if record['settings'].get('display',{}).get('adapter')=='virtual':
                record['resolved']['host_display']={'verified':True,'resolution':record.get('stream_resolution','1920x1080'),'checked_at':int(time.time())}
                persist()
            result={'reconnect':False}
        else:
            raise RuntimeError('unexpected operation')
        persist()
print(json.dumps({'ok':True,'result':result}))
'''

CLIENT = r'''
import os, signal, sys, time
from pathlib import Path
directory=Path(sys.argv[1])
with (directory/'launches').open('a') as log: log.write(str(os.getpid())+' '+(sys.argv[2] if len(sys.argv)>2 else '')+'\n')
def close(*_):
    print('Quit event received',flush=True)
    raise SystemExit(0)
signal.signal(signal.SIGTERM,close)
print('Video stream is 2560x1440x60 (format 0x100)',flush=True)
while True: time.sleep(60)
'''


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(BIN.exists(), "Build the Rust binary before running integration.py")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = {**os.environ, "HOME": str(self.root), "XDG_STATE_HOME": str(self.root / "state"),
                    "XDG_DATA_HOME": str(self.root / "data"),
                    "XDG_CONFIG_HOME": str(self.root / "config"), "XDG_RUNTIME_DIR": str(self.root / "runtime"),
                    "REMOTE_DESKTOPS_HELPERS": str(self.root / "helpers")}
        self.env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
        self.env.pop("PYTHONPATH", None)
        self.state = self.root / "state/remote-desktops"
        (self.root / "state/hypertile/streams").mkdir(parents=True)
        package = self.root / "helpers/remote_desktops"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "worker.py").write_text(WORKER)
        (package / "client.py").write_text(CLIENT)
        config = self.root / "config/remote-desktops/computers.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"version": 1, "computers": {
            name: {"pairing_uuid": f"12345678-1234-1234-1234-{index:012d}", "title": name + " - Moonlight",
                   "profiles": {"desktop": {"display": {"adapter": "external"}}}}
            for index, name in enumerate(("laptop", "other"), 1)}}))
        self.daemon = None
        self.start()

    def start(self):
        self.daemon = subprocess.Popen([str(BIN), "daemon"], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.wait(lambda: (self.root / "runtime/remote-desktops/control.sock").exists())

    def stop_daemon(self):
        self.daemon.terminate()
        self.daemon.communicate(timeout=5)
        self.daemon = None

    def tearDown(self):
        try:
            if self.daemon:
                for name in ("laptop", "other"):
                    self.cli("disconnect", name, check=False)
                time.sleep(.2)
            for directory in (self.state / "sessions").glob("*"):
                (directory / "hold").unlink(missing_ok=True)
                for path in directory.glob("job-*.json"):
                    try:
                        job = json.loads(path.read_text())
                        for pid in (job.get("pid"), job.get("supervisor")):
                            if pid and ("REMOTE_DESKTOPS_TOKEN=" + job["token"]).encode() in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
                                os.kill(pid, signal.SIGKILL)
                    except (OSError, ValueError):
                        pass
            if self.daemon:
                self.stop_daemon()
        finally:
            self.temp.cleanup()

    def cli(self, *args, check=True):
        p = subprocess.run([str(BIN), "--json", *args], env=self.env, capture_output=True, text=True, timeout=5)
        if not check:
            return p
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def wait(self, predicate, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            if self.daemon and self.daemon.poll() is not None:
                self.fail(self.daemon.communicate()[1].decode())
            time.sleep(.04)
        self.fail("timed out waiting for backend state")

    def session(self, name="laptop"):
        return self.state / "sessions" / name

    def launched(self, name="laptop"):
        return [line.split()[0] for line in (self.session(name) / "launches").read_text().splitlines()]

    def connect(self, name="laptop"):
        self.cli("connect", name)
        self.wait(lambda: self.cli("status", name)["pid"] is not None)
        pid = self.cli("status", name)["pid"]
        launches = self.session(name) / "launches"
        self.wait(lambda: launches.exists() and str(pid) in [line.split()[0] for line in launches.read_text().splitlines()])
        return pid

    def test_repeat_connect_and_daemon_restart_reuse_the_same_client(self):
        pid = self.connect()
        first = self.cli("status", "laptop")["generation"]
        self.assertEqual(self.cli("connect", "laptop")["generation"], first)
        self.stop_daemon()
        self.start()
        self.assertEqual(self.cli("connect", "laptop")["pid"], pid)
        self.assertEqual(self.launched(), [str(pid)])
        self.cli("disconnect", "laptop")
        self.wait(lambda: self.cli("status", "laptop")["phase"] == "idle")
        self.assertFalse(self.cli("status", "laptop")["recovery_pending"])

    def test_disconnect_during_prepare_never_launches_and_restores(self):
        directory = self.session()
        directory.mkdir(parents=True)
        (directory / "hold").touch()
        self.cli("connect", "laptop")
        self.wait(lambda: (directory / "prepared").exists())
        start = time.monotonic()
        self.assertFalse(self.cli("disconnect", "laptop")["desired"])
        self.assertLess(time.monotonic() - start, 1)
        (directory / "hold").unlink()
        self.wait(lambda: self.cli("status", "laptop")["phase"] == "idle")
        self.assertFalse((directory / "launches").exists())
        self.assertFalse(self.cli("status", "laptop")["recovery_pending"])

    def test_client_close_and_unknown_crash_restore_without_relaunch(self):
        for sig, expected in ((signal.SIGTERM, "idle"), (signal.SIGKILL, "attention")):
            with self.subTest(signal=sig):
                pid = self.connect()
                launches = (self.session() / "launches").read_text()
                os.kill(pid, sig)
                self.wait(lambda: self.cli("status", "laptop")["phase"] == expected)
                result = self.cli("status", "laptop")
                self.assertFalse(result["desired"])
                self.assertFalse(result["recovery_pending"])
                self.assertIsNone(result["pid"])
                self.assertEqual((self.session() / "launches").read_text(), launches)

    def test_concurrent_connect_requests_launch_exactly_one_client(self):
        requests = [subprocess.Popen([str(BIN), "--json", "connect", "laptop"],
                                     env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    for _ in range(8)]
        for request in requests:
            stdout, stderr = request.communicate(timeout=5)
            self.assertEqual(request.returncode, 0, stderr.decode())
            self.assertEqual(json.loads(stdout)["generation"], 1)
        pid = self.connect()
        self.assertEqual(self.launched(), [str(pid)])

    def test_slow_host_does_not_block_another_computer(self):
        directory = self.session()
        directory.mkdir(parents=True)
        (directory / "hold").touch()
        self.cli("connect", "laptop")
        self.wait(lambda: (directory / "prepared").exists())
        self.connect("other")
        self.assertTrue((directory / "hold").exists())
        self.assertIsNone(self.cli("status", "laptop")["pid"])
        self.assertIsNotNone(self.cli("status", "other")["pid"])

    def test_recovery_conflict_blocks_reconnect_until_explicit_release(self):
        self.connect()
        (self.session() / "conflict").touch()
        self.cli("disconnect", "laptop")
        self.wait(lambda: self.cli("status", "laptop")["phase"] == "restore-pending")
        self.assertNotEqual(self.cli("connect", "laptop", check=False).returncode, 0)
        self.assertNotEqual(self.cli("release", "laptop", check=False).returncode, 0)
        self.cli("release", "laptop", "--keep-host-settings")
        self.wait(lambda: self.cli("status", "laptop")["phase"] == "idle")
        self.assertFalse(self.cli("status", "laptop")["recovery_pending"])

    def test_reconnect_replaces_client_once_and_preserves_recovery(self):
        pid = self.connect()
        self.cli("reconnect", "laptop")
        self.cli("reconnect", "laptop", check=False)
        self.wait(lambda: self.cli("status", "laptop")["pid"] not in (None, pid))
        self.wait(lambda: len((self.session() / "launches").read_text().splitlines()) == 2)
        self.assertEqual(len((self.session() / "launches").read_text().splitlines()), 2)
        self.assertTrue(self.cli("status", "laptop")["recovery_pending"])

    def test_malformed_journal_is_not_treated_as_completed_recovery(self):
        self.connect()
        self.cli("disconnect", "laptop")
        self.wait(lambda: self.cli("status", "laptop")["phase"] == "idle")
        path = self.session() / "recovery.json"
        record = json.loads(path.read_text())
        record["journal"] = None
        path.write_text(json.dumps(record))
        result = self.cli("status", "laptop")
        self.assertIsNone(result["recovery_pending"])
        self.assertIn("invalid recovery journal", result["recovery_error"])
        self.assertNotEqual(self.cli("connect", "laptop", check=False).returncode, 0)
        self.assertIsNone(json.loads(path.read_text())["journal"])

    def test_legacy_journal_requires_explicit_handoff(self):
        legacy = self.root / "state/hypertile/streams/state.json"
        legacy.write_text(json.dumps({"version": 1, "computers": {"old-name": {
            "config": {"pairing_uuid": "12345678-1234-1234-1234-000000000001"},
            "desired": False, "journal": {"output": {"original": "1"}}}}}))
        result = self.cli("connect", "laptop", check=False)
        self.assertIn("handoff-required", result.stderr)
        self.assertFalse(self.session().exists())

    def test_legacy_exclusive_controller_lock_is_not_bypassed(self):
        self.stop_daemon()
        with (self.root / "state/hypertile/streams/writer.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run([str(BIN), "daemon"], env=self.env, capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"handoff-required", result.stderr)

    def test_oversized_socket_request_does_not_stall_other_commands(self):
        sock = socket.socket(socket.AF_UNIX)
        self.addCleanup(sock.close)
        sock.connect(str(self.root / "runtime/remote-desktops/control.sock"))
        sock.sendall(b"x" * 65_537)
        self.assertEqual(self.cli("status")["computers"], [])

    def test_manager_catalog_exposes_labels_without_pairing_material(self):
        entries = self.cli("computers")
        self.assertEqual([c["computer"] for c in entries], ["laptop", "other"])
        self.assertEqual(entries[0]["name"], "laptop")
        self.assertEqual(entries[0]["profiles"], ["desktop"])
        self.assertEqual(set(entries[0]), {"computer", "name", "host", "platform", "default_profile", "profiles"})
        self.assertNotIn("pairing_uuid", json.dumps(entries))
        self.assertEqual(self.cli("status")["computers"], [])

    def test_launcher_install_metadata_and_removal_preserve_other_apps(self):
        installed = self.cli("launcher", "install", "laptop")
        path = Path(installed["installed"])
        self.assertEqual(path.parent, self.root / "data/applications")
        entry = path.read_text()
        self.assertIn("Name=laptop (Remote Desktop)", entry)
        command = next(line[5:] for line in entry.splitlines() if line.startswith("Exec="))
        self.assertEqual(shlex.split(command), [str(BIN), "open", "laptop"])
        self.assertNotIn("StartupWMClass", entry)
        metadata = installed["launcher"]["match"]
        self.assertEqual(metadata["title"], "laptop - Moonlight")
        self.assertEqual(metadata["tag"], "remote-desktops-laptop")
        self.cli("launcher", "install", "other")
        other = path.with_name("remote-desktops-other.desktop")
        self.cli("launcher", "remove", "laptop")
        self.assertFalse(path.exists())
        self.assertTrue(other.exists())
        path.write_text("[Desktop Entry]\nName=My own launcher\n")
        self.assertNotEqual(self.cli("launcher", "install", "laptop", check=False).returncode, 0)
        self.assertNotEqual(self.cli("launcher", "remove", "laptop", check=False).returncode, 0)
        self.assertIn("My own launcher", path.read_text())

    def fake_desktop(self, monitors=None):
        """A Hyprland stand-in: an event socket plus a hyprctl shim reading clients.json and monitors.json."""
        self.stop_daemon()
        self.env["HYPRLAND_INSTANCE_SIGNATURE"] = "test-instance"
        desktop_path = self.root / "runtime/hypr/test-instance/.socket2.sock"
        desktop_path.parent.mkdir(parents=True)
        server = socket.socket(socket.AF_UNIX)
        self.addCleanup(server.close)
        server.bind(str(desktop_path))
        server.listen(1)
        server.settimeout(3)
        bins = self.root / "helpers/bin"
        bins.mkdir()
        clients = self.root / "clients.json"
        calls = self.root / "desktop-calls.jsonl"
        clients.write_text("[]")
        (self.root / "monitors.json").write_text(json.dumps(monitors or []))
        shim = bins / "hyprctl"
        shim.write_text("#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\n"
                        f"with Path({str(calls)!r}).open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
                        f"root=Path({str(self.root)!r})\n"
                        "if 'clients' in sys.argv: print((root/'clients.json').read_text())\n"
                        "elif 'monitors' in sys.argv: print((root/'monitors.json').read_text())\n"
                        "elif 'general:gaps_out' in sys.argv: print(json.dumps({'option':'general:gaps_out','css':'10 10 10 10','set':True}))\n"
                        "elif 'general:border_size' in sys.argv: print(json.dumps({'option':'general:border_size','int':2,'set':True}))\n"
                        "elif 'activewindow' in sys.argv: p=root/'activewindow.json'; print(p.read_text() if p.exists() else '{}')\n"
                        "else: print('ok')\n")
        shim.chmod(0o755)
        self.env["PATH"] = str(bins) + os.pathsep + self.env["PATH"]
        self.start()
        connection, _ = server.accept()
        self.addCleanup(connection.close)
        return server, connection, clients, calls

    def test_workspace_and_geometry_changes_never_place_or_restart_the_window(self):
        server, connection, clients, calls = self.fake_desktop()
        pid = self.connect()
        window = {"address": "0x1", "pid": pid, "stableId": "123", "class": "com.moonlight_stream.Moonlight",
                  "title": "laptop - Moonlight", "mapped": True, "hidden": False, "visible": True,
                  "workspace": {"id": 1}, "size": [1200, 800], "floating": False, "fullscreen": 0}
        clients.write_text(json.dumps([window]))
        connection.sendall(b"openwindow>>0x1\n")
        self.wait(lambda: self.cli("status", "laptop")["phase"] == "window-ready")
        generation = self.cli("status", "laptop")["generation"]
        window.update(workspace={"id": 9}, size=[800, 600], floating=True, fullscreen=2)
        clients.write_text(json.dumps([window]))
        connection.sendall(b"movewindow>>0x1,9\n" * 20)
        self.wait(lambda: self.cli("status", "laptop")["window"]["size"] == [800, 600])
        result = self.cli("status", "laptop")
        self.assertEqual(result["pid"], pid)
        self.assertEqual(result["generation"], generation)
        self.assertNotIn("assignment", (self.session() / "session.json").read_text())
        commands = calls.read_text()
        self.assertNotIn("window.move", commands)
        self.assertEqual(commands.count("fullscreen_state"), 1, "only initial startup may clear fullscreen")
        self.assertNotIn("workspace", commands)
        self.assertLess(len(commands.splitlines()), 10, "event burst should be coalesced")
        self.assertEqual(self.cli("open", "laptop")["pid"], pid)
        self.stop_daemon()
        connection.close()
        self.start()
        replacement, _ = server.accept()
        self.addCleanup(replacement.close)
        self.assertEqual(self.cli("open", "laptop")["pid"], pid)
        self.assertEqual(calls.read_text().count("fullscreen_state"), 1,
                         "reopen and daemon restart must preserve the user's fullscreen choice")
        other_pid = self.connect("other")
        startup = {**window, "address": "0x2", "pid": other_pid, "stableId": "124", "title": "Moonlight"}
        clients.write_text(json.dumps([window, startup]))
        replacement.sendall(b"openwindow>>0x2\n")
        time.sleep(.2)
        self.assertIsNone(self.cli("status", "other")["window"])
        self.assertEqual(calls.read_text().count("fullscreen_state"), 1)
        startup["title"] = "other - Moonlight"
        clients.write_text(json.dumps([window, startup]))
        replacement.sendall(b"windowtitle>>0x2\n")
        self.wait(lambda: self.cli("status", "other")["phase"] == "window-ready")
        self.assertEqual(self.cli("open", "other")["pid"], other_pid)
        self.assertEqual(self.cli("status", "laptop")["pid"], pid)
        self.assertEqual(calls.read_text().count("fullscreen_state"), 2,
                         "only final owned windows receive startup policy")

    def test_connect_launches_at_the_last_known_size_and_never_restarts_to_fit(self):
        config = self.root / "config/remote-desktops/computers.json"
        value = json.loads(config.read_text())
        value["computers"]["laptop"]["profiles"]["desktop"]["stream_resolution"] = "auto"
        config.write_text(json.dumps(value))
        monitor = {"id": 0, "name": "DP-1", "width": 3840, "height": 2160, "scale": 2, "focused": True, "activeWorkspace": {"id": 1}}
        server, connection, clients, calls = self.fake_desktop([monitor])
        launches = self.session() / "launches"
        sizes = lambda: [line.split()[1] for line in launches.read_text().splitlines()]
        pid = self.connect()
        # No memory yet: the connect opens at the saved initial size, and stays there.
        self.assertEqual(sizes(), ["1920x1080"])
        self.assertTrue(self.cli("status", "laptop")["fit_window"])
        self.assertEqual(self.cli("status", "laptop")["resolution"], "1920x1080")
        window = {"address": "0x1", "pid": pid, "stableId": "123", "class": "com.moonlight_stream.Moonlight",
                  "title": "laptop - Moonlight", "mapped": True, "hidden": False, "visible": True, "monitor": 0,
                  "workspace": {"id": 1}, "size": [1200, 800], "floating": False, "fullscreen": 0}
        clients.write_text(json.dumps([window]))
        connection.sendall(b"openwindow>>0x1\n")
        self.wait(lambda: self.cli("status", "laptop")["phase"] == "window-ready")
        # A connect never restarts to fit: the window can differ from the stream and nothing happens.
        time.sleep(3)
        self.assertEqual(sizes(), ["1920x1080"])
        self.assertEqual(self.cli("status", "laptop")["pid"], pid)
        self.assertEqual(self.cli("status", "laptop")["resolution"], "1920x1080")
        self.assertFalse(self.cli("status", "laptop")["refit_available"])
        self.assertIn("refit-unavailable", self.cli("refit", "laptop", check=False).stderr)
        self.assertEqual(self.cli("status", "laptop")["pid"], pid)
        self.assertNotIn("move", calls.read_text())

    def test_sunshine_refit_without_verified_host_uses_saved_size(self):
        config = self.root / "config/remote-desktops/computers.json"
        value = json.loads(config.read_text())
        value["computers"]["laptop"]["profiles"]["desktop"]["stream_resolution"] = "2560x1440"
        value["computers"]["laptop"]["profiles"]["desktop"]["display"] = {"adapter": "sunshine"}
        config.write_text(json.dumps(value))
        monitor = {"id": 0, "name": "DP-1", "width": 3840, "height": 2160, "scale": 1, "focused": True, "activeWorkspace": {"id": 1}}
        server, connection, clients, calls = self.fake_desktop([monitor])
        launches = self.session() / "launches"
        sizes = lambda: [line.split()[1] for line in launches.read_text().splitlines()]
        pid = self.connect()
        self.assertEqual(sizes(), ["2560x1440"])  # Saved size, no memory yet
        window = {"address": "0x1", "pid": pid, "stableId": "123", "class": "com.moonlight_stream.Moonlight",
                  "title": "laptop - Moonlight", "mapped": True, "hidden": False, "visible": True, "monitor": 0,
                  "workspace": {"id": 1}, "size": [1900, 1060], "floating": False, "fullscreen": 0}
        clients.write_text(json.dumps([window]))
        connection.sendall(b"openwindow>>0x1\n")
        self.wait(lambda: (self.cli("status", "laptop")["window"] or {}).get("size") == [1900, 1060])
        # Refit restarts the stream to the window's size and records it.
        self.assertTrue(self.cli("refit", "laptop")["fit_window"])
        self.wait(lambda: len(sizes()) == 2 and self.cli("status", "laptop")["pid"] not in (None, pid), timeout=8)
        self.assertEqual(sizes()[-1], "1900x1060")
        self.assertFalse(self.cli("status", "laptop").get("host_display", {}).get("verified", False))

    def test_refit_matches_the_window_remembers_it_and_restores_the_workspace(self):
        config = self.root / "config/remote-desktops/computers.json"
        value = json.loads(config.read_text())
        value["computers"]["laptop"]["profiles"]["desktop"]["stream_resolution"] = "auto"
        value["computers"]["laptop"]["profiles"]["desktop"]["display"] = {"adapter": "virtual"}
        config.write_text(json.dumps(value))
        monitor = {"id": 0, "name": "DP-1", "width": 3840, "height": 2160, "scale": 1, "focused": True, "activeWorkspace": {"id": 1}}
        server, connection, clients, calls = self.fake_desktop([monitor])
        launches = self.session() / "launches"
        sizes = lambda: [line.split()[1] for line in launches.read_text().splitlines()]
        pid = self.connect()
        self.assertEqual(sizes(), ["1920x1080"])  # 1080p default, no memory yet
        window = {"address": "0x1", "pid": pid, "stableId": "123", "class": "com.moonlight_stream.Moonlight",
                  "title": "laptop - Moonlight", "mapped": True, "hidden": False, "visible": True, "monitor": 0,
                  "workspace": {"id": 1}, "size": [1900, 1060], "floating": False, "fullscreen": 0}
        clients.write_text(json.dumps([window]))
        connection.sendall(b"openwindow>>0x1\n")
        self.wait(lambda: (self.cli("status", "laptop")["window"] or {}).get("size") == [1900, 1060])
        # Refit restarts the stream to the window's size and records it.
        self.assertTrue(self.cli("refit", "laptop")["fit_window"])
        self.wait(lambda: len(sizes()) == 2 and self.cli("status", "laptop")["pid"] not in (None, pid), timeout=8)
        self.assertEqual(sizes()[-1], "1900x1060")
        second = self.cli("status", "laptop")["pid"]
        window.update(pid=second, address="0x2", stableId="124")
        clients.write_text(json.dumps([window]))
        connection.sendall(b"openwindow>>0x2\n")
        self.wait(lambda: (self.cli("status", "laptop")["window"] or {}).get("size") == [1900, 1060] and self.cli("status", "laptop")["pid"] == second)
        self.assertEqual(self.cli("status", "laptop")["resolution"], "1900x1060")
        # Reconnecting to the same spot launches at the remembered size with no restart.
        self.cli("disconnect", "laptop")
        self.wait(lambda: self.cli("status", "laptop")["phase"] == "idle")
        clients.write_text("[]")
        connection.sendall(b"closewindow>>0x2\n")
        third = self.connect()
        self.assertEqual(sizes()[-1], "1900x1060")
        window.update(pid=third, address="0x3", stableId="125", size=[1900, 1060])
        clients.write_text(json.dumps([window]))
        connection.sendall(b"openwindow>>0x3\n")
        self.wait(lambda: self.cli("status", "laptop")["phase"] == "window-ready")
        time.sleep(2)
        self.assertEqual(self.cli("status", "laptop")["pid"], third)
        self.assertEqual(len(sizes()), 3)
        # Refit with no name targets the focused window; moving it means the restart
        # reopens it on the active workspace and the daemon returns it to workspace 4.
        window.update(size=[3000, 1600], workspace={"id": 4})
        clients.write_text(json.dumps([window]))
        (self.root / "activewindow.json").write_text(json.dumps({"pid": third, "address": "0x3"}))
        connection.sendall(b"movewindow>>0x3,4\n")
        self.wait(lambda: (self.cli("status", "laptop")["window"] or {}).get("size") == [3000, 1600])
        self.cli("refit")
        self.wait(lambda: len(sizes()) == 4 and self.cli("status", "laptop")["pid"] not in (None, third), timeout=8)
        self.assertEqual(sizes()[-1], "3000x1600")
        fourth = self.cli("status", "laptop")["pid"]
        window.update(pid=fourth, address="0x4", stableId="126", workspace={"id": 1})
        clients.write_text(json.dumps([window]))
        calls.write_text("")
        connection.sendall(b"openwindow>>0x4\n")
        self.wait(lambda: "hl.dsp.window.move" in calls.read_text() and "workspace=4" in calls.read_text(), timeout=6)
        # A fixed-resolution profile cannot be refit.
        self.cli("disconnect", "laptop")
        self.wait(lambda: self.cli("status", "laptop")["phase"] == "idle")
        value["computers"]["laptop"]["profiles"]["desktop"]["stream_resolution"] = "1920x1080"
        config.write_text(json.dumps(value))
        self.assertNotEqual(self.cli("refit", "laptop", check=False).returncode, 0)

    def test_window_rule_owns_one_block_in_the_hyprland_config(self):
        config = self.root / "config/hypr/hyprland.lua"
        config.parent.mkdir(parents=True)
        # Without a config the status is unavailable and install fails without writing.
        self.assertFalse(self.cli("window-rule", "status")["available"])
        self.assertNotEqual(self.cli("window-rule", "install", check=False).returncode, 0)
        original = 'dofile("boot.lua")\nrequire("hypr.bindings")\n'
        config.write_text(original)
        config.chmod(0o644)
        self.fake_desktop()
        status = self.cli("window-rule", "install")
        self.assertTrue(status["installed"] and status["available"] and not status["manual"])
        text = config.read_text()
        self.assertTrue(text.startswith(original))
        self.assertIn('hl.window_rule({ match = { class = "com.moonlight_stream.Moonlight" }, fullscreen = false })', text)
        self.assertEqual(oct(config.stat().st_mode & 0o777), "0o644")
        self.assertEqual(config.with_suffix(".lua.remote-desktops.bak").read_text(), original)
        # Installing again keeps a single block; other later edits survive both ways.
        self.cli("window-rule", "install")
        self.assertEqual(config.read_text().count("remote-desktops: begin"), 1)
        config.write_text(config.read_text() + 'o.window("qemu", { workspace = "5" })\n')
        self.assertTrue(self.cli("window-rule", "status")["installed"])
        self.assertFalse(self.cli("window-rule", "remove")["installed"])
        self.assertEqual(config.read_text(), original + 'o.window("qemu", { workspace = "5" })\n')
        self.assertFalse(self.cli("window-rule", "remove")["installed"])
        calls = (self.root / "desktop-calls.jsonl").read_text()
        self.assertIn('"reload"]', calls)
        self.assertIn('"configerrors"]', calls)
        # A hand-written rule is reported, never duplicated or removed.
        config.write_text(original + 'o.window("com.moonlight_stream.Moonlight", { fullscreen = false })\n')
        status = self.cli("window-rule", "status")
        self.assertTrue(status["manual"] and not status["installed"])
        self.cli("window-rule", "remove")
        self.assertIn("fullscreen = false", config.read_text())

    def test_fit_window_needs_the_compositor(self):
        config = self.root / "config/remote-desktops/computers.json"
        value = json.loads(config.read_text())
        value["computers"]["laptop"]["profiles"]["desktop"]["stream_resolution"] = "auto"
        config.write_text(json.dumps(value))
        self.cli("connect", "laptop")
        self.wait(lambda: self.cli("status", "laptop")["phase"] in ("idle", "attention"))
        self.assertIn("fit-unavailable", self.cli("status", "laptop")["error"])
        self.assertFalse((self.session() / "launches").exists())

    def daemons(self):
        # Detached daemons started by the CLI are found through their private HOME.
        found = []
        for entry in Path("/proc").iterdir():
            try:
                argv = entry.joinpath("cmdline").read_bytes().split(b"\0")
                environ = entry.joinpath("environ").read_bytes().split(b"\0")
            except (OSError, ValueError):
                continue
            if argv[:2] == [str(BIN).encode(), b"daemon"] and ("HOME=" + str(self.root)).encode() in environ:
                found.append(int(entry.name))
        return found

    def test_start_launches_the_service_without_connecting(self):
        self.stop_daemon()
        try:
            self.assertEqual(self.cli("start")["computers"], [])
            self.assertTrue((self.root / "runtime/remote-desktops/control.sock").exists())
            self.assertFalse(self.session().exists())
            self.assertEqual(self.cli("start")["computers"], [])
            self.assertEqual(len(self.daemons()), 1)
        finally:
            for pid in self.daemons():
                os.kill(pid, signal.SIGTERM)
            self.wait(lambda: not self.daemons())

    def test_remove_forgets_only_settled_sessions_and_updates_settings(self):
        config = self.root / "config/remote-desktops/computers.json"
        self.connect()
        refused = self.cli("settings", "remove", "laptop", check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("Disconnect", refused.stderr)
        self.assertIn("laptop", json.loads(config.read_text())["computers"])
        (self.session() / "conflict").touch()
        self.cli("disconnect", "laptop")
        self.wait(lambda: self.cli("status", "laptop")["phase"] == "restore-pending")
        self.assertIn("restore", self.cli("settings", "remove", "laptop", check=False).stderr)
        self.assertTrue(self.session().exists())
        self.cli("release", "laptop", "--keep-host-settings")
        self.wait(lambda: self.cli("status", "laptop")["phase"] == "idle")
        launcher = Path(self.cli("launcher", "install", "laptop")["installed"])
        removed = self.cli("settings", "remove", "laptop")
        self.assertEqual(removed, {"removed": True, "computer": "laptop", "launcher": True})
        self.assertEqual(self.cli("status")["computers"], [])
        self.assertFalse(self.session().exists())
        self.assertFalse(launcher.exists())
        self.assertNotIn("laptop", json.loads(config.read_text())["computers"])
        self.assertEqual([c["computer"] for c in self.cli("computers")], ["other"])
        self.assertIn("unknown computer", self.cli("settings", "remove", "laptop", check=False).stderr)
        # The forgotten worker is gone; the same name connects again from a clean record.
        self.assertEqual(self.cli("connect", "laptop", check=False).returncode, 1)
        self.assertIsNotNone(self.connect("other"))

    def test_restart_during_prepare_finishes_cancelled_recovery_without_launch(self):
        directory = self.session()
        directory.mkdir(parents=True)
        (directory / "hold").touch()
        self.cli("connect", "laptop")
        self.wait(lambda: (directory / "prepared").exists())
        self.cli("disconnect", "laptop")
        self.stop_daemon()
        self.start()
        (directory / "hold").unlink()
        self.wait(lambda: self.cli("status", "laptop")["phase"] == "idle")
        self.assertFalse((directory / "launches").exists())
        self.assertFalse(self.cli("status", "laptop")["recovery_pending"])



class SettingsTests(unittest.TestCase):
    """Real config validation and writes; synthetic Moonlight and no networking."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {**os.environ, "HOME": str(self.root), "XDG_CONFIG_HOME": str(self.root / "config"),
                    "XDG_RUNTIME_DIR": str(self.root / "runtime"), "XDG_STATE_HOME": str(self.root / "state"),
                    "REMOTE_DESKTOPS_HELPERS": str(self.root / "helpers")}
        self.env.pop("PYTHONPATH", None)
        package = self.root / "helpers/remote_desktops"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("__path__.append(" + repr(str(ROOT / "remote_desktops")) + ")\n")
        (package / "worker.py").write_text(
            "import contextlib\nfrom remote_desktops import host\n"
            "host.socket.create_connection = lambda *a, **k: contextlib.nullcontext()\n"
            "exec(compile(open(" + repr(str(ROOT / "remote_desktops/worker.py")) + ").read(), 'worker.py', 'exec'))\n")
        bindir = self.root / "bin"
        bindir.mkdir()
        self.env["PATH"] = str(bindir) + os.pathsep + self.env["PATH"]
        moonlight = bindir / "moonlight"
        moonlight.write_text("#!/bin/sh\ncase \"$1\" in --version) echo 'Moonlight v6.1.0';; list) echo \"${FAKE_APP-Desktop}\";;\n"
                             "pair) if [ \"$4\" = 0000 ]; then echo 'Failed to pair: incorrect PIN' >&2; exit 1; fi;\n"
                             "  printf '2\\\\uuid=22222222-3333-4444-5555-666666666666\\n2\\\\hostname=Garage PC\\n2\\\\srvcert=y\\n2\\\\manualaddress=%s\\n' \"$2\" >> \"$XDG_CONFIG_HOME/Moonlight Game Streaming Project/Moonlight.conf\";;\n"
                             "*) exit 99;; esac\n")
        (bindir / "pgrep").write_text("#!/bin/sh\nexit 1\n")
        (bindir / "pgrep").chmod(0o700)
        moonlight.chmod(0o700)
        self.uuid = "11111111-2222-3333-4444-555555555555"
        paired = self.root / "config/Moonlight Game Streaming Project/Moonlight.conf"
        paired.parent.mkdir(parents=True)
        paired.write_text("[hosts]\n1\\uuid=" + self.uuid + "\n1\\hostname=Home PC\n1\\srvcert=synthetic-test-only\n1\\localaddress=home.example.net\n")
        self.config = self.root / "config/remote-desktops/computers.json"

    def cli(self, *args, draft=None, ok=True):
        p = subprocess.run([str(BIN), "--json", "settings", *args], input=json.dumps(draft) if draft else None,
                           env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode == 0, ok, p.stderr)
        return json.loads(p.stdout) if ok else p.stderr

    def draft(self):
        catalog = self.cli("catalog")
        self.assertNotIn("synthetic-test-only", json.dumps(catalog))
        self.assertEqual(catalog["paired"][0]["host"], "home.example.net")
        return {"computer": "home", "pairing_uuid": self.uuid, "revision": catalog["revision"],
                "name": "Home", "host": "home.example.net", "platform": "linux", "profile": "desktop",
                "stream_resolution": "1920x1080", "fps": 60, "bitrate": 30000,
                "codec": "auto", "input": "absolute", "audio": "focus"}

    def test_setup_checks_and_saves_without_starting_daemon_or_stream(self):
        draft = self.draft()
        self.assertTrue(self.cli("test", draft=draft)["tested"])
        self.assertFalse(self.config.exists())
        self.cli("save", draft=draft)
        value = json.loads(self.config.read_text())["computers"]["home"]
        self.assertEqual(value["title"], "Home PC - Moonlight")
        self.assertEqual(value["profiles"]["desktop"]["display"], {"adapter": "external"})
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.root / "runtime").exists())
        self.assertFalse((self.root / "state").exists())
        self.assertTrue(self.cli("catalog")["paired"][0]["configured"])

    def test_audio_settings_round_trip_to_stream_arguments(self):
        self.cli("save", draft=self.draft())
        for audio, focus, host in [("continuous", False, False), ("host", False, True), ("focus", True, False)]:
            with self.subTest(audio=audio):
                draft = self.cli("get", "home")
                draft["audio"] = audio
                self.cli("save", draft=draft)
                self.assertEqual(self.cli("get", "home")["audio"], audio)
                c = json.loads(self.config.read_text())["computers"]["home"]
                result = subprocess.run(
                    ["python3", "-c", "import json, sys; from remote_desktops.host import stream_argv; "
                     "c = json.load(sys.stdin); print(json.dumps(stream_argv(c, c['profiles']['desktop'])))"],
                    input=json.dumps(c), cwd=ROOT, capture_output=True, text=True, check=True, timeout=10)
                args = json.loads(result.stdout)
                self.assertIn("--mute-on-focus-loss" if focus else "--no-mute-on-focus-loss", args)
                self.assertNotIn("--no-mute-on-focus-loss" if focus else "--mute-on-focus-loss", args)
                self.assertIn("--audio-on-host" if host else "--no-audio-on-host", args)
                self.assertNotIn("--no-audio-on-host" if host else "--audio-on-host", args)

    def test_edits_preserve_other_profiles_display_ssh_and_window_identity(self):
        self.cli("save", draft=self.draft())
        value = json.loads(self.config.read_text())
        c = value["computers"]["home"]
        c["platform"] = "macos"
        c["ssh"] = {"user": "synthetic"}
        c["profiles"]["desktop"]["display"] = {"adapter": "macos"}
        c["profiles"]["desktop"].update(hdr=True, system_keys="always")
        c["profiles"]["presentation"] = {"stream_resolution": "3840x2160"}
        value["extra"] = "preserve"
        self.config.write_text(json.dumps(value))
        session = self.root / "state/remote-desktops/sessions/home/session.json"
        session.parent.mkdir(parents=True)
        session.write_text(json.dumps({"desired": True, "phase": "window-ready", "config": c}))
        snapshot = session.read_bytes()
        draft = self.cli("get", "home")
        self.assertEqual(draft["ssh"], {"user": "synthetic"})
        self.assertEqual(draft["display"], {"adapter": "macos"})
        self.assertEqual(draft["profiles"]["desktop"]["display"], {"adapter": "macos"})
        self.assertNotIn("hdr", draft["profiles"]["desktop"])
        draft.update(name="Renamed", stream_resolution="2560x1440", title="ignored", pairing_uuid="ignored-too")
        draft["ssh"] = {"user": "renamed-user", "control_path": "", "alias": ""}
        self.assertIn("reopen it to edit", self.cli("save", draft=draft, ok=False))
        del draft["pairing_uuid"]
        self.cli("save", draft=draft)
        after = json.loads(self.config.read_text())
        expected = value
        expected["computers"]["home"]["name"] = "Renamed"
        expected["computers"]["home"]["ssh"] = {"user": "renamed-user"}
        expected["computers"]["home"]["profiles"]["desktop"]["stream_resolution"] = "2560x1440"
        self.assertEqual(after, expected)
        self.assertEqual(session.read_bytes(), snapshot)

    def test_stale_invalid_duplicate_and_failed_probe_do_not_write(self):
        draft = self.draft()
        self.env["FAKE_APP"] = "Unavailable"
        self.assertIn("pairing-or-app-required", self.cli("test", draft=draft, ok=False))
        self.assertFalse(self.config.exists())
        self.cli("save", draft=draft)
        original = self.config.read_bytes()
        self.assertIn("changed elsewhere", self.cli("save", draft=draft, ok=False))
        duplicate = self.draft()
        duplicate["computer"] = "duplicate"
        self.assertIn("same pairing", self.cli("save", draft=duplicate, ok=False))
        bad = self.cli("get", "home")
        bad["fps"] = 0
        self.assertIn("invalid FPS", self.cli("save", draft=bad, ok=False))
        self.assertEqual(self.config.read_bytes(), original)

    def test_locked_save_leaves_configuration_unchanged(self):
        self.cli("save", draft=self.draft())
        before = self.config.read_bytes()
        draft = self.cli("get", "home")
        draft["name"] = "Changed"
        with self.config.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.assertIn("save is in progress", self.cli("save", draft=draft, ok=False))
        self.assertEqual(self.config.read_bytes(), before)

    def test_remove_without_service_drops_settled_session_and_keeps_pending_recovery(self):
        self.cli("save", draft=self.draft())
        directory = self.root / "state/remote-desktops/sessions/home"
        directory.mkdir(parents=True)
        (directory / "session.json").write_text(json.dumps({"desired": False, "phase": "idle", "config": {"pairing_uuid": self.uuid}}))
        (directory / "recovery.json").write_text(json.dumps({"journal": {"output": {"original": "1"}}}))
        self.assertIn("restore", self.cli("remove", "home", ok=False))
        self.assertIn("home", json.loads(self.config.read_text())["computers"])
        (directory / "recovery.json").write_text(json.dumps({"journal": {}}))
        with (self.root / "state/remote-desktops/writer.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.assertIn("not responding", self.cli("remove", "home", ok=False))
        self.assertTrue(directory.exists())
        self.assertEqual(self.cli("remove", "home"), {"removed": True, "computer": "home", "launcher": False})
        self.assertFalse(directory.exists())
        self.assertEqual(json.loads(self.config.read_text())["computers"], {})
        self.assertIn("unknown computer", self.cli("remove", "home", ok=False))
        # Without a stale session record the same paired computer can be added again.
        self.cli("save", draft=self.draft())
        self.assertIn("home", json.loads(self.config.read_text())["computers"])

    def test_discover_and_pair_use_local_tools_and_moonlight_only(self):
        bindir = self.root / "bin"
        (bindir / "tailscale").write_text("#!/bin/sh\ncat <<'EOF'\n" + json.dumps({"Peer": {"a": {
            "HostName": "Garage PC", "DNSName": "garage.tail.ts.net.", "OS": "windows", "Online": True, "TailscaleIPs": ["100.9.9.9"]}}}) + "\nEOF\n")
        (bindir / "tailscale").chmod(0o700)
        (bindir / "avahi-browse").write_text("#!/bin/sh\nprintf '%s\\n' '=;e;IPv4;Home\\032PC;_nvstream._tcp;local;home-pc.local;192.168.1.2;47989;'\n")
        (bindir / "avahi-browse").chmod(0o700)
        found = self.cli("discover")
        self.assertEqual([c["name"] for c in found["candidates"]], ["Garage PC", "Home PC"])
        self.assertEqual(found["candidates"][1]["pairing_uuid"], self.uuid)
        self.assertFalse(found["candidates"][1]["configured"])
        self.cli("save", draft=self.draft())
        self.assertTrue(self.cli("discover")["candidates"][1]["configured"])
        self.assertIn("incorrect PIN", self.cli("pair", draft={"host": "garage.tail.ts.net", "pin": "0000"}, ok=False))
        paired = self.cli("pair", draft={"host": "garage.tail.ts.net", "pin": "1234"})["paired"]
        self.assertEqual(paired, {"paired": True, "pairing_uuid": "22222222-3333-4444-5555-666666666666", "name": "Garage PC", "host": "garage.tail.ts.net"})
        self.assertTrue(any(c["pairing_uuid"] == paired["pairing_uuid"] for c in self.cli("catalog")["paired"]))
        self.assertFalse((self.root / "state").exists())

    def test_sunshine_without_ssh_survives_check_save_and_reopen(self):
        draft = self.draft()
        draft.update(platform="windows", ssh={}, stream_resolution="1920x1080", display={"adapter": "sunshine"})
        self.assertTrue(self.cli("test", draft=draft)["tested"])
        self.cli("save", draft=draft)
        reopened = self.cli("get", "home")
        self.assertEqual(reopened["display"], {"adapter": "sunshine"})
        self.assertEqual(reopened["stream_resolution"], "1920x1080")

    def test_sunshine_matching_fields_survive_check_save_and_reopen(self):
        output = "{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}"
        reply = {"ok": True, "options": {"output_name": output, "dd_resolution_option": "auto",
                                        "dd_configuration_option": "ensure_only_display"},
                 "offset": 0, "created": "fake-log", "text": ""}
        ssh = self.root / "bin/ssh"
        ssh.write_text("#!/usr/bin/env python3\nimport sys\nsys.stdin.read()\nprint(" + repr(json.dumps(reply)) + ")\n")
        ssh.chmod(0o700)
        draft = self.draft()
        display = {"adapter": "virtual", "output": output, "sync_modes": True,
                   "settings": r"D:\VirtualDisplayDriver\vdd_settings.xml", "initial_resolution": "2560x1440"}
        draft.update(platform="windows", ssh={"alias": "fake-pc"}, stream_resolution="auto", display=display)
        self.assertTrue(self.cli("test", draft=draft)["tested"])
        self.cli("save", draft=draft)
        reopened = self.cli("get", "home")
        self.assertEqual(reopened["display"], display)
        self.assertEqual(reopened["stream_resolution"], "auto")
        reopened["display"]["sync_modes"] = False
        self.assertTrue(self.cli("test", draft=reopened)["tested"])
        self.cli("save", draft=reopened)
        self.assertFalse(self.cli("get", "home")["display"]["sync_modes"])
        # Switching back to the basic adapter discards matching-only settings.
        basic = self.cli("get", "home")
        basic["display"]["adapter"] = "external"
        basic["stream_resolution"] = "1920x1080"
        self.cli("save", draft=basic)
        self.assertEqual(self.cli("get", "home")["display"], {"adapter": "external"})

    def test_managed_display_settings_are_editable_and_inspectable(self):
        draft = self.draft()
        draft.update(platform="macos", ssh={"user": "streamer", "control_path": "/tmp/ctl"}, display={"adapter": "macos", "require_ac": True})
        self.cli("save", draft=draft)
        saved = json.loads(self.config.read_text())["computers"]["home"]
        self.assertEqual(saved["ssh"], {"user": "streamer", "control_path": "/tmp/ctl"})
        self.assertEqual(saved["profiles"]["desktop"]["display"], {"adapter": "macos", "require_ac": True})
        edit = self.cli("get", "home")
        edit["display"] = {"adapter": "external", "require_ac": True}
        edit["ssh"] = {"user": "", "control_path": "", "alias": ""}
        self.cli("save", draft=edit)
        saved = json.loads(self.config.read_text())["computers"]["home"]
        self.assertNotIn("ssh", saved)
        self.assertEqual(saved["profiles"]["desktop"]["display"], {"adapter": "external"})
        bad = self.cli("get", "home")
        bad["display"] = {"adapter": "windows"}
        self.assertIn("platform=windows", self.cli("save", draft=bad, ok=False))
        self.assertIn("ssh-user-required", self.cli("inspect", draft={"computer": "home", "platform": "macos"}, ok=False))
        # Windows inspection goes through SSH only; a fake ssh answers the staged script.
        bindir = self.root / "bin"
        (bindir / "ssh").write_text("#!/bin/sh\nscript=$(cat)\ncase \"$script\" in\n"
            "*Install.ps1*) printf '%s' '{\"ok\":true,\"result\":{\"sunshine_output\":\"{ABCDEF01-1111-2222-3333-444444444444}\",\"helper\":{\"installed\":false},\"displays\":[{\"id\":\"\\\\\\\\?\\\\DISPLAY#MTT1337#1#{g}\",\"name\":\"Virtual\",\"active\":false,\"available\":true}]}}';;\n"
            "*) printf '%s' '{\"ok\":true}';;\nesac\n")
        (bindir / "ssh").chmod(0o700)
        (bindir / "scp").write_text("#!/bin/sh\nexit 0\n")
        (bindir / "scp").chmod(0o700)
        observed = self.cli("inspect", draft={"computer": "home", "platform": "windows", "ssh": {"alias": "laptop"}})
        self.assertEqual(observed["displays"][0]["hardware"], "MTT1337")
        self.assertFalse(observed["helper"]["installed"])
        self.assertIn("choose a paired computer", self.cli("inspect", draft={"computer": "nobody", "platform": "windows", "ssh": {"alias": "laptop"}}, ok=False))

    def test_removed_computer_session_cannot_gain_a_second_owner(self):
        draft = self.draft()
        directory = self.root / "state/remote-desktops/sessions/original"
        directory.mkdir(parents=True)
        (directory / "session.json").write_text(json.dumps({"config":{"pairing_uuid":self.uuid}}))
        self.assertIn("saved session", self.cli("save", draft=draft, ok=False))
        self.assertFalse(self.config.exists())


if __name__ == "__main__":
    unittest.main()
