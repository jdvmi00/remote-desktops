"""Host preparation and recovery extracted from Hypertile (MIT).

Invoked by the Rust session worker; this module never owns windows or clients.
"""
import configparser
import copy
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
from .storage import atomic_json, read_json
from .mac_display import same_setting, manages_mode
from . import virtual_display, windows_display

NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
UUID = re.compile(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}\Z")


def load(path, default):
    try:
        return read_json(path)
    except FileNotFoundError:
        return copy.deepcopy(default)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def resolution(value, allow_auto=False):
    if allow_auto and value == "auto":
        return value  # Fit the window: the daemon resolves the size at launch.
    require(isinstance(value, str) and re.fullmatch(r"\d{3,5}x\d{3,5}", value), "resolution must be WIDTHxHEIGHT")
    require(all(240 <= int(n) <= 16384 for n in value.split("x")), "resolution outside supported range")
    return value


def configuration(path):
    return configuration_value(load(path, {"version": 1, "computers": {}}))


def configuration_value(value):
    require(value.get("version") == 1 and isinstance(value.get("computers"), dict), "unsupported computers.json schema")
    identities = set()
    titles = set()
    for name, computer in value["computers"].items():
        require(NAME.fullmatch(name), "invalid computer ID")
        require(isinstance(computer.get("host"), str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", computer["host"]), "invalid host")
        require(UUID.fullmatch(computer.get("pairing_uuid", "")), "pairing_uuid must reference a paired Moonlight computer")
        identity = computer["pairing_uuid"].lower()
        require(identity not in identities, "two computers refer to the same pairing identity")
        identities.add(identity)
        require(isinstance(computer.get("title"), str) and 1 <= len(computer["title"]) <= 250, "title must be the final Moonlight window title")
        require(not any(ord(c) < 32 for c in computer["title"]), "title must not contain control characters")
        require(computer["title"] not in titles, "computer window titles must be unique for launcher matching")
        titles.add(computer["title"])
        if "name" in computer:
            require(isinstance(computer["name"], str) and 1 <= len(computer["name"]) <= 100
                    and not any(ord(c) < 32 or ord(c) == 127 for c in computer["name"]), "name must be 1–100 characters without control characters")
        require(isinstance(computer.get("profiles"), dict) and computer["profiles"], "computer needs profiles")
        require(computer.get("platform", "unknown") in ("macos", "windows", "linux", "unknown"), "invalid host platform")
        require("default_profile" not in computer or computer["default_profile"] in computer["profiles"], "unknown default profile")
        for profile_name, p in computer["profiles"].items():
            require(NAME.fullmatch(profile_name), "invalid profile ID")
            resolution(p.get("stream_resolution"), allow_auto=True)
            require(type(p.get("fps", 60)) is int and 20 <= p.get("fps", 60) <= 240, "invalid FPS")
            require(type(p.get("bitrate", 60000)) is int and 1000 <= p.get("bitrate", 60000) <= 200000, "invalid bitrate")
            require(p.get("codec", "HEVC") in ("HEVC", "H.264", "AV1", "auto"), "invalid codec")
            require(p.get("audio", "focus") in ("focus", "continuous", "host"), "invalid audio policy")
            require(p.get("input", "absolute") in ("absolute", "relative"), "invalid input policy")
            require(p.get("system_keys", "never") in ("never", "fullscreen", "always"), "invalid system key capture policy")
            require(p.get("keep_awake", "visible") in ("visible", "always", "never"), "invalid keep_awake policy")
            require(p.get("aspect", "fit") == "fit", "only aspect=fit is supported")
            require(p.get("decoder", "hardware") in ("hardware", "software", "auto"), "invalid decoder")
            for flag in ("hdr", "yuv444"):
                require(type(p.get(flag, False)) is bool, "invalid " + flag)
            display = p.get("display", {"adapter": "external"})
            require(display.get("adapter") in ("external", "betterdisplay", "macos", "windows", "virtual", "sunshine"), "unknown display adapter")
            if display["adapter"] == "sunshine":
                require(computer.get("platform") == "windows", "Sunshine matching requires platform=windows")
            if display["adapter"] == "virtual":
                require(computer.get("platform") == "windows", "virtual display adapter requires platform=windows")
                alias = computer.get("ssh", {}).get("alias")
                require(alias is None or windows_display.ALIAS.fullmatch(alias), "invalid ssh.alias")
                virtual_display.settings_path(display)
                require(type(display.get("sync_modes", False)) is bool, "sync_modes must be boolean")
                if "initial_resolution" in display:
                    resolution(display["initial_resolution"])
                if "output" in display:
                    from .sunshine_display import output_id
                    output_id(display["output"])
            if display["adapter"] == "windows":
                require(computer.get("platform") == "windows", "Windows display adapter requires platform=windows")
                require(windows_display.ALIAS.fullmatch(computer.get("ssh", {}).get("alias", "")), "Windows adapter requires an approved ssh.alias")
                device = display.get("device_id", "")
                require(isinstance(device, str) and 1 <= len(device) <= 512 and device.startswith("\\\\?\\DISPLAY#")
                        and all(ord(c) >= 32 for c in device), "Windows adapter requires a persistent display device_id")
            if display["adapter"] == "betterdisplay":
                require(UUID.fullmatch(display.get("uuid", "")), "display requires a persistent UUID")
                require(type(display.get("follow_main", False)) is bool, "follow_main must be boolean")
                mode = display.get("mode", {})
                resolution(mode.get("resolution"))
                require(type(mode.get("hidpi")) is bool and type(mode.get("refresh")) in (int, float)
                        and 20 <= mode["refresh"] <= 240, "invalid host mode")
            if display["adapter"] in ("betterdisplay", "macos"):
                if display["adapter"] == "macos":
                    require(computer.get("platform") == "macos", "native adapter requires platform=macos")
                    require(display.get("follow_main", True) is True, "native desktop follows the main display")
                    require("mode" not in display and "uuid" not in display, "native desktop preserves the main display mode")
                ssh = computer.get("ssh", {})
                require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", ssh.get("user", "")), "Mac adapter requires ssh.user")
                if "control_path" in ssh:
                    require(isinstance(ssh["control_path"], str) and ssh["control_path"].startswith("/"), "SSH control_path must be absolute")
    return value["computers"]


def moonlight_hosts():
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    c = configparser.ConfigParser(interpolation=None)
    c.read(base / "Moonlight Game Streaming Project/Moonlight.conf")
    hosts = c["hosts"] if c.has_section("hosts") else {}
    result = {}
    for key, value in hosts.items():
        if key.endswith("\\uuid"):
            prefix = key[:-4]
            # Certificate material never leaves Moonlight's own configuration.
            result[value.lower()] = {"name": hosts.get(prefix + "hostname"),
                                      "paired": bool(hosts.get(prefix + "srvcert")),
                                      "address": hosts.get(prefix + "manualaddress") or hosts.get(prefix + "localaddress") or hosts.get(prefix + "remoteaddress")}
    return result


class Host:
    def __init__(self, computer, profile):
        self.computer, self.profile = computer, profile
        self.display = profile.get("display", {"adapter": "external"})

    def remote(self, operation, **values):
        if self.display["adapter"] == "windows":
            return windows_display.remote(self.computer, self.display, operation, **values)
        ssh = self.computer["ssh"]
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=5"]
        if ssh.get("control_path"):
            argv += ["-S", ssh["control_path"]]
        argv += [ssh["user"] + "@" + self.computer["host"], "python3 -"]
        request = {"operation": operation, "adapter": self.display["adapter"], "display_uuid": self.display.get("uuid"),
                   "follow_main": self.display.get("follow_main", self.display["adapter"] == "macos"),
                   "pairing_uuid": self.computer["pairing_uuid"], **values}
        program = "REQUEST = " + repr(request) + "\n" + Path(__file__).with_name("mac_display.py").read_text()
        p = subprocess.run(argv, input=program, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
        if p.returncode:
            # SSH diagnostics can contain configuration details; expose a typed error.
            raise ValueError("host-unreachable: SSH unavailable; check the approved account/control socket")
        try:
            result = json.loads(p.stdout)
        except ValueError:
            raise ValueError("display-probe-failed: remote adapter returned invalid data") from None
        if not result.get("ok"):
            raise ValueError(result.get("error", "display operation failed"))
        return result["result"]

    def probe(self, pairing=True):
        info = {"adapter": self.display["adapter"], "permissions": "unknown", "media_path": "unknown"}
        if pairing:
            known = moonlight_hosts().get(self.computer["pairing_uuid"].lower())
            require(known and known["paired"], "pairing-required: pair this UUID in Moonlight first")
            require(shutil.which("moonlight"), "moonlight-missing: install Moonlight Qt")
            version = subprocess.run(["moonlight", "--version"], text=True, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, timeout=4)
            match = re.search(r"Moonlight v?(\d+\.\d+(?:\.\d+)?)", version.stdout)
            info["client_version"] = match[1] if match else "unknown"
            # Address is useful for diagnostics; the actual launch uses the paired
            # UUID so host selection and certificate verification stay in Moonlight.
            try:
                with socket.create_connection((self.computer["host"], 47989), timeout=4):
                    pass
            except OSError:
                raise ValueError("host-unreachable: Sunshine port 47989 unavailable") from None
            info["pairing"] = "configured; certificate checked by Moonlight at connection"
            apps = subprocess.run(["moonlight", "list", self.computer["pairing_uuid"]], text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12)
            require(apps.returncode == 0 and "Desktop" in (line.strip() for line in apps.stdout.splitlines()),
                    "pairing-or-app-required: Moonlight could not list the paired host's Desktop app")
            info["pairing"] = "authenticated app list via Moonlight"
            info["moonlight_saved_address"] = known["address"]
        if self.display["adapter"] == "external":
            return {**info, "restoration": "externally-managed", "display": "externally-managed"}
        if self.display["adapter"] == "sunshine":
            return {**info, "restoration": "sunshine", "host_display": {"verified": False}, "display": "host resolution unverified"}
        if self.display["adapter"] == "virtual":
            from . import sunshine_display
            sunshine_display.snapshot(self)
            return {**info, "restoration": "sunshine", "display": "capture verification pending"}
        observed = self.remote("probe")
        if self.display["adapter"] == "windows":
            require(not observed.get("error"), observed.get("error", "Windows display helper error"))
            return {**info, "display": observed, "restoration": "managed"}
        require(not manages_mode(self.display, observed) or
                any(same_setting("mode", self.display["mode"], m) for m in observed["modes"]),
                "display-mode-unavailable: requested mode is not advertised")
        require(not self.display.get("require_ac", False) or observed["ac_power"], "power-required: connect the Mac to AC")
        return {**info, **observed, "restoration": "managed"}

    def change(self, field, expected, value, **guards):
        return self.remote("change", field=field, expected=expected, value=value, **guards)

    def for_display(self, identity):
        profile = copy.deepcopy(self.profile)
        profile["display"].update(uuid=identity, follow_main=False)
        return Host(self.computer, profile)


def prepare(record, host, persist):
    if host.display["adapter"] in ("external", "sunshine"):
        return
    if host.display["adapter"] == "virtual":
        return virtual_display.prepare(record, host, persist)
    if host.display["adapter"] == "windows":
        return windows_display.prepare(record, host, persist)
    observed = host.probe(pairing=False)
    following = host.display.get("follow_main", host.display["adapter"] == "macos")
    desired = {"output": observed["identity"]["displayID"]}
    if manages_mode(host.display, observed):
        desired["mode"] = host.display["mode"]
    recovery = record.get("display_recovery")
    if recovery:
        require(observed.get("topology") == recovery["topology"], "display-topology-changed: lid changed again during recovery")
        for field in desired:
            require(same_setting(field, observed["current"][field], recovery["current"][field])
                    or same_setting(field, observed["current"][field], desired[field]),
                    "restore-conflict: display changed after recovery was requested")
    journal = record.setdefault("journal", {})
    if "mode" not in desired and "mode" in journal:
        # A mode belongs to its physical UUID, never to whichever panel is now
        # primary. Restore the old display when reachable; retain pending work
        # if it has been unplugged or changed independently.
        restore(record, host, persist, fields=("mode",))
        observed = host.probe(pairing=False)
        require(observed["identity"]["displayID"] == desired["output"], "display-topology-changed: main display moved")
    # Capture every baseline before the first mutation. Restarting Sunshine
    # must not turn a side effect into the next setting's "original" value.
    for field in desired:
        current = observed["current"][field]
        if field not in journal and not same_setting(field, current, desired[field]):
            journal[field] = {"original": current, "applied": desired[field], "phase": "intent"}
            if following and field == "mode":
                journal[field]["display_uuid"] = observed["identity"]["UUID"]
    persist()
    for field in desired:
        current = observed["current"][field]
        entry = journal.get(field)
        if entry is None:
            require(same_setting(field, current, desired[field]), "restore-conflict: unchanged setting moved during preparation")
            continue
        if field == "mode" and following:
            require(entry.get("display_uuid", host.display["uuid"]).lower() == observed["identity"]["UUID"].lower(),
                    "display-identity-changed: mode journal belongs to another display")
        if field == "output" and recovery and entry["applied"] != desired[field]:
            require(entry["applied"] == recovery["current"][field], "capture-display-changed: output no longer owned")
            # Follow a new main display or a renewed CoreGraphics ID without
            # replacing the original Sunshine output baseline.
            entry.update(applied=desired[field], phase="intent")
            persist()
        require(same_setting(field, entry["applied"], desired[field]), "display-identity-changed: restore the previous journal first")
        if same_setting(field, current, entry["applied"]):
            entry["phase"] = "applied"  # Recover a crash after the write, before readback.
            persist()
            continue
        expected = recovery["current"][field] if recovery else entry["original"]
        require(same_setting(field, current, expected) and (recovery or entry["phase"] == "intent"),
                "restore-conflict: host setting changed while owned")
        guards = {"expected_identity": observed["identity"]["UUID"]} if following else {}
        host.change(field, current, entry["applied"], **guards)
        observed = host.probe(pairing=False)
        require(observed["identity"]["displayID"] == desired["output"], "display-topology-changed: main display moved")
        require(same_setting(field, observed["current"][field], entry["applied"]), "display-readback-failed: restoration required")
        entry["requested"] = desired[field]
        entry["applied"] = observed["current"][field]
        entry["phase"] = "applied"
        persist()
    if following:
        # Opening/closing a panel can change Sunshine's cached input display
        # even when its numeric output setting needed no write.
        host.remote("refresh", expected_identity=observed["identity"]["UUID"], expected=observed["current"])
    record["resolved"] = {**record.get("resolved", {}), **{k: v for k, v in observed.items() if k != "modes"}}
    record["mac_topology"] = observed.get("topology")
    record.pop("display_recovery", None)
    persist()


def restore(record, host, persist, fields=("mode", "output")):
    if host.display["adapter"] in ("virtual", "sunshine"):
        return True  # Sunshine reverts the display itself when the session ends.
    if host.display["adapter"] == "windows":
        return windows_display.restore(record, host, persist)
    journal = record.get("journal", {})
    if not journal:
        return True
    # Mode is a compound setting: changing only one component can select another
    # mode. Compare/restore the entire tuple, then the capture output.
    for field in fields:
        entry = journal.get(field)
        if not entry:
            continue
        target = host.for_display(entry.get("display_uuid", host.display["uuid"])) if field == "mode" and host.display.get("follow_main") else host
        try:
            observed = target.remote("probe")
        except ValueError as error:
            if field != "mode" or "display-missing" not in str(error):
                raise
            entry["phase"] = "unavailable"
            persist()
            continue
        current = observed["current"][field]
        if same_setting(field, current, entry["original"]):
            del journal[field]
            persist()
            continue
        recovery = record.get("display_recovery")
        lid_reset = (recovery and observed.get("topology") == recovery["topology"]
                     and same_setting(field, current, recovery["current"][field]))
        if not same_setting(field, current, entry["applied"]) and not lid_reset:
            entry["phase"] = "conflict"
            persist()
            continue
        target.change(field, current, entry["original"])
        observed = target.remote("probe")
        require(same_setting(field, observed["current"][field], entry["original"]), "restore-readback-failed")
        del journal[field]
        persist()
    if not journal:
        record.pop("display_recovery", None)
    return not journal


def stream_argv(computer, p, fitted=None):
    size = fitted or p["stream_resolution"]
    require(size != "auto", "resolution-required: the window size was not resolved before launch")
    # Sunshine requires the client optimization flag to apply its automatic
    # display resolution. Other adapters retain ownership of their host modes.
    follows_stream = computer.get("platform") == "windows" and p.get("display", {}).get("adapter") in ("virtual", "sunshine")
    return ["moonlight", "stream", "--resolution", resolution(size), "--fps", str(p.get("fps", 60)),
            "--bitrate", str(p.get("bitrate", 60000)), "--display-mode", "windowed",
            "--absolute-mouse" if p.get("input", "absolute") == "absolute" else "--no-absolute-mouse",
            "--capture-system-keys", p.get("system_keys", "never"), "--no-quit-after",
            "--game-optimization" if follows_stream else "--no-game-optimization",
            "--video-codec", p.get("codec", "HEVC"), "--video-decoder", p.get("decoder", "hardware"),
            "--keep-awake" if p.get("keep_awake") == "always" else "--no-keep-awake",
            "--mute-on-focus-loss" if p.get("audio", "focus") == "focus" else "--no-mute-on-focus-loss",
            "--audio-on-host" if p.get("audio") == "host" else "--no-audio-on-host",
            "--hdr" if p.get("hdr") else "--no-hdr", "--yuv444" if p.get("yuv444") else "--no-yuv444",
            computer["pairing_uuid"], "Desktop"]
