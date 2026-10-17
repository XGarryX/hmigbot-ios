"""Real compiled structural pipeline layout and non-mutation regressions."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.native_pipeline_runtime import HELPERS, VENDOR, _platform, invoke, runtime_layout


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def fixture(project):
    write(project / '.migbot/config.json', json.dumps({'source_platform': 'ios',
        'ios_harness': {'spec_contract_version': 2}}))
    write(project / 'build-profile.json5', json.dumps({'app': {'products': [{'name': 'default'}]},
        'modules': [{'name': 'entry', 'srcPath': './entry',
                     'targets': [{'name': 'default', 'applyToProducts': ['default']}]}]}))
    write(project / 'entry/src/main/module.json5', '{"module":{"name":"entry","type":"entry"}}')
    write(project / 'entry/src/main/ets/pages/Index.ets',
        "@Entry\n@ComponentV2\nstruct Index {\n build() {\n  Column() {\n   Image($r('app.media.icon'))\n    .width(24)\n    .height(24)\n   Text('visible')\n  }\n }\n}\n")
    write(project / 'spec/archive/template/entry/src/main/ets/pages/Historical.ets',
        "@ComponentV2\nstruct Historical { build() { Image($r('app.media.icon')) } }\n")
    write(project / 'spec/baseline/plans/feature-plan.md', '# Feature Plan\n')


class PipelineLayoutTests(unittest.TestCase):
    def test_all_six_helpers_are_original_bytes_and_image_entry_is_read_only(self):
        with runtime_layout() as (executable, env):
            scripts = executable.parent
            skills = scripts.parent.parent
            self.assertTrue(executable.is_file())
            system, architecture = _platform()
            original_bin = VENDOR / 'arkts-structural-closure/scripts/bin' / (system + '-' + architecture) / '_entry.dist' / executable.name
            self.assertEqual(executable.read_bytes(), original_bin.read_bytes())
            a2h_bin = Path('a2h-execute/scripts/bin') / (system + '-' + architecture) / '_entry.dist' / executable.name
            self.assertEqual((skills / a2h_bin).read_bytes(), (VENDOR / a2h_bin).read_bytes())
            self.assertEqual(env['ARKTS_SKILL_DIR'], str(scripts))
            for skill, names in HELPERS.items():
                for name in names:
                    self.assertEqual((skills / skill / 'scripts' / name).read_bytes(),
                                     (VENDOR / skill / 'scripts' / name).read_bytes())
            icon = (skills / 'arkts-icon-sizing/scripts/icon_autofix.py').read_text(encoding='utf-8')
            self.assertIn('native_icon_scope import autofix_main', icon)

    def test_actual_pipeline_executes_all_six_gates_and_keeps_source_bytes(self):
        with tempfile.TemporaryDirectory(prefix='pipeline-original-fixture-') as temporary:
            project = Path(temporary)
            fixture(project)
            before = {str(path.relative_to(project)): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in project.rglob('*.ets')}
            state = project / 'spec/execution/loops-final-structural-closure.json'
            output = project / 'result.json'
            result = invoke(['iterate', '--project-root', project, '--mode', 'pipeline',
                             '--target', 'final', '--state-file', state,
                             '--max-iter', 3, '--output-json', output])
            self.assertIn(result.returncode, (0, 1), result.stderr + result.stdout)
            reports = state.parent
            for detector in ('assembly', 'binding', 'deadshell', 'carrier', 'hittest', 'resname'):
                with self.subTest(detector=detector):
                    data = json.loads((reports / (detector + '-pipeline-iter0.json')).read_text(encoding='utf-8'))
                    self.assertFalse(data.get('skipped'), data)
                    self.assertNotIn(' absent', json.dumps(data, ensure_ascii=False))
            icon = json.loads((reports / 'icon-pipeline-iter0.json').read_text(encoding='utf-8'))
            self.assertEqual((icon['fixed_count'], icon['scanned']), (0, 1))
            self.assertFalse(icon['mutated'])
            self.assertEqual(before, {str(path.relative_to(project)): hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in project.rglob('*.ets')})
            current = json.loads(output.read_text(encoding='utf-8'))
            self.assertNotEqual(current['verdict'], 'CONVERGED', current)
            history = json.loads(state.read_text(encoding='utf-8'))['history'][0]
            detectors = {'assembly', 'audit', 'binding', 'carrier',
                'deadshell', 'hittest', 'icon', 'immersive', 'ledger', 'literal', 'orphans', 'resname', 'theme'}
            self.assertEqual(set(history['detectors_run']), detectors)
            self.assertEqual(set(history['detectors_effective']), detectors)
            self.assertEqual(history['detectors_skipped'], [])

    def test_actual_native_image_failure_is_not_mutated_or_converged(self):
        with tempfile.TemporaryDirectory(prefix='pipeline-image-failure-') as temporary:
            project = Path(temporary)
            fixture(project)
            page = project / 'entry/src/main/ets/pages/Index.ets'
            page.write_text(page.read_text(encoding='utf-8').replace('    .width(24)\n    .height(24)\n', ''), encoding='utf-8')
            original = page.read_bytes()
            state = project / 'spec/execution/loop.json'
            output = project / 'result.json'
            result = invoke(['iterate', '--project-root', project, '--mode', 'pipeline',
                             '--target', 'final', '--state-file', state, '--output-json', output])
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            icon = json.loads((state.parent / 'icon-pipeline-iter0.json').read_text(encoding='utf-8'))
            self.assertFalse(icon['passed'])
            self.assertGreater(icon['flagged_after'], 0)
            self.assertEqual(icon['fixed_count'], 0)
            self.assertEqual(page.read_bytes(), original)
            self.assertNotEqual(json.loads(output.read_text(encoding='utf-8'))['verdict'], 'CONVERGED')

    def test_original_finalizer_rejects_unconverged_state(self):
        with tempfile.TemporaryDirectory(prefix='pipeline-finalize-failure-') as temporary:
            project = Path(temporary)
            fixture(project)
            state = project / 'spec/execution/loop.json'
            invoke(['iterate', '--project-root', project, '--mode', 'pipeline',
                    '--target', 'final', '--state-file', state])
            result = invoke(['finalize', '--state-file', state, '--output-json', project / 'final.json'])
            self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
            final = json.loads((project / 'final.json').read_text(encoding='utf-8'))
            self.assertNotEqual(final.get('final_state'), 'PASS', final)

    @unittest.skipUnless(os.name == 'nt', 'Windows process ownership bridge')
    def test_owned_timeout_preserves_actual_partial_output_and_failure(self):
        error = subprocess.TimeoutExpired(['original'], 180, output=b'partial original stdout',
                                          stderr=b'partial original stderr')
        with patch('hmigbot_ios.native_pipeline_runtime.run_owned_process', side_effect=error):
            result = invoke(['finalize', '--state-file', 'missing.json'])
        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.stdout, 'partial original stdout')
        self.assertIn('partial original stderr', result.stderr)
        self.assertIn('timed out', result.stderr)


if __name__ == '__main__':
    unittest.main()
