"""Coverage must retain a deterministic feature/source boundary."""
import json
import os
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import MigrationError, digest, json_bytes, read_json, write_json
from hmigbot_ios.ios_harness import _coverage_source_paths, ac_inventory, check


class CoverageOwnershipTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='coverage ownership ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source, self.project = self.root / 'source', self.root / 'project'
        self.source.mkdir()
        (self.project / 'spec/baseline/features').mkdir(parents=True)
        (self.project / 'spec/ref').mkdir(parents=True)
        for name in ('Account.swift', 'Widget.swift', 'Shared.swift'):
            (self.source / name).write_text('struct Example {}\n', encoding='utf-8')
        self.feature = self.project / 'spec/baseline/features/F001-account.md'
        self.feature.write_text('''source_anchors:
  - path: Account.swift
# Account
## 验收标准
- [ ] F001-AC01 Account input updates displayed value `判:ui | expected account value`
''', encoding='utf-8')
        (self.project / 'spec/baseline/features/F002-widget.md').write_text('''source_anchors:
  - path: Widget.swift
# Widget
## 验收标准
- [ ] F002-AC01 Widget input updates displayed value `判:ui | expected widget value`
''', encoding='utf-8')

    def paths(self, ident='F001-AC01'):
        return _coverage_source_paths(self.project, self.source, ident, ac_inventory(self.project)[ident])

    def reference(self, ref):
        self.feature.write_text('contract_refs: ' + json.dumps([ref]) + '\n' + self.feature.read_text(encoding='utf-8'), encoding='utf-8')

    def test_ownership_comes_from_ac_main_feature_not_other_feature_or_review_text(self):
        inventory = ac_inventory(self.project)
        self.assertEqual(inventory['F001-AC01']['feature_id'], 'F001')
        self.assertEqual(inventory['F001-AC01']['source_paths'], ['Account.swift'])
        self.assertEqual(self.paths(), {'Account.swift'})
        self.assertNotIn('Widget.swift', self.paths())
        self.assertEqual(self.paths('F002-AC01'), {'Widget.swift'})

    def test_addendum_uses_main_feature_anchors(self):
        addendum = self.project / 'spec/baseline/features/F001-account.details.md'
        addendum.write_text('source_anchors:\n  - path: Widget.swift\n'
                            '- [ ] F001-AC02 Addendum expected value `判:ui | expected value`\n', encoding='utf-8')
        self.assertEqual(self.paths('F001-AC02'), {'Account.swift'})

    def test_ac_cannot_impersonate_another_feature(self):
        self.feature.write_text(self.feature.read_text(encoding='utf-8').replace('F001-AC01', 'F002-AC99'), encoding='utf-8')
        with self.assertRaisesRegex(MigrationError, 'main feature'):
            ac_inventory(self.project)

    def test_missing_anchors_cannot_be_replaced_by_generic_base_reference(self):
        self.feature.write_text(self.feature.read_text(encoding='utf-8').replace(
            'source_anchors:\n  - path: Account.swift\n', ''), encoding='utf-8')
        (self.project / 'spec/baseline/feature-base.md').write_text('''source_anchors:
  - path: Widget.swift
# Base
## Common model
Shared application model; F001 and F002 consume the base contract.
## Widget behavior
Widget.swift:1
''', encoding='utf-8')
        self.reference('spec/baseline/feature-base.md#Common model')
        self.assertEqual(self.paths(), set())

    def test_ambiguous_shared_heading_cannot_authorize_source(self):
        (self.project / 'spec/ref/shared.md').write_text(
            '# Shared\n## Service\nShared.swift:1\n## Service\nWidget.swift:1\n', encoding='utf-8')
        self.reference('spec/ref/shared.md#Service')
        with self.assertRaisesRegex(MigrationError, 'exact existing heading'):
            self.paths()

    def test_exact_shared_contract_allows_real_evidence_without_granting_other_sections(self):
        shared = self.project / 'spec/ref/shared.md'
        shared.write_text('''source_anchors:
  - path: Widget.swift
# Shared
## Account service
| 源证据 | 定义方/消费方 |
|---|---|
| Shared.swift:1 | F001/F002 |
## Widget service
Widget.swift:1
''', encoding='utf-8')
        self.reference('spec/ref/shared.md#Account service')
        self.assertEqual(self.paths(), {'Account.swift', 'Shared.swift'})

    def test_transitive_exact_shared_contract_is_supported(self):
        (self.project / 'spec/ref/outer.md').write_text('contract_refs: ["spec/ref/inner.md#Service"]\n# Outer\n## Service\nDelegates to shared service.\n', encoding='utf-8')
        (self.project / 'spec/ref/inner.md').write_text('# Inner\n## Service\nShared.swift:1\n', encoding='utf-8')
        self.reference('spec/ref/outer.md#Service')
        self.assertIn('Shared.swift', self.paths())

    def test_scratch_reference_and_code_example_do_not_expand_ownership(self):
        (self.project / 'spec/ref/scratch.md').write_text('# Scratch\n## Service\nWidget.swift:1\n', encoding='utf-8')
        shared = self.project / 'spec/ref/shared.md'
        shared.write_text('# Shared\n## Service\n```swift\nWidget.swift:1\n```\n', encoding='utf-8')
        self.reference('spec/ref/shared.md#Service')
        self.assertEqual(self.paths(), {'Account.swift'})

    def test_shared_contract_requires_existing_source_and_current_line(self):
        shared = self.project / 'spec/ref/shared.md'
        shared.write_text('# Shared\n## Service\nShared.swift:99\n', encoding='utf-8')
        self.reference('spec/ref/shared.md#Service')
        with self.assertRaisesRegex(MigrationError, 'outside file'):
            self.paths()

    def test_shared_action_is_bound_to_its_owner_ac_and_active_scope(self):
        shared = self.project / 'spec/ref/actions.md'
        action = {'action_id': 'F001-A01', 'owner': 'F001', 'target': 'SharedService.update',
                  'source_anchors': [{'path': 'Shared.swift', 'line': 1}],
                  'immediate_effect': 'requests update', 'completion_event': 'handler return',
                  'final_effect': 'value changes', 'failure_cancel': 'no async work',
                  'scope': 'active', 'ac_ids': ['F001-AC01']}

        def write_action():
            shared.write_text('# Actions\n## Update\n```action-contract\n' + json.dumps(action) + '\n```\n', encoding='utf-8')

        write_action()
        self.reference('spec/ref/actions.md#Update')
        self.assertIn('Shared.swift', self.paths())
        action['ac_ids'] = ['F001-AC02']
        write_action()
        self.assertNotIn('Shared.swift', self.paths())
        action['ac_ids'] = ['F001-AC01']
        action['scope'] = 'skipped'
        action['skip_ref'] = 'spec/baseline/skip-list.md#Skip'
        action['decision_ref'] = 'spec/decision-ledger.md#Decision'
        write_action()
        self.assertNotIn('Shared.swift', self.paths())


