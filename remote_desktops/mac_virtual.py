"""A BetterDisplay virtual screen that is attached only while a session wants it.

The screen is attached and made the main display before Moonlight connects,
and detached when the session ends, so the Mac never keeps a phantom main
display after a disconnect. Sunshine captures the main display, so its
output_name must be unset; no app preparation command is needed.

The journal entry is written before the first host change. Its presence means
the screen may be attached on our behalf; restore detaches it and tries to
hand the main role back to the display recorded at the start of the session.
"""
from .mac_display import same_setting

KEY = "virtual"


def prepare(record, host, persist):
    journal = record.setdefault("journal", {})
    if KEY not in journal:
        observed = host.remote("probe")
        if observed["main"]["active"] and observed["main"]["uuid"] is None:
            observed = host.remote("probe")  # One more look before refusing a baseline.
        virtual, main = observed["virtual"], observed["main"]
        if observed["sunshine_output"]:
            raise ValueError("display-configuration-invalid: remove output_name from sunshine.conf so Sunshine captures the main display")
        if (virtual["connected"] and virtual["main"]) or not main["active"]:
            # Nothing to hand back: either a screen left attached and main (for
            # example by an older app preparation hook) is adopted, or no
            # display is active at all. macOS chooses after the detach.
            original = None
        elif main["uuid"] is None:
            raise ValueError("display-probe-failed: the current main display could not be identified")
        else:
            original = main["uuid"]
        journal[KEY] = {"original": {"connected": virtual["connected"], "main": original}, "phase": "intent"}
        persist()
    observed = host.remote("attach", mode=host.display["mode"])
    virtual = observed["virtual"]
    if not (virtual["connected"] and virtual["main"] and virtual["active"] and not virtual["asleep"]
            and same_setting("mode", virtual["mode"], host.display["mode"])):
        raise ValueError("display-readback-failed: the virtual screen is not ready")
    journal[KEY].update(applied={"connected": True, "main": virtual["uuid"]}, phase="applied")
    record.pop("unreadable_checks", None)  # A clean attach is a good read.
    record["resolved"] = {**record.get("resolved", {}), "identity": {"UUID": virtual["uuid"], "displayID": virtual["display_id"],
                                                                       "name": virtual.get("name")},
                          "current": {"mode": virtual["mode"]}, "lid_closed": observed["lid_closed"],
                          "ac_power": observed["ac_power"]}
    persist()


def restore(record, host, persist):
    journal = record.get("journal", {})
    entry = journal.get(KEY)
    if entry is not None:
        observed = host.remote("detach", original_main=entry["original"]["main"])
        if observed["virtual"]["connected"]:
            raise ValueError("virtual-display-detach-failed: the screen is still connected")
        del journal[KEY]
        record.pop("display_recovery", None)
        persist()
    return not journal


UNREADABLE_CHECKS = 3


def health(record, host):
    try:
        observed = host.remote("probe")
    except ValueError as error:
        if not str(error).startswith("display-operation-failed"):
            raise
        # Unknown is not lost: keep a working stream and look again at the
        # next check. A screen that stays unreadable (deleted, or BetterDisplay
        # hung) is not healthy; preparing again checks it and reports why.
        record["unreadable_checks"] = record.get("unreadable_checks", 0) + 1
        if record["unreadable_checks"] >= UNREADABLE_CHECKS:
            record.pop("unreadable_checks")
            return {"reconnect": True}
        return {"reconnect": False}
    record.pop("unreadable_checks", None)
    virtual = observed["virtual"]
    if host.display.get("require_ac", False) and observed["ac_power"] is False:
        raise ValueError("power-required: host lost AC power")  # Unknown power is not a loss.
    if not (virtual["connected"] and virtual["active"] and not virtual["asleep"]):
        # Capture has nothing to read; preparing again reattaches and wakes it.
        return {"reconnect": True}
    # The user may move the main role or change the mode during a session;
    # report it rather than undo it. A later reconnect applies both again.
    return {"reconnect": False,
            "degraded": not virtual["main"] or not same_setting("mode", virtual["mode"], host.display["mode"])}
