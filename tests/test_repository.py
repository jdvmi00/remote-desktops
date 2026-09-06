"""Ensure repository validation rejects errors on both Linux and Windows."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check import check_file


class RepositoryChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))

    def test_missing_or_untracked_link_is_rejected(self):
        self.write("README.md", "[Guide](docs/guide.md)\n")
        self.assertTrue(check_file(self.root, "README.md", {"README.md"}))
        self.write("docs/guide.md", "# Guide\n")
        self.assertTrue(check_file(self.root, "README.md", {"README.md"}))
        self.assertEqual(check_file(self.root, "README.md", {"README.md", "docs/guide.md"}), [])

    def test_relative_links_and_anchors_work_without_fetching_external_urls(self):
        self.write("README.md", "# Home\n")
        self.write("docs/guide.md", "[Home](../README.md#home) [Web](https://example.invalid) [Here](#here)\n")
        self.assertEqual(check_file(self.root, "docs/guide.md", {"README.md", "docs/guide.md"}), [])

    def test_invalid_python_is_rejected_without_execution(self):
        self.write("example.py", "if:\n")
        self.assertTrue(check_file(self.root, "example.py", {"example.py"}))
        self.write("example.py", "raise RuntimeError('must not execute')\n")
        self.assertEqual(check_file(self.root, "example.py", {"example.py"}), [])

    def test_nonportable_line_endings_and_whitespace_are_rejected(self):
        self.write("README.md", "# Heading \r\nNo final newline")
        errors = check_file(self.root, "README.md", {"README.md"})
        self.assertTrue(any("LF line endings" in error for error in errors))
        self.assertTrue(any("trailing whitespace" in error for error in errors))
        self.assertTrue(any("final newline" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
