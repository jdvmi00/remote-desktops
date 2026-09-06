"""Setup-time discovery, pairing, and inspection with fake tools on PATH."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from remote_desktops import setup, windows_display

TAILSCALE = json.dumps({"Self": {"HostName": "me", "OS": "linux"}, "Peer": {
    "a": {"HostName": "Work PC", "DNSName": "work.tail.ts.net.", "OS": "windows", "Online": True, "TailscaleIPs": ["100.1.1.1", "fd7a::1"]},
    "b": {"HostName": "Phone", "DNSName": "phone.tail.ts.net.", "OS": "iOS", "Online": True, "TailscaleIPs": ["100.1.1.2"]},
    "c": {"HostName": "Studio", "DNSName": "studio.tail.ts.net.", "OS": "macOS", "Online": False, "TailscaleIPs": ["100.1.1.3"]}}})
AVAHI = ("+;eth0;IPv4;Work\\032PC;_nvstream._tcp;local\n"
         "=;eth0;IPv4;Work\\032PC;_nvstream._tcp;local;work-pc.local;192.168.1.5;47989;\n"
         "=;eth0;IPv6;Work\\032PC;_nvstream._tcp;local;work-pc.local;fe80::1;47989;\n"
         "=;eth0;IPv4;Garage;_nvstream._tcp;local;garage.local;192.168.1.9;47989;\n")


class SetupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = patch.dict(os.environ, {"PATH": str(self.bin) + os.pathsep + "/usr/bin:/bin",
                                           "XDG_CONFIG_HOME": str(self.root / "config")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.conf = self.root / "config/Moonlight Game Streaming Project/Moonlight.conf"
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text("[hosts]\n1\\uuid=11111111-2222-3333-4444-555555555555\n1\\hostname=Work PC\n1\\srvcert=x\n1\\manualaddress=work.tail.ts.net\n")

    def shim(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def test_discovery_merges_sources_filters_phones_and_marks_paired(self):
        self.shim("tailscale", "cat <<'EOF'\n" + TAILSCALE + "\nEOF\n")
        self.shim("avahi-browse", "printf '%s' '" + AVAHI + "'\n")
        found = setup.discover()["candidates"]
        names = [c["name"] for c in found]
        self.assertEqual(names, ["Garage", "Work PC", "Studio"], "online first, then by name; merged; phones excluded")
        work = found[1]
        self.assertEqual(work["platform"], "windows")
        self.assertEqual(work["pairing_uuid"], "11111111-2222-3333-4444-555555555555")
        self.assertEqual(work["addresses"], ["work.tail.ts.net", "100.1.1.1", "work-pc.local", "192.168.1.5"])
        self.assertIsNone(found[0]["platform"])
        self.assertIsNone(found[0]["pairing_uuid"])
        self.assertFalse(found[2]["online"])

    def test_discovery_survives_missing_or_broken_tools(self):
        with patch.dict(os.environ, {"PATH": str(self.bin)}):
            self.assertEqual(setup.discover()["candidates"], [])
            self.shim("tailscale", "echo not-json\n")
            self.shim("avahi-browse", "exit 3\n")
            self.assertEqual(setup.discover()["candidates"], [])

    def test_pair_reads_the_new_host_back_from_moonlight(self):
        self.shim("pgrep", "exit 1\n")
        self.shim("moonlight", 'if [ "$1" = pair ]; then\n'
                  '  printf "2\\\\\\\\uuid=22222222-3333-4444-5555-666666666666\\n2\\\\\\\\hostname=Garage PC\\n2\\\\\\\\srvcert=y\\n2\\\\\\\\manualaddress=$2\\n" >> "$XDG_CONFIG_HOME/Moonlight Game Streaming Project/Moonlight.conf"\n'
                  '  echo "00:00:02 - Qt Info: Pairing completed"; exit 0\nfi\nexit 99\n')
        result = setup.pair("garage.local", "1234")
        self.assertEqual(result, {"paired": True, "pairing_uuid": "22222222-3333-4444-5555-666666666666", "name": "Garage PC", "host": "garage.local"})

    def test_pair_reports_moonlight_reason_and_refuses_while_gui_is_open(self):
        self.shim("pgrep", "exit 1\n")
        self.shim("moonlight", 'echo "00:00:01 - Qt Warning: Failed to pair: incorrect PIN" >&2; exit 1\n')
        with self.assertRaisesRegex(ValueError, "pairing-failed: Failed to pair: incorrect PIN"):
            setup.pair("garage.local", "0000")
        self.shim("pgrep", "echo '4242 moonlight'\n")
        with self.assertRaisesRegex(ValueError, "moonlight-running"):
            setup.pair("garage.local", "1234")
        self.shim("pgrep", "echo '4242 moonlight stream 1111 Desktop'\n")
        self.shim("moonlight", "exit 1\n")
        with self.assertRaisesRegex(ValueError, "pairing-failed"):
            setup.pair("garage.local", "1234")
        with self.assertRaisesRegex(ValueError, "invalid PIN"):
            setup.pair("garage.local", "12")
        with self.assertRaisesRegex(ValueError, "invalid host"):
            setup.pair("bad host", "1234")

    def test_summary_drops_urls_and_keeps_the_last_pairing_line(self):
        self.assertEqual(setup.summarize("00:00:00 - SDL Info (0): Detected Wayland\nGET https://host:47989/pair?x\n00:00:01 - Qt Info: Pairing failed: timed out"),
                         "Pairing failed: timed out")
        self.assertEqual(setup.summarize("nothing relevant"), "Moonlight did not report a paired host")

    def test_windows_inspection_parses_displays_and_hardware(self):
        reply = {"ok": True, "result": {"sunshine_output": "{ABCDEF01-1111-2222-3333-444444444444}",
                 "helper": {"installed": False, "phase": None, "capture_id": None, "fresh": False},
                 "displays": [{"id": "\\\\?\\DISPLAY#MTT1337#5&2c4d1f3&0&UID4352#{e6f07b5f}", "name": "Virtual", "active": False, "available": True, "internal": False, "primary": False, "width": 2560, "height": 1440},
                              {"id": "\\\\?\\DISPLAY#BOE0A1B#4&1&0&UID256#{e6f07b5f}", "name": "Panel", "active": True, "available": True, "internal": True, "primary": True, "width": 1920, "height": 1200}]}}
        with patch.object(windows_display, "powershell", return_value=reply) as ps:
            observed = windows_display.inspect("laptop", "11111111-2222-3333-4444-555555555555")
        self.assertIn("11111111-2222-3333-4444-555555555555", ps.call_args[0][1])
        self.assertEqual([d["hardware"] for d in observed["displays"]], ["MTT1337", "BOE0A1B"])
        self.assertFalse(observed["helper"]["installed"])
        computer = {"platform": "windows", "ssh": {"alias": "laptop"}, "pairing_uuid": "11111111-2222-3333-4444-555555555555", "host": "x"}
        with patch.object(windows_display, "powershell", return_value=reply):
            with self.assertRaisesRegex(ValueError, "display-missing"):
                setup.install_helper(computer, "\\\\?\\DISPLAY#NOPE")
            with patch.object(windows_display, "install", return_value={"ok": True}) as install:
                setup.install_helper(computer, "\\\\?\\display#mtt1337#5&2c4d1f3&0&UID4352#{e6f07b5f}")
            self.assertEqual(install.call_args[0], ("laptop", "11111111-2222-3333-4444-555555555555", "{ABCDEF01-1111-2222-3333-444444444444}", "MTT1337"))
        with self.assertRaisesRegex(ValueError, "ssh-alias-required"):
            setup.inspect({"platform": "windows", "ssh": {}, "pairing_uuid": "11111111-2222-3333-4444-555555555555"})
        with self.assertRaisesRegex(ValueError, "ssh-user-required"):
            setup.inspect({"platform": "macos", "ssh": {"user": "bad user"}, "pairing_uuid": "11111111-2222-3333-4444-555555555555"})
        with self.assertRaisesRegex(ValueError, "macOS and Windows"):
            setup.inspect({"platform": "linux", "pairing_uuid": "11111111-2222-3333-4444-555555555555"})


if __name__ == "__main__":
    unittest.main()
