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
            result={'argv':['python3','-u',str(Path(__file__).with_name('client.py')),str(path.parent)],'resolved':record['resolved']}
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
with (directory/'launches').open('a') as log: log.write(str(os.getpid())+'\n')
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

    def connect(self, name="laptop"):
        self.cli("connect", name)
        self.wait(lambda: self.cli("status", name)["pid"] is not None)
        pid = self.cli("status", name)["pid"]
        launches = self.session(name) / "launches"
        self.wait(lambda: launches.exists() and str(pid) in launches.read_text().splitlines())
        return pid

    def test_repeat_connect_and_daemon_restart_reuse_the_same_client(self):
        pid = self.connect()
        first = self.cli("status", "laptop")["generation"]
        self.assertEqual(self.cli("connect", "laptop")["generation"], first)
        self.stop_daemon()
        self.start()
        self.assertEqual(self.cli("connect", "laptop")["pid"], pid)
        self.assertEqual(self.session().joinpath("launches").read_text().splitlines(), [str(pid)])
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
        self.assertEqual((self.session() / "launches").read_text().splitlines(), [str(pid)])

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

    def test_workspace_and_geometry_changes_never_place_or_restart_the_window(self):
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
        shim = bins / "hyprctl"
        shim.write_text("#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\n"
                        f"with Path({str(calls)!r}).open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
                        f"print(Path({str(clients)!r}).read_text() if 'clients' in sys.argv else 'ok')\n")
        shim.chmod(0o755)
        self.env["PATH"] = str(bins) + os.pathsep + self.env["PATH"]
        self.start()
        connection, _ = server.accept()
        self.addCleanup(connection.close)
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


if __name__ == "__main__":
    unittest.main()
