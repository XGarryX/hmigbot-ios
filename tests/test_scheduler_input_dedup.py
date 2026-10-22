"""Task contracts share immutable inputs; verify bytes once per step, not per ref."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from hmigbot_ios.core import MigrationError, digest, json_bytes, write_json
from hmigbot_ios.ios_scheduler import step


class FactGateReached(Exception):
    """Stop after input validation without replacing any original state writer."""


class SchedulerInputDedupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ios-input-dedup-')
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.source = self.project / 'source'
        self.source.mkdir()
        self.shared = self.project / 'spec/baseline/shared.md'
        self.shared.parent.mkdir(parents=True)
        self.shared.write_bytes(b'# Shared\nsource behavior\n')
        self.expected = digest(self.shared.read_bytes())
        self.plan = {'ios_adapter_version': 2, 'wave': 'domains', 'tasks': []}
        write_json(self.project / 'spec/waves/plan-domains.json', self.plan)

    def ref(self, *, path='spec/baseline/shared.md', expected=None, heading='Shared'):
        return {'path': path, 'sha256': self.expected if expected is None else expected,
                'heading': heading}

    def invoke_to_fact_gate(self, inputs):
        write_json(self.project / 'spec/blueprint/contracts.json', {
            'task_inputs': inputs, 'prompt_hashes': {},
            'plan_identity_sha256': digest(json_bytes(self.plan)),
        })
        with patch('hmigbot_ios.native_pipeline.context', return_value=(self.source, self.project)), \
                patch('hmigbot_ios.plan_contract.assert_pinned'), \
                patch('hmigbot_ios.ios_scheduler.validate_graph', side_effect=FactGateReached):
            return step(self.project, 'domains')

    def test_two_hundred_shared_heading_refs_read_the_file_once(self):
        inputs = {f'task-{index}': [self.ref(), self.ref(heading='Other')]
                  for index in range(100)}
        reads = []
        original = Path.read_bytes

        def read_bytes(path):
            if path == self.shared:
                reads.append(path)
            return original(path)

        with patch.object(Path, 'read_bytes', read_bytes), self.assertRaises(FactGateReached):
            self.invoke_to_fact_gate(inputs)
        self.assertEqual(len(reads), 1, 'Shared contract bytes must be hashed once per step')

    def test_conflicting_expected_hashes_are_rejected_before_reading_any_input(self):
        inputs = {'first': [self.ref()], 'second': [self.ref(expected='0' * 64)]}
        reads = []
        original = Path.read_bytes

        def read_bytes(path):
            if path == self.shared:
                reads.append(path)
            return original(path)

        with patch.object(Path, 'read_bytes', read_bytes), \
                self.assertRaisesRegex(MigrationError, 'Conflicting.*hash'):
            self.invoke_to_fact_gate(inputs)
        self.assertEqual(reads, [], 'Check conflicting claims before content validation')

    def test_wrong_hash_is_still_rejected(self):
        with self.assertRaisesRegex(MigrationError, 'Pinned task contract input changed'):
            self.invoke_to_fact_gate({'task': [self.ref(expected='0' * 64)]})

    def test_missing_input_is_still_rejected(self):
        self.shared.unlink()
        with self.assertRaises((MigrationError, FileNotFoundError)):
            self.invoke_to_fact_gate({'task': [self.ref()]})

    def test_every_reference_is_path_checked_even_after_a_valid_reference(self):
        for path in ['../shared.md', 'spec/baseline/../baseline/shared.md', '/shared.md']:
            with self.subTest(path=path), self.assertRaises(MigrationError):
                self.invoke_to_fact_gate({'first': [self.ref()], 'second': [self.ref(path=path)]})

    def test_same_size_and_mtime_content_change_is_rejected_on_the_next_step(self):
        inputs = {'task': [self.ref(), self.ref()]}
        with self.assertRaises(FactGateReached):
            self.invoke_to_fact_gate(inputs)
        old = self.shared.stat()
        self.shared.write_bytes(b'# Shared\nchanged content\n')
        self.assertEqual(self.shared.stat().st_size, old.st_size)
        os.utime(self.shared, ns=(old.st_atime_ns, old.st_mtime_ns))
        with self.assertRaisesRegex(MigrationError, 'Pinned task contract input changed'):
            self.invoke_to_fact_gate(inputs)

    def test_distinct_inputs_are_both_validated(self):
        other = self.project / 'spec/baseline/other.md'
        other.write_bytes(b'# Other\nnot the pinned content\n')
        with self.assertRaisesRegex(MigrationError, 'Pinned task contract input changed: spec/baseline/other.md'):
            self.invoke_to_fact_gate({'task': [self.ref(), self.ref(path='spec/baseline/other.md')]})


if __name__ == '__main__':
    unittest.main()
