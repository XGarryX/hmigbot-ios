"""Release-runner options must preserve tests and never purge an existing path."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('release_check_runner', ROOT / 'scripts/validate_release.py')
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class ReleaseCheckOptionsTests(unittest.TestCase):
    def invoke(self, *arguments, run=None):
        completed = subprocess.CompletedProcess([], 0, b'', b'')
        with patch.object(sys, 'argv', ['validate_release.py', *map(str, arguments)]), \
                patch.object(RUNNER.subprocess, 'run', side_effect=run, return_value=completed) as mocked, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                code = RUNNER.main()
            except SystemExit as exc:
                code = exc.code
        return code, mocked

    def test_custom_unit_timeout_and_fresh_short_temp_reach_pytest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            output, test_temp = base / 'evidence', base / 'short'
            code, mocked = self.invoke('--output', output, '--unit-timeout-seconds', 1800,
                                       '--test-temp', test_temp)
            self.assertNotEqual(code, 2, 'Valid release-runner options must be accepted')
            command = mocked.call_args_list[0]
            arguments = command.args[0]
            self.assertEqual(arguments[arguments.index('--basetemp') + 1], str(test_temp.resolve()))
            self.assertIn('tests', arguments)
            self.assertEqual(command.kwargs['timeout'], 1800)
            for check in mocked.call_args_list[1:]:
                self.assertEqual(check.kwargs['timeout'], 600)
            report = json.loads((output / 'release-checks.json').read_text(encoding='utf-8'))
            self.assertEqual(report['runner_options']['unit_timeout_seconds'], 1800)
            self.assertEqual(report['runner_options']['test_temp'], str(test_temp.resolve()))
            self.assertEqual(report['checks'][0]['timeout_seconds'], 1800)

    def test_default_unit_timeout_is_1800_and_default_temp_is_owned(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'evidence'
            code, mocked = self.invoke('--output', output)
            self.assertNotEqual(code, 2)
            self.assertEqual(mocked.call_args_list[0].kwargs['timeout'], 1800)
            report = json.loads((output / 'release-checks.json').read_text(encoding='utf-8'))
            self.assertEqual(report['runner_options']['test_temp'], str(output.resolve() / 'test-temp'))

    def test_timeout_bounds_reject_invalid_values_before_any_mutation(self):
        for value in ('0', '-1', '7201', '1.5', 'not-an-integer'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / 'evidence'
                code, mocked = self.invoke('--output', output, '--unit-timeout-seconds', value)
                self.assertEqual(code, 2)
                mocked.assert_not_called()
                self.assertFalse(output.exists())

    def test_existing_test_temp_is_rejected_and_contents_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            existing = base / 'user-data'
            existing.mkdir()
            marker = existing / 'keep.txt'
            marker.write_text('user content', encoding='utf-8')
            output = base / 'evidence'
            code, mocked = self.invoke('--output', output, '--test-temp', existing)
            self.assertEqual(code, 2)
            mocked.assert_not_called()
            self.assertEqual(marker.read_text(encoding='utf-8'), 'user content')
            self.assertFalse(output.exists())

    def test_drive_root_and_evidence_ancestor_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for test_temp, output in [(Path(base.anchor), base / 'evidence'),
                                      (base / 'new-parent', base / 'new-parent/evidence'),
                                      (base / 'same', base / 'same')]:
                with self.subTest(test_temp=test_temp):
                    code, mocked = self.invoke('--output', output, '--test-temp', test_temp)
                    self.assertEqual(code, 2)
                    mocked.assert_not_called()
                    self.assertFalse(output.exists())

    def test_timeout_failure_is_reported_with_its_actual_limit_and_output(self):
        calls = 0
        def run(arguments, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise subprocess.TimeoutExpired(arguments, kwargs['timeout'], output=b'partial unit output')
            return subprocess.CompletedProcess(arguments, 0, b'', b'')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'evidence'
            code, _ = self.invoke('--output', output, '--unit-timeout-seconds', 7200, run=run)
            self.assertNotEqual(code, 2)
            report = json.loads((output / 'release-checks.json').read_text(encoding='utf-8'))
            unit = report['checks'][0]
            self.assertFalse(unit['passed'])
            self.assertTrue(unit['timed_out'])
            self.assertEqual(unit['timeout_seconds'], 7200)
            self.assertEqual((output / 'unit-tests.stdout.log').read_bytes(), b'partial unit output')


if __name__ == '__main__':
    unittest.main()
