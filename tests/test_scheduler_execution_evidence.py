"""Execution ownership ignores named evidence, never arbitrary project files."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))

from hmigbot_ios.core import EXCLUDED, MigrationError, digest, json_bytes, read_json, write_json
from hmigbot_ios.ios_scheduler import execution_files, baseline_inputs, generate, step, replan
import test_plan_contract as plan_fixture
import test_ios_harness as harness_fixture


class ExecutionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = plan_fixture.PlanContractTests('test_valid_explicit_merge_and_transitive_consumer')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.project = self.fixture.project

    def put(self, path, content='execution evidence\n'):
        target = self.project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')

    def test_named_pipeline_and_execution_evidence_are_not_product_changes(self):
        before = execution_files(self.project)
        source_exclusions = set(EXCLUDED)
        for path in [
            'work/pipeline-20261017/run.py',
            'work/pipeline-20261017/support/check-domain.mjs',
            'work/pipeline-20261017/calls/20261017T021327973146-945af9.json',
            'work/pipeline-20261017/calls/20261017T021327973146-945af9.stdout.log',
            'work/pipeline-20261017/calls/20261017T021327973146-945af9.stderr.log',
            'spec/pipeline-run-20261017.md',
            'spec/execution/briefs/group_01_brief.md',
            'spec/execution/writeback/writeback-group-01.json',
            'spec/execution/writeback/writeback-base-06.5.json',
            'spec/execution/writeback/writeback-base-06_5.json',
            'spec/execution/autofix-log/round-1/loops-final-structural-closure.json',
            'spec/execution/autofix-log/round-1/audit-final-iter1.json',
            'spec/execution/source-understanding/F001-source-notes.md',
            'spec/execution/base-contracts.md',
            'spec/execution/capability-manifest.json',
            'spec/execution/autofix-log/round-1/loop-state-pipeline-final.json',
            'spec/execution/autofix-log/round-1/loop-result-latest-pipeline-final.json',
            'spec/execution/autofix-log/round-1/capability-manifest.json',
            'spec/reports/product-literals.json',
            'spec/reports/visual-verify-report.md',
            'spec/reports/derived/round-1/spec-summary.json',
            'spec/reports/host-oracle/adapter.mjs',
            'spec/reports/host-oracle/observations.json',
            'spec/reports/host-oracle/AppRouter.cjs',
            'spec/reports/host-oracle/BrewDomain.cjs',
            'spec/reports/host-oracle/BrewModels.cjs',
            'spec/reports/host-oracle/BrewStore.cjs',
            'spec/reports/host-oracle/compile-target.cjs',
            'spec/reports/host-oracle/run-foundation.cjs',
            'spec/reports/host-oracle/run-unicode.cjs',
            'spec/execution/autofix-log/round-18/native-pipeline-dispositions-iter0.json',
            'spec/execution/autofix-log/round-18/native-pipeline-dispositions-iter1.json',
            'spec/execution/autofix-log/round-18/native-pipeline-raw/loop-state-pipeline-final-iter0-f868b7e4576547a6947ded2660584571/assembly-pipeline-iter0.json',
            'spec/execution/autofix-log/round-18/native-pipeline-raw/loop-state-pipeline-final-iter0-f868b7e4576547a6947ded2660584571/audit-pipeline-iter0.json',
            'spec/execution/autofix-log/round-18/native-pipeline-raw/loop-state-pipeline-final-iter0-f868b7e4576547a6947ded2660584571/theme-pipeline-iter0.json',
            'spec/execution/autofix-log/round-18/native-pipeline-raw/loop-state-pipeline-final-iter0-f868b7e4576547a6947ded2660584571/result.json',
            'spec/execution/autofix-log/round-18/native-pipeline-raw/loop-state-pipeline-final-iter0-f868b7e4576547a6947ded2660584571/state.json',
            'spec/execution/autofix-log/round-18/native-pipeline-raw/loop-state-pipeline-final-iter1-b1820a60b0934c0fb379e7880a844650/hittest-pipeline-iter0.json',
            'spec/reports/static-runtime/land-counter.json',
            'spec/waves/wave-domains.result.json',
            'work/pipeline-20261017/support/states/host-oracle-state.json',
            'spec/.a2h/open-findings.json',
            'spec/.a2h/impl-claims.json',
            'spec/migration-report.md',
            'build_out.log',
            'build_temp.bat',
        ]:
            self.put(path)
        self.assertEqual(before, execution_files(self.project))
        self.assertEqual(source_exclusions, EXCLUDED)

    def test_unowned_code_resources_configuration_and_unlisted_specs_remain_visible(self):
        before = execution_files(self.project)
        paths = [
            'entry/src/main/ets/pages/Unowned.ets',
            'entry/src/main/resources/base/element/color.json',
            'spec/execution/briefs/Unowned.ets',
            'spec/execution/resources/color.json',
            'work/pipeline-20261017/Unowned.ets',
            'work/pipeline-20261017/calls/Unowned.ets',
            'work/pipeline-20261017/support/Unowned.ets',
            'work/pipeline-20261017/support/color.json',
            'work/pipeline-20261017/resources/color.json',
            'work/pipeline-20261017/arbitrary.json',
            'work/ordinary.log',
            'spec/reports/host-oracle/Unowned.ets',
            'spec/reports/host-oracle/unknown.txt',
            'spec/reports/host-oracle/other/extra.cjs',
            'spec/execution/autofix-log/round-18/native-pipeline-raw/loop-state-pipeline-final-iter0-f868b7e4576547a6947ded2660584571/Unowned.ets',
            'spec/execution/autofix-log/round-18/native-pipeline-raw/loop-state-pipeline-final-iter0-f868b7e4576547a6947ded2660584571/unknown-pipeline-iter0.json',
            'spec/execution/autofix-log/round-18/native-pipeline-raw/loop-state-pipeline-final-iter0-f868b7e4576547a6947ded2660584571/unknown.json',
            'spec/execution/autofix-log/round-18/native-pipeline-raw/loop-state-pipeline-final-iter0-f868b7e4576547a6947ded2660584571/unsupported-pipeline-iter9.json',
            'spec/execution/autofix-log/round-18/native-pipeline-raw/loop-state-pipeline-final-iter0-f868b7e4576547a6947ded2660584571/nested/result.json',
            'spec/execution/autofix-log/round-18/extra.json',
            'spec/execution/autofix-log/round-18/native-pipeline-dispositions-iter0.yaml',
            'spec/unauthorized.md',
            '.migbot/config.json',
        ]
        for path in paths:
            if path == '.migbot/config.json':
                write_json(self.project / path, {'ios_harness': {'spec_contract_version': 2}, 'changed': True})
            else:
                self.put(path)
        after = execution_files(self.project)
        changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
        self.assertEqual(changed, set(paths))

    def test_core_progress_is_mutable_but_business_contract_is_not(self):
        before = execution_files(self.project)
        frozen = baseline_inputs(self.project, 'domains')
        for name in ('feature-index.md', 'ui-manifest.md'):
            path = self.project / 'spec/baseline' / name
            path.write_text(path.read_text(encoding='utf-8').replace('pending', 'implemented'), encoding='utf-8')
        self.assertEqual(before, execution_files(self.project))
        self.assertEqual(frozen, baseline_inputs(self.project, 'domains'))
        path = self.project / 'spec/baseline/ui-manifest.md'
        path.write_text(path.read_text(encoding='utf-8').replace('entry/Counter.ets', 'entry/Other.ets'), encoding='utf-8')
        self.assertNotEqual(before, execution_files(self.project))
        self.assertNotEqual(frozen, baseline_inputs(self.project, 'domains'))

    def test_unrelated_same_id_status_table_is_never_a_progress_exemption(self):
        path = self.project / 'spec/baseline/feature-index.md'
        text = path.read_text(encoding='utf-8') + '\n## Payment result\n| ID | status |\n|---|---|\n| F001 | failed |\n'
        path.write_text(text, encoding='utf-8')
        before = execution_files(self.project)
        frozen = baseline_inputs(self.project, 'domains')
        path.write_text(text.replace('| failed |', '| passed |'), encoding='utf-8')
        self.assertNotEqual(before, execution_files(self.project))
        self.assertNotEqual(frozen, baseline_inputs(self.project, 'domains'))


class LandingEvidenceTests(unittest.TestCase):
    def test_real_dispatch_and_landing_accept_logs_but_reject_hidden_product_writes(self):
        with tempfile.TemporaryDirectory(prefix='execution-evidence-') as directory:
            root = Path(directory)
            _, project, graph = harness_fixture.fixture(root)
            output = 'entry/src/main/ets/pages/Counter.ets'
            request = root / 'request.json'
            write_json(request, {'schema_version': 2, 'wave': 'domains',
                'graph_sha256': digest(json_bytes(graph)), 'tasks': [{
                    'id': 'counter', 'role': 'a2h-ios-converter', 'goal': 'Implement source counter',
                    'ownership': [output], 'ac_ids': ['F001-AC01'],
                    'fact_ids': [f['id'] for f in graph['facts']], 'parents': []}]})
            generate(project, request)
            action, _ = step(project, 'domains')
            self.assertEqual(action['action'], 'dispatch')
            log = project / 'work/pipeline-20261017/calls/20261017T021327973146-945af9.stdout.log'
            log.parent.mkdir(parents=True)
            log.write_text('actual invocation output', encoding='utf-8')
            write_json(log.with_name('20261017T021327973146-945af9.json'), {'exit_code': 0})
            (project / 'spec/pipeline-run-20261017.md').write_text('# Actual calls\n', encoding='utf-8')
            for relative in ('spec/execution/briefs/Hidden.ets',
                             'work/pipeline-20261017/support/Hidden.ets',
                             'spec/state/fence-snapshot/entry/Hidden.ets',
                             'spec/execution/resources/color.json', 'spec/unauthorized.md'):
                unowned = project / relative
                unowned.parent.mkdir(parents=True, exist_ok=True)
                unowned.write_text('unowned product change', encoding='utf-8')
                journal_path = project / 'spec/state/journal.json'
                journal = journal_path.read_bytes() if journal_path.exists() else None
                with self.assertRaisesRegex(MigrationError, 'outside ownership'):
                    step(project, 'domains', landing=True)
                self.assertEqual(journal_path.read_bytes() if journal_path.exists() else None, journal)
                unowned.unlink()
            for relative in ('.manifest.json', 'spec/baseline/features/F001-counter.md'):
                backup = project / 'spec/state/fence-snapshot' / relative
                original_backup = backup.read_bytes()
                for tampered in (None, b'{}'):
                    if tampered is None:
                        backup.unlink()
                    else:
                        backup.write_bytes(tampered)
                    with self.assertRaisesRegex(MigrationError, 'outside ownership'):
                        step(project, 'domains', landing=True)
                    with self.assertRaisesRegex(MigrationError, 'outside ownership'):
                        step(project, 'domains')
                    backup.write_bytes(original_backup)
            file = project / output
            file.parent.mkdir(parents=True)
            file.write_text('export class Counter { count: number = 0; add(): void { this.count += 1; } }', encoding='utf-8')
            write_json(project / action['batch'][0]['result_path'], {
                'ios_receipt_version': 2, 'source_sha256': graph['source_sha256'],
                'plan_sha256': digest((project / 'spec/waves/plan-domains.json').read_bytes()),
                'task_id': 'counter', 'status': 'generated', 'behavior_verified': False,
                'file_hashes': {output: digest(file.read_bytes())}, 'ac_ids': ['F001-AC01'],
                'findings': [], 'final_state': 'PASS', 'task': 'counter', 'files_touched': [output],
                'files': [output], 'fixed': [], 'unresolved': [], 'domain': 'counter', 'skipped': []})
            landed, code = step(project, 'domains', landing=True)
            self.assertEqual(code, 0, landed)
            self.assertEqual(step(project, 'domains')[0]['action'], 'done')
            self.assertFalse(landed['behavior_verified'])

    def test_original_fence_refreshes_between_two_batches_without_losing_ownership_checks(self):
        with tempfile.TemporaryDirectory(prefix='execution-evidence-two-batches-') as directory:
            root = Path(directory)
            _, project, graph = harness_fixture.fixture(root)
            outputs = ['entry/src/main/resources/base/element/string.json', 'entry/Second.ets']
            request = root / 'request.json'
            write_json(request, {'schema_version': 2, 'wave': 'domains',
                'graph_sha256': digest(json_bytes(graph)), 'tasks': [{
                    'id': ident, 'role': 'a2h-ios-converter', 'goal': 'Implement ' + ident,
                    'ownership': [output], 'ac_ids': ['F001-AC01'],
                    'fact_ids': [f['id'] for f in graph['facts']], 'parents': parents}
                    for ident, output, parents in [('first', outputs[0], []), ('second', outputs[1], ['first'])]]})
            generate(project, request)
            for ident, output in zip(('first', 'second'), outputs):
                action, _ = step(project, 'domains')
                self.assertEqual(action['action'], 'dispatch')
                self.assertEqual(action['batch'][0]['id'], ident)
                file = project / output
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text('{}' if ident == 'first' else 'export class Second {}', encoding='utf-8')
                write_json(project / action['batch'][0]['result_path'], {
                    'ios_receipt_version': 2, 'source_sha256': graph['source_sha256'],
                    'plan_sha256': digest((project / 'spec/waves/plan-domains.json').read_bytes()),
                    'task_id': ident, 'status': 'generated', 'behavior_verified': False,
                    'file_hashes': {output: digest(file.read_bytes())}, 'ac_ids': ['F001-AC01'],
                    'findings': [], 'final_state': 'PASS', 'task': ident, 'files_touched': [output],
                    'files': [output], 'fixed': [], 'unresolved': [], 'domain': ident, 'skipped': []})
                landed, code = step(project, 'domains', landing=True)
                self.assertEqual(code, 0, landed)
            self.assertTrue((project / 'spec/state/fence-snapshot' / outputs[0]).is_file())
            self.assertEqual(step(project, 'domains')[0]['action'], 'done')
            value = read_json(request)
            value['replan_review'] = {'reviewer': 'independent-test', 'reason': 'Repeat identical reviewed plan without stale dispatch evidence'}
            write_json(request, value)
            result = replan(project, request)
            self.assertTrue((Path(result['archive']) / 'spec/reports/ios-dispatch-domains.json').is_file())
            self.assertFalse((project / 'spec/reports/ios-dispatch-domains.json').exists())
            self.assertEqual(step(project, 'domains')[0]['action'], 'dispatch')


if __name__ == '__main__':
    unittest.main()
