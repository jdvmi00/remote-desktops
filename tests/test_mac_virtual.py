"""Session-scoped macOS virtual screen: journal ordering and remote behavior.

Everything here uses fakes for BetterDisplay, CoreGraphics, and SSH; it does not
prove capture on a real Mac.
"""
import copy
import itertools
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from remote_desktops import host as s, mac_display, mac_virtual

IDENTITY = "12345678-1234-1234-1234-123456789ABC"
BUILTIN = "AAAAAAAA-1234-1234-1234-123456789ABC"
VIRTUAL = "BBBBBBBB-1234-1234-1234-123456789ABC"
MODE = {"resolution": "3072x1280", "hidpi": True, "refresh": 60}
DISPLAY = {"adapter": "mac-virtual", "tag_id": "7", "mode": MODE}


def computer(display=None):
    return {"host": "mac.example", "pairing_uuid": IDENTITY, "title": "Mac - Moonlight", "platform": "macos",
            "ssh": {"user": "tester"},
            "profiles": {"desktop": {"stream_resolution": "6144x2560", "display": copy.deepcopy(display or DISPLAY)}}}


class Mac:
    """BetterDisplay and CoreGraphics as the remote helper sees them."""

    def __init__(self):
        self.connected = False
        self.main = BUILTIN
        self.mode = {"resolution": "1920x1080", "hidpi": False, "refresh": 60.0}
        self.asleep = False
        self.builtin_present = True
        self.reject_after_connect = 2  # BetterDisplay answers "Failed." just after connecting.
        self.reject_connect = 0  # Writes to -connected that land but report "Failed.".
        self.builtin_refuses_main = False
        self.connected_answer = None
        self.calls = []

    def ids(self):
        return {BUILTIN: "1", VIRTUAL: "12"}

    def run(self, argv):
        assert argv[0] == mac_display.BETTER or argv[0] == "/usr/bin/pmset" or argv[0] == "/usr/sbin/ioreg", argv
        if argv[0] == "/usr/bin/pmset":
            return "Now drawing from 'AC Power'"
        if argv[0] == "/usr/sbin/ioreg":
            return '"AppleClamshellState" = Yes'
        verb, args = argv[1], argv[2:]
        options = dict(a[1:].split("=", 1) if "=" in a else (a[1:], None) for a in args)
        self.calls.append((verb, tuple(args)))
        virtual = options.get("type") == "VirtualScreen" and options.get("tagID") == "7"
        if verb == "set":
            if virtual and options.get("connected") in ("on", "off"):
                self.connected = options["connected"] == "on"
                if not self.connected and self.main == VIRTUAL:
                    self.main = BUILTIN if self.builtin_present else None
                if self.reject_connect:
                    self.reject_connect -= 1
                    return "Failed."
                return ""
            if options.get("UUID") == BUILTIN and self.builtin_refuses_main:
                return "Failed."
            if virtual and not self.connected:
                return "Failed."
            if self.reject_after_connect:
                self.reject_after_connect -= 1
                # The write still lands, as on the real host.
                self.apply(options, virtual)
                return "Failed."
            self.apply(options, virtual)
            return ""
        key = next(k for k, v in options.items() if v is None)
        if virtual:
            if key == "connected":
                return self.connected_answer or ("on,on" if self.connected else "off,off")
            if not self.connected:
                return "Failed."
            if key == "identifiers":
                return json.dumps({"UUID": VIRTUAL, "displayID": "12", "name": "Stream Screen"})
            if key == "main":
                return "true" if self.main == VIRTUAL else "false"
            return {"resolution": self.mode["resolution"], "hiDPI": "on" if self.mode["hidpi"] else "off",
                    "refreshRate": "%gHz" % self.mode["refresh"]}[key]
        if "displayID" in options and key == "identifiers":
            uuid = {v: k for k, v in self.ids().items()}.get(options["displayID"])
            if uuid is None:
                return "Failed."
            # The real CLI appends the default display group as a second object.
            return json.dumps({"UUID": uuid, "displayID": options["displayID"]}) + ',{"deviceType": "DisplayGroup", "tagID": "-1001"}'
        if options.get("UUID") == BUILTIN:
            if not self.builtin_present:
                return "Failed."
            return {"connected": "on", "main": "true" if self.main == BUILTIN else "false"}[key]
        return "Failed."

    def apply(self, options, virtual):
        if virtual and "resolution" in options:
            self.mode = {"resolution": options["resolution"], "hidpi": options["hiDPI"] == "on",
                         "refresh": float(options["refreshRate"].removesuffix("Hz"))}
        if options.get("main") == "on":
            self.main = VIRTUAL if virtual else options["UUID"]

    def graphics(self):
        mac = self
        def main_id():
            return int(mac.ids().get(mac.main, "0"))
        def active(did):
            return 1 if did == 1 or (did == 12 and mac.connected and not mac.asleep) else 0
        def asleep(did):
            return 1 if did == 12 and mac.asleep else 0
        class CG:
            pass
        cg = CG()
        cg.CGMainDisplayID, cg.CGDisplayIsActive, cg.CGDisplayIsAsleep = main_id, active, asleep
        return cg


class RemoteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / ".config/sunshine").mkdir(parents=True)
        (root / ".config/sunshine/sunshine_state.json").write_text(json.dumps({"root": {"uniqueid": IDENTITY}}))
        self.conf = root / ".config/sunshine/sunshine.conf"
        self.conf.write_text("sunshine_name = Mac\n")
        self.mac = Mac()
        self.woken = []
        self.stay_asleep = False
        self.hang = lambda argv: False
        self.timeouts = []
        self.clock = None
        for target in (patch.object(Path, "home", return_value=root),
                       patch.object(mac_display, "run", side_effect=self.betterdisplay),
                       patch.object(mac_display.ctypes, "CDLL", side_effect=lambda path: self.mac.graphics()),
                       patch.object(mac_display.time, "sleep")):
            target.start()
            self.addCleanup(target.stop)

    def betterdisplay(self, argv, timeout=8):
        self.timeouts.append(timeout)
        if self.hang(argv):
            if self.clock:
                self.clock.now += timeout  # A hung command uses all the time it is given.
            raise subprocess.TimeoutExpired(argv, timeout)
        if argv[0] == "/usr/bin/caffeinate":
            self.woken.append(argv)
            self.mac.asleep = self.stay_asleep
            return ""
        # The real helper raises on BetterDisplay's "Failed." answer.
        result = self.mac.run(argv)
        if result == "Failed.":
            raise ValueError("display-operation-failed")
        return result

    def call(self, operation, **values):
        return mac_display.display({"operation": operation, "adapter": "mac-virtual", "tag_id": "7",
                                    "pairing_uuid": IDENTITY, **values})

    def test_host_identity_is_checked_before_betterdisplay(self):
        with self.assertRaisesRegex(ValueError, "host-identity-mismatch"):
            mac_display.display({"operation": "attach", "adapter": "mac-virtual", "tag_id": "7",
                                 "pairing_uuid": BUILTIN, "mode": MODE})
        self.assertEqual(self.mac.calls, [])

    def test_attach_retries_rejected_writes_until_readback_and_wakes_the_screen(self):
        self.mac.asleep = True
        observed = self.call("attach", mode=MODE)
        virtual = observed["virtual"]
        self.assertTrue(virtual["connected"] and virtual["main"] and virtual["active"])
        self.assertFalse(virtual["asleep"])
        self.assertTrue(mac_display.same_setting("mode", virtual["mode"], MODE))
        self.assertEqual(observed["main"]["uuid"], VIRTUAL)
        self.assertEqual(self.woken, [["/usr/bin/caffeinate", "-u", "-t", "1"]])

    def test_attach_fails_closed_when_the_screen_stays_asleep(self):
        self.stay_asleep = True
        clock = itertools.count(0, .5)
        with patch.object(mac_display.time, "monotonic", side_effect=lambda: next(clock)):
            self.mac.asleep = True
            with self.assertRaisesRegex(ValueError, "virtual-display-inactive"):
                self.call("attach", mode=MODE)

    def test_attach_retries_a_connect_that_reports_failure_but_lands(self):
        self.mac.reject_connect = 1
        self.assertTrue(self.call("attach", mode=MODE)["virtual"]["main"])

    def test_attach_refuses_a_pinned_sunshine_output(self):
        self.conf.write_text("output_name = 1\n")
        with self.assertRaisesRegex(ValueError, "output_name"):
            self.call("attach", mode=MODE)
        self.assertFalse([call for call in self.mac.calls if call[0] == "set"])
        self.assertEqual(self.call("probe")["sunshine_output"], "1")

    def test_attach_gives_up_within_one_deadline(self):
        self.mac.apply = lambda options, virtual: None  # The mode never takes.
        clock = itertools.count(0, 1)
        with patch.object(mac_display.time, "monotonic", side_effect=lambda: next(clock)):
            with self.assertRaisesRegex(ValueError, "display-mode-unavailable"):
                self.call("attach", mode=MODE)
            self.assertLessEqual(next(clock), mac_display.OPERATION_SECONDS + 2)

    def test_every_command_is_bounded_by_the_remaining_time(self):
        clock = itertools.count(0, 2)  # Every reading of the clock costs two seconds.
        with patch.object(mac_display.time, "monotonic", side_effect=lambda: next(clock)):
            with self.assertRaises(ValueError):
                mac_display.display(
                    {"operation": "attach", "adapter": "mac-virtual", "tag_id": "7", "pairing_uuid": IDENTITY,
                     "mode": {**MODE, "resolution": "1280x720"}}, 0)
        self.assertTrue(self.timeouts)
        self.assertTrue(all(0 < t <= 8 for t in self.timeouts))

    def use_clock(self):
        class Clock:
            now = 0.0
            def monotonic(self):
                return self.now
            def sleep(self, seconds):
                self.now += seconds
        self.clock = Clock()
        for target in (patch.object(mac_display.time, "monotonic", side_effect=self.clock.monotonic),
                       patch.object(mac_display.time, "sleep", side_effect=self.clock.sleep)):
            target.start()
            self.addCleanup(target.stop)
        return self.clock

    def test_a_slow_handback_leaves_time_to_detach(self):
        self.call("attach", mode=MODE)
        clock = self.use_clock()
        self.hang = lambda argv: "-UUID=" + BUILTIN in argv
        clock.now = 18  # Most of the budget went on waiting for the lock: 2 s remain for handback.
        observed = mac_display.display({"operation": "detach", "adapter": "mac-virtual", "tag_id": "7",
                                        "pairing_uuid": IDENTITY, "original_main": BUILTIN}, 0)
        self.assertFalse(self.mac.connected)
        self.assertIs(observed["main_restored"], False)
        self.assertLessEqual(clock.now, mac_display.OPERATION_SECONDS)

    def detach_with_reserve(self, reserve):
        """Handback hangs and the first disconnect writes hang until t=26."""
        self.call("attach", mode=MODE)
        clock = self.use_clock()
        self.hang = lambda argv: "-UUID=" + BUILTIN in argv or "-connected=off" in argv and clock.now < 26
        clock.now = 18
        with patch.object(mac_display, "DETACH_RESERVE_SECONDS", reserve), \
             patch.object(mac_display, "FINAL_WRITE_SECONDS", 0):
            return mac_display.display({"operation": "detach", "adapter": "mac-virtual", "tag_id": "7",
                                        "pairing_uuid": IDENTITY, "original_main": BUILTIN}, 0)

    def test_the_reserve_leaves_time_to_detach(self):
        self.detach_with_reserve(mac_display.DETACH_RESERVE_SECONDS)
        self.assertFalse(self.mac.connected)

    def test_without_the_reserve_the_same_detach_runs_out_of_time(self):
        with self.assertRaisesRegex(ValueError, "virtual-display-detach-failed"):
            self.detach_with_reserve(0)
        self.assertTrue(self.mac.connected)

    def test_a_detach_that_waited_out_the_budget_still_writes_once(self):
        self.call("attach", mode=MODE)
        clock = self.use_clock()
        clock.now = 31  # The lock wait used the whole budget.
        mac_display.display({"operation": "detach", "adapter": "mac-virtual", "tag_id": "7",
                             "pairing_uuid": IDENTITY, "original_main": BUILTIN}, 0)
        self.assertFalse(self.mac.connected)

    def test_unrelated_context_reads_do_not_fail_the_probe(self):
        self.call("attach", mode=MODE)
        self.hang = lambda argv: argv[0] in ("/usr/sbin/ioreg", "/usr/bin/pmset") or argv[-2:] == ["-displayID=12", "-identifiers"]
        clock = self.use_clock()
        observed = self.call("probe")
        self.assertTrue(observed["virtual"]["main"])
        self.assertIsNone(observed["lid_closed"])
        self.assertIsNone(observed["ac_power"])
        self.assertIsNone(observed["main"]["uuid"])

    def test_detach_writes_even_when_every_read_hangs(self):
        self.call("attach", mode=MODE)
        clock = self.use_clock()
        self.hang = lambda argv: "-connected" in argv  # Reads of the connection state never answer.
        clock.now = 14
        with self.assertRaisesRegex(ValueError, "virtual-display-detach-failed"):
            mac_display.display({"operation": "detach", "adapter": "mac-virtual", "tag_id": "7",
                                 "pairing_uuid": IDENTITY, "original_main": BUILTIN}, 0)
        self.assertIn(("set", ("-type=VirtualScreen", "-tagID=7", "-connected=off")), self.mac.calls)
        self.assertFalse(self.mac.connected)

    def test_a_failed_poll_reports_its_cause(self):
        clock = self.use_clock()
        self.hang = lambda argv: "-connected" in argv
        with self.assertRaisesRegex(ValueError, "could not be read .*BetterDisplay did not answer"):
            self.call("probe")

    def test_a_fully_hung_betterdisplay_is_reported_as_such(self):
        self.call("attach", mode=MODE)
        self.use_clock()
        self.hang = lambda argv: argv[0] == mac_display.BETTER
        with self.assertRaisesRegex(ValueError, "detach-failed.*BetterDisplay did not answer"):
            self.call("detach", original_main=BUILTIN)

    def test_a_disconnect_that_is_rejected_and_does_not_land_reports_the_rejection(self):
        self.call("attach", mode=MODE)
        real = self.mac.run
        self.mac.run = lambda argv: "Failed." if "-connected=off" in argv else real(argv)
        self.use_clock()
        with self.assertRaisesRegex(ValueError, "detach-failed.*display-operation-failed"):
            self.call("detach", original_main=None)
        self.assertTrue(self.mac.connected)

    def test_a_later_answer_replaces_an_earlier_failure_as_the_cause(self):
        self.mac.apply = lambda options, virtual: None  # Rejected at first, then accepted but never applied.
        self.use_clock()
        with self.assertRaises(ValueError) as raised:
            self.call("attach", mode=MODE)
        self.assertTrue(str(raised.exception).startswith("display-mode-unavailable"))
        self.assertNotIn("(", str(raised.exception))

    def test_duplicate_identifier_objects_count_once(self):
        self.call("attach", mode=MODE)
        real = self.mac.run
        def run(argv):
            if "-identifiers" in argv and "-tagID=7" in argv:
                one = json.dumps({"UUID": VIRTUAL, "displayID": "12"})
                return one + "," + one
            return real(argv)
        self.mac.run = run
        self.assertEqual(self.call("probe")["virtual"]["uuid"], VIRTUAL)

    def test_the_handback_phase_is_bounded_even_with_slow_reads(self):
        self.call("attach", mode=MODE)
        clock = self.use_clock()
        self.hang = lambda argv: "-UUID=" + BUILTIN in argv or ("-main" in argv and "-tagID=7" in argv)
        observed = self.call("detach", original_main=BUILTIN)
        self.assertFalse(self.mac.connected)
        self.assertIs(observed["main_restored"], False)
        self.assertLessEqual(clock.now, mac_display.HANDBACK_SECONDS + 1)

    def test_a_hung_screen_read_is_a_bounded_read_failure(self):
        clock = self.use_clock()
        self.hang = lambda argv: "-connected" in argv
        with self.assertRaisesRegex(ValueError, "display-operation-failed"):
            self.call("probe")
        self.assertLessEqual(clock.now, mac_display.PROBE_SECONDS + .5)

    def test_reattach_does_not_need_a_full_state_read_first(self):
        self.call("attach", mode=MODE)
        failures = iter([True])
        self.hang = lambda argv: "-refreshRate" in argv and next(failures, False)
        self.assertTrue(self.call("attach", mode=MODE)["virtual"]["main"])

    def test_an_identifier_without_a_display_id_is_a_failed_read(self):
        self.call("attach", mode=MODE)
        real = self.mac.run
        def run(argv):
            if "-identifiers" in argv and "-tagID=7" in argv:
                return json.dumps({"UUID": VIRTUAL})
            return real(argv)
        self.mac.run = run
        clock = self.use_clock()
        with self.assertRaisesRegex(ValueError, "display-operation-failed"):
            self.call("probe")
        self.assertLessEqual(clock.now, mac_display.PROBE_SECONDS + .5)

    def test_a_queued_attach_is_refused_without_touching_the_screen(self):
        with patch.object(mac_display.time, "monotonic", return_value=100):
            with self.assertRaisesRegex(ValueError, "attach-stale"):
                mac_display.display({"operation": "attach", "adapter": "mac-virtual", "tag_id": "7",
                                     "pairing_uuid": IDENTITY, "mode": MODE}, 90)
        self.assertEqual(self.mac.calls, [])

    def test_probe_retries_a_transient_read_failure(self):
        self.call("attach", mode=MODE)
        failures = iter([True])
        self.hang = lambda argv: "-refreshRate" in argv and next(failures, False)
        self.assertTrue(self.call("probe")["virtual"]["main"])

    def test_probe_reports_an_inactive_main_display_without_identifying_it(self):
        self.mac.main = None  # Lid closed, screen detached: nothing is active.
        main = self.call("probe")["main"]
        self.assertFalse(main["active"])
        self.assertIsNone(main["uuid"])

    def test_unclear_connection_state_is_never_read_as_detached(self):
        self.call("attach", mode=MODE)
        self.mac.connected_answer = "on,off"
        clock = itertools.count(0, .5)
        with patch.object(mac_display.time, "monotonic", side_effect=lambda: next(clock)):
            with self.assertRaisesRegex(ValueError, "virtual-display-detach-failed"):
                self.call("detach", original_main=BUILTIN)
        self.assertIn(("set", ("-type=VirtualScreen", "-tagID=7", "-connected=off")), self.mac.calls)
        self.mac.connected_answer = None  # A clean answer lets cleanup finish.
        self.assertFalse(self.call("detach", original_main=BUILTIN)["virtual"]["connected"])

    def test_detach_does_not_depend_on_unrelated_reads(self):
        self.call("attach", mode=MODE)
        self.hang = lambda argv: "-refreshRate" in argv or "-identifiers" in argv or argv[0] == "/usr/bin/pmset"
        observed = self.call("detach", original_main=BUILTIN)
        self.assertFalse(observed["virtual"]["connected"])
        self.assertFalse(self.mac.connected)

    def test_a_handback_that_hangs_still_detaches(self):
        self.call("attach", mode=MODE)
        self.hang = lambda argv: "-UUID=" + BUILTIN in argv
        clock = itertools.count(0, .5)
        with patch.object(mac_display.time, "monotonic", side_effect=lambda: next(clock)):
            observed = self.call("detach", original_main=BUILTIN)
        self.assertFalse(self.mac.connected)
        self.assertIs(observed["main_restored"], False)

    def test_handback_is_skipped_when_the_screen_is_no_longer_main(self):
        self.call("attach", mode=MODE)
        self.mac.main = BUILTIN  # The user moved the main role during the session.
        self.mac.calls.clear()
        observed = self.call("detach", original_main=BUILTIN)
        self.assertIsNone(observed["main_restored"])
        self.assertNotIn(("-type=Display", "-UUID=" + BUILTIN, "-main=on"),
                         [args for verb, args in self.mac.calls if verb == "set"])

    def test_detach_still_removes_the_screen_when_main_cannot_be_handed_back(self):
        self.call("attach", mode=MODE)
        self.mac.builtin_refuses_main = True  # For example, the lid is closed.
        clock = itertools.count(0, .5)
        with patch.object(mac_display.time, "monotonic", side_effect=lambda: next(clock)):
            observed = self.call("detach", original_main=BUILTIN)
        self.assertFalse(observed["virtual"]["connected"])
        self.assertIs(observed["main_restored"], False)

    def test_detach_returns_main_to_the_recorded_display_before_disconnecting(self):
        self.call("attach", mode=MODE)
        self.mac.calls.clear()
        observed = self.call("detach", original_main=BUILTIN)
        self.assertFalse(observed["virtual"]["connected"])
        self.assertEqual(self.mac.main, BUILTIN)
        self.assertIs(observed["main_restored"], True)
        writes = [args for verb, args in self.mac.calls if verb == "set"]
        self.assertEqual(writes[0], ("-type=Display", "-UUID=" + BUILTIN, "-main=on"))
        self.assertEqual(writes[-1], ("-type=VirtualScreen", "-tagID=7", "-connected=off"))

    def test_detach_skips_a_recorded_display_that_has_gone(self):
        self.call("attach", mode=MODE)
        self.mac.builtin_present = False
        observed = self.call("detach", original_main=BUILTIN)
        self.assertFalse(observed["virtual"]["connected"])
        self.assertNotIn(("-type=Display", "-UUID=" + BUILTIN, "-main=on"),
                         [args for verb, args in self.mac.calls if verb == "set"])

    def test_detach_of_a_detached_screen_changes_nothing(self):
        self.call("detach", original_main=BUILTIN)
        self.assertFalse([call for call in self.mac.calls if call[0] == "set"])

    def test_invalid_tag_and_mode_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "tag_id"):
            mac_display.display({"operation": "probe", "adapter": "mac-virtual", "tag_id": "4; x", "pairing_uuid": IDENTITY})
        with self.assertRaisesRegex(ValueError, "invalid display mode"):
            self.call("attach", mode={**MODE, "resolution": "big"})


