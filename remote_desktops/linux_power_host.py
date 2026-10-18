"""Standalone, per-user Omarchy host power integration; never exports credentials.

Sunshine's public busy flag tracks an application, not connected clients. This
adapter observes the per-session video workers in a specifically supported build.
Unknown binaries and unreadable state release inhibition rather than guessing.
"""
import fcntl
from functools import lru_cache
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

VERSION = 1
SUPPORTED = {"2026.914.233613"}
UNIT = "remote-desktops-host-power.service"
SUNSHINE_UNIT = "app-dev.lizardbyte.app.Sunshine.service"
BEGIN = "-- BEGIN remote-desktops host power"
END = "-- END remote-desktops host power"
TTL = 6


def check(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path, default=None):
    try:
        check(path.stat().st_size <= 131072, "host-power-file-too-large")
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def write(path, text, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    check(not path.is_symlink(), "host-power-symlink-refused")
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temp = Path(name)
    os.fchmod(fd, mode)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def run(argv, timeout=8):
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    check(result.returncode == 0, "host-power-command-failed: " + Path(argv[0]).name)
    return result.stdout.strip()


def hyprland_command():
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return ["hyprctl"]
    # SSH sessions do not inherit the compositor environment. Select only an
    # unambiguous instance from hyprctl's per-user discovery before writing files.
    instances = json.loads(run(["hyprctl", "instances", "-j"]))
    check(isinstance(instances, list) and len(instances) == 1,
          "host-power-hyprland-session-ambiguous: keep one Omarchy desktop session open")
    instance = instances[0].get("instance", "") if isinstance(instances[0], dict) else ""
    check(isinstance(instance, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", instance),
          "host-power-hyprland-session-unavailable")
    return ["hyprctl", "-i", instance]


def locations():
    home = Path.home()
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/" + str(os.getuid()))) / "remote-desktops-host-power"
    return home / ".local/share/remote-desktops/host-power", runtime


def process_start(pid, proc=Path("/proc")):
    # comm can contain spaces and parentheses; fields following the final ')' begin at field 3.
    return (proc / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]


def stream_count(pid, expected_binary, proc=Path("/proc")):
    check(pid > 0, "host-power-sunshine-not-running")
    path = proc / str(pid)
    before = process_start(pid, proc)
    check((path / "exe").resolve(strict=True) == expected_binary, "host-power-process-changed")
    tasks = list((path / "task").iterdir())
    check(len(tasks) <= 4096, "host-power-too-many-threads")
    count = 0
    for task in tasks:
        try:
            count += task.joinpath("comm").read_text().strip() == "session::video"
        except FileNotFoundError:
            pass  # A worker can end while its task directory is being read.
    check(process_start(pid, proc) == before, "host-power-process-changed")
    return count


@lru_cache(maxsize=4)
def _binary_hash(path, stamp):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def binary_hash(path):
    stat = path.stat()
    return _binary_hash(path, (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns))


def on_ac(root=Path("/sys/class/power_supply")):
    batteries, sources = [], []
    for supply in root.iterdir():
        try:
            kind = (supply / "type").read_text().strip()
            if kind == "Battery":
                batteries.append((supply / "status").read_text().strip())
            elif (supply / "online").exists():
                sources.append((supply / "online").read_text().strip() == "1")
        except FileNotFoundError:
            pass
    # Unknown power state is not permission to inhibit on battery.
    return any(sources) if sources else bool(batteries) and all(s == "Charging" for s in batteries)


def lease_valid(runtime, proc=Path("/proc"), now=None):
    try:
        value = read_json(runtime / "lease.json", {})
        return (value.get("version") == VERSION and type(value.get("pid")) is int
                and 0 <= (time.monotonic() if now is None else now) - value["heartbeat"] < TTL
                and process_start(value["pid"], proc) == value["start"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def observation(config):
    binary = Path("/usr/bin/sunshine")
    check(binary_hash(binary) == config["binary_hash"], "host-power-sunshine-updated: reapply the policy")
    state = read_json(Path.home() / ".config/sunshine/sunshine_state.json", {})
    check(state.get("root", {}).get("uniqueid", "").lower() == config["pairing_uuid"], "host-power-host-identity-changed")
    pid = int(run(["systemctl", "--user", "show", SUNSHINE_UNIT, "-p", "MainPID", "--value"]))
    if not pid:
        return 0, on_ac()
    # A stopped/frozen host must not retain inhibition just because its threads exist.
    connection = http.client.HTTPConnection("127.0.0.1", config.get("port", 47989), timeout=2)
    try:
        connection.request("GET", "/serverinfo")
        response = connection.getresponse()
        body = response.read(32769)
        check(response.status == 200 and len(body) <= 32768, "host-power-server-unavailable")
        tree = ET.fromstring(body)
        check(tree.findtext("uniqueid", "").lower() == config["pairing_uuid"], "host-power-server-identity-changed")
    finally:
        connection.close()
    return stream_count(pid, binary.resolve()), on_ac()


def hold(runtime):
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    value = {"version": VERSION, "pid": os.getpid(), "start": process_start(os.getpid())}
    try:
        while True:
            value["heartbeat"] = time.monotonic()
            write(runtime / "lease.json", json.dumps(value) + "\n")
            # The inherited inhibitor FD closes on EOF, missing heartbeats, or process death.
            ready, _, _ = select.select([sys.stdin.buffer], [], [], TTL)
            if not ready or not os.read(sys.stdin.fileno(), 4096):
                break
    finally:
        (runtime / "lease.json").unlink(missing_ok=True)


def watch():
    root, runtime = locations()
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (runtime / "watch.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        watch_locked(root, runtime)
    finally:
        lock.close()


def eligible(stream_workers, policy, ac):
    return stream_workers > 0 and (policy == "always" or policy == "ac" and ac)


def watch_locked(root, runtime):
    child = None
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        while True:
            active, stream_workers, ac, error = False, 0, False, ""
            try:
                config = read_json(root / "policy.json")
                check(config.get("version") == VERSION, "host-power-unknown-policy-version")
                stream_workers, ac = observation(config)
                active = eligible(stream_workers, config["policy"], ac)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError, http.client.HTTPException, ET.ParseError):
                error = "Host state unavailable or Sunshine changed; inhibition released. Recheck the host."
            if child and (not active or child.poll() is not None):
                child.stdin.close()
                try:
                    child.wait(timeout=TTL + 1)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                child = None
            if active and child is None:
                child = subprocess.Popen(["systemd-inhibit", "--what=sleep:idle:handle-lid-switch", "--mode=block",
                                          "--who=Remote Desktops", "--why=Sunshine stream connected",
                                          "/usr/bin/python3", str(root / "host.py"), "hold"],
                                         stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if child:
                try:
                    child.stdin.write(b".")
                    child.stdin.flush()
                except BrokenPipeError:
                    error = "Sleep inhibition was refused. Check the host's inhibitor permissions."
            if active and not lease_valid(runtime):
                error = "Waiting for the sleep inhibitor. Recheck host permissions if this persists."
            write(runtime / "status.json", json.dumps({"version": VERSION, "heartbeat": time.monotonic(),
                  "active": lease_valid(runtime), "stream_workers": stream_workers, "on_ac": ac, "error": error}) + "\n")
            time.sleep(2)
    finally:
        if child:
            child.stdin.close()
        (runtime / "status.json").unlink(missing_ok=True)


def lid_close():
    _, runtime = locations()
    if not lease_valid(runtime):
        run(["/usr/share/omarchy/bin/omarchy-system-lid-close"], timeout=25)


def inspect(pairing_uuid):
    root, runtime = locations()
    check(Path("/usr/share/omarchy/bin/omarchy-system-lid-close").is_file(), "host-power-requires-omarchy")
    binary = Path("/usr/bin/sunshine")
    version = run([str(binary), "--version"])
    match = re.search(r"(?:version:|Sunshine v?)\s*(\d[\d.]+)", version, re.I)
    version = match[1] if match else "unknown"
    state = read_json(Path.home() / ".config/sunshine/sunshine_state.json", {})
    check(state.get("root", {}).get("uniqueid", "").lower() == pairing_uuid, "host-power-host-identity-mismatch")
    config = read_json(root / "policy.json", {})
    port = 47989
    for line in (Path.home() / ".config/sunshine/sunshine.conf").read_text().splitlines():
        if re.match(r"^\s*port\s*=", line):
            port = int(line.split("=", 1)[1].split("#", 1)[0].strip())
    check(1024 <= port <= 65519, "host-power-invalid-sunshine-port")
    status = read_json(runtime / "status.json", {})
    fresh = 0 <= time.monotonic() - status.get("heartbeat", -TTL) < TTL
    supported = version in SUPPORTED
    stream_workers, ac = observation({"binary_hash": binary_hash(binary), "pairing_uuid": pairing_uuid, "port": port}) if supported else (None, on_ac())
    return {"installed": (root / "host.py").is_file(), "policy": config.get("policy", "off"),
            "supported": supported, "sunshine_version": version, "stream_workers": stream_workers, "on_ac": ac,
            "active": lease_valid(runtime), "running": fresh,
            "error": (status.get("error", "") if fresh else "") if supported else "Unsupported Sunshine build; only disabling the policy is available.",
            "binary_hash": binary_hash(binary), "port": port}


def lid_config(text, command=None):
    check(text.count(BEGIN) == text.count(END) and text.count(BEGIN) <= 1, "host-power-malformed-lid-block")
    if BEGIN in text:
        start, end = text.index(BEGIN), text.index(END) + len(END)
        check(start < end - len(END), "host-power-malformed-lid-block")
        text = text[:start] + text[end:].lstrip("\n")
    if command:
        text = text.rstrip("\n") + "\n\n" + BEGIN + "\n"
        for switch in ("Lid Switch", "Apple SMC power/lid events"):
            text += "o.rebind(" + json.dumps("switch:on:" + switch) + ", nil, " + json.dumps(command) + ", { locked = true })\n"
        text += END + "\n"
    return text


def configure(request):
    policy, identity = request["policy"], request["pairing_uuid"]
    check(policy in ("off", "ac", "always"), "host-power-invalid-policy")
    observed = inspect(identity)
    check(policy == "off" or observed["supported"], "host-power-unsupported-sunshine")
    check(policy == "off" and not observed["supported"] or observed["stream_workers"] == 0,
          "host-power-streams-active: disconnect all Sunshine clients before changing host power")
    root, runtime = locations()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    lock = (root / "configure.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return configure_locked(request, observed, root)
    finally:
        lock.close()


def configure_locked(request, observed, root):
    policy, identity = request["policy"], request["pairing_uuid"]
    hypr = Path.home() / ".config/hypr/hyprland.lua"
    previous = hypr.read_text()
    # Do not override user-authored lid bindings, including bindings in included files.
    if policy != "off":
        for path in hypr.parent.rglob("*.lua"):
            text = lid_config(path.read_text()) if path == hypr else path.read_text()
            check(not re.search(r"switch:on:(Lid Switch|Apple SMC power/lid events)", text),
                  "host-power-custom-lid-binding: preserve the host's custom binding")
    source = request["source"]
    check(len(source) <= 100000, "host-power-source-too-large")
    unit = Path.home() / ".config/systemd/user" / UNIT
    config = root / "policy.json"
    script = root / "host.py"
    for path in (hypr, unit, config, script):
        check(not path.is_symlink(), "host-power-symlink-refused")
    if policy != "off":
        # Check permission in the same user-manager context as the installed
        # service. The SSH session itself may not have logind seat privileges.
        run(["systemd-run", "--user", "--wait", "--pipe", "--collect", "--quiet",
             "systemd-inhibit", "--what=sleep:idle:handle-lid-switch", "--mode=block", "/usr/bin/true"])
    compositor = hyprland_command()
    files = {p: p.read_bytes() if p.exists() else None for p in (hypr, unit, config, script)}
    written = {}

    def replace(path, content):
        check(not path.is_symlink(), "host-power-symlink-refused")
        current = path.read_bytes() if path.exists() else None
        check(current == files[path], "host-power-files-changed: recheck before applying")
        write(path, content)
        written[path] = content.encode()

    old_policy = read_json(config, {}).get("policy", "off")
    backup = hypr.with_name("hyprland.lua.before-host-power")
    if not backup.exists():
        write(backup, previous)
    try:
        # No streams are active; releasing an old inhibitor cannot interrupt a stream.
        subprocess.run(["systemctl", "--user", "stop", UNIT], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        replace(script, source)
        replace(config, json.dumps({"version": VERSION, "policy": policy, "pairing_uuid": identity,
                                   "binary_hash": observed["binary_hash"], "port": observed.get("port", 47989)}) + "\n")
        replace(unit, "[Unit]\nDescription=Remote Desktops host sleep policy\nPartOf=graphical-session.target\n"
              "After=graphical-session.target\n[Service]\nType=simple\nExecStart=/usr/bin/python3 "
              + json.dumps(str(script).replace("%", "%%")) + " watch\nRestart=on-failure\nRestartSec=2\n"
              "KillMode=control-group\nTimeoutStopSec=10\n[Install]\nWantedBy=graphical-session.target\n")
        command = shlex.join(["/usr/bin/python3", str(script), "lid-close"]) if policy != "off" else None
        replace(hypr, lid_config(previous, command))
        run(compositor + ["reload"])
        check(not run(compositor + ["configerrors"]), "host-power-hyprland-config-error")
        run(["systemctl", "--user", "daemon-reload"])
        run(["systemctl", "--user", "disable" if policy == "off" else "enable", UNIT])
        if policy != "off":
            run(["systemctl", "--user", "start", UNIT])
    except Exception:
        conflict = False
        for path, expected in reversed(list(written.items())):
            if path.is_symlink() or not path.exists() or path.read_bytes() != expected:
                conflict = True
                continue
            content = files[path]
            if content is None:
                path.unlink(missing_ok=True)
            else:
                write(path, content.decode())
        subprocess.run(compositor + ["reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        subprocess.run(["systemctl", "--user", "daemon-reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        subprocess.run(["systemctl", "--user", "disable" if old_policy == "off" else "enable", UNIT],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        if old_policy != "off" and not conflict:
            subprocess.run(["systemctl", "--user", "start", UNIT], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        if conflict:
            raise ValueError("host-power-restore-conflict: a file changed during setup; your edit was preserved; recheck the host") from None
        raise
    try:
        return {k: v for k, v in inspect(identity).items() if k != "binary_hash"}
    except Exception:
        raise ValueError("host-power-status-unavailable: policy applied; recheck Host power for its current status") from None


def request_main(request):
    identity = request.get("pairing_uuid", "").lower()
    check(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", identity), "host-power-invalid-identity")
    request["pairing_uuid"] = identity
    if request["operation"] == "status":
        return {k: v for k, v in inspect(identity).items() if k != "binary_hash"}
    check(request["operation"] == "configure", "host-power-unknown-operation")
    return configure(request)


if __name__ == "__main__":
    if "REQUEST" in globals():
        try:
            print(json.dumps({"ok": True, "result": request_main(REQUEST)}))
        except Exception as error:
            message = str(error) if isinstance(error, ValueError) else "host-power-operation-failed: check the host and retry"
            print(json.dumps({"ok": False, "error": message}))
    elif sys.argv[1:] == ["watch"]:
        watch()
    elif sys.argv[1:] == ["hold"]:
        hold(locations()[1])
    elif sys.argv[1:] == ["lid-close"]:
        lid_close()
