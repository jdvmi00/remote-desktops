"""Development UI refuses a daemon from a different executable."""
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import dev


@unittest.skipUnless(sys.platform == "linux", "Linux socket peer credentials and /proc")
class DevelopmentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "remote-desktops").mkdir()
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(self.listener.close)
        self.listener.bind(str(self.root / "remote-desktops/control.sock"))
        self.listener.listen(1)
        env = patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.root)})
        env.start()
        self.addCleanup(env.stop)

    def test_accepts_matching_executable(self):
        with patch.object(dev, "BACKEND", Path(sys.executable)), patch("builtins.print"):
            dev.check_daemon()

    def test_rejects_different_executable(self):
        other = self.root / "other-build"
        other.write_text("not the running executable")
        with patch.object(dev, "BACKEND", other):
            with self.assertRaisesRegex(RuntimeError, "not the current checkout build"):
                dev.check_daemon()

    def test_missing_daemon_explains_how_to_start_it(self):
        self.listener.close()
        with self.assertRaisesRegex(RuntimeError, "scripts/dev.py daemon"):
            dev.check_daemon()
