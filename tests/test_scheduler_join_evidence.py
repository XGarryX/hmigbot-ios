"""Join metadata is execution evidence only at its documented exact paths."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))

from hmigbot_ios.core import EXCLUDED, MigrationError, digest, json_bytes, read_json, snapshot, write_json
from hmigbot_ios.ios_scheduler import execution_files, generate, step
from hmigbot_ios import quality_views
from test_ios_harness import fixture


class JoinEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='join-evidence-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source, self.project, self.graph = fixture(self.root)

    def metadata(self, root=None):
        root = root or self.project
        for name in ('stage1_batch-02', 'STAGE2_slice_03'):
            write_json(root / f'spec/a2h/_work/expected_{name}.json', {
                'join_point': name, 'task_names': ['counter'],
                'artifacts': [{'path': 'entry/Counter.ets', 'min_count': 1, 'min_bytes': 1, 'json': False}]})
        ledger = root / 'spec/a2h/_work/join-ledger.jsonl'
        ledger.write_text('{"join_point":"stage1_batch-02","joined":["counter"]}\n', encoding='utf-8')

    def test_only_named_join_metadata_is_ignored_by_execution_ownership(self):
        before = execution_files(self.project)
        self.metadata()
        self.assertEqual(execution_files(self.project), before)
        paths = ('spec/a2h/_work/arbitrary.json', 'spec/a2h/_work/Shadow.ets',
                 'spec/a2h/_work/expected_counter.ets', 'spec/a2h/_work/expected_counter.json.bak',
                 'spec/a2h/_work/expected_.json', 'spec/a2h/_work/expected_counter/nested.json',
                 'spec/a2h/_work/other/join-ledger.jsonl', 'spec/a2h/_work/join-ledger.json',
                 'spec/a2h/_work/join-ledger.jsonl.ets', 'spec/a2h/_workish/expected_counter.json',
                 'spec/a2h/expected_counter.json')
        for relative in paths:
            path = self.project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('unclassified product or configuration input', encoding='utf-8')
        after = execution_files(self.project)
        self.assertEqual({path for path in before.keys() | after.keys() if before.get(path) != after.get(path)},
                         set(paths))

    def test_join_metadata_keeps_quality_inputs_current_without_changing_source_fingerprints(self):
        exclusions = set(EXCLUDED)
        source_before = snapshot(self.source)
        raw_project_before = snapshot(self.project)['sha256']
        target_before = quality_views.target_inputs(self.project)
        spec_before = quality_views.spec_inputs(self.project)
        report = quality_views.render_report(quality_views.summary(self.project))
        self.metadata()
        self.assertEqual(snapshot(self.source), source_before)
        self.assertNotEqual(snapshot(self.project)['sha256'], raw_project_before)
        self.assertEqual(quality_views.target_inputs(self.project), target_before)
        self.assertEqual(quality_views.spec_inputs(self.project), spec_before)
        self.assertTrue(quality_views.validate_report(self.project, report))
        # These names remain real source inputs if present in an iOS source
        # tree: the exception belongs only to adapter execution ownership.
        self.metadata(self.source)
        self.assertNotEqual(snapshot(self.source)['sha256'], source_before['sha256'])
        self.assertEqual(EXCLUDED, exclusions)

    def test_original_dispatch_join_metadata_receipt_and_landing_keep_the_fence(self):
        output = 'entry/Counter.ets'
        request = self.root / 'request.json'
        write_json(request, {'schema_version': 2, 'wave': 'domains',
            'graph_sha256': digest(json_bytes(self.graph)), 'tasks': [{
                'id': 'counter', 'role': 'a2h-ios-converter', 'goal': 'Implement source counter',
                'ownership': [output], 'ac_ids': ['F001-AC01'],
                'fact_ids': [fact['id'] for fact in self.graph['facts']], 'parents': []}]})
        generate(self.project, request)
        action, code = step(self.project, 'domains')
        self.assertEqual((action['action'], code), ('dispatch', 0))
        self.metadata()
        target = self.project / output
        target.parent.mkdir(parents=True)
        target.write_text('export class Counter { count: number = 0; }', encoding='utf-8')
        write_json(self.project / action['batch'][0]['result_path'], {
            'ios_receipt_version': 2, 'source_sha256': self.graph['source_sha256'],
            'plan_sha256': digest((self.project / 'spec/waves/plan-domains.json').read_bytes()),
            'task_id': 'counter', 'status': 'generated', 'behavior_verified': False,
            'file_hashes': {output: digest(target.read_bytes())}, 'ac_ids': ['F001-AC01'],
            'findings': [], 'final_state': 'PASS', 'task': 'counter', 'files_touched': [output],
            'files': [output], 'fixed': [], 'unresolved': [], 'domain': 'counter', 'skipped': []})
        journal = self.project / 'spec/state/journal.json'
        before_journal = journal.read_bytes() if journal.exists() else None
        for relative in ('spec/a2h/_work/arbitrary.json', 'spec/a2h/_work/Shadow.ets',
                         'spec/a2h/_work/expected_counter.json.bak',
                         'spec/a2h/_workish/expected_counter.json',
                         'spec/a2h/_work/other/join-ledger.jsonl'):
            with self.subTest(path=relative):
                path = self.project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('unauthorized adjacent input', encoding='utf-8')
                with self.assertRaisesRegex(MigrationError, 'outside ownership'):
                    step(self.project, 'domains', landing=True)
                self.assertEqual(journal.read_bytes() if journal.exists() else None, before_journal)
                path.unlink()
        landed, code = step(self.project, 'domains', landing=True)
        self.assertEqual(code, 0, landed)
        self.assertFalse(landed.get('fence_breach'), landed)
        self.assertEqual(step(self.project, 'domains')[0]['action'], 'done')
        self.assertEqual(read_json(journal)['operation_outputs'][0]['status'], 'OK')


if __name__ == '__main__':
    unittest.main()
