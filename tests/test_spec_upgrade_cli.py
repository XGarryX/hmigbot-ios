"""Exercise upgrade and read-only harness behavior through the actual CLI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import read_json, write_json
from hmigbot_ios.native_pipeline import configure
from hmigbot_ios.ios_harness import initialize
from hmigbot_ios.spec_upgrade import inspect
from spec_contract_fixture import complete_contract


class SpecUpgradeCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='spec-upgrade-cli-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'; self.source.mkdir()
        self.project = self.root / 'target'; self.project.mkdir()
        (self.source / 'Counter.swift').write_text('import SwiftUI\nstruct Counter: View {\n    @State var count = 0\n    var body: some View {\n        VStack {\n            Text("Count")\n            Button("Add") { count += 1 }\n        }\n    }\n}\n', encoding='utf-8')
        configure(self.source, self.project); initialize(self.project); complete_contract(self.project)
        self.feature = self.project / 'spec/baseline/features/F001-counter.md'

    def command(self, *arguments):
        return subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'scripts/a2h_ios.py'),
            *map(str, arguments)], cwd=self.root, capture_output=True, text=True, encoding='utf-8', timeout=60)

    def upgrade(self, *arguments):
        return self.command('spec-upgrade', '--project', self.project, *arguments)

    def files(self):
        return {p.relative_to(self.project).as_posix(): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}

    def report(self):
        self.feature.write_text(self.feature.read_text(encoding='utf-8').replace('标:CounterPage.add', '标:add'), encoding='utf-8')
        report = inspect(self.project)
        path = self.project / 'spec/reports/spec-upgrade.json'
        write_json(path, report)
        return path, report

    def test_diagnose_stdout_is_zero_write_even_when_profile_two_has_findings(self):
        before = self.files()
        result = self.upgrade()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'diagnostic_requires_review')
        self.assertEqual(report['profile_diagnostics']['2']['status'], 'FAIL')
        self.assertEqual(self.files(), before)

    def test_diagnose_explicit_report_path_preserves_every_existing_file(self):
        before = self.files()
        output = self.project / 'spec/reports/spec-upgrade.json'
        result = self.upgrade('--output', output)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        report = read_json(output)
        self.assertEqual(report['status'], 'diagnostic_requires_review')
        after = self.files(); del after['spec/reports/spec-upgrade.json']
        self.assertEqual(after, before)

    def test_output_cannot_overwrite_baseline_control_or_external_file(self):
        before = self.files()
        for output in (self.feature, self.project / 'spec/.a2h/open-findings.json',
                       self.root / 'outside.json', self.project / 'spec/reports'):
            with self.subTest(output=output):
                result = self.upgrade('--output', output)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.files(), before)
        self.assertFalse((self.root / 'outside.json').exists())

    def test_diagnose_cannot_include_apply_selection(self):
        before = self.files()
        for arguments in (('--patch', 'UP-' + '0' * 20), ('--all-candidates',)):
            with self.subTest(arguments=arguments):
                result = self.upgrade(*arguments)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.files(), before)

    def test_apply_requires_selection_and_rejects_conflicting_selectors(self):
        path, report = self.report()
        before = self.files(); ident = report['patches'][0]['patch_id']
        for arguments in ((), ('--patch', ident, '--all-candidates'), ('--all-candidates', '--output', self.project / 'spec/reports/applied.json')):
            with self.subTest(arguments=arguments):
                result = self.upgrade('--apply', path, *arguments)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.files(), before)

    def test_apply_selected_current_patch_preserves_profile_and_all_other_files(self):
        path, report = self.report()
        before = self.files()
        ident = report['patches'][0]['patch_id']
        result = self.upgrade('--apply', path, '--patch', ident)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        applied = json.loads(result.stdout)
        self.assertEqual(applied['status'], 'applied_requires_review')
        self.assertEqual(applied['applied_patch_ids'], [ident])
        self.assertFalse(applied['behavior_verified'])
        self.assertIn('标:CounterPage.add', self.feature.read_text(encoding='utf-8'))
        after = self.files(); del before['spec/baseline/features/F001-counter.md']; del after['spec/baseline/features/F001-counter.md']
        self.assertEqual(after, before)
        self.assertEqual(read_json(self.project / '.migbot/config.json')['ios_harness']['spec_contract_version'], 1)

    def test_apply_all_candidates_is_an_explicit_selection(self):
        path, report = self.report()
        result = self.upgrade('--apply', path, '--all-candidates')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)['applied_patch_ids'], [p['patch_id'] for p in report['patches']])

    def test_unknown_or_repeated_patch_is_rejected_before_writes(self):
        path, report = self.report(); ident = report['patches'][0]['patch_id']
        before = self.files()
        for arguments in (('--patch', 'UP-' + '0' * 20), ('--patch', ident, '--patch', ident)):
            with self.subTest(arguments=arguments):
                result = self.upgrade('--apply', path, *arguments)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.files(), before)

    def test_stale_source_refuses_apply_without_target_changes(self):
        path, report = self.report()
        (self.source / 'Counter.swift').write_text('struct Changed {}\n', encoding='utf-8')
        before = self.files()
        result = self.upgrade('--apply', path, '--all-candidates')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.files(), before)

    def test_source_harness_report_only_keeps_existing_findings_and_reports(self):
        from test_ios_harness import fixture
        from hmigbot_ios.native_pipeline import findings_module
        root = self.root / 'harness'; root.mkdir()
        _, project, _ = fixture(root)
        queue = findings_module()
        queue.replace_section(str(project), 'spec.ios-harness', [queue.make('IOS.SENTINEL', 'spec', 'preserve', 'Existing finding')])
        before = {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob('*') if p.is_file()}
        result = self.command('source-check', '--project', project, '--harness', '--report-only')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(json.loads(result.stdout)['behavior_verified'])
        after = {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob('*') if p.is_file()}
        self.assertEqual(after, before)

    def test_failing_source_harness_report_only_is_nonzero_and_still_zero_write(self):
        from test_ios_harness import fixture
        root = self.root / 'failing-harness'; root.mkdir()
        _, project, _ = fixture(root)
        feature = project / 'spec/baseline/features/F001-counter.md'
        feature.write_text(feature.read_text(encoding='utf-8').replace('标:CounterPage.add', '标:MissingOwner.add'), encoding='utf-8')
        before = {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob('*') if p.is_file()}
        result = self.command('source-check', '--project', project, '--harness', '--report-only')
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)['status'], 'FAIL')
        after = {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob('*') if p.is_file()}
        self.assertEqual(after, before)

    def test_all_candidates_cannot_turn_an_empty_proposal_into_success(self):
        report = inspect(self.project)
        self.assertFalse(report['patches'])
        path = self.project / 'spec/reports/spec-upgrade.json'; write_json(path, report)
        before = self.files()
        result = self.upgrade('--apply', path, '--all-candidates')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.files(), before)


if __name__ == '__main__':
    unittest.main()
