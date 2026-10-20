"""Supplied budgets stop real scheduler dispatch without preventing landing."""
import io
import os
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios import ios_scheduler as scheduler, native_pipeline, usage_budget as budget
from hmigbot_ios.core import MigrationError, digest, json_bytes, read_json, write_json
import test_ios_harness as harness_fixture


class UsageDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='usage-dispatch-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        _, self.project, self.graph = harness_fixture.fixture(self.root)
        self.output = 'entry/src/main/ets/pages/Counter.ets'
        request = self.root / 'request.json'
        write_json(request, {'schema_version': 2, 'wave': 'domains',
            'graph_sha256': digest(json_bytes(self.graph)), 'tasks': [{
                'id': 'counter', 'role': 'a2h-ios-converter', 'goal': 'Implement source counter',
                'ownership': [self.output], 'ac_ids': ['F001-AC01'],
                'fact_ids': [f['id'] for f in self.graph['facts']], 'parents': []}]})
        scheduler.generate(self.project, request)
        self.boot = patch.object(budget, '_boot_id', return_value='synthetic-dispatch-boot')
        self.boot.start()
        self.addCleanup(self.boot.stop)

    def start(self, name):
        ledger = self.project / 'spec/reports/derived' / name / 'usage-budget.json'
        budget.start(ledger, 'cuike', project_root=self.project)
        return ledger

    def record(self, ledger, raw):
        return budget.record(ledger, 'attempt-1', raw, run_id='cuike',
                             normalization_mode='unreported' if raw is None else 'openai_responses',
                             stage='convert', agent='remote-codex', provider='synthetic')

    def control_bytes(self):
        return {str(p.relative_to(self.project)): p.read_bytes()
                for p in (self.project / 'spec/state').rglob('*') if p.is_file()}

    def assert_refused_without_dispatch(self, ledger, run='cuike'):
        before = self.control_bytes()
        with patch.object(scheduler, 'invoke', wraps=scheduler.invoke) as original:
            with self.assertRaises((MigrationError, budget.BudgetError)):
                scheduler.step(self.project, 'domains', usage_ledger=ledger, usage_run_id=run)
            original.assert_not_called()
        self.assertEqual(before, self.control_bytes())
        self.assertFalse((self.project / 'spec/reports/ios-dispatch-domains.json').exists())

    def test_unknown_and_over_limit_do_not_mutate_original_control_state(self):
        for name, raw in [('unknown', None), ('over-limit', {'input_tokens': 19_900_001, 'output_tokens': 0})]:
            with self.subTest(name=name):
                ledger = self.start(name)
                self.record(ledger, raw)
                self.assert_refused_without_dispatch(ledger)

    def test_finished_elapsed_and_wrong_identity_do_not_dispatch(self):
        finished = self.start('finished')
        budget.finish(finished, run_id='cuike')
        self.assert_refused_without_dispatch(finished)
        ledger = self.start('elapsed')
        clock = read_json(ledger)['clock']
        with patch.object(budget, '_clock', return_value=(clock['start_wall'] + 7201, clock['start_mono'] + 7201)):
            self.assert_refused_without_dispatch(ledger)
        self.assert_refused_without_dispatch(self.start('wrong-run'), run='another-run')
        wrong_project = self.start('wrong-project')
        data = read_json(wrong_project)
        data['project_root'] = str(self.project.parent)
        write_json(wrong_project, data)
        self.assert_refused_without_dispatch(wrong_project)

    def test_live_budget_dispatches_and_over_limit_work_can_still_land(self):
        ledger = self.start('live')
        self.record(ledger, {'input_tokens': 100, 'output_tokens': 20})
        action, code = scheduler.step(self.project, 'domains', usage_ledger=ledger, usage_run_id='cuike')
        self.assertEqual((code, action['action']), (0, 'dispatch'))
        self.assertEqual(action['usage_budget']['total_tokens'], 120)
        self.assertTrue(action['usage_budget']['can_continue'])
        budget.record(ledger, 'attempt-2', {'input_tokens': 20_000_000, 'output_tokens': 0},
                      run_id='cuike', normalization_mode='openai_responses', stage='convert',
                      agent='remote-codex', provider='synthetic')
        target = self.project / self.output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('export class Counter {}', encoding='utf-8')
        write_json(self.project / action['batch'][0]['result_path'], {
            'ios_receipt_version': 2, 'source_sha256': self.graph['source_sha256'],
            'plan_sha256': digest((self.project / 'spec/waves/plan-domains.json').read_bytes()),
            'task_id': 'counter', 'status': 'generated', 'behavior_verified': False,
            'file_hashes': {self.output: digest(target.read_bytes())}, 'ac_ids': ['F001-AC01'],
            'findings': [], 'final_state': 'PASS', 'task': 'counter', 'files_touched': [self.output],
            'files': [self.output], 'fixed': [], 'unresolved': [], 'domain': 'counter', 'skipped': []})
        landed, code = scheduler.step(self.project, 'domains', landing=True)
        self.assertEqual(code, 0, landed)
        self.assertFalse(landed['behavior_verified'])

    def test_public_cli_requires_pair_and_uses_selected_run(self):
        ledger = self.start('cli')
        self.record(ledger, None)
        for options in [('--usage-ledger', str(ledger)), ('--usage-run-id', 'cuike'),
                        ('--usage-ledger', str(ledger), '--usage-run-id', 'cuike')]:
            with self.subTest(options=options), redirect_stdout(io.StringIO()) as output:
                code = native_pipeline.main(['next-batch', '--project', str(self.project), *options])
                self.assertEqual(code, 2, output.getvalue())
        self.assertFalse((self.project / 'spec/reports/ios-dispatch-domains.json').exists())


if __name__ == '__main__':
    unittest.main()
