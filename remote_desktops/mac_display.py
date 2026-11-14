"""Typed Mac display operations, sent to the user's approved SSH account.

No persistent remote agent is installed. REQUEST is supplied by the client.
Only the display mode, Sunshine output_name, and (for mac-virtual) the
attachment and main role of one BetterDisplay virtual screen can be changed.
"""
import json
import ctypes
import fcntl
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

BETTER = "/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay"


def same_setting(field, a, b):
    if field != "mode":
        return a == b
    # EDID/CLI mode lists round nominal timings (60 can read back as 59.95).
    return (isinstance(a, dict) and isinstance(b, dict) and a.get("resolution") == b.get("resolution")
            and a.get("hidpi") == b.get("hidpi")
            and (a["refresh"] == b["refresh"] or
                 (type(a["refresh"]) in (int, float) and type(b["refresh"]) in (int, float)
                  and abs(a["refresh"] - b["refresh"]) < .15)))


def manages_mode(display, observed):
    return display.get("adapter") != "macos" and (not display.get("follow_main") or observed["identity"]["UUID"].lower() == display["uuid"].lower())


def run(argv, timeout=8):
    p = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if p.returncode or p.stdout.strip() == "Failed.":
        raise ValueError("display-operation-failed: check BetterDisplay, display connection and permissions")
    return p.stdout.strip()


