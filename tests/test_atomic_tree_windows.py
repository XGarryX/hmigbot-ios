import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hmigbot_ios.core import MigrationError, write_new_tree


def windows_denied():
    error = PermissionError(errno.EACCES, "Access is denied")
    error.winerror = 5
    return error


class AtomicTreeWindowsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="atomic-tree-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.output = self.root / "published"
        self.files = {"manifest.json": b'{"complete":true}', "nested/blob.bin": b"\x00\xff"}

    def assert_no_staging(self):
        self.assertEqual(list(self.root.glob(".hmigbot-ios-*")), [])

    def assert_link_rejected(self):
        with patch.object(Path, "rename", autospec=True) as rename:
            try:
                write_new_tree(self.output, self.files)
            except MigrationError:
                pass
            except OSError as error:
                self.fail(f"An output link must be rejected before publication: {error}")
            else:
                self.fail("An output link was accepted as a publication directory")
        rename.assert_not_called()
        self.assertTrue(os.path.lexists(self.output))
        self.assert_no_staging()

    def create_symlink(self, target):
        try:
            self.output.symlink_to(target, target_is_directory=True)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Directory symlink creation is unavailable: {error}")

    def create_junction(self, target):
        created = subprocess.run(
            ["cmd", "/d", "/c", "mklink", "/J", str(self.output), str(target)],
            capture_output=True,
        )
        if created.returncode:
            self.skipTest(f"Directory junction creation is unavailable: {created.stderr!r}")

    def test_existing_empty_directory_symlink_is_preserved(self):
        target = self.root / "linked-target"
        target.mkdir()
        self.create_symlink(target)
        self.assert_link_rejected()
        self.assertTrue(self.output.is_symlink())
        self.assertEqual(list(target.iterdir()), [])

    def test_dangling_directory_symlink_is_preserved(self):
        target = self.root / "missing-target"
        self.create_symlink(target)
        self.assert_link_rejected()
        self.assertTrue(self.output.is_symlink())
        self.assertFalse(target.exists())

    @unittest.skipUnless(os.name == "nt", "Windows junctions require Windows")
    def test_existing_empty_windows_junction_is_preserved(self):
        target = self.root / "junction-target"
        target.mkdir()
        self.create_junction(target)
        before = os.readlink(self.output)
        self.assert_link_rejected()
        self.assertEqual(os.readlink(self.output), before)
        self.assertEqual(list(target.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "Windows junctions require Windows")
    def test_dangling_windows_junction_is_preserved(self):
        target = self.root / "removed-junction-target"
        target.mkdir()
        self.create_junction(target)
        target.rmdir()
        before = os.readlink(self.output)
        self.assertFalse(self.output.exists())
        self.assert_link_rejected()
        self.assertEqual(os.readlink(self.output), before)
        self.assertFalse(target.exists())

    def test_transient_windows_denial_retries_atomic_publication(self):
        real_rename = Path.rename
        attempts = []

        def rename(source, target):
            attempts.append(source)
            self.assertFalse(target.exists(), "Publication must not expose a partial tree")
            for name, expected in self.files.items():
                self.assertEqual((source / name).read_bytes(), expected)
            if len(attempts) == 1:
                raise windows_denied()
            return real_rename(source, target)

        with patch.object(Path, "rename", autospec=True, side_effect=rename), patch("time.sleep") as sleep:
            try:
                write_new_tree(self.output, self.files)
            except PermissionError as error:
                self.fail(f"A transient Windows access denial must be retried: {error}")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0], attempts[1])
        self.assertEqual(sleep.call_count, 1)
        for name, expected in self.files.items():
            self.assertEqual((self.output / name).read_bytes(), expected)
        self.assert_no_staging()

    def test_persistent_windows_denial_is_bounded_and_preserves_error(self):
        denial = windows_denied()
        with patch.object(Path, "rename", autospec=True, side_effect=denial) as rename, patch("time.sleep") as sleep:
            with self.assertRaises(PermissionError) as caught:
                write_new_tree(self.output, self.files)
        self.assertIs(caught.exception, denial)
        self.assertEqual(rename.call_count, 5)
        self.assertEqual(sleep.call_count, 4)
        self.assertTrue(all(0 < call.args[0] <= 0.4 for call in sleep.call_args_list))
        self.assertFalse(self.output.exists())
        self.assert_no_staging()

    def test_cleanup_failure_cannot_mask_publication_failure(self):
        denial = windows_denied()
        cleanup_failure = PermissionError(errno.EACCES, "Staging tree is still locked")
        with patch.object(Path, "rename", autospec=True, side_effect=denial) as rename, patch("time.sleep"), patch("shutil.rmtree", side_effect=cleanup_failure) as cleanup:
            with self.assertRaises(PermissionError) as caught:
                write_new_tree(self.output, self.files)
        self.assertIs(caught.exception, denial)
        self.assertEqual(rename.call_count, 5)
        cleanup.assert_called_once()
        self.assertFalse(self.output.exists())
        notes = "\n".join(getattr(caught.exception, "__notes__", []))
        self.assertIn("cleanup", notes.lower())
        self.assertIn(str(cleanup.call_args.args[0]), notes)
        self.assertIn(str(cleanup_failure), notes)

    def test_cleanup_failure_without_publication_failure_is_raised(self):
        cleanup_failure = PermissionError(errno.EACCES, "Staging tree is still locked")
        with patch.object(Path, "rename", autospec=True), patch("shutil.rmtree", side_effect=cleanup_failure):
            with self.assertRaises(PermissionError) as caught:
                write_new_tree(self.output, self.files)
        self.assertIs(caught.exception, cleanup_failure)

    def test_non_windows_permission_error_is_not_retried(self):
        denial = PermissionError(errno.EACCES, "A real permission failure")
        with patch.object(Path, "rename", autospec=True, side_effect=denial) as rename, patch("time.sleep") as sleep:
            with self.assertRaises(PermissionError) as caught:
                write_new_tree(self.output, self.files)
        self.assertIs(caught.exception, denial)
        self.assertEqual(rename.call_count, 1)
        sleep.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assert_no_staging()

    def test_other_windows_error_is_not_retried(self):
        denial = PermissionError(errno.EACCES, "Other Windows failure")
        denial.winerror = 32
        with patch.object(Path, "rename", autospec=True, side_effect=denial) as rename, patch("time.sleep") as sleep:
            with self.assertRaises(PermissionError) as caught:
                write_new_tree(self.output, self.files)
        self.assertIs(caught.exception, denial)
        self.assertEqual(rename.call_count, 1)
        sleep.assert_not_called()
        self.assert_no_staging()

    def test_existing_output_is_never_replaced(self):
        for kind in ("file", "directory"):
            with self.subTest(kind=kind):
                output = self.root / kind
                if kind == "file":
                    output.write_bytes(b"user work")
                    sentinel = output
                else:
                    output.mkdir()
                    sentinel = output / "keep.txt"
                    sentinel.write_bytes(b"user work")
                with patch.object(Path, "rename", autospec=True) as rename, patch("time.sleep") as sleep:
                    with self.assertRaises(MigrationError):
                        write_new_tree(output, self.files)
                self.assertEqual(sentinel.read_bytes(), b"user work")
                rename.assert_not_called()
                sleep.assert_not_called()
        self.assert_no_staging()

    def test_initially_empty_output_can_be_published(self):
        self.output.mkdir()
        write_new_tree(self.output, self.files)
        for name, expected in self.files.items():
            self.assertEqual((self.output / name).read_bytes(), expected)
        self.assert_no_staging()

    def test_concurrent_output_on_denial_is_preserved_without_retry(self):
        for empty in (True, False):
            with self.subTest(empty=empty):
                output = self.root / f"concurrent-{empty}"
                denial = windows_denied()

                def rename(source, target):
                    target.mkdir()
                    if not empty:
                        (target / "keep.txt").write_bytes(b"user work")
                    raise denial

                with patch.object(Path, "rename", autospec=True, side_effect=rename) as rename_mock, patch("time.sleep") as sleep:
                    with self.assertRaises(PermissionError) as caught:
                        write_new_tree(output, self.files)
                self.assertIs(caught.exception, denial)
                self.assertEqual(rename_mock.call_count, 1)
                sleep.assert_not_called()
                self.assertTrue(output.is_dir())
                if empty:
                    self.assertEqual(list(output.iterdir()), [])
                else:
                    self.assertEqual((output / "keep.txt").read_bytes(), b"user work")
        self.assert_no_staging()

    def test_concurrent_output_during_backoff_is_not_removed(self):
        def occupy_output(delay):
            self.output.mkdir()
            (self.output / "keep.txt").write_bytes(b"user work")

        with patch.object(Path, "rename", autospec=True, side_effect=windows_denied()) as rename, patch("time.sleep", side_effect=occupy_output):
            with self.assertRaises((MigrationError, PermissionError)):
                write_new_tree(self.output, self.files)
        self.assertEqual(rename.call_count, 1)
        self.assertTrue(self.output.exists(), "The retry backoff must run before detecting concurrent output")
        self.assertEqual((self.output / "keep.txt").read_bytes(), b"user work")
        self.assert_no_staging()

    def test_file_exists_error_is_not_retried(self):
        failure = FileExistsError(errno.EEXIST, "Destination already exists")
        with patch.object(Path, "rename", autospec=True, side_effect=failure) as rename, patch("time.sleep") as sleep:
            with self.assertRaises(FileExistsError) as caught:
                write_new_tree(self.output, self.files)
        self.assertIs(caught.exception, failure)
        self.assertEqual(rename.call_count, 1)
        sleep.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assert_no_staging()


if __name__ == "__main__":
    unittest.main()
