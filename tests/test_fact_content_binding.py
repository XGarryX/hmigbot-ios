"""A cached file read must match its snapshot even across a real A -> B -> A edit."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios import ios_facts
from hmigbot_ios.core import MigrationError, digest


class FactContentBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir='D:/Temp' if os.name == 'nt' else None,
                                                prefix='fact-content-binding-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def switching_read(self, file, initial, transient):
        """Switch the actual file only for the cache read; both snapshots see A."""
        original = Path.read_bytes
        reads = []
        def read(path):
            if path == file:
                reads.append(path)
                if len(reads) == 2:  # initial snapshot, then _FileViews
                    file.write_bytes(transient)
                    try:
                        return original(path)
                    finally:
                        file.write_bytes(initial)
            return original(path)
        return patch.object(Path, 'read_bytes', read), reads

    def test_transient_content_rejected_before_refresh_can_replace_published_evidence(self):
        source, project = self.root / 'source', self.root / 'project'
        source.mkdir()
        project.mkdir()
        file = source / 'Counter.swift'
        initial = b'struct Counter { var count = 1 }\n'
        file.write_bytes(initial)
        previous = ios_facts.refresh(project, source)
        baseline = project / 'spec/baseline/ios-facts.json'
        obligations = project / 'spec/baseline/ios-obligations.json'
        before = baseline.read_bytes(), obligations.read_bytes()
        switch, reads = self.switching_read(file, initial, initial.replace(b'= 1', b'= 2'))
        with switch:
            with self.assertRaisesRegex(MigrationError, 'Source content changed.*Counter.swift'):
                ios_facts.refresh(project, source)
        self.assertEqual(len(reads), 2)
        self.assertEqual(file.read_bytes(), initial)
        self.assertEqual((baseline.read_bytes(), obligations.read_bytes()), before)
        self.assertEqual(next(f for f in previous['facts'] if f['kind'] == 'state')['value']['initializer'], '1')

    def test_storyboard_and_binary_resource_reads_are_bound_before_decode_or_fallback(self):
        for name, initial, transient in (
            ('Main.storyboard', b'<document><action id="first"/></document>\n',
             b'<document><action id="other"/></document>\n'),
            ('Info.plist', b'\xff\xfe initial binary\n', b'\xff\xfe changed binary\n'),
        ):
            with self.subTest(name=name):
                source = self.root / name
                source.mkdir()
                project = self.root / (name + '-project')
                project.mkdir()
                file = source / name
                file.write_bytes(initial)
                switch, reads = self.switching_read(file, initial, transient)
                with switch:
                    with self.assertRaisesRegex(MigrationError, 'Source content changed'):
                        ios_facts.refresh(project, source)
                self.assertEqual(len(reads), 2)
                self.assertEqual(file.read_bytes(), initial)
                self.assertFalse((project / 'spec/baseline/ios-facts.json').exists())

    def test_verified_token_text_and_snippet_lines_share_one_read_and_hash(self):
        file = self.root / 'Counter.swift'
        initial = b'struct Counter {\r\n    var count = 1\r\n}\r\n'
        file.write_bytes(initial)
        expected_hash = digest(initial)
        views = ios_facts._FileViews()
        original_read = Path.read_bytes
        with patch.object(Path, 'read_bytes', autospec=True, side_effect=original_read) as reads, \
                patch.object(ios_facts, 'digest', wraps=digest) as hashes:
            text = views.text('Counter.swift', file, expected_hash)
            file.write_bytes(initial.replace(b'= 1', b'= 2'))
            lines = views.lines('Counter.swift', file, expected_hash)
            self.assertEqual(lines, text.splitlines())
            self.assertIn('count = 1', lines[1])
            self.assertEqual(reads.call_count, 1)
            self.assertEqual(hashes.call_count, 1)
            self.assertEqual(hashes.call_args.args, (initial,))

    def test_new_expected_hash_does_not_reuse_a_previous_verified_view(self):
        file = self.root / 'Counter.swift'
        initial = b'struct Counter { var count = 1 }\n'
        changed = initial.replace(b'= 1', b'= 2')
        file.write_bytes(initial)
        views = ios_facts._FileViews()
        self.assertIn('count = 1', views.text('Counter.swift', file, digest(initial)))
        with self.assertRaisesRegex(MigrationError, 'Source content changed'):
            views.text('Counter.swift', file, digest(changed))
        file.write_bytes(changed)
        self.assertIn('count = 2', views.text('Counter.swift', file, digest(changed)))


if __name__ == '__main__':
    unittest.main()
