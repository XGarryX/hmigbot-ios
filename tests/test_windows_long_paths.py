import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hmigbot_ios.core import MigrationError, digest, safe_child, snapshot, source_files, write_new_tree


@unittest.skipUnless(os.name == "nt", "Windows extended-length IO requires Windows")
class WindowsLongPathTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="hmigbot-long-path-"))
        self.addCleanup(shutil.rmtree, self.extended(self.root))
        self.relative = "/".join(["segment-" + "x" * 48] * 5 + ["EntryAbility.ets"])
        self.deep_file = self.root.joinpath(*self.relative.split("/"))
        self.assertGreater(len(str(self.deep_file.parent)), 260)
        self.extended(self.deep_file).parent.mkdir(parents=True)
        self.payload = b"export default class EntryAbility {}\n"
        self.extended(self.deep_file).write_bytes(self.payload)

    @staticmethod
    def extended(path):
        return Path("\\\\?\\" + str(path))

    def test_safe_child_reads_long_file_and_preserves_relative_path_contract(self):
        child = safe_child(self.root, self.relative)
        try:
            actual = child.read_bytes()
        except OSError as error:
            self.fail(f"A real extended-length file must remain readable: {error}")
        self.assertEqual(actual, self.payload)
        self.assertEqual(child, self.deep_file)
        self.assertEqual(child.relative_to(self.root.resolve()).as_posix(), self.relative)
        self.assertTrue(child.is_relative_to(self.root.resolve()))
        self.assertEqual(child.resolve().relative_to(self.root.resolve()).as_posix(), self.relative)
        self.assertFalse(str(child).startswith("\\\\?\\"))
        self.assertTrue(child.is_file())
        self.assertEqual(child.stat().st_size, len(self.payload))

    def test_safe_child_supports_long_root_and_extended_input_without_prefix_leak(self):
        root = self.deep_file.parent
        for root_form in (root, self.extended(root)):
            with self.subTest(root_form=str(root_form)):
                child = safe_child(root_form, self.deep_file.name)
                try:
                    actual = child.read_bytes()
                except OSError as error:
                    self.fail(f"Long roots must support direct child IO: {error}")
                self.assertEqual(actual, self.payload)
                self.assertTrue(child.is_relative_to(root), "IO prefixes must not change path identity")
                self.assertEqual(child.relative_to(root).as_posix(), self.deep_file.name)
                self.assertFalse(str(child.resolve()).startswith("\\\\?\\"))

    def test_source_files_and_snapshot_do_not_silently_omit_deep_directories(self):
        paths = source_files(self.root)
        self.assertEqual([path.relative_to(self.root).as_posix() for path in paths], [self.relative])
        for path in paths:
            self.assertEqual(path.read_bytes(), self.payload)
        expected = {"path": self.relative, "sha256": digest(self.payload), "bytes": len(self.payload)}
        first = snapshot(self.root)
        self.assertEqual(first["files"], [expected])
        self.assertEqual(snapshot(self.extended(self.root)), first)
        self.extended(self.deep_file).write_bytes(self.payload + b"// changed\n")
        self.assertNotEqual(snapshot(self.root)["sha256"], first["sha256"])

    def test_history_files_keep_participating_in_default_source_fingerprint(self):
        archive = self.root / "spec/.a2h/history/replan-test"
        relative = "spec/.a2h/history/replan-test/" + self.relative
        archived = archive.joinpath(*self.relative.split("/"))
        self.extended(archived).parent.mkdir(parents=True)
        self.extended(archived).write_bytes(b"archived evidence")
        files = {item["path"]: item for item in snapshot(self.root)["files"]}
        self.assertIn(relative, files)
        self.assertEqual(files[relative]["sha256"], digest(b"archived evidence"))

    def test_long_path_traversal_and_nonportable_names_remain_rejected(self):
        for relative in ("../outside.txt", "a/../../outside.txt", "C:/outside.txt", "a\\b", "NUL.txt", "trailing."):
            with self.subTest(relative=relative):
                with self.assertRaises(MigrationError):
                    safe_child(self.deep_file.parent, relative)

    def test_long_output_publishes_complete_tree_and_preserves_existing_files(self):
        output = self.deep_file.parent / "published"
        files = {"nested/data.bin": b"\x00\xff", "manifest.json": b"{}\n"}
        try:
            write_new_tree(output, files)
        except OSError as error:
            self.fail(f"Atomic publication must support long output directories: {error}")
        for relative, payload in files.items():
            self.assertEqual(safe_child(output, relative).read_bytes(), payload)
        with self.assertRaises(MigrationError):
            write_new_tree(output, {"replace.txt": b"not allowed"})
        self.assertEqual(safe_child(output, "nested/data.bin").read_bytes(), b"\x00\xff")

    def test_junction_escape_and_deep_source_link_are_rejected(self):
        target = self.root / "outside"
        target.mkdir()
        link = self.root / "junction"
        created = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if created.returncode:
            self.skipTest(f"Junction creation unavailable: {created.stderr!r}")
        inside_root = self.deep_file.parent / "scope"
        self.extended(inside_root).mkdir()
        deep_link = inside_root / "linked"
        self.extended(link).rename(self.extended(deep_link))
        with self.assertRaises(MigrationError):
            safe_child(inside_root, "linked/escape.txt")
        with self.assertRaises(MigrationError):
            source_files(inside_root)


if __name__ == "__main__":
    unittest.main()
