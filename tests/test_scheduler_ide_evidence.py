"""Only the four observed DevEco metadata files leave execution ownership."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import EXCLUDED, snapshot
from hmigbot_ios.ios_scheduler import execution_files
import test_scheduler_join_evidence as protocol

IDE = ('.idea/.deveco/cxx/.clang-format', '.idea/.deveco/module/entry.cache.json',
       '.idea/.deveco/project.cache.json', '.idea/.gitignore')
NEIGHBORS = ('.idea/.deveco/cxx/Hidden.ets', '.idea/.deveco/module/other.cache.json',
             '.idea/.deveco/other.json', '.idea/.deveco/build-profile.json5',
             '.idea/.deveco/module/entry.cache.json.ets', '.idea/resources/string.json',
             'entry/src/main/resources/base/element/string.json', 'build-profile.json5')


class IdeEvidenceTests(protocol.JoinEvidenceTests):
    # Reuse the real original dispatch/receipt/landing protocol while replacing
    # its join metadata producer with precisely the four observed IDE files.
    def metadata(self, root=None):
        root = root or self.project
        for name in IDE:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('DevEco generated metadata\n', encoding='utf-8')

    def test_exact_ide_paths_remain_raw_snapshot_inputs_and_neighbors_are_audited(self):
        exclusions = set(EXCLUDED)
        before = execution_files(self.project)
        raw_before = snapshot(self.project)
        quality_before = protocol.quality_views.target_inputs(self.project)
        self.metadata()
        self.assertEqual(execution_files(self.project), before)
        raw_after = snapshot(self.project)
        self.assertNotEqual(raw_after['sha256'], raw_before['sha256'])
        self.assertTrue(set(IDE).issubset({entry['path'] for entry in raw_after['files']}))
        self.assertEqual(protocol.quality_views.target_inputs(self.project), quality_before)
        source_before = snapshot(self.source)
        self.metadata(self.source)
        source_after = snapshot(self.source)
        self.assertNotEqual(source_before['sha256'], source_after['sha256'])
        self.assertTrue(set(IDE).issubset({entry['path'] for entry in source_after['files']}))
        for relative in NEIGHBORS:
            path = self.project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('product or configuration\n', encoding='utf-8')
        after = execution_files(self.project)
        self.assertEqual({p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}, set(NEIGHBORS))
        self.assertEqual(EXCLUDED, exclusions)

    def test_original_dispatch_join_metadata_receipt_and_landing_keep_the_fence(self):
        output = 'entry/Counter.ets'
        request = self.root / 'request.json'
        protocol.write_json(request, {'schema_version': 2, 'wave': 'domains',
            'graph_sha256': protocol.digest(protocol.json_bytes(self.graph)), 'tasks': [{
                'id': 'counter', 'role': 'a2h-ios-converter', 'goal': 'Implement source counter',
                'ownership': [output], 'ac_ids': ['F001-AC01'],
                'fact_ids': [fact['id'] for fact in self.graph['facts']], 'parents': []}]})
        protocol.generate(self.project, request)
        action, code = protocol.step(self.project, 'domains')
        self.assertEqual((action['action'], code), ('dispatch', 0))
        self.metadata()
        target = self.project / output
        target.parent.mkdir(parents=True)
        target.write_text('export class Counter { count: number = 0; }', encoding='utf-8')
        protocol.write_json(self.project / action['batch'][0]['result_path'], {
            'ios_receipt_version': 2, 'source_sha256': self.graph['source_sha256'],
            'plan_sha256': protocol.digest((self.project / 'spec/waves/plan-domains.json').read_bytes()),
            'task_id': 'counter', 'status': 'generated', 'behavior_verified': False,
            'file_hashes': {output: protocol.digest(target.read_bytes())}, 'ac_ids': ['F001-AC01'],
            'findings': [], 'final_state': 'PASS', 'task': 'counter', 'files_touched': [output],
            'files': [output], 'fixed': [], 'unresolved': [], 'domain': 'counter', 'skipped': []})
        journal = self.project / 'spec/state/journal.json'
        journal_before = journal.read_bytes() if journal.exists() else None
        for relative in NEIGHBORS:
            with self.subTest(path=relative):
                path = self.project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('unauthorized neighboring product\n', encoding='utf-8')
                with self.assertRaisesRegex(protocol.MigrationError, 'outside ownership'):
                    protocol.step(self.project, 'domains', landing=True)
                self.assertEqual(journal.read_bytes() if journal.exists() else None, journal_before)
                path.unlink()
        result, code = protocol.step(self.project, 'domains', landing=True)
        self.assertEqual(code, 0, result)
        self.assertFalse(result.get('fence_breach'), result)
        self.assertEqual(protocol.step(self.project, 'domains')[0]['action'], 'done')
        self.assertEqual(protocol.read_json(journal)['operation_outputs'][0]['status'], 'OK')

    # Other inherited join-specific assertions are covered by their own suite.
    test_only_named_join_metadata_is_ignored_by_execution_ownership = None
    test_join_metadata_keeps_quality_inputs_current_without_changing_source_fingerprints = None
    test_patrol_receipts_use_only_original_route_domains_and_numeric_batch_ids = None


if __name__ == '__main__':
    unittest.main()