def restart_sunshine():
    subprocess.run(["/usr/bin/pkill", "-TERM", "-x", "Sunshine"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if subprocess.run(["/usr/bin/pgrep", "-x", "Sunshine"], stdout=subprocess.DEVNULL).returncode:
            break
        time.sleep(.1)
    else:
        raise ValueError("Sunshine did not stop; display restore may be pending")
    run(["/usr/bin/open", "/Applications/Sunshine.app"])


def lid_closed(read=None):
    result = (read or run)(["/usr/sbin/ioreg", "-r", "-k", "AppleClamshellState", "-d", "4"])
    match = re.search(r'"AppleClamshellState"\s*=\s*(Yes|No)', result)
    return match[1] == "Yes" if match else None


def native_display():
    """Read the primary screen through CoreGraphics; never change its mode."""
    cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    def bind(lib, name, result, *args):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, list(args)
        return fn
    u32, ptr = ctypes.c_uint32, ctypes.c_void_p
    main = bind(cg, "CGMainDisplayID", u32)()
    if not bind(cg, "CGDisplayIsActive", u32, u32)(main):
        raise ValueError("display-missing: main display is inactive")
    # Native profiles own only the current capture output, not a persistent
    # physical display mode. Include the live ID and hardware identifiers so
    # a changed primary screen cannot reuse another screen's write guard.
    hardware = [bind(cg, name, u32, u32)(main) for name in
                ("CGDisplayVendorNumber", "CGDisplayModelNumber", "CGDisplaySerialNumber")]
    identity = str(uuid.uuid5(uuid.NAMESPACE_URL, "coregraphics:" + str([main, *hardware]))).upper()
    mode = bind(cg, "CGDisplayCopyDisplayMode", ptr, u32)(main)
    if not mode:
        raise ValueError("display-missing: main display has no mode")
    try:
        values = {key: bind(cg, "CGDisplayModeGet" + key, ctypes.c_size_t, ptr)(mode)
                  for key in ("Width", "Height", "PixelWidth", "PixelHeight")}
        refresh = bind(cg, "CGDisplayModeGetRefreshRate", ctypes.c_double, ptr)(mode)
    finally:
        bind(cg, "CGDisplayModeRelease", None, ptr)(mode)
    built_in = bool(bind(cg, "CGDisplayIsBuiltin", u32, u32)(main))
    return ({"UUID": identity, "displayID": str(main), "name": "Built-in Display" if built_in else "External Display"},
            {"resolution": f'{values["Width"]}x{values["Height"]}',
             "hidpi": values["PixelWidth"] > values["Width"],
             "refresh": refresh if refresh else "variable"},
            f'{values["PixelWidth"]}x{values["PixelHeight"]}')


def list_displays():
    """Read-only inventory for setup: every active display, its mode list, and power state."""
    cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    u32, ptr = ctypes.c_uint32, ctypes.c_void_p
    def bind(name, result, *args):
        fn = getattr(cg, name)
        fn.restype, fn.argtypes = result, list(args)
        return fn
    count, ids = u32(), (u32 * 16)()
    bind("CGGetActiveDisplayList", ctypes.c_int32, u32, ctypes.POINTER(u32), ctypes.POINTER(u32))(16, ids, ctypes.byref(count))
    main = bind("CGMainDisplayID", u32)()
    better = os.path.exists(BETTER)
    displays = []
    for i in range(count.value):
        did = ids[i]
        built_in = bool(bind("CGDisplayIsBuiltin", u32, u32)(did))
        entry = {"display_id": str(did), "main": did == main, "builtin": built_in, "uuid": None,
                 "name": "Built-in Display" if built_in else "External Display", "modes": [], "current": None}
        mode = bind("CGDisplayCopyDisplayMode", ptr, u32)(did)
        if mode:
            try:
                width = bind("CGDisplayModeGetWidth", ctypes.c_size_t, ptr)(mode)
                height = bind("CGDisplayModeGetHeight", ctypes.c_size_t, ptr)(mode)
                pixels = bind("CGDisplayModeGetPixelWidth", ctypes.c_size_t, ptr)(mode)
                refresh = bind("CGDisplayModeGetRefreshRate", ctypes.c_double, ptr)(mode)
                entry["current"] = {"resolution": f"{width}x{height}", "hidpi": pixels > width, "refresh": refresh or "variable"}
            finally:
                bind("CGDisplayModeRelease", None, ptr)(mode)
        if better:
            try:
                idents = json.loads(run([BETTER, "get", "-type=Display", "-displayID=" + str(did), "-identifiers"]))
                if isinstance(idents, dict) and re.fullmatch(r"[A-Fa-f0-9-]{36}", idents.get("UUID", "")):
                    entry["uuid"] = idents["UUID"]
                    entry["name"] = idents.get("name") or entry["name"]
                    for line in run([BETTER, "get", "-type=Display", "-UUID=" + idents["UUID"], "-displayModeList"]).splitlines():
                        m = re.fullmatch(r"\d+ - (\d+x\d+)( HiDPI)? (\d+(?:\.\d+)?)Hz.*", line.strip())
                        if m:
                            entry["modes"].append({"resolution": m[1], "hidpi": bool(m[2]), "refresh": float(m[3])})
            except ValueError:
                pass
        displays.append(entry)
    power = run(["/usr/bin/pmset", "-g", "batt"])
    return {"betterdisplay": better, "displays": displays, "ac_power": "AC Power" in power, "lid_closed": lid_closed()}


def poll(read, ready, deadline, error):
    """Repeat a read until it satisfies `ready` or the monotonic deadline passes.
    BetterDisplay can reject a write issued just after a connect, then apply it."""
    cause = None
    while time.monotonic() < deadline:
        try:
            value = read()
            if ready(value):
                return value
            cause = None  # A fresh answer replaces an earlier failure.
        except ValueError as failure:
            # Running out of time is a symptom; keep the failure that used it.
            if cause is None or "out of time" not in str(failure):
                cause = failure
        time.sleep(.2)
    raise ValueError(error + (" (" + str(cause) + ")" if cause else ""))


OPERATION_SECONDS = 30  # Every operation, including each command, stays inside the client's 40-second SSH bound.
PROBE_SECONDS = 3  # Every probe retries briefly; a full read measured about 0.5 s on a real Mac.
PRECHECK_SECONDS = 2  # Detach's look before writing.
FINAL_WRITE_SECONDS = 3  # Detach always gets this long to write, even past the budget. After a lock wait
# near 40 s the client may time out first; the write still lands and restore is retried.
HANDBACK_SECONDS = 5
DETACH_RESERVE_SECONDS = 10  # Handing main back is optional; detaching is not.


def sunshine_output():
    config = Path.home() / ".config/sunshine/sunshine.conf"
    outputs = re.findall(r"^\s*output_name\s*=\s*(.*?)\s*$", config.read_text(), re.M) if config.exists() else []
    return outputs[-1] if outputs else None


def virtual_screen(request, started=None):
    """Session-scoped BetterDisplay virtual screen: probe, attach, detach.

    The screen selected by tag_id belongs to streaming. Attach makes it the
    main display and wakes it before Moonlight connects, because Sunshine
    checks for an active display before it runs any app preparation. Detach
    tries to return the main role to the recorded display, then writes the
    disconnect (unless the screen already reads detached) and finishes only
    once it reads as detached.
    Sunshine must capture the main display (no output_name).
    """
    deadline = (started if started is not None else time.monotonic()) + OPERATION_SECONDS
    # The current phase's limit: a phase shortens it; only detach's final write extends it.
    limit = [deadline]
    tag = request.get("tag_id")
    if not isinstance(tag, str) or not re.fullmatch(r"\d{1,6}", tag):
        raise ValueError("invalid virtual screen tag_id")
    screen = ["-type=VirtualScreen", "-tagID=" + tag]
    cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    cg.CGMainDisplayID.restype = ctypes.c_uint32
    for name in ("CGDisplayIsActive", "CGDisplayIsAsleep"):
        getattr(cg, name).restype, getattr(cg, name).argtypes = ctypes.c_uint32, [ctypes.c_uint32]

    def command(argv):
        # Bound every command by the operation's remaining time; a hung
        # BetterDisplay is a failed read, never an escaped exception.
        remaining = min(8, limit[0] - time.monotonic())
        if remaining <= 0:
            raise ValueError("display-operation-failed: out of time")
        try:
            return run(argv, timeout=remaining)
        except subprocess.TimeoutExpired:
            raise ValueError("display-operation-failed: " + Path(argv[0]).name + " did not answer") from None

    def get(*args):
        return command([BETTER, "get", *args])

    def set_(*args):
        command([BETTER, "set", *args])

    def flag(value):
        # The screen answers once per device it exposes ("on,on"). A mixed or
        # unknown answer is not evidence either way.
        tokens = {t.strip().lower() for t in value.split(",") if t.strip()}
        if tokens and tokens <= {"on", "true", "1"}:
            return True
        if tokens and tokens <= {"off", "false", "0"}:
            return False
        raise ValueError("display-state-unknown: BetterDisplay gave an unclear answer")

    def identifiers(*selector):
        text = get(*selector, "-identifiers")
        try:
            value = json.loads(text)
        except ValueError:
            # Several matches arrive as comma-separated objects, for example
            # a screen followed by BetterDisplay's default display group.
            value = json.loads("[" + text + "]")
        if isinstance(value, list):
            unique = {(v.get("UUID"), str(v["displayID"])): v for v in value if isinstance(v, dict) and v.get("displayID")}
            value = next(iter(unique.values())) if len(unique) == 1 else None
        if not isinstance(value, dict) or not isinstance(value.get("UUID"), str) \
                or not re.fullmatch(r"[A-Fa-f0-9-]{36}", value["UUID"]) or not re.fullmatch(r"\d+", str(value.get("displayID", ""))):
            raise ValueError("display-missing: display has no unique identifier")
        return value

    def phase(seconds, step):
        # Run `step` under a shorter limit, then restore the operation's.
        limit[0] = min(deadline, time.monotonic() + seconds)
        try:
            return step()
        finally:
            limit[0] = deadline

    def mode():
        refresh = get(*screen, "-refreshRate").split(",")[0].strip()
        return {"resolution": get(*screen, "-resolution").split(",")[0].strip(), "hidpi": flag(get(*screen, "-hiDPI")),
                "refresh": refresh if refresh == "ProMotion" else float(refresh.removesuffix("Hz"))}

    def connected():
        return flag(get(*screen, "-connected"))

    def state():
        main_id = cg.CGMainDisplayID()
        # The screen is read first and must succeed; it alone decides health.
        virtual = {"connected": connected()}
        if virtual["connected"]:
            ids = identifiers(*screen)
            did = int(ids["displayID"])
            virtual.update(uuid=ids["UUID"].upper(), display_id=str(did), name=ids.get("name"),
                           active=bool(cg.CGDisplayIsActive(did)), asleep=bool(cg.CGDisplayIsAsleep(did)),
                           main=did == main_id, mode=mode())
        main = {"uuid": None, "display_id": str(main_id), "name": None, "active": bool(cg.CGDisplayIsActive(main_id))}
        if main["active"]:
            try:
                ids = identifiers("-displayID=" + str(main_id))
                main.update(uuid=ids["UUID"].upper(), name=ids.get("name"))
            except ValueError:
                pass  # Unknown, not absent: prepare refuses to record it as a baseline.
        # Context reads are best effort: only the screen itself decides health.
        try:
            lid = lid_closed(command)
        except ValueError:
            lid = None
        try:
            power = "AC Power" in command(["/usr/bin/pmset", "-g", "batt"])
        except ValueError:
            power = None
        return {"virtual": virtual, "main": main, "sunshine_output": sunshine_output(),
                "lid_closed": lid, "ac_power": power}

    operation = request["operation"]
    if operation == "probe":
        return phase(PROBE_SECONDS, lambda: poll(state, bool, limit[0],
                                                 "display-operation-failed: the virtual screen state could not be read"))
    if operation == "attach":
        wanted = request["mode"]
        if not re.fullmatch(r"[0-9]{3,5}x[0-9]{3,5}", wanted.get("resolution", "")) or type(wanted.get("hidpi")) is not bool \
                or type(wanted.get("refresh")) not in (int, float) or not 20 <= wanted["refresh"] <= 240:
            raise ValueError("invalid display mode")
        if sunshine_output():
            raise ValueError("display-configuration-invalid: remove output_name from sunshine.conf so Sunshine captures the main display")
        def attach():
            if not connected():
                set_(*screen, "-connected=on")
            return connected()
        poll(attach, bool, deadline, "virtual-display-attach-failed: BetterDisplay did not connect the screen")
        def apply_mode():
            if not same_setting("mode", mode(), wanted):
                set_(*screen, "-resolution=" + wanted["resolution"], "-hiDPI=" + ("on" if wanted["hidpi"] else "off"),
                     "-refreshRate=" + str(wanted["refresh"]) + "Hz")
            return mode()
        poll(apply_mode, lambda m: same_setting("mode", m, wanted), deadline,
             "display-mode-unavailable: the virtual screen did not accept the mode")
        def apply_main():
            if not flag(get(*screen, "-main")):
                set_(*screen, "-main=on")
            return flag(get(*screen, "-main"))
        poll(apply_main, bool, deadline, "virtual-display-main-failed: the virtual screen did not become the main display")
        # Declare user activity: a slept display reports inactive, and Sunshine
        # refuses to start a stream when no display is active.
        try:
            command(["/usr/bin/caffeinate", "-u", "-t", "1"])
        except ValueError:
            pass  # Readiness below is the check that matters.
        def ready():
            observed = state()
            v = observed["virtual"]
            return observed if v["connected"] and v["main"] and v["active"] and not v["asleep"] else None
        return poll(ready, bool, deadline, "virtual-display-inactive: the virtual screen is attached but not awake")
    if operation == "detach":
        # Cleanup reads only what it needs: whether the screen is attached
        # and, best effort, whether it is main. Unrelated reads cannot block it.
        original = request.get("original_main")
        if original is not None and not re.fullmatch(r"[A-Fa-f0-9-]{36}", original):
            raise ValueError("invalid display UUID")
        try:
            if phase(PRECHECK_SECONDS, connected) is False:
                return {"virtual": {"connected": False}, "main_restored": None}
        except ValueError:
            pass  # Unclear: treat as attached; detaching again is harmless.
        restored = None
        handback = min(HANDBACK_SECONDS, deadline - DETACH_RESERVE_SECONDS - time.monotonic())
        if original and handback <= 0:
            restored = False  # No time to spare: detach, and let macOS choose.
        elif original:
            # Hand the main role back first so macOS does not pick. A display
            # that has gone, is asleep, refuses the role (a closed lid), or does
            # not answer must not keep the screen attached; macOS then chooses.
            def restore_main():
                if not flag(get("-type=Display", "-UUID=" + original, "-main")):
                    set_("-type=Display", "-UUID=" + original, "-main=on")
                return flag(get("-type=Display", "-UUID=" + original, "-main"))
            def hand_back():
                if flag(get(*screen, "-main")):
                    if not flag(get("-type=Display", "-UUID=" + original, "-connected")):
                        raise ValueError("display-missing")
                    poll(restore_main, bool, limit[0], "restore-main-failed")
                    return True
                return None
            try:
                restored = phase(handback, hand_back)
            except ValueError:
                restored = False
        rejected = []
        def detach():
            # Write first: it is harmless when already detached, and reading
            # first could spend the remaining time without ever writing.
            try:
                set_(*screen, "-connected=off")
                rejected.clear()
            except ValueError as failure:
                rejected[:] = [failure]  # It can report failure for a write that lands.
            if connected() is False:
                return True
            if rejected:
                raise rejected[0]
            return False
        # A long lock wait must not cost the write itself: allow one short
        # attempt past the budget.
        final = max(deadline, time.monotonic() + FINAL_WRITE_SECONDS)
        limit[0] = final
        poll(detach, bool, final, "virtual-display-detach-failed: the screen is still connected")
        return {"virtual": {"connected": False}, "main_restored": restored}
    raise ValueError("unsupported virtual screen operation")


STALE_ATTACH_SECONDS = 5


def display(request, started=None):
    state = json.loads((Path.home() / ".config/sunshine/sunshine_state.json").read_text())
    identity = state.get("root", {}).get("uniqueid", "")
    if identity.lower() != request["pairing_uuid"].lower():
        raise ValueError("host-identity-mismatch: SSH host is not the paired Sunshine computer")
    if request["operation"] == "list":
        return list_displays()
    if request.get("adapter") == "mac-virtual":
        if request["operation"] == "attach" and started is not None and time.monotonic() - started > STALE_ATTACH_SECONDS:
            # An attach that queued behind another operation may belong to a
            # client that already gave up and restored; never attach late.
            raise ValueError("attach-stale: the display was busy; connect again")
        return virtual_screen(request, started)
    native = request.get("adapter") == "macos"
    if native:
        ids, native_mode, render_resolution = native_display()
        identity = ids["UUID"]
        if request.get("expected_identity") and identity.lower() != request["expected_identity"].lower():
            raise ValueError("display-topology-changed: main display changed before the operation")
    else:
        graphics = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        graphics.CGMainDisplayID.restype = ctypes.c_uint32
        identity = request["display_uuid"]
        if request.get("follow_main"):
            ids = json.loads(run([BETTER, "get", "-type=Display", "-displayID=" + str(graphics.CGMainDisplayID()), "-identifiers"]))
            identity = ids["UUID"]
        if request.get("expected_identity") and identity.lower() != request["expected_identity"].lower():
            raise ValueError("display-topology-changed: main display changed before the operation")
        if not re.fullmatch(r"[A-Fa-f0-9-]{36}", identity):
            raise ValueError("invalid display UUID")
        def get(key):
            # UUID alone also matches BetterDisplay's default display group.
            # Restrict all reads and writes to a physical Display before resolving.
            return run([BETTER, "get", "-type=Display", "-UUID=" + identity, "-" + key])
        try:
            ids = json.loads(get("identifiers"))
        except (ValueError, KeyError):
            raise ValueError("display-missing: selected display is unavailable") from None
        if not isinstance(ids, dict) or ids.get("UUID", "").lower() != identity.lower():
            raise ValueError("display-missing: no unique UUID match")
        graphics.CGDisplayIsActive.argtypes = [ctypes.c_uint32]
        graphics.CGDisplayIsActive.restype = ctypes.c_uint32
        if not graphics.CGDisplayIsActive(int(ids["displayID"])):
            raise ValueError("display-missing: selected display is disconnected")
    config = Path.home() / ".config/sunshine/sunshine.conf"
    text = config.read_text()
    outputs = re.findall(r"^\s*output_name\s*=\s*(.*?)\s*$", text, re.M)
    if len(outputs) > 1:
        raise ValueError("display-configuration-invalid: duplicate output_name")
    def get_mode():
        if native:
            return native_mode
        refresh = get("refreshRate")
        return {"resolution": get("resolution"), "hidpi": get("hiDPI") == "on",
                "refresh": refresh if refresh == "ProMotion" else float(refresh.removesuffix("Hz"))}
    mode = get_mode()
    current = {"mode": mode, "output": outputs[0] if outputs else None}
    if request["operation"] == "probe":
        modes = []
        for line in ([] if native else get("displayModeList").splitlines()):
            m = re.fullmatch(r"\d+ - (\d+x\d+)( HiDPI)? (\d+(?:\.\d+)?)Hz.*", line.strip())
            if m:
                modes.append({"resolution": m[1], "hidpi": bool(m[2]), "refresh": float(m[3])})
        power = run(["/usr/bin/pmset", "-g", "batt"])
        return {"identity": ids, "current": current, "modes": modes,
                "topology": {"lid_closed": lid_closed(), "display_id": ids["displayID"], "display_uuid": identity},
                "sunshine_uuid": request["pairing_uuid"],
                "ac_power": "AC Power" in power, "permissions": "unknown",
                "render_resolution": render_resolution if native else "x".join(str(int(v) * (2 if mode["hidpi"] else 1)) for v in mode["resolution"].split("x"))}
    if request["operation"] == "refresh":
        if not all(same_setting(k, current[k], request["expected"][k]) for k in current):
            raise ValueError("restore-conflict: capture changed before refreshing input")
        restart_sunshine()
        return {"refreshed": ids["displayID"]}
    field, expected, value = request["field"], request["expected"], request["value"]
    # Compare and change in one remote invocation; preserve a manual change.
    if field not in current or not same_setting(field, current[field], expected):
        raise ValueError("restore-conflict: current setting differs from the journal")
    if field == "mode":
        if native:
            raise ValueError("unsupported display field: native desktop preserves the host mode")
        if not re.fullmatch(r"[0-9]{3,5}x[0-9]{3,5}", value["resolution"]):
            raise ValueError("invalid resolution")
        if type(value["hidpi"]) is not bool or not (value["refresh"] == "ProMotion" or
                (type(value["refresh"]) in (int, float) and 20 <= value["refresh"] <= 240)):
            raise ValueError("invalid display mode")
        run([BETTER, "set", "-type=Display", "-UUID=" + identity, "-resolution=" + value["resolution"],
             "-hiDPI=" + ("on" if value["hidpi"] else "off"), "-refreshRate=" + str(value["refresh"])])
        if not same_setting("mode", get_mode(), value):
            raise ValueError("display-readback-failed: restoration required")
        # Sunshine's macOS input context caches displayScaling at startup.
        # A mode switch must refresh it even when output_name stays the same.
        restart_sunshine()
    elif field == "output":
        if value is not None and not re.fullmatch(r"\d{1,10}", value):
            raise ValueError("invalid capture output")
        updated = re.sub(r"^\s*output_name\s*=.*\n?", "", text, flags=re.M)
        if value is not None:
            updated = updated.rstrip() + "\noutput_name = " + value + "\n"
        fd, path = tempfile.mkstemp(dir=config.parent)
        try:
            with os.fdopen(fd, "w") as out:
                out.write(updated)
                out.flush()
                os.fsync(out.fileno())
            os.replace(path, config)
        finally:
            if os.path.exists(path):
                os.unlink(path)
        restart_sunshine()
    else:
        raise ValueError("unsupported display field")
    return {"changed": field}


if __name__ == "__main__":
    try:
        # A client timeout can leave a remote operation finishing its write.
        # Serialize probes too: restoration cannot observe the old value and
        # discard its journal while an earlier write is still in flight.
        with (Path.home() / ".config/sunshine/hypertile-display.lock").open("a") as lock:
            os.fchmod(lock.fileno(), 0o600)
            started = time.monotonic()
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = display(REQUEST, started)
        print(json.dumps({"ok": True, "result": result}))
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}))
