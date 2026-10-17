"""Derived views must retain raw evidence and never promote legacy progress to PASS."""
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import MigrationError, digest, json_bytes, read_json, snapshot, write_json
from hmigbot_ios.native_pipeline import configure
from hmigbot_ios.ios_facts import refresh
from hmigbot_ios.ios_literals import run as literals


class QualityViewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ios-quality-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source, self.project = self.root / 'source', self.root / 'target'
        self.source.mkdir(); self.project.mkdir()
        (self.source / 'Screen.swift').write_text('''import SwiftUI
struct Screen: View {
    @State var count = 0
    var body: some View {
        VStack {
            Text("Same")
            Button("Add") { count += 1 }
        }
    }
}
#Preview {
    Text("Same")
}
let protocolName = "not a displayed label"
''', encoding='utf-8')
        (self.source / 'Support.swift').write_text('let testOracle = "Same"\n', encoding='utf-8')
        configure(self.source, self.project)
        self.graph = refresh(self.project, self.source)
        literals(self.project)
        base = self.project / 'spec/baseline'
        (base / 'features').mkdir()
        (base / 'ui').mkdir()
        (base / 'features/F001-screen.md').write_text(
            '# F001\n- [ ] F001-AC01 Add increments count `判:ui | Count becomes 1`\n', encoding='utf-8')
        (base / 'feature-index.md').write_text(
            '| ID | 状态 |\n|---|---|\n| F001 | verified |\n', encoding='utf-8')
        (base / 'ui-manifest.md').write_text(
            '| page_id | 状态 |\n|---|---|\n| page_0001 | verified |\n', encoding='utf-8')
        (base / 'ui/page_0001_Screen.md').write_text('# Screen\n', encoding='utf-8')
        write_json(base / 'ios-source-disposition.json', {
            'source_sha256': self.graph['source_sha256'], 'files': [{
                'path': 'Support.swift', 'disposition': 'test', 'reason': 'Independent source oracle only',
                'source_sha256': digest((self.source / 'Support.swift').read_bytes()),
                'line': 1, 'end_line': 1}]})
        write_json(base / 'ios-coverage.json', {
            'schema_version': 2, 'graph_sha256': digest(json_bytes(self.graph)),
            'mappings': [{'obligation_id': 'IO-' + f['id'][3:], 'ac_ids': ['F001-AC01'],
                          'source_review': {'status': 'reviewed', 'input': 'Tap Add',
                              'processing': 'Increment the state', 'observable': 'Updated text',
                              'reviewer': 'independent-source-reader'}} for f in self.graph['facts']]})

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('hmigbot_ios.quality_views'),
                             'Missing executable product/evidence views')
        return importlib.import_module('hmigbot_ios.quality_views')

    def test_product_preview_and_test_with_same_text_keep_distinct_sources(self):
        view = self.module().product_literals(self.project)
        same = [e for e in view['entries'] if e.get('value') == 'Same']
        self.assertEqual({e['classification'] for e in same}, {'product', 'preview', 'test'})
        self.assertTrue(all(e['raw_ref'] and e['sources'] for e in same))

    def test_unclassified_string_stays_unknown_instead_of_becoming_ui_text(self):
        view = self.module().product_literals(self.project)
        entry = next(e for e in view['entries'] if e.get('value') == 'not a displayed label')
        self.assertEqual(entry['usage'], 'unresolved')

    def test_raw_ledger_and_control_files_are_not_changed(self):
        ledger = self.project / 'spec/baseline/literal-ledger.json'
        state = self.project / 'spec/state/state.json'
        write_json(state, {'gates': {'untouched': True}})
        before = {p: p.read_bytes() for p in (ledger, state)}
        self.module().product_literals(self.project)
        self.module().summary(self.project)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_edited_raw_ledger_is_rejected(self):
        p = self.project / 'spec/baseline/literal-ledger.json'
        data = read_json(p); data['texts'] = []; write_json(p, data)
        with self.assertRaises(MigrationError): self.module().product_literals(self.project)

    def test_stale_scope_is_not_used_to_exclude_product_literals(self):
        p = self.project / 'spec/baseline/ios-source-disposition.json'
        data = read_json(p); data['source_sha256'] = '0' * 64; write_json(p, data)
        with self.assertRaises(MigrationError): self.module().product_literals(self.project)

    def test_cached_view_cannot_be_changed_or_reused_after_scope_changes(self):
        mod = self.module()
        view = mod.product_literals(self.project)
        self.assertTrue(mod.validate_product_view(self.project, view))
        view['entries'][0]['classification'] = 'test'
        with self.assertRaises(MigrationError): mod.validate_product_view(self.project, view)

    def test_legacy_verified_without_evidence_is_not_behavior_or_visual_pass(self):
        report = self.module().summary(self.project)
        self.assertEqual(report['axes']['behavior']['status'], 'not_run')
        self.assertEqual(report['axes']['visual']['status'], 'not_run')
        self.assertFalse(report['behavior_verified'])
        self.assertEqual(report['legacy_progress']['features']['verified'], 1)

    def test_ac_and_registry_counts_come_from_current_rows(self):
        p = self.project / 'spec/placeholder-registry.md'
        p.write_text('''# Registry
Total: 0
| P-ID | kind | status |
|---|---|---|
| P-S1-001 | forward-ref | registered |
| P-S1-002 | forward-ref | resolved |
''', encoding='utf-8')
        mod = self.module()
        report = mod.summary(self.project)
        self.assertEqual(report['counts']['acceptance'], 1)
        self.assertEqual(report['placeholders']['registered'], 1)
        self.assertEqual(report['placeholders']['resolved'], 1)
        self.assertEqual(report['placeholders']['status'], 'parsed')
        feature = self.project / 'spec/baseline/features/F001-screen.md'
        feature.write_text(feature.read_text(encoding='utf-8') +
                           '- [ ] F001-AC02 Reload `判:unit | Saved value is restored`\n', encoding='utf-8')
        self.assertEqual(mod.summary(self.project)['counts']['acceptance'], 2)

    def test_malformed_registry_is_not_reported_as_empty(self):
        (self.project / 'spec/placeholder-registry.md').write_text(
            '| P-ID | kind |\n|---|---|\n| P-S1-001 | forward-ref |\n', encoding='utf-8')
        report = self.module().summary(self.project)
        self.assertEqual(report['placeholders']['status'], 'parse_error')

    def test_feature_addendum_is_not_counted_as_another_feature(self):
        (self.project / 'spec/baseline/features/F001-screen.state.md').write_text(
            '# State addendum\nShared details for F001.\n', encoding='utf-8')
        self.assertEqual(self.module().summary(self.project)['counts']['features'], 1)

    def test_registry_counts_all_supported_states_and_ignores_template_examples(self):
        states = ['registered', 'pending', 'due', 'fired', 'resolved', 'deferred']
        rows = ''.join(f'| `P-S1-{n:03d}` | forward-ref | `{status}` |\n'
                       for n, status in enumerate(states, 1))
        (self.project / 'spec/placeholder-registry.md').write_text(
            '# Registry\n## 注册表\n| P-ID | kind | status |\n|---|---|---|\n' + rows +
            '\n## 延期记录\n| P-ID | reason |\n|---|---|\n| P-S1-006 | approved |\n'
            '\n## 示例\n| P-ID | kind | status |\n|---|---|---|\n| P-S9-999 | forward-ref | pending |\n',
            encoding='utf-8')
        result = self.module().summary(self.project)['placeholders']
        self.assertEqual(result['status'], 'parsed')
        self.assertEqual({s: result[s] for s in states}, dict.fromkeys(states, 1))

    def test_textual_brief_pass_does_not_become_compilation_evidence(self):
        p = self.project / 'spec/execution/briefs/group_1_brief.md'
        p.parent.mkdir(parents=True)
        p.write_text('build_status: PASS\nfinal_state: PASS\n', encoding='utf-8')
        self.assertEqual(self.module().summary(self.project)['axes']['compilation']['status'], 'not_run')

    def test_native_build_evidence_is_stale_after_target_change(self):
        target = self.project / 'entry/Main.ets'
        target.parent.mkdir(parents=True); target.write_text('export const value = 1;')
        hap = self.project / 'entry/build/app.hap'
        hap.parent.mkdir(parents=True); hap.write_bytes(b'unit-test artifact, not a real HAP')
        report_path = self.root / 'build/build.json'
        write_json(report_path, {'schema_version': 'hmigbot-ios/1', 'status': 'build_passed',
            'source_sha256': self.graph['source_sha256'], 'target_project': str(self.project.resolve()),
            'target_input_hashes': self.module().target_inputs(self.project),
            'spec_input_hashes': self.module().spec_inputs(self.project),
            'exit_code': 0, 'hvigor_success_marker': True, 'source_changed': False,
            'artifacts': [{'path': 'entry/build/app.hap', 'sha256': digest(hap.read_bytes())}]})
        mod = self.module()
        self.assertEqual(mod.summary(self.project, build_evidence=report_path)['axes']['compilation']['status'], 'passed')
        target.write_text('export const value = 2;')
        self.assertEqual(mod.summary(self.project, build_evidence=report_path)['axes']['compilation']['status'], 'stale')

    def test_legacy_build_evidence_without_input_binding_is_unclassified(self):
        report_path = self.root / 'build.json'
        write_json(report_path, {'status': 'build_passed', 'exit_code': 0})
        report = self.module().summary(self.project, build_evidence=report_path)
        self.assertEqual(report['axes']['compilation']['status'], 'legacy_unclassified')

    def test_new_project_defaults_to_v2_contract_profile(self):
        from hmigbot_ios.ios_harness import initialize
        initialize(self.project)
        self.assertEqual(read_json(self.project / '.migbot/config.json')['ios_harness'].get('spec_contract_version'), 2)

    def test_existing_harness_does_not_silently_upgrade_contracts(self):
        from hmigbot_ios.ios_harness import initialize
        cfg_path = self.project / '.migbot/config.json'
        cfg = read_json(cfg_path); cfg['ios_harness'] = {'version': 2}; write_json(cfg_path, cfg)
        initialize(self.project)
        self.assertEqual(read_json(cfg_path)['ios_harness'].get('spec_contract_version'), 1)

    def test_read_only_cli_commands_are_executable(self):
        from hmigbot_ios.native_pipeline import main
        for command in ('product-literals', 'spec-summary'):
            with self.subTest(command=command), redirect_stdout(StringIO()) as output:
                self.assertEqual(main([command, '--project', str(self.project)]), 0)
                self.assertIn('"schema_version"', output.getvalue())

    def test_cli_view_cannot_overwrite_control_or_baseline(self):
        from hmigbot_ios.native_pipeline import main
        target = self.project / 'spec/baseline/literal-ledger.json'
        before = target.read_bytes()
        with redirect_stdout(StringIO()):
            self.assertEqual(main(['product-literals', '--project', str(self.project),
                                   '--output', str(target)]), 2)
        self.assertEqual(target.read_bytes(), before)

    def test_observed_process_evidence_expires_with_logs_and_ac_changes(self):
        from hmigbot_ios.behavior import verify
        mod = self.module()
        feature = self.project / 'spec/baseline/features/F001-screen.md'
        feature.write_text('# F001\n- [ ] F001-AC01 Add `判:unit | Count becomes 1`\n', encoding='utf-8')
        target = self.project / 'counter.py'
        target.write_text('def add():\n    return 1\nprint(add())\n', encoding='utf-8')
        node = {'path': 'counter.py', 'line': 1, 'symbol': 'add', 'sha256': digest(target.read_bytes())}
        events = [f for f in self.graph['facts'] if f['kind'] == 'event']
        spec = {'schema_version': 2, 'source_sha256': self.graph['source_sha256'],
                'chains': [{'source_fact': f['id'], **{k: node for k in ('input', 'processing', 'feedback')},
                            'review': {'status': 'reviewed', 'reviewer': 'source-test-reader'}} for f in events],
                'cases': [{'id': 'add', 'ac_ids': ['F001-AC01'], 'runner': 'unit',
                    'oracle': {'source_fact': events[0]['id'], 'expected': 1, 'reviewer': 'source-test-reader'},
                    'target_hashes': {'counter.py': digest(target.read_bytes())},
                    'command': [sys.executable, 'counter.py']}]}
        write_json(self.project / 'spec/verification/ios-behavior.json', spec)
        report, code = verify(self.project, self.source, self.graph,
                              {'F001-AC01': {'judgment': 'unit'}}, run=True)
        self.assertEqual(code, 0, report)
        self.assertEqual(mod.summary(self.project)['axes']['behavior']['status'], 'passed')
        log = self.project / 'spec/reports/behavior/add/stdout.log'
        original = log.read_bytes(); log.write_bytes(b'edited')
        self.assertNotEqual(mod.summary(self.project)['axes']['behavior']['status'], 'passed')
        log.write_bytes(original)
        feature.write_text(feature.read_text(encoding='utf-8') +
                           '- [ ] F001-AC02 Reload `判:unit | Value survives reload`\n', encoding='utf-8')
        self.assertEqual(mod.summary(self.project)['axes']['behavior']['status'], 'stale')

    def test_runner_cannot_change_oracle_and_bind_the_unexecuted_version(self):
        from hmigbot_ios.behavior import verify
        target = self.project / 'counter.py'
        target.write_text('''import json
from pathlib import Path
def add():
    return 1
p = Path('spec/verification/ios-behavior.json')
s = json.loads(p.read_text())
s['cases'][0]['oracle']['expected'] = 2
p.write_text(json.dumps(s))
print(add())
''', encoding='utf-8')
        node = {'path': 'counter.py', 'line': 3, 'symbol': 'add', 'sha256': digest(target.read_bytes())}
        events = [f for f in self.graph['facts'] if f['kind'] == 'event']
        path = self.project / 'spec/verification/ios-behavior.json'
        write_json(path, {'schema_version': 2, 'source_sha256': self.graph['source_sha256'],
            'chains': [{'source_fact': f['id'], **{k: node for k in ('input', 'processing', 'feedback')},
                        'review': {'status': 'reviewed', 'reviewer': 'test-source-reader'}} for f in events],
            'cases': [{'id': 'changed-oracle', 'ac_ids': ['F001-AC01'], 'runner': 'unit',
                      'oracle': {'source_fact': events[0]['id'], 'expected': 1, 'reviewer': 'test-source-reader'},
                      'target_hashes': {'counter.py': digest(target.read_bytes())},
                      'command': [sys.executable, 'counter.py']}]})
        before = digest(path.read_bytes())
        report, code = verify(self.project, self.source, self.graph,
                              {'F001-AC01': {'judgment': 'unit'}}, run=True)
        self.assertEqual(code, 2, report)
        self.assertFalse(report['behavior_verified'])
        self.assertEqual(report['verification_sha256'], before)
        self.assertIn('IOS.BEHAVIOR_INPUT_CHANGED', [f['rule'] for f in report['failures']])

    def test_evidence_inputs_pin_tool_contract_revision(self):
        from unittest.mock import patch
        mod = self.module()
        first = mod.spec_inputs(self.project)
        with patch('hmigbot_ios.plan_contract.contract_revision', return_value='f' * 64):
            self.assertNotEqual(first, mod.spec_inputs(self.project))


if __name__ == '__main__':
    unittest.main()
