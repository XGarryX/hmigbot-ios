"""Only a proven existence contradiction becomes unavailable, never guessed unsigned."""
from io import BytesIO
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
WRAPPER = ROOT / 'skills/hmos-fix-build-errors/scripts/check_signing.py'
MISSING = b'{"configured":false,"product_ref":false,"expired":false,"verdict":"unsigned","reason":"unsigned(build-profile.json5 not found)"}\n'


class SigningProbeWrapperTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='signing wrapper 空格 ')
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name)
        self.profile = self.project / 'build-profile.json5'
        self.profile.write_bytes(b'{"app":{"signingConfigs":[]}}\n')
        self.main = runpy.run_path(str(WRAPPER))['main']

    def invoke(self, args, stdout=MISSING, stderr=b'', code=0):
        output, error = BytesIO(), BytesIO()
        result = SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)
        with patch('sys.argv', [str(WRAPPER), *args]), patch('sys.stdout', SimpleNamespace(buffer=output)), \
                patch('sys.stderr', SimpleNamespace(buffer=error)), patch('subprocess.run', return_value=result) as run:
            returned = self.main()
        self.assertEqual(run.call_args.args[0][2:], args, 'Forward caller arguments unchanged')
        self.assertFalse(run.call_args.kwargs['shell'])
        self.assertNotIn('cwd', run.call_args.kwargs, 'Preserve the caller working directory')
        return returned, output.getvalue(), error.getvalue()

    def test_existing_profile_contradiction_is_unavailable_with_no_invented_fields(self):
        original = self.profile.read_bytes()
        read_text, read_bytes = Path.read_text, Path.read_bytes
        def no_profile_read(path, *args, **kwargs):
            self.assertNotEqual(path, self.profile, 'The wrapper must not parse profile contents')
            return read_text(path, *args, **kwargs)
        def no_profile_bytes(path, *args, **kwargs):
            self.assertNotEqual(path, self.profile, 'The wrapper must not read profile contents')
            return read_bytes(path, *args, **kwargs)
        with patch.object(Path, 'read_text', no_profile_read), patch.object(Path, 'read_bytes', no_profile_bytes):
            code, stdout, stderr = self.invoke([str(self.project)])
        value = json.loads(stdout)
        self.assertEqual((code, value['status'], value['verdict']), (3, 'unavailable', 'unverified'))
        self.assertEqual(set(value), {'status', 'verdict', 'reason'})
        self.assertNotIn(str(self.project).encode(), stdout + stderr)
        self.assertEqual(self.profile.read_bytes(), original)

    def test_genuine_missing_profile_preserves_exact_original_bytes(self):
        self.profile.unlink()
        self.assertEqual(self.invoke([str(self.project)], stderr=b'original warning\n'),
                         (0, MISSING, b'original warning\n'))

    def test_normal_signed_unsigned_other_reason_and_structured_values_are_unchanged(self):
        for stdout in (b' {"verdict":"signed","configured":true}\r\n',
                       b'{"verdict":"unsigned","reason":"no signing configured"}\n',
                       b'{"verdict":"signed","reason":"unsigned(build-profile.json5 not found)"}',
                       b'[]\n', b'null\n'):
            with self.subTest(stdout=stdout):
                self.assertEqual(self.invoke([str(self.project)], stdout=stdout), (0, stdout, b''))

    def test_nonzero_nonjson_and_nonutf8_output_preserve_stdout_stderr_and_exit(self):
        for code, stdout, stderr in ((7, MISSING, b'original failure\r\n'),
                                     (0, b'non JSON\r\n', b'warning'),
                                     (0, b'\xff\xfe\x00', b'\x80original stderr')):
            with self.subTest(code=code, stdout=stdout):
                self.assertEqual(self.invoke([str(self.project)], stdout, stderr, code), (code, stdout, stderr))

    def test_relative_space_path_and_current_cwd_contract(self):
        previous = Path.cwd()
        try:
            os.chdir(self.project.parent)
            self.assertEqual(self.invoke([self.project.name])[0], 3)
            os.chdir(self.project)
            self.assertEqual(self.invoke(['.'])[0], 3)
        finally:
            os.chdir(previous)

    def test_undocumented_file_input_and_no_argument_keep_original_semantics(self):
        self.assertEqual(self.invoke([str(self.profile)]), (0, MISSING, b''))
        self.assertEqual(self.invoke([]), (0, MISSING, b''))


if __name__ == '__main__':
    unittest.main()
