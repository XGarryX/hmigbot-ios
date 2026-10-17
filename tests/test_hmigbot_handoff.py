import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import MigrationError, anchor, digest, json_bytes, snapshot
from hmigbot_ios.hmigbot import bind, binding_data, check_binding, check_handoff, contract_draft, handoff, ROUTES, SKILLS


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'Counter.swift').write_text('import UIKit\nclass Counter: UIViewController {\n var count = 0\n func add() { count += 1 }\n}\n', encoding='utf-8')
        self.upstream = self.root / 'hmigbot'
        (self.upstream / '.codex-plugin').mkdir(parents=True)
        (self.upstream / '.codex-plugin/plugin.json').write_bytes(json_bytes({'name': 'migbot', 'version': '1.6.1', 'repository': 'https://github.com/fuxi-ailabs/hmigbot-CodeX'}))
        for name in SKILLS + ['a2h-run']:
            path = self.upstream / 'skills' / name
            (path / 'references').mkdir(parents=True)
            (path / 'SKILL.md').write_text('---\nname: ' + name + '\n---\nOriginal test provider\n', encoding='utf-8')
            (path / 'references/guide.md').write_text('test reference', encoding='utf-8')
        self.binding = self.root / 'binding.json'
        bind(self.upstream, self.binding)
        self.analysis = self.root / 'analysis'
        contract_draft(self.source, self.analysis)
        self.path = self.analysis / 'contract.json'
        self.contract = json.loads(self.path.read_text(encoding='utf-8'))
        self.contract['target_sdk'] = '6.0.2(22)'
        self.unit = self.contract['units'][0]
        self.unit.update({'status': 'ready', 'kind': 'state', 'contract': {
            'owners': 'Counter view controller', 'initial_values': {'count': 0},
            'transitions': ['add increments count by 1']}, 'target_files': ['entry/src/main/ets/pages/Index.ets'],
            'acceptance': [{'id': 'count-add', 'given': 'count is 0', 'when': 'add is called', 'then': 'count is 1',
                'source_anchors_ref': [anchor('Counter.swift', digest((self.source / 'Counter.swift').read_bytes()), 4)]}]})
        self.contract['units'] = [self.unit]
        self.save()

    def save(self):
        self.path.write_bytes(json_bytes(self.contract))

    def run_handoff(self, **kwargs):
        self.save()
        return handoff(self.source, self.root / 'target', self.path, self.binding, self.root / 'packets', **kwargs)

    def test_routes_source_contract_to_actual_original_skills_without_claiming_execution(self):
        before = snapshot(self.upstream)
        result = self.run_handoff()
        self.assertEqual(result['units'][0]['skills'], ['arkts-state-manager'])
        self.assertEqual(result['status'], 'prepared_not_executed')
        self.assertFalse(result['migration_complete'])
        self.assertFalse((self.root / 'target').exists())
        self.assertEqual(before, snapshot(self.upstream))
        packet = json.loads((self.root / 'packets/tasks/U0001.json').read_text())
        self.assertEqual(packet['source_root'], str(self.source.resolve()))
        self.assertEqual(packet['unit']['contract']['initial_values']['count'], 0)
        self.assertTrue(Path(packet['skill_entries']['arkts-state-manager']).is_file())
        self.assertNotIn('android_source', packet)

    def test_binding_detects_reference_changes_and_wrong_plugin(self):
        path = self.upstream / 'skills/arkts-state-manager/references/guide.md'
        path.write_text('changed')
        with self.assertRaisesRegex(MigrationError, 'binding changed'):
            check_binding(self.binding)
        (self.upstream / '.codex-plugin/plugin.json').write_bytes(json_bytes({'name': 'hmigbot-plus'}))
        with self.assertRaisesRegex(MigrationError, 'standalone'):
            bind(self.upstream, self.root / 'second.json')

    @unittest.skipUnless(os.name == 'nt', 'Windows extended-path binding regression')
    def test_deep_binding_keeps_normal_contract_keys_and_detects_changed_bytes(self):
        base = self.upstream / 'skills/arkts-state-manager/references/deep-path-regression'
        self.assertTrue(base.resolve().is_relative_to(self.root.resolve()))
        extended_base = Path('\\\\?\\' + str(base))
        self.addCleanup(shutil.rmtree, extended_base)
        relative = '/'.join(['segment-' + 'x' * 48] * 5 + ['guide.md'])
        logical = base.joinpath(*relative.split('/'))
        self.assertGreater(len(str(logical.parent)), 260)
        physical = Path('\\\\?\\' + str(logical))
        physical.parent.mkdir(parents=True)
        physical.write_bytes(b'original deep reference')
        data = binding_data(self.upstream)
        key = logical.relative_to(self.upstream).as_posix()
        self.assertEqual(data['skills']['arkts-state-manager']['files'][key], digest(physical.read_bytes()))
        self.assertEqual(data['root'], str(self.upstream.resolve()))
        self.assertFalse(any('?' in name for entry in data['skills'].values() for name in entry['files']))
        with self.assertRaisesRegex(MigrationError, 'binding changed'):
            check_binding(self.binding)
        updated = self.root / 'deep-binding.json'
        bind(self.upstream, updated)
        self.assertEqual(check_binding(updated), data)
        physical.write_bytes(b'changed deep reference')
        with self.assertRaisesRegex(MigrationError, 'binding changed'):
            check_binding(updated)

    def test_rejects_stale_source_unready_or_missing_semantics(self):
        self.unit['status'] = 'needs_analysis'
        with self.assertRaisesRegex(MigrationError, 'needs source analysis'):
            self.run_handoff()
        self.unit['status'] = 'ready'
        self.unit['contract']['transitions'] = None
        with self.assertRaisesRegex(MigrationError, 'source semantics'):
            self.run_handoff()
        self.unit['contract']['transitions'] = ['add increments count']
        (self.source / 'Counter.swift').write_text('changed')
        with self.assertRaisesRegex(MigrationError, 'stale'):
            self.run_handoff()

    def test_rejects_unsafe_target_and_invalid_anchor(self):
        self.unit['target_files'] = ['../overwrite.ets']
        with self.assertRaises(MigrationError):
            self.run_handoff()
        self.unit['target_files'] = ['entry/Index.ets']
        self.unit['acceptance'][0]['source_anchors_ref'][0]['line'] = 999
        with self.assertRaisesRegex(MigrationError, 'outside the file'):
            self.run_handoff()

    def test_dependency_closure_cycle_and_serial_file_ownership(self):
        second = copy.deepcopy(self.unit)
        second['id'] = 'U0002'
        second['depends_on'] = ['U0001']
        self.contract['units'].append(second)
        with self.assertRaisesRegex(MigrationError, 'all unit dependencies'):
            self.run_handoff(selected=['U0002'])
        self.unit['depends_on'] = ['U0002']
        with self.assertRaisesRegex(MigrationError, 'cycle'):
            self.run_handoff()
        self.unit['depends_on'] = []
        result = self.run_handoff()
        self.assertEqual(result['execution_order'], ['U0001', 'U0002'])
        self.assertEqual(result['shared_file_writers']['entry/src/main/ets/pages/index.ets'], ['U0001', 'U0002'])

    def test_unknown_route_does_not_silently_fall_back(self):
        self.unit['kind'] = 'unknown-service'
        with self.assertRaisesRegex(MigrationError, 'No audited HMigBot route'):
            self.run_handoff()

    def test_android_only_consumer_is_blocked(self):
        self.unit['kind'] = 'tests'
        with self.assertRaisesRegex(MigrationError, 'Android oracle'):
            self.run_handoff()

    def test_execution_rechecks_source_and_packet_integrity(self):
        self.run_handoff()
        folder = self.root / 'packets'
        self.assertEqual(check_handoff(self.source, folder)['execution'], 'not_verified')
        task = folder / 'tasks/U0001.json'
        data = task.read_bytes()
        task.write_text('{}')
        with self.assertRaisesRegex(MigrationError, 'artifact changed'):
            check_handoff(self.source, folder)
        task.write_bytes(data)
        (self.source / 'Counter.swift').write_text('different source')
        with self.assertRaisesRegex(MigrationError, 'source changed'):
            check_handoff(self.source, folder)

    def test_draft_does_not_treat_lexical_candidates_as_ready(self):
        output = self.root / 'draft-two'
        result = contract_draft(self.source, output)
        self.assertFalse(result['code_generated'])
        draft = json.loads((output / 'contract.json').read_text())
        self.assertTrue(all(u['status'] == 'needs_analysis' for u in draft['units']))
        self.assertTrue(draft['unresolved'])

    def test_external_binding_is_retired_without_touching_upstream(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        from manage_install import manage
        workspace = self.root / 'workspace'
        workspace.mkdir()
        before = snapshot(self.upstream)
        with self.assertRaisesRegex(ValueError, 'External binding retired'):
            manage(workspace, 'install', self.upstream)
        self.assertEqual(before, snapshot(self.upstream))
        self.assertFalse((workspace / '.hmigbot-ios').exists())


if __name__ == '__main__':
    unittest.main()