class FakeHost:
    """The daemon-side view: remote operations against a simulated Mac."""

    def __init__(self):
        self.display = copy.deepcopy(DISPLAY)
        self.connected, self.main, self.asleep = False, BUILTIN, False
        self.mode = copy.deepcopy(MODE)
        self.operations = []
        self.fail = None
        self.before = None
        self.output = None
        self.main_unknown = False
        self.main_active = True
        self.probe_error = None
        self.ac_power = True

    def state(self):
        virtual = {"connected": self.connected}
        if self.connected:
            virtual.update(uuid=VIRTUAL, display_id="12", name="Stream Screen", active=not self.asleep,
                           asleep=self.asleep, main=self.main == VIRTUAL, mode=copy.deepcopy(self.mode))
        return {"virtual": virtual, "main": {"uuid": None if self.main_unknown else self.main, "active": self.main_active,
                                             "display_id": "12" if self.main == VIRTUAL else "1"},
                "sunshine_output": self.output, "lid_closed": True, "ac_power": self.ac_power}

    def remote(self, operation, **values):
        if self.before:
            self.before(operation, values)
        self.operations.append((operation, values))
        if operation == "probe" and self.probe_error:
            raise ValueError(self.probe_error)
        if self.fail == operation:
            raise ValueError("host-unreachable: injected")
        if operation == "attach":
            self.connected, self.main, self.asleep = True, VIRTUAL, False
        elif operation == "detach":
            if values["original_main"] and self.main == VIRTUAL:
                self.main = values["original_main"]
            self.connected = False
            if self.main == VIRTUAL:
                self.main = BUILTIN
        return self.state()


