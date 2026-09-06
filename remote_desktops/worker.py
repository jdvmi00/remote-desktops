"""One bounded host operation. Rust owns session intent and client processes.

Only this helper writes recovery.json, under its own lock. A daemon crash must
not let a second helper rebaseline an in-flight host mutation.
"""
import fcntl
import json
import os
from pathlib import Path
import sys
from .host import Host, configuration, configuration_value, moonlight_hosts, UUID, prepare, restore, require, stream_argv
from .mac_display import same_setting, manages_mode
from .storage import atomic_json, read_json


def health(record, host):
    if host.display["adapter"] == "external":
        return {"reconnect": False}
    observed = host.remote("status" if host.display["adapter"] == "windows" else "probe")
    if host.display["adapter"] == "windows":
        require(not observed.get("error"), observed.get("error"))
        require(observed.get("phase") in ("preparing", "streaming"), "display-restored: reconnect required")
        return {"reconnect": False}
    require(not host.display.get("require_ac") or observed["ac_power"], "power-required: host lost AC power")
    before, after = record.get("mac_topology") or {}, observed.get("topology") or {}
    following = host.display.get("follow_main", host.display["adapter"] == "macos")
    lid_changed = (type(before.get("lid_closed")) is bool and type(after.get("lid_closed")) is bool
                   and before["lid_closed"] != after["lid_closed"])
    capture_changed = following and before and any(before.get(k) != after.get(k) for k in ("display_id", "display_uuid"))
    mode_changed = following and not manages_mode(host.display, observed) and not same_setting(
        "mode", observed["current"]["mode"], record["resolved"]["current"]["mode"])
    if lid_changed or capture_changed or mode_changed:
        require(observed["current"]["output"] == record["resolved"]["current"]["output"], "capture-display-changed")
        record["display_recovery"] = {"current": observed["current"], "topology": after}
        return {"reconnect": True}
    require(observed["current"]["output"] == observed["identity"]["displayID"], "capture-display-changed")
    record["mac_topology"] = after
    record["resolved"].update({k: v for k, v in observed.items() if k != "modes"})
    return {"reconnect": False, "degraded": manages_mode(host.display, observed)
            and not same_setting("mode", observed["current"]["mode"], host.display["mode"])}


def operation(request):
    if request["operation"] == "validate":
        return configuration(Path(request["config"]))
    if request["operation"] == "validate-value":
        return configuration_value(request["value"])
    if request["operation"] == "paired":
        return [{"pairing_uuid": key, "name": h["name"], "host": h["address"] or ""}
                for key, h in moonlight_hosts().items() if UUID.fullmatch(key) and h["paired"] and h["name"]]
    if request["operation"] == "setup-probe":
        Host(request["computer"], {"display": {"adapter": "external"}}).probe()
        return {"authenticated": True}
    path = Path(request["path"])
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = read_json(path)
        host = Host(record["config"], record["settings"])
        persist = lambda: atomic_json(path, record)
        action = request["operation"]
        if action == "probe":
            record["resolved"] = {k: v for k, v in host.probe().items() if k != "modes"}
            result = {"argv": stream_argv(record["config"], record["settings"]), "resolved": record["resolved"]}
        elif action == "prepare":
            prepare(record, host, persist)
            result = {"resolved": record.get("resolved", {})}
        elif action == "restore":
            result = {"complete": restore(record, host, persist)}
        elif action == "health":
            result = health(record, host)
        elif action == "release":
            require(request.get("keep_host_settings") is True, "explicit acknowledgement required")
            record["journal"] = {}
            record.pop("display_recovery", None)
            result = {"complete": True}
        else:
            raise ValueError("unknown host operation")
        persist()
        return result


def main():
    os.umask(0o077)
    try:
        data = sys.stdin.buffer.read(2_000_001)
        require(len(data) <= 2_000_000, "host request too large")
        result = {"ok": True, "result": operation(json.loads(data))}
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        result = {"ok": False, "error": str(error)}
    except Exception as error:
        # Avoid persisting command arguments or authentication details from
        # subprocess exceptions. Unknown outcomes retain the recovery journal.
        result = {"ok": False, "error": "host operation failed: " + type(error).__name__}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
