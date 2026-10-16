"""Page reports use current landed outputs and individual observations, never a global PASS."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import MigrationError, digest, json_bytes, read_json, write_json
from hmigbot_ios.ios_scheduler import generate, step
from hmigbot_ios import quality_views as views
from test_ios_harness import fixture


class PageEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source, self.project, self.graph = fixture(self.root)
        self.output = 'entry/src/main/ets/pages/CounterPage.ets'
        (self.project / 'spec/baseline/ui-manifest.md').write_text(
            '# UI\n## 全局约定\nOne counter page.\n\n'
            '| page_id | 目标文件 | 功能 |\n|---|---|---|\n'
            '| page_0001 | ' + self.output + ' | F001 |\n', encoding='utf-8')

    def dispatch(self):
        request = self.root / 'request.json'
        write_json(request, {'schema_version': 2, 'wave': 'domains',
            'graph_sha256': digest(json_bytes(self.graph)), 'tasks': [{
                'id': 'counter', 'role': 'a2h-ios-converter', 'goal': 'Implement counter',
                'ownership': [self.output], 'ac_ids': ['F001-AC01'],
                'fact_ids': [f['id'] for f in self.graph['facts']], 'parents': []}]})
        generate(self.project, request)
        action, code = step(self.project, 'domains'); self.assertEqual(code, 0)
        task = action['batch'][0]
        target = self.project / self.output; target.parent.mkdir(parents=True)
        target.write_text('export class CounterPage { count:number=0; add():void { this.count+=1; } }')
        self.receipt = self.project / task['result_path']
        write_json(self.receipt, {'ios_receipt_version': 2, 'source_sha256': self.graph['source_sha256'],
            'plan_sha256': digest((self.project / 'spec/waves/plan-domains.json').read_bytes()),
            'task_id': 'counter', 'status': 'generated', 'behavior_verified': False,
            'file_hashes': {self.output: digest(target.read_bytes())}, 'ac_ids': ['F001-AC01'],
            'findings': [], 'final_state': 'PASS', 'task': 'counter', 'files_touched': [self.output],
            'files': [self.output], 'fixed': [], 'unresolved': [], 'domain': 'counter', 'skipped': []})

    def page(self, **kwargs):
        return views.summary(self.project, **kwargs)['pages'][0]

    def test_no_evidence_has_explicit_page_axes(self):
        page = self.page()
        self.assertEqual(page['page_id'], 'page_0001')
        self.assertEqual(page['axes']['generation']['status'], 'not_run')
        self.assertEqual(page['axes']['behavior']['status'], 'not_run')
        self.assertEqual(page['ac_ids'], ['F001-AC01'])

    def test_receipt_presence_is_not_landed_generation(self):
        self.dispatch()
        self.assertEqual(self.page()['axes']['generation']['status'], 'unlanded')

    def test_original_landing_and_current_hashes_are_required(self):
        self.dispatch(); landed, code = step(self.project, 'domains', landing=True)
        self.assertEqual(code, 0, landed)
        page = self.page()
        self.assertEqual(page['axes']['generation']['status'], 'generated')
        self.assertEqual(page['task_ids'], ['counter'])
        self.assertEqual(page['axes']['behavior']['status'], 'not_run')
        (self.project / self.output).write_text('changed')
        self.assertEqual(self.page()['axes']['generation']['status'], 'stale')

    def test_edited_pinned_plan_cannot_keep_generated_page(self):
        self.dispatch(); step(self.project, 'domains', landing=True)
        plan = self.project / 'spec/waves/plan-domains.json'; data = read_json(plan)
        data['tasks'][0]['ownership'] = ['entry/Other.ets']; write_json(plan, data)
        self.assertEqual(self.page()['axes']['generation']['status'], 'stale')

    def test_report_render_is_deterministic_current_and_readonly(self):
        report = views.summary(self.project)
        before = {p: p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        rendered = views.render_report(report)
        self.assertIn('page_0001', rendered)
        self.assertIn('F001-AC01', rendered)
        self.assertTrue(views.validate_report(self.project, rendered))
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        with self.assertRaises(MigrationError):
            views.validate_report(self.project, rendered.replace('not_run', 'passed'))
        page = self.project / 'spec/baseline/ui/page_0001_Counter.md'
        page.write_text(page.read_text(encoding='utf-8') + '\nSource review corrected\n', encoding='utf-8')
        with self.assertRaises(MigrationError): views.validate_report(self.project, rendered)

    def test_page_behavior_uses_only_its_own_observed_ac(self):
        from hmigbot_ios.behavior import verify
        from hmigbot_ios.ios_harness import ac_inventory
        base = self.project / 'spec/baseline'
        (base / 'features/F001-counter.md').write_text(
            '# F001\n' + ''.join(f'- [ ] F001-AC0{i} Value {i} `判:unit | Expected {i}`\n' for i in (1, 2, 3)), encoding='utf-8')
        for number in (2, 3):
            (base / f'ui/page_000{number}_Other.md').write_text(f'# Page {number}\nF001-AC0{number}\n', encoding='utf-8')
        target = self.project / 'counter.py'; target.write_text('def add():\n    return 1\nprint(add())\n')
        node = {'path': 'counter.py', 'line': 1, 'symbol': 'add', 'sha256': digest(target.read_bytes())}
        events = [f for f in self.graph['facts'] if f['kind'] == 'event']
        write_json(self.project / 'spec/verification/ios-behavior.json', {
            'schema_version': 2, 'source_sha256': self.graph['source_sha256'],
            'chains': [{'source_fact': f['id'], **{k: node for k in ('input', 'processing', 'feedback')},
                'review': {'status': 'reviewed', 'reviewer': 'independent-source-reader'}} for f in events],
            'cases': [{'id': f'case{i}', 'ac_ids': [f'F001-AC0{i}'], 'runner': 'unit',
                'oracle': {'source_fact': events[0]['id'], 'expected': i, 'reviewer': 'independent-source-reader'},
                'target_hashes': {'counter.py': digest(target.read_bytes())}, 'command': [sys.executable, 'counter.py']}
                for i in (1, 2)]})
        result, code = verify(self.project, self.source, self.graph, ac_inventory(self.project), run=True)
        self.assertEqual(code, 2, result)
        report = views.summary(self.project)
        self.assertEqual(report['axes']['behavior']['status'], 'failed')
        self.assertEqual([p['axes']['behavior']['status'] for p in report['pages']], ['passed', 'failed', 'unverified'])
        observation = self.project / 'spec/reports/ios-behavior-check.json'
        edited = read_json(observation); edited['observations'].append(dict(edited['observations'][0]))
        write_json(observation, edited)
        self.assertNotEqual(views.summary(self.project)['pages'][0]['axes']['behavior']['status'], 'passed')

    def test_cli_report_and_readonly_harness(self):
        from hmigbot_ios.native_pipeline import main
        path = self.project / 'spec/migration-report.md'
        with redirect_stdout(StringIO()):
            self.assertEqual(main(['migration-report', '--project', str(self.project), '--output', str(path)]), 0)
            self.assertEqual(main(['migration-report', '--project', str(self.project), '--check', str(path)]), 0)
        before = {p: p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        with redirect_stdout(StringIO()):
            self.assertEqual(main(['source-check', '--harness', '--report-only', '--project', str(self.project)]), 0)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_summary_schema_is_enforced_by_report_consumer(self):
        report = views.summary(self.project)
        report['pages'][0]['axes']['behavior']['status'] = 'looks-good-to-me'
        with self.assertRaises(MigrationError): views.render_report(report)

    def test_derived_outputs_cannot_overwrite_execution_evidence(self):
        from hmigbot_ios.native_pipeline import main
        for command, relative in [('migration-report', 'spec/reports/behavior/new.md'),
                                  ('migration-report', 'spec/reports/visual-verify-report.md'),
                                  ('spec-summary', 'spec/reports/ios-behavior-check.json'),
                                  ('spec-upgrade', 'spec/reports/ios-behavior-check.json')]:
            path = self.project / relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('keep original evidence', encoding='utf-8')
            with self.subTest(command=command, path=relative), redirect_stdout(StringIO()):
                self.assertEqual(main([command, '--project', str(self.project), '--output', str(path)]), 2)
                self.assertEqual(path.read_text(encoding='utf-8'), 'keep original evidence')
            path.unlink()


if __name__ == '__main__': unittest.main()