class JournalTests(unittest.TestCase):
    def test_original_main_is_durable_before_the_screen_is_attached(self):
        host, record, saved = FakeHost(), {}, []
        def before(operation, values):
            if operation == "attach":
                self.assertEqual(saved[-1]["journal"]["virtual"]["original"], {"connected": False, "main": BUILTIN})
        host.before = before
        mac_virtual.prepare(record, host, lambda: saved.append(copy.deepcopy(record)))
        self.assertEqual(record["journal"]["virtual"]["phase"], "applied")
        self.assertEqual(record["resolved"]["identity"]["UUID"], VIRTUAL)

    def test_restore_detaches_and_hands_main_back(self):
        host, record = FakeHost(), {}
        s.prepare(record, s_host(host), lambda: None)
        self.assertTrue(s.restore(record, s_host(host), lambda: None))
        self.assertEqual(host.operations[-1], ("detach", {"original_main": BUILTIN}))
        self.assertFalse(host.connected)
        self.assertEqual(host.main, BUILTIN)
        self.assertEqual(record["journal"], {})

    def test_reconnect_keeps_the_first_baseline(self):
        host, record = FakeHost(), {}
        mac_virtual.prepare(record, host, lambda: None)
        mac_virtual.prepare(record, host, lambda: None)  # Main is now the virtual screen.
        self.assertEqual(record["journal"]["virtual"]["original"]["main"], BUILTIN)

    def test_failed_attach_keeps_the_journal_so_restore_detaches(self):
        host, record = FakeHost(), {}
        host.fail = "attach"
        with self.assertRaises(ValueError):
            mac_virtual.prepare(record, host, lambda: None)
        self.assertEqual(record["journal"]["virtual"]["phase"], "intent")
        host.fail = None
        host.connected, host.main = True, VIRTUAL  # The write landed before the failure.
        self.assertTrue(mac_virtual.restore(record, host, lambda: None))
        self.assertFalse(host.connected)
        self.assertEqual(host.main, BUILTIN)

    def test_unreachable_host_keeps_restore_pending(self):
        host, record = FakeHost(), {}
        mac_virtual.prepare(record, host, lambda: None)
        host.fail = "detach"
        with self.assertRaisesRegex(ValueError, "host-unreachable"):
            mac_virtual.restore(record, host, lambda: None)
        self.assertIn("virtual", record["journal"])

    def test_an_attached_screen_that_is_not_main_keeps_the_known_baseline(self):
        host, record = FakeHost(), {}
        host.connected, host.main = True, IDENTITY  # An external display is main.
        mac_virtual.prepare(record, host, lambda: None)
        self.assertEqual(record["journal"]["virtual"]["original"], {"connected": True, "main": IDENTITY})

    def test_a_clean_attach_resets_the_unreadable_count(self):
        host, record = FakeHost(), {"unreadable_checks": 2}
        mac_virtual.prepare(record, host, lambda: None)
        self.assertNotIn("unreadable_checks", record)

    def test_an_unidentified_main_display_is_looked_at_twice(self):
        host, record = FakeHost(), {}
        answers = iter([True, False])
        original = host.state
        def state():
            host.main_unknown = next(answers, False)
            return original()
        host.state = state
        mac_virtual.prepare(record, host, lambda: None)
        self.assertEqual(record["journal"]["virtual"]["original"]["main"], BUILTIN)

    def test_unknown_power_is_refused_at_connect_but_tolerated_by_health(self):
        fake = FakeHost()
        host = s_host(fake, require_ac=True)
        record = {}
        mac_virtual.prepare(record, fake, lambda: None)
        fake.ac_power = None
        with self.assertRaisesRegex(ValueError, "power-unknown"):
            host.probe(pairing=False)
        self.assertEqual(mac_virtual.health(record, host)["reconnect"], False)

    def test_an_unidentified_main_display_stops_before_any_change(self):
        host, record = FakeHost(), {}
        host.main_unknown = True
        with self.assertRaisesRegex(ValueError, "display-probe-failed"):
            mac_virtual.prepare(record, host, lambda: None)
        self.assertNotIn("attach", [op for op, _ in host.operations])
        self.assertNotIn("virtual", record.get("journal", {}))

    def test_no_active_display_records_nothing_to_hand_back(self):
        host, record = FakeHost(), {}
        host.main_active, host.main_unknown = False, True  # Lid closed, no monitor.
        mac_virtual.prepare(record, host, lambda: None)
        self.assertEqual(record["journal"]["virtual"]["original"], {"connected": False, "main": None})

    def test_a_failed_health_read_keeps_the_stream_and_looks_again(self):
        host, record = FakeHost(), {}
        mac_virtual.prepare(record, host, lambda: None)
        host.probe_error = "display-operation-failed: BetterDisplay did not answer"
        self.assertEqual(mac_virtual.health(record, host), {"reconnect": False})
        host.probe_error = None
        mac_virtual.health(record, host)  # A good read resets the count.
        host.probe_error = "display-operation-failed: BetterDisplay did not answer"
        results = [mac_virtual.health(record, host)["reconnect"] for _ in range(mac_virtual.UNREADABLE_CHECKS)]
        self.assertEqual(results, [False] * (mac_virtual.UNREADABLE_CHECKS - 1) + [True])
        host.probe_error = "host-unreachable: SSH unavailable"
        with self.assertRaisesRegex(ValueError, "host-unreachable"):
            mac_virtual.health(record, host)

    def test_a_pinned_sunshine_output_stops_before_any_change(self):
        host, record = FakeHost(), {}
        host.output = "1"
        with self.assertRaisesRegex(ValueError, "output_name"):
            mac_virtual.prepare(record, host, lambda: None)
        self.assertNotIn("attach", [op for op, _ in host.operations])

    def test_restore_leaves_other_journal_entries_pending(self):
        record = {"journal": {"mode": {}}}
        self.assertFalse(mac_virtual.restore(record, FakeHost(), lambda: None))

    def test_require_ac_is_checked_in_probe_and_health(self):
        fake = FakeHost()
        fake.ac_power = False
        host = s_host(fake, require_ac=True)
        with patch.object(s, "moonlight_hosts"):
            with self.assertRaisesRegex(ValueError, "power-required"):
                host.probe(pairing=False)
        record = {}
        fake.ac_power = True
        mac_virtual.prepare(record, fake, lambda: None)
        fake.ac_power = False
        with self.assertRaisesRegex(ValueError, "power-required"):
            mac_virtual.health(record, host)

    def test_the_worker_keeps_the_unreadable_count_between_checks(self):
        from remote_desktops import worker
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recovery.json"
            value = computer()
            path.write_text(json.dumps({"config": value, "settings": value["profiles"]["desktop"], "journal": {}}))
            fake = FakeHost()
            fake.connected, fake.main = True, VIRTUAL
            fake.probe_error = "display-operation-failed: BetterDisplay did not answer"
            with patch.object(s.Host, "remote", lambda self, operation, **values: fake.remote(operation, **values)):
                results = [worker.operation({"operation": "health", "path": str(path)})["reconnect"]
                           for _ in range(mac_virtual.UNREADABLE_CHECKS)]
        self.assertEqual(results, [False] * (mac_virtual.UNREADABLE_CHECKS - 1) + [True])

    def test_worker_health_and_probe_use_the_virtual_screen(self):
        from remote_desktops import worker
        fake = FakeHost()
        host = s_host(fake)
        record = {}
        s.prepare(record, host, lambda: None)
        self.assertEqual(worker.health(record, host), {"reconnect": False, "degraded": False})
        probed = host.probe(pairing=False)
        self.assertEqual(probed["virtual_screen"]["uuid"], VIRTUAL)
        fake.output = "1"
        with self.assertRaisesRegex(ValueError, "output_name"):
            host.probe(pairing=False)

    def test_an_already_attached_screen_is_adopted_and_detached_later(self):
        host, record = FakeHost(), {}
        host.connected, host.main = True, VIRTUAL  # Left behind by an older app preparation hook.
        mac_virtual.prepare(record, host, lambda: None)
        self.assertIsNone(record["journal"]["virtual"]["original"]["main"])
        self.assertTrue(mac_virtual.restore(record, host, lambda: None))
        self.assertFalse(host.connected)

    def test_health_reconnects_a_lost_or_sleeping_screen_and_reports_a_moved_main(self):
        host, record = FakeHost(), {}
        mac_virtual.prepare(record, host, lambda: None)
        self.assertEqual(mac_virtual.health(record, host), {"reconnect": False, "degraded": False})
        host.main = BUILTIN
        self.assertEqual(mac_virtual.health(record, host), {"reconnect": False, "degraded": True})
        host.asleep = True
        self.assertEqual(mac_virtual.health(record, host)["reconnect"], True)
        host.connected = False
        self.assertEqual(mac_virtual.health(record, host)["reconnect"], True)


