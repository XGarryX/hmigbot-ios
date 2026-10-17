"""Upgrade proposals are read-only, evidence bound and never invent semantics."""
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import MigrationError, digest, read_json, write_json
from hmigbot_ios.native_pipeline import configure
from hmigbot_ios.ios_harness import initialize
from spec_contract_fixture import complete_contract


class SpecUpgradeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='spec-upgrade-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / 'source'; self.source.mkdir()
        self.project = self.root / 'target'; self.project.mkdir()
        (self.source / 'Counter.swift').write_text('import SwiftUI\nstruct Counter: View {\n    @State var count = 0\n    var body: some View {\n        VStack {\n            Text("Count")\n            Button("Add") { count += 1 }\n        }\n    }\n}\n', encoding='utf-8')
        configure(self.source, self.project); initialize(self.project); complete_contract(self.project)
        self.feature = self.project / 'spec/baseline/features/F001-counter.md'
        self.meta = self.project / 'spec/baseline/ui-snapshots/page_0001/meta.json'

    def tool(self):
        self.assertIsNotNone(importlib.util.find_spec('hmigbot_ios.spec_upgrade'), 'Missing controlled Spec upgrade tool')
        return importlib.import_module('hmigbot_ios.spec_upgrade')

    def files(self):
        return {p.relative_to(self.project).as_posix(): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}

    def legacy_meta(self, **extras):
        value = {'schema_version': 1, 'spec_contract_version': 2, 'page_id': 'page_0001',
                 'source_platform': 'ios', 'frameworks': ['swiftui'],
                 'source_refs': [{'path': 'Counter.swift', 'line': 2, 'symbol': 'Counter'}],
                 'source_anchors': [{'path': 'Counter.swift', 'line': 2, 'symbol': 'Counter'}],
                 'screenshot': None, 'runtime': 'not_run', **extras}
        write_json(self.meta, value)
        return value

    def short_target(self):
        self.feature.write_text(self.feature.read_text(encoding='utf-8').replace('标:CounterPage.add', '标:add'), encoding='utf-8')

    def test_inspection_compares_both_profiles_without_touching_originals(self):
        before = self.files()
        report = self.tool().inspect(self.project)
        self.assertEqual(self.files(), before)
        self.assertEqual(set(report['profile_diagnostics']), {'1', '2'})
        self.assertEqual(report['profile_diagnostics']['1']['status'], 'PASS')
        self.assertEqual(report['profile_diagnostics']['2']['status'], 'FAIL')
        self.assertFalse(report['behavior_verified'])
        self.assertIn('F001-AC01', report['retained_ids']['acceptance'])
        self.assertIn('page_0001', report['retained_ids']['pages'])
        self.assertTrue(any(f['category'] == 'v2_added' for f in report['findings']))

    def test_missing_document_is_one_finding_with_both_rule_origins(self):
        (self.project / 'spec/baseline/feature-base.md').unlink()
        report = self.tool().inspect(self.project)
        rows = [f for f in report['findings'] if f['category'] == 'missing' and f['subject'] == 'spec/baseline/feature-base.md']
        self.assertEqual(len(rows), 1, report['findings'])
        self.assertEqual(rows[0]['profiles'], [1, 2])

    def test_meta_candidate_preserves_anchors_and_moves_known_explanatory_fields(self):
        old = self.legacy_meta(limitations=['host unknown'], non_product_ranges=[{'path': 'Counter.swift', 'line': 10}])
        report = self.tool().inspect(self.project)
        patch = next(p for p in report['patches'] if p['path'].endswith('/meta.json'))
        self.assertEqual(read_json(self.meta), old)
        outcome = self.tool().apply(self.project, report, patch_ids=[patch['patch_id']])
        new = read_json(self.meta)
        self.assertEqual(new['source_refs'], ['Counter.swift:2'])
        self.assertEqual(new['source_anchors'], old['source_anchors'])
        self.assertEqual(new['extensions']['limitations'], old['limitations'])
        self.assertEqual(new['extensions']['non_product_ranges'], old['non_product_ranges'])
        self.assertEqual(new['runtime'], 'not_run')
        self.assertEqual(outcome['status'], 'applied_requires_review')
        self.assertEqual(read_json(self.project / '.migbot/config.json')['ios_harness']['spec_contract_version'], 1)

    def test_meta_disagreed_anchors_are_manual(self):
        self.legacy_meta(source_anchors=[{'path': 'Counter.swift', 'line': 7}])
        report = self.tool().inspect(self.project)
        self.assertFalse(report['patches'])
        self.assertTrue(any(f['rule'] == 'UPGRADE.META_MANUAL' for f in report['manual']))

    def test_unknown_top_level_meta_and_extension_conflicts_are_manual(self):
        self.legacy_meta(mystery_flag='unknown', limitations=['one'], extensions={'limitations': ['different']})
        report = self.tool().inspect(self.project)
        self.assertTrue(any(f['rule'] == 'UPGRADE.META_MANUAL' for f in report['manual']))
        self.assertFalse(report['patches'])

    def test_unique_explicit_target_is_candidate_without_feature_name_guessing(self):
        self.short_target()
        report = self.tool().inspect(self.project)
        patch = next(p for p in report['patches'] if p['path'].endswith('F001-counter.md'))
        self.assertIn('标:CounterPage.add', patch['content'])
        self.assertNotIn('标:F001.add', patch['content'])
        self.tool().apply(self.project, report, patch_ids=[patch['patch_id']])
        self.assertIn('标:CounterPage.add', self.feature.read_text(encoding='utf-8'))

    def test_ambiguous_target_and_missing_behavior_are_not_filled(self):
        self.short_target()
        text = self.feature.read_text(encoding='utf-8').replace('## 状态管理', '## 目标接口\n| 目标接口 | 生命周期 |\n|---|---|\n| OtherPage.add | page |\n## 状态管理')
        self.feature.write_text(text.replace('点击后文本为Count:1', ''), encoding='utf-8')
        report = self.tool().inspect(self.project)
        self.assertFalse(report['patches'])
        self.assertTrue(any(f['rule'] == 'UPGRADE.TARGET_MANUAL' for f in report['manual']))
        self.assertTrue(any(f['category'] == 'legacy' for f in report['findings']))

    def test_apply_requires_explicit_selected_candidates(self):
        self.short_target()
        report = self.tool().inspect(self.project)
        before = self.files()
        with self.assertRaises(MigrationError):
            self.tool().apply(self.project, report)
        self.assertEqual(self.files(), before)

    def test_source_and_any_spec_input_change_invalidates_report(self):
        self.short_target()
        tool = self.tool(); report = tool.inspect(self.project)
        ids = [p['patch_id'] for p in report['patches']]
        (self.source / 'Counter.swift').write_text('struct Changed {}\n', encoding='utf-8')
        with self.assertRaises(MigrationError):
            tool.apply(self.project, report, patch_ids=ids)

    def test_unselected_input_change_invalidates_report(self):
        self.short_target()
        tool = self.tool(); report = tool.inspect(self.project)
        ids = [p['patch_id'] for p in report['patches']]
        (self.project / 'spec/decision-ledger.md').write_text('# New decision\n', encoding='utf-8')
        with self.assertRaises(MigrationError):
            tool.apply(self.project, report, patch_ids=ids)

    def test_tampered_candidate_cannot_change_ids_or_approval(self):
        self.short_target()
        tool = self.tool(); report = tool.inspect(self.project)
        patch = report['patches'][0]
        patch['content'] = patch['content'].replace('F001-AC01', 'F999-AC99').replace('- [ ]', '- [x]')
        patch['after_sha256'] = digest(patch['content'].encode('utf-8'))
        before = self.files()
        with self.assertRaises(MigrationError):
            tool.apply(self.project, report, patch_ids=[patch['patch_id']])
        self.assertEqual(self.files(), before)

    def test_tampered_patch_path_cannot_write_control_ledger(self):
        self.short_target()
        tool = self.tool(); report = tool.inspect(self.project)
        patch = report['patches'][0]; patch['path'] = 'spec/.a2h/open-findings.json'
        with self.assertRaises(MigrationError):
            tool.apply(self.project, report, patch_ids=[patch['patch_id']])
        self.assertFalse((self.project / patch['path']).exists())

    def test_changed_config_and_new_input_are_stale(self):
        self.short_target()
        tool = self.tool(); report = tool.inspect(self.project)
        write_json(self.project / 'spec/baseline/extra.json', {'new': True})
        with self.assertRaises(MigrationError):
            tool.apply(self.project, report, patch_ids=[p['patch_id'] for p in report['patches']])

    def test_shared_explicit_target_can_qualify_without_copying_its_contract(self):
        self.short_target()
        shared = self.project / 'spec/baseline/feature-base.md'
        shared.write_text(shared.read_text(encoding='utf-8') + '\n## 目标接口\n| 目标接口 | 生命周期 |\n|---|---|\n| SharedCounter.add | page |\n', encoding='utf-8')
        text = self.feature.read_text(encoding='utf-8').replace('CounterPage.add', 'CounterPage.increment')
        text = text.replace('  - spec/baseline/feature-base.md#数据模型', '  - spec/baseline/feature-base.md#数据模型\n  - spec/baseline/feature-base.md#目标接口')
        self.feature.write_text(text, encoding='utf-8')
        report = self.tool().inspect(self.project)
        patch = next(p for p in report['patches'] if p['path'].endswith('.md'))
        self.assertIn('标:SharedCounter.add', patch['content'])
        self.assertNotIn('| SharedCounter.add |', patch['content'])

    def test_meta_stale_object_sha_and_extra_object_fields_stay_manual(self):
        self.legacy_meta(source_refs=[{'path': 'Counter.swift', 'line': 2, 'sha256': '0' * 64}])
        report = self.tool().inspect(self.project)
        self.assertFalse(report['patches'])
        self.assertTrue(report['manual'])

    def test_malformed_and_unknown_report_fields_are_rejected(self):
        self.short_target()
        tool = self.tool(); report = tool.inspect(self.project)
        ids = [p['patch_id'] for p in report['patches']]
        report['patches'] = None
        with self.assertRaises(MigrationError):
            tool.apply(self.project, report, patch_ids=ids)
        report = tool.inspect(self.project); report['approve_profile'] = True
        with self.assertRaises(MigrationError):
            tool.apply(self.project, report, patch_ids=ids)

    def test_all_selected_edits_are_checked_before_any_write(self):
        self.short_target(); self.legacy_meta()
        tool = self.tool(); report = tool.inspect(self.project)
        ids = [p['patch_id'] for p in report['patches']]
        self.assertEqual(len(ids), 2)
        report['patches'][-1]['content'] += '\nUNTRUSTED\n'
        before = self.files()
        with self.assertRaises(MigrationError):
            tool.apply(self.project, report, patch_ids=ids)
        self.assertEqual(self.files(), before)

    def test_feature_edit_preserves_bom_crlf_ids_and_checkbox_state(self):
        self.short_target()
        contents = self.feature.read_text(encoding='utf-8').replace('- [ ]', '- [x]')
        original = b'\xef\xbb\xbf' + contents.replace('\n', '\r\n').encode('utf-8')
        self.feature.write_bytes(original)
        tool = self.tool(); report = tool.inspect(self.project)
        patch = next(p for p in report['patches'] if p['path'].endswith('.md'))
        tool.apply(self.project, report, patch_ids=[patch['patch_id']])
        self.assertEqual(self.feature.read_bytes(), original.replace(b'\xe6\xa0\x87:add', b'\xe6\xa0\x87:CounterPage.add'))

    def test_fenced_example_ac_is_not_a_candidate_or_manual_target(self):
        example = '\n## Format example\n```md\n- [ ] F009-AC01 Example `源:Example → 标:add` `判:ui | Demonstration only`\n```\n'
        self.feature.write_text(self.feature.read_text(encoding='utf-8') + example, encoding='utf-8')
        report = self.tool().inspect(self.project)
        self.assertFalse(report['patches'])
        self.assertFalse(any(m.get('ac_id') == 'F009-AC01' for m in report['manual']))

    def test_visible_ac_changes_while_fenced_and_indented_examples_stay_exact(self):
        self.short_target()
        examples = ('\n## Format examples\n~~~~markdown\n- [ ] F009-AC01 Example `标:add`\n~~~~\n'
                    '\n    - [ ] F010-AC01 Indented example `标:add`\n')
        self.feature.write_text(self.feature.read_text(encoding='utf-8') + examples, encoding='utf-8')
        original_example_bytes = self.feature.read_bytes().split(b'## Format examples', 1)[1]
        tool = self.tool(); report = tool.inspect(self.project)
        patch = next(p for p in report['patches'] if p['path'].endswith('.md'))
        self.assertEqual([op['ac_id'] for op in patch['operations']], ['F001-AC01'])
        self.assertTrue(patch['content'].encode('utf-8').endswith(original_example_bytes))
        tool.apply(self.project, report, patch_ids=[patch['patch_id']])
        self.assertTrue(self.feature.read_text(encoding='utf-8').endswith(examples))

    def test_qualified_formal_target_never_rewrites_expected_literal_marker(self):
        self.feature.write_text(self.feature.read_text(encoding='utf-8').replace(
            '点击后文本为Count:1', '点击后文本为标:add '), encoding='utf-8')
        before = self.files()
        report = self.tool().inspect(self.project)
        self.assertFalse(report['patches'])
        self.assertEqual(self.files(), before)

    def test_only_formal_source_target_slot_changes_and_expected_stays_exact(self):
        self.short_target()
        expected = '判:ui | 点击后文本为标:add ，并显示源:Example → 标:add '
        self.feature.write_text(self.feature.read_text(encoding='utf-8').replace(
            '判:ui | 点击后文本为Count:1', expected), encoding='utf-8')
        tool = self.tool(); report = tool.inspect(self.project)
        patch = next(p for p in report['patches'] if p['path'].endswith('.md'))
        self.assertIn(expected, patch['content'])
        self.assertIn('源:Counter.body → 标:CounterPage.add', patch['content'])
        self.assertEqual(len(patch['operations']), 1)
        tool.apply(self.project, report, patch_ids=[patch['patch_id']])
        self.assertIn(expected, self.feature.read_text(encoding='utf-8'))

    def test_standalone_short_target_without_source_slot_is_manual(self):
        self.feature.write_text(self.feature.read_text(encoding='utf-8').replace(
            '源:Counter.body → 标:CounterPage.add', '标:add'), encoding='utf-8')
        report = self.tool().inspect(self.project)
        self.assertFalse(report['patches'])
        self.assertTrue(any(f['rule'] == 'UPGRADE.TARGET_MANUAL' for f in report['manual']))


if __name__ == '__main__':
    unittest.main()
