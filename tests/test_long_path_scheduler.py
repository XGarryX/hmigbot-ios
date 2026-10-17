"""Exercise Windows archive paths through the real original scheduler protocol."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))

from hmigbot_ios.core import MigrationError, digest, json_bytes, read_json, write_json
from hmigbot_ios.ios_scheduler import generate, kernel, replan, step
from hmigbot_ios.plan_contract import contract_revision
import test_ios_harness as harness_fixture


@unittest.skipUnless(os.name == 'nt', 'Windows long-path scheduler regression')
class LongPathSchedulerTests(unittest.TestCase):
    @staticmethod
    def extended(path):
        value = str(path.absolute())
        return Path(value if value.startswith('\\\\?\\') else '\\\\?\\' + value)

    def write_receipt(self, project, graph, action, output):
        file = project / output
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('export class Counter { count: number = 0; }', encoding='utf-8')
        task = action['batch'][0]
        write_json(project / task['result_path'], {
            'ios_receipt_version': 2, 'source_sha256': graph['source_sha256'],
            'plan_sha256': digest((project / 'spec/waves/plan-domains.json').read_bytes()),
            'task_id': 'counter', 'status': 'generated', 'behavior_verified': False,
            'file_hashes': {output: digest(file.read_bytes())}, 'ac_ids': ['F001-AC01'],
            'findings': [], 'final_state': 'PASS', 'task': 'counter', 'files_touched': [output],
            'files': [output], 'fixed': [], 'unresolved': [], 'domain': 'counter', 'skipped': []})

    def test_reviewed_replan_keeps_deep_history_and_completes_native_receipt_protocol(self):
        root = Path(tempfile.mkdtemp(prefix='lp-scheduler-'))
        self.addCleanup(shutil.rmtree, self.extended(root))
        _, project, graph = harness_fixture.fixture(root)
        # Keep the archived filename at the observed 261-character boundary:
        # its parent is still discoverable by the original os.walk, while a
        # normal Windows Path.read_bytes fails. An even longer parent would
        # make os.walk silently omit it and would not reproduce this failure.
        archive_prefix = 'spec/.a2h/history/replan-' + '0' * 32 + '/spec/state/fence-snapshot/'
        template_prefix = '.hmigbot-ios/plugin/'
        template_suffix = '/template/entry/src/main/ets/entryability/EntryAbility.ets'
        padding = 261 - len(str(project)) - 1 - len(archive_prefix + template_prefix + template_suffix)
        self.assertGreater(padding, 0)
        template = template_prefix + 'v' * padding + template_suffix
        template_file = self.extended(project / template)
        template_file.parent.mkdir(parents=True)
        template_file.write_bytes(b'// unchanged bundled entry template\n')
        output = 'entry/Counter.ets'
        request = root / 'request.json'
        value = {'schema_version': 2, 'wave': 'domains',
            'graph_sha256': digest(json_bytes(graph)), 'tasks': [{
                'id': 'counter', 'role': 'a2h-ios-converter', 'goal': 'Implement source counter',
                'ownership': [output], 'ac_ids': ['F001-AC01'],
                'fact_ids': [fact['id'] for fact in graph['facts']], 'parents': []}]}
        write_json(request, value)
        generate(project, request)
        first, code = step(project, 'domains')
        self.assertEqual((first['action'], code), ('dispatch', 0))
        self.write_receipt(project, graph, first, output)
        self.assertEqual(step(project, 'domains', landing=True)[1], 0)
        value['replan_review'] = {'reviewer': 'long-path-regression',
            'reason': 'Re-run the reviewed plan while retaining the complete previous original fence'}
        write_json(request, value)
        new_run = replan(project, request)
        self.assertFalse(new_run['prior_success_inherited'])
        deep_relative = ('spec/.a2h/history/' + Path(new_run['archive']).name
                         + '/spec/state/fence-snapshot/' + template)
        self.assertGreater(len(str(project / deep_relative)), 260)
        self.assertEqual(self.extended(project / deep_relative).read_bytes(), template_file.read_bytes())
        deeper_relative = 'spec/.a2h/history/' + 'preserved-history/' * 14 + 'entryability/EntryAbility.ets'
        deeper = self.extended(project / deeper_relative)
        deeper.parent.mkdir(parents=True)
        deeper.write_bytes(b'// historical EntryAbility retained as audit input\n')
        self.assertGreater(len(str((project / deeper_relative).parent)), 260)
        # Pass the extended filesystem spelling because the original helper
        # starts with Path(root), which strips a custom Path subclass.
        scope = set(kernel()._scope_files(str(self.extended(project))))
        self.assertIn(deep_relative, scope)
        self.assertIn(deeper_relative, scope)
        contract = read_json(project / 'spec/blueprint/contracts.json')
        self.assertEqual(contract['contract_revision'], contract_revision(project))
        self.assertFalse((project / 'spec/state/dispatch.json').exists())
        second, code = step(project, 'domains')
        self.assertEqual((second['action'], code), ('dispatch', 0))
        deep_copy = self.extended(project / 'spec/state/fence-snapshot' / deeper_relative)
        self.assertEqual(deep_copy.read_bytes(), deeper.read_bytes())
        self.assertEqual(step(project, 'domains')[0]['action'], 'wait')
        self.write_receipt(project, graph, second, output)
        original_deep = deeper.read_bytes()
        deeper.write_bytes(b'forged historical EntryAbility')
        with self.assertRaisesRegex(MigrationError, 'outside ownership'):
            step(project, 'domains', landing=True)
        deeper.write_bytes(original_deep)
        unauthorized = project / 'spec/.a2h/history/unowned-history.ets'
        unauthorized.write_text('export class Unowned {}', encoding='utf-8')
        journal = project / 'spec/state/journal.json'
        prior_journal = journal.read_bytes() if journal.exists() else None
        with self.assertRaisesRegex(MigrationError, 'outside ownership'):
            step(project, 'domains', landing=True)
        self.assertEqual(journal.read_bytes() if journal.exists() else None, prior_journal)
        unauthorized.unlink()
        fence = project / 'spec/state/fence-snapshot/spec/baseline/features/F001-counter.md'
        original_fence = fence.read_bytes()
        fence.write_bytes(b'forged archived control contract')
        with self.assertRaisesRegex(MigrationError, 'outside ownership'):
            step(project, 'domains', landing=True)
        fence.write_bytes(original_fence)
        landed, code = step(project, 'domains', landing=True)
        self.assertEqual(code, 0, landed)
        self.assertFalse(landed.get('fence_breach'), landed)
        self.assertEqual(step(project, 'domains')[0]['action'], 'done')
        self.assertEqual(self.extended(project / deep_relative).read_bytes(), template_file.read_bytes())


if __name__ == '__main__':
    unittest.main()