def s_host(fake, **display):
    """Route the generic host entry points to the fake."""
    value = computer({**DISPLAY, **display})
    host = s.Host(value, value["profiles"]["desktop"])
    host.remote = fake.remote
    return host


class ConfigurationTests(unittest.TestCase):
    def check(self, value):
        return s.configuration_value({"version": 1, "computers": {"mac": value}})

    def test_valid_profile(self):
        self.check(computer())

    def test_invalid_profiles_are_rejected(self):
        cases = {
            "platform=macos": {**computer(), "platform": "windows"},
            "tag_id": computer({**DISPLAY, "tag_id": 4}),
            "selected by tag_id": computer({**DISPLAY, "uuid": VIRTUAL}),
            "invalid host mode": computer({**DISPLAY, "mode": {**MODE, "hidpi": "yes"}}),
        }
        for message, value in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                self.check(value)
        no_user = computer()
        no_user["ssh"] = {}
        with self.assertRaisesRegex(ValueError, "ssh.user"):
            self.check(no_user)

    def test_stream_launch_does_not_ask_sunshine_to_quit_or_resize(self):
        argv = s.stream_argv(computer(), computer()["profiles"]["desktop"])
        self.assertIn("--no-quit-after", argv)
        self.assertIn("--no-game-optimization", argv)


if __name__ == "__main__":
    unittest.main()
