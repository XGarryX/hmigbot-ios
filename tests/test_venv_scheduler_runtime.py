"""A Windows venv redirector must never be copied as the staged interpreter."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import MigrationError
from hmigbot_ios.windows_python_runtime import base_python_executable, stage_base_python


class BaseInterpreterSelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='base-python-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.base = self.root / 'base'
        self.venv = self.base / 'nested-venv'
        self.launcher = self.venv / 'Scripts/python.exe'
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_bytes(b'venv redirector')
        (self.venv / 'pyvenv.cfg').write_text('home=base')
        self.executable = self.base / 'python.exe'
        self.executable.write_bytes(b'real base interpreter')
        for name, value in [('prefix', str(self.venv)), ('base_prefix', str(self.base)),
                            ('executable', str(self.launcher)), ('_base_executable', str(self.executable))]:
            patcher = patch.object(sys, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_uses_runtime_base_and_falls_back_only_to_same_base_install(self):
        self.assertEqual(base_python_executable(), self.executable)
        with patch.object(sys, '_base_executable', None):
            self.assertEqual(base_python_executable(), self.executable)
        with patch.object(sys, '_base_executable', str(self.launcher)):
            self.assertEqual(base_python_executable(), self.executable)

    def test_missing_base_never_falls_back_to_venv_or_path_python(self):
        self.executable.unlink()
        with patch.object(sys, '_base_executable', str(self.launcher)):
            with self.assertRaisesRegex(MigrationError, 'refusing.*virtual-environment launcher'):
                base_python_executable()

    def test_outside_base_candidate_is_not_used(self):
        outside = self.root / 'other-python.exe'
        outside.write_bytes(b'unrelated installation')
        self.executable.unlink()
        with patch.object(sys, '_base_executable', str(outside)):
            with self.assertRaises(MigrationError):
                base_python_executable()


@unittest.skipUnless(os.name == 'nt', 'Windows executable staging')
class StagedInterpreterProcessTests(unittest.TestCase):
    def test_real_base_aliases_start_in_disposable_directory_without_pyvenv_cfg(self):
        with tempfile.TemporaryDirectory(prefix='staged-python-') as temporary:
            directory = Path(temporary)
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
            selected = stage_base_python(directory, env)
            self.assertTrue(selected.is_relative_to(Path(sys.base_prefix).resolve()))
            self.assertFalse((directory / 'pyvenv.cfg').exists())
            probe = ('import json,sys,encodings; print(json.dumps({"version":list(sys.version_info[:2]),'
                     '"prefix":sys.prefix,"base_prefix":sys.base_prefix}))')
            for alias in ('python.exe', 'python3.exe'):
                result = subprocess.run([str(directory / alias), '-c', probe], cwd=directory,
                                        env=env, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
                observed = json.loads(result.stdout)
                self.assertEqual(observed['version'], list(sys.version_info[:2]))
                self.assertEqual(Path(observed['base_prefix']).resolve(), Path(sys.base_prefix).resolve())

    @unittest.skipUnless(sys.prefix != sys.base_prefix, 'requires invocation through a real venv')
    def test_old_copied_launcher_reproduces_pyvenv_cfg_failure(self):
        if Path(sys.executable).read_bytes() == base_python_executable().read_bytes():
            self.skipTest('this venv uses the real interpreter instead of a redirector')
        with tempfile.TemporaryDirectory(prefix='copied-venv-launcher-') as temporary:
            alias = Path(temporary) / 'python.exe'
            shutil.copy2(sys.executable, alias)
            env = dict(os.environ, PYTHONHOME=sys.base_prefix, PYTHONUTF8='1')
            result = subprocess.run([str(alias), '-c', 'print("must not run")'],
                                    cwd=temporary, env=env, capture_output=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'pyvenv.cfg', result.stderr)


if __name__ == '__main__':
    unittest.main()