class CoverageOwnershipHarnessTests(unittest.TestCase):
    def test_unrelated_feature_mapping_fails_even_with_ui_judgment_and_complete_review(self):
        from test_ios_harness import fixture
        from hmigbot_ios.ios_facts import RULES, refresh
        from hmigbot_ios.ios_literals import run as literal_index
        from hmigbot_ios.native_pipeline import refresh_source_index
        temp = tempfile.TemporaryDirectory(prefix='cross feature harness ')
        self.addCleanup(temp.cleanup)
        source, project, original_graph = fixture(Path(temp.name))
        (source / 'Widget.swift').write_text((source / 'Counter.swift').read_text(encoding='utf-8').replace('Counter', 'Widget'), encoding='utf-8')
        feature = project / 'spec/baseline/features/F001-counter.md'
        (feature.parent / 'F002-widget.md').write_text(feature.read_text(encoding='utf-8').replace('F001', 'F002').replace('Counter', 'Widget'), encoding='utf-8')
        graph = refresh(project, source)
        review = Path(temp.name) / 'source-review.json'
        write_json(review, {'previous_source_sha256': original_graph['source_sha256'],
                            'source_sha256': graph['source_sha256'], 'reviewer': 'fixture',
                            'reason': 'Added isolated Widget source to test cross-feature bindings'})
        refresh_source_index(project, review)
        literal_index(project)
        semantics_path = project / 'spec/baseline/ios-semantics.json'
        semantics = read_json(semantics_path)
        widget = deepcopy(semantics['documents'][0])
        widget['id'] = 'F002'
        for dimension, claim in widget['facts'].items():
            relevant = [fact for fact in graph['facts'] if fact['anchor']['path'] == 'Widget.swift'
                        and dimension in RULES[fact['kind']]['dimensions']]
            if relevant:
                claim['fact_ids'] = [fact['id'] for fact in relevant]
                claim['evidence'] = [{'path': fact['anchor']['path'], 'line': fact['anchor']['line']} for fact in relevant]
                if dimension == 'state_ownership':
                    claim['value'] = {'states': [{'fact_id': fact['id'], 'owner': fact['owner'], **fact['value']}
                                                 for fact in relevant if fact['kind'] == 'state']}
        semantics['documents'].append(widget)
        write_json(semantics_path, semantics)
        obligations = read_json(project / 'spec/baseline/ios-obligations.json')['obligations']
        coverage_path = project / 'spec/baseline/ios-coverage.json'
        coverage = read_json(coverage_path)
        template = coverage['mappings'][0]
        coverage['graph_sha256'] = digest(json_bytes(graph))
        facts = {fact['id']: fact for fact in graph['facts']}
        widget_ids = {o['id'] for o in obligations if facts[o['fact_id']]['anchor']['path'] == 'Widget.swift'}
        coverage['mappings'] = [{**template, 'obligation_id': obligation['id'],
                                 'ac_ids': ['F002-AC01' if obligation['id'] in widget_ids else 'F001-AC01']}
                                for obligation in obligations]
        write_json(coverage_path, coverage)
        # Isolate ownership from expertise refresh: all files and facts above
        # are real and validate_graph still re-extracts the complete graph.
        with patch('hmigbot_ios.expertise.check', return_value={}):
            valid_report, valid_code = check(project, report_only=True)
        self.assertEqual(valid_code, 0, valid_report)
        for mapping in coverage['mappings']:
            mapping['ac_ids'] = ['F001-AC01']
        write_json(coverage_path, coverage)
        with patch('hmigbot_ios.expertise.check', return_value={}):
            report, code = check(project, report_only=True)
        mismatches = [f for f in report['findings'] if f['rule'] == 'IOS.OBLIGATION_FEATURE_MISMATCH']
        self.assertEqual(code, 2)
        self.assertTrue(widget_ids)
        self.assertEqual({f['subject'].split(':')[0] for f in mismatches}, widget_ids)
        self.assertTrue(all('Widget.swift' in f['detail'] for f in mismatches))
        self.assertEqual(report['excluded_obligation_ids'], [])
        self.assertEqual({m['obligation_id'] for m in read_json(coverage_path)['mappings']}, {o['id'] for o in obligations})


if __name__ == '__main__':
    unittest.main()
