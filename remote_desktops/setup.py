"""Setup-time operations: discovery, Moonlight pairing, and host inspection.

None of these start a stream, change a host display, or write recovery state.
Pairing is delegated to Moonlight's own command line so certificates and the
client identity stay in Moonlight's configuration.
"""
import json
import re
import shutil
import subprocess
from .host import Host, moonlight_hosts, require
from . import windows_display

HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}\Z")
SSH_USER = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}\Z")
PLATFORMS = {"macos": "macos", "windows": "windows", "linux": "linux"}


def _run(argv, timeout):
    return subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def tailscale_peers(timeout=5):
    """Peers from the local tailscale daemon; only platforms that can run Sunshine."""
    if not shutil.which("tailscale"):
        return []
    try:
        data = json.loads(_run(["tailscale", "status", "--json"], timeout).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    peers = []
    for peer in (data.get("Peer") or {}).values():
        platform = PLATFORMS.get((peer.get("OS") or "").lower())
        dns = (peer.get("DNSName") or "").rstrip(".")
        ips = [ip for ip in (peer.get("TailscaleIPs") or []) if ":" not in ip]
        host = dns or (ips[0] if ips else "")
        if not platform or not HOST.fullmatch(host):
            continue
        peers.append({"name": peer.get("HostName") or dns.split(".")[0], "host": host, "platform": platform,
                      "source": "tailscale", "online": bool(peer.get("Online")), "addresses": [a for a in [dns, *ips] if a]})
    return peers


def lan_hosts(timeout=4):
    """Sunshine hosts announcing _nvstream._tcp on the local network."""
    if not shutil.which("avahi-browse"):
        return []
    try:
        out = _run(["avahi-browse", "-rtp", "_nvstream._tcp"], timeout + 3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = {}
    for line in out.splitlines():
        parts = line.split(";")
        if len(parts) < 9 or parts[0] != "=":
            continue
        name = re.sub(r"\\(\d{3})", lambda m: chr(int(m[1])), parts[3])
        hostname, address = parts[6].rstrip("."), parts[7]
        if not HOST.fullmatch(hostname):
            continue
        entry = found.setdefault(hostname.lower(), {"name": name, "host": hostname, "platform": None, "source": "lan",
                                                     "online": True, "addresses": [hostname]})
        if address and ":" not in address and HOST.fullmatch(address) and address not in entry["addresses"]:
            entry["addresses"].append(address)
    return list(found.values())


def discover():
    paired = {key: h for key, h in moonlight_hosts().items() if h["paired"]}
    candidates = []
    for entry in tailscale_peers() + lan_hosts():
        addresses = {a.lower() for a in entry["addresses"]}
        # Tailscale and LAN can report the same machine; merge by short name.
        short = entry["host"].split(".")[0].lower()
        existing = next((c for c in candidates if c["host"].split(".")[0].lower() == short
                         or c["name"].lower() == entry["name"].lower()), None)
        if existing:
            existing["addresses"] = existing["addresses"] + [a for a in entry["addresses"] if a not in existing["addresses"]]
            existing["online"] = existing["online"] or entry["online"]
            existing["platform"] = existing["platform"] or entry["platform"]
            continue
        entry["pairing_uuid"] = next((key for key, h in paired.items()
                                      if (h["address"] or "").lower() in addresses
                                      or (h["name"] or "").lower() in (entry["name"].lower(), short)), None)
        candidates.append(entry)
    candidates.sort(key=lambda c: (not c["online"], c["name"].lower()))
    return {"candidates": candidates}


def moonlight_gui_running():
    """The Moonlight GUI rewrites its configuration on exit; pairing must not race it."""
    try:
        out = _run(["pgrep", "-a", "-x", "moonlight"], 3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    for line in out.splitlines():
        argv = line.split()[1:]
        if len(argv) < 2 or argv[1] not in ("stream", "pair", "list", "quit"):
            return True
    return False


def summarize(text):
    """Last informative Moonlight line, without URLs or paths."""
    lines = [l.strip() for l in text.splitlines() if l.strip() and "://" not in l and "/" not in l]
    for line in reversed(lines):
        message = re.sub(r"^\d\d:\d\d:\d\d - \S+ (?:Info|Warning|Warn|Error|Critical|Debug)(?: \(\d+\))?: ", "", line)
        if re.search(r"pair|PIN|fail|error|refused|timed out", message, re.I):
            return message[:200]
    return "Moonlight did not report a paired host"


def pair(host, pin):
    require(isinstance(host, str) and HOST.fullmatch(host), "invalid host")
    require(isinstance(pin, str) and re.fullmatch(r"\d{4}", pin), "invalid PIN")
    require(shutil.which("moonlight"), "moonlight-missing: install Moonlight Qt")
    require(not moonlight_gui_running(), "moonlight-running: close the Moonlight window before pairing")
    before = set(moonlight_hosts())
    try:
        p = _run(["moonlight", "pair", host, "--pin", pin], 120)
    except subprocess.TimeoutExpired:
        raise ValueError("pairing-timeout: enter the PIN on the host within two minutes, then try again") from None
    hosts = moonlight_hosts()
    matches = [(key, h) for key, h in hosts.items() if h["paired"] and key not in before]
    matches = matches or [(key, h) for key, h in hosts.items() if h["paired"] and (h["address"] or "").lower() == host.lower()]
    if p.returncode or not matches:
        raise ValueError("pairing-failed: " + summarize(p.stdout + "\n" + p.stderr))
    key, h = matches[0]
    return {"paired": True, "pairing_uuid": key, "name": h["name"] or host, "host": h["address"] or host}


def inspect(computer):
    """Read-only look at a host's displays for choosing managed recovery settings."""
    ssh = computer.get("ssh") or {}
    if computer.get("platform") == "macos":
        require(SSH_USER.fullmatch(ssh.get("user", "")), "ssh-user-required: enter the approved SSH user for this Mac")
        listing = Host(computer, {"display": {"adapter": "betterdisplay"}}).remote("list")
        return {"platform": "macos", **listing}
    if computer.get("platform") == "windows":
        require(windows_display.ALIAS.fullmatch(ssh.get("alias", "")), "ssh-alias-required: enter the approved SSH alias for this PC")
        return {"platform": "windows", **windows_display.inspect(ssh["alias"], computer["pairing_uuid"])}
    raise ValueError("display recovery is available for macOS and Windows hosts")


def install_helper(computer, device_id):
    ssh = computer.get("ssh") or {}
    require(computer.get("platform") == "windows", "the display helper is only for Windows hosts")
    require(windows_display.ALIAS.fullmatch(ssh.get("alias", "")), "ssh-alias-required: enter the approved SSH alias for this PC")
    observed = windows_display.inspect(ssh["alias"], computer["pairing_uuid"])
    require(not observed["helper"]["installed"], "helper-installed: the display helper is already installed")
    capture = next((d for d in observed["displays"] if d["id"].lower() == (device_id or "").lower()), None)
    require(capture is not None, "display-missing: choose a display reported by the host")
    require(capture.get("hardware"), "display-hardware-unknown: the chosen display has no EDID hardware ID")
    require(observed.get("sunshine_output"), "sunshine-output-required: set output_name in Sunshine's configuration first")
    return windows_display.install(ssh["alias"], computer["pairing_uuid"], observed["sunshine_output"], capture["hardware"])
