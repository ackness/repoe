"""Exercise Windows publication boundaries with real files and directory handles."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from RePoE import native_descriptions as publication


@unittest.skipUnless(os.name == "nt", "Windows directory-handle publication")
class WindowsPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=publication.ROOT / ".cache")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw = self.root / "input"
        self.raw.mkdir()

    def test_exact_bytes_and_exclusive_output(self):
        target = self.root / "nested" / "candidate"
        payload = {"manifest.json": b'{"complete":true}\n', "tables.json": "原文\r\n".encode()}
        publication._publish(target, self.raw, payload)
        self.assertEqual({p.name: p.read_bytes() for p in target.iterdir()}, payload)
        with self.assertRaises(FileExistsError):
            publication._publish(target, self.raw, payload)

    def test_input_and_payload_escape_rejected(self):
        for target, payload in [
            (self.raw / "candidate", {"data": b"x"}),
            (self.root / "candidate", {"../escaped": b"x"}),
            (self.root / "candidate", {"data:stream": b"x"}),
        ]:
            with self.assertRaises(ValueError):
                publication._publish(target, self.raw, payload)
            self.assertFalse(target.exists())

    def test_no_manifest_when_payload_write_fails(self):
        target = self.root / "candidate"
        original = Path.open

        def fail_payload(path, *args, **kwargs):
            if path.name == "tables.json":
                raise OSError("simulated publication interruption")
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", fail_payload), self.assertRaises(OSError):
            publication._publish(target, self.raw, {"manifest.json": b"complete", "tables.json": b"data"})
        self.assertFalse((target / "manifest.json").exists())

    def test_reparse_parent_rejected_without_writing_target(self):
        other = self.root / "other"
        other.mkdir()
        alias = self.root / "alias"
        try:
            alias.symlink_to(other, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Directory symlink privilege unavailable: {error}")
        with self.assertRaises(ValueError):
            publication._publish(alias / "candidate", self.raw, {"tables.json": b"data"})
        self.assertFalse((other / "candidate").exists())

    def test_directory_is_locked_against_replacement_during_write(self):
        target = self.root / "candidate"
        original = Path.open
        refused = []

        def attempt_rename(path, *args, **kwargs):
            try:
                target.rename(self.root / "moved")
            except PermissionError:
                refused.append(True)
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", attempt_rename):
            publication._publish(target, self.raw, {"tables.json": b"data"})
        self.assertEqual(refused, [True])


if __name__ == "__main__":
    unittest.main()
