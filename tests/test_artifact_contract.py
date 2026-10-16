"""Profile 2 must validate real content, references and schemas without writing state."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import read_json, write_json
from hmigbot_ios.spec_contract import check
from spec_contract_fixture import complete_contract, strict_contract
from test_ios_harness import fixture


class ArtifactContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='spec-v2-')
        self.addCleanup(temporary.cleanup)
        self.source, self.project, _ = fixture(Path(temporary.name))
        self.feature = self.project / 'spec/baseline/features/F001-counter.md'
        strict_contract(self.project)

    def rules(self):
        return {f['rule'] for f in check(self.project)[0]['findings']}

    def replace(self, path, old, new):
        self.assertIn(old, path.read_text(encoding='utf-8'), 'Mutation must hit the intended contract')
        path.write_text(path.read_text(encoding='utf-8').replace(old, new), encoding='utf-8')

    def test_strict_contract_and_upgrade_preserve_business_ids(self):
        report, code = check(self.project)
        self.assertEqual(code, 0, report)
        self.assertEqual(report['spec_contract_version'], 2)
        self.assertFalse(report['behavior_verified'])
        self.assertIn('F001-AC01', self.feature.read_text(encoding='utf-8'))

    def test_legacy_fixture_explicitly_selects_version_one(self):
        complete_contract(self.project)
        self.assertEqual(read_json(self.project / '.migbot/config.json')['ios_harness']['spec_contract_version'], 1)
        self.assertEqual(check(self.project)[1], 0)

    def test_missing_core_outline_and_wrong_header_are_not_accepted(self):
        path = self.project / 'spec/baseline/feature-index.md'
        self.replace(path, '## 依赖图', '## Misc')
        self.replace(path, '| 排序依赖 |', '| 依赖 |')
        self.assertIn('IOS.SPEC_ARTIFACT_SECTION', self.rules())
        self.assertIn('IOS.SPEC_ARTIFACT_TABLE', self.rules())

    def test_code_fence_cannot_satisfy_missing_heading(self):
        path = self.project / 'spec/baseline/feature-index.md'
        self.replace(path, '## 依赖图\nbase -> F001', '```markdown\n## 依赖图\nbase -> F001\n```')
        self.assertIn('IOS.SPEC_ARTIFACT_SECTION', self.rules())

    def test_duplicate_headings_cannot_hide_empty_section(self):
        path = self.project / 'spec/baseline/feature-base.md'
        path.write_text(path.read_text(encoding='utf-8') + '\n## 数据模型\n', encoding='utf-8')
        self.assertIn('IOS.SPEC_ARTIFACT_HEADING_DUPLICATE', self.rules())

    def test_page_generic_layout_is_rejected(self):
        path = self.project / 'spec/baseline/ui/page_0001_Counter.md'
        self.replace(path, '| root | - | VStack | Column | count and Add | Counter.swift:5 |', '')
        self.assertIn('IOS.SPEC_ARTIFACT_TABLE', self.rules())

    def test_feature_shape_cannot_hide_under_similar_section_name(self):
        self.replace(self.feature, '## 源行为表', '## 源行为摘要')
        self.assertIn('IOS.SPEC_ARTIFACT_SECTION', self.rules())

    def test_page_state_and_event_columns_are_contracts(self):
        path = self.project / 'spec/baseline/ui/page_0001_Counter.md'
        self.replace(path, '| UI 影响 |', '| Notes |')
        self.assertIn('IOS.SPEC_ARTIFACT_TABLE', self.rules())

    def test_unknown_and_na_without_evidence_are_blocking(self):
        path = self.project / 'spec/baseline/feature-base.md'
        self.replace(path, 'not_applicable: no network; source: Counter.swift:1-10', 'not_applicable: none')
        self.assertIn('IOS.SPEC_ARTIFACT_NA_EVIDENCE', self.rules())
        self.replace(path, 'not_applicable: none', 'unknown: pending source review')
        self.assertIn('IOS.SPEC_ARTIFACT_UNRESOLVED', self.rules())

    def test_missing_meta_wrong_type_and_source_are_rejected(self):
        path = self.project / 'spec/baseline/ui-snapshots/page_0001/meta.json'
        metadata = read_json(path)
        metadata['frameworks'] = 'swiftui'
        metadata['source_anchors'][0]['path'] = '../outside.swift'
        write_json(path, metadata)
        self.assertIn('IOS.SPEC_ARTIFACT_JSON', self.rules())
        path.unlink()
        self.assertIn('IOS.SPEC_ARTIFACT_MISSING', self.rules())

    def test_meta_optional_fields_are_typed_and_dual_source_views_agree(self):
        path = self.project / 'spec/baseline/ui-snapshots/page_0001/meta.json'
        metadata = read_json(path); metadata['needs_immersive_safearea'] = 'false'
        write_json(path, metadata)
        self.assertIn('IOS.SPEC_ARTIFACT_JSON', self.rules())
        metadata['needs_immersive_safearea'] = False
        metadata['source_refs'] = ['Counter.swift:7']
        write_json(path, metadata)
        self.assertIn('IOS.SPEC_ARTIFACT_META_EVIDENCE', self.rules())

    def test_screenshot_evidence_is_not_invented(self):
        path = self.project / 'spec/baseline/ui-snapshots/page_0001/meta.json'
        metadata = read_json(path); metadata['runtime'] = 'captured'
        write_json(path, metadata)
        self.assertIn('IOS.SPEC_ARTIFACT_META_EVIDENCE', self.rules())

    def add_action(self, suffix=''):
        self.replace(self.feature, 'action_contracts: not_applicable', 'action_contracts: required')
        action = {'action_id': 'F001-A01', 'owner': 'F001', 'target': 'CounterPage.add',
                  'source_anchors': [{'path': 'Counter.swift', 'line': 7}],
                  'immediate_effect': 'count increments by one', 'completion_event': 'handler-return',
                  'final_effect': 'Text displays Count:1', 'failure_cancel': 'No async work exists',
                  'scope': 'active', 'ac_ids': ['F001-AC01']}
        self.feature.write_text(self.feature.read_text(encoding='utf-8') + '\n## Add action\n```action-contract\n' + json.dumps(action) + '\n```\n' + suffix, encoding='utf-8')
        return action

    def test_high_risk_action_requires_definition_or_reference(self):
        self.replace(self.feature, 'action_contracts: not_applicable', 'action_contracts: required')
        self.assertIn('IOS.SPEC_ACTION_REQUIRED', self.rules())

    def test_unique_definition_and_exact_use_pass(self):
        self.add_action()
        page = self.project / 'spec/baseline/ui/page_0001_Counter.md'
        use = {'action_id': 'F001-A01', 'contract_ref': 'spec/baseline/features/F001-counter.md#Add action', 'ac_ids': ['F001-AC01']}
        page.write_text(page.read_text(encoding='utf-8') + '\ncontract_refs: ["' + use['contract_ref'] + '"]\n## Shared Add action\n```action-use\n' + json.dumps(use) + '\n```\n', encoding='utf-8')
        self.assertEqual(check(self.project)[1], 0, check(self.project)[0])

    def test_action_use_must_enter_transitive_consumer_inputs(self):
        self.add_action()
        use = {'action_id': 'F001-A01', 'contract_ref': 'spec/baseline/features/F001-counter.md#Add action', 'ac_ids': ['F001-AC01']}
        page = self.project / 'spec/baseline/ui/page_0001_Counter.md'
        page.write_text(page.read_text(encoding='utf-8') + '\n## Use\n```action-use\n' + json.dumps(use) + '\n```\n', encoding='utf-8')
        self.assertIn('IOS.SPEC_ACTION_REFERENCE', self.rules())

    def test_nested_shared_definition_enters_actual_reference_closure(self):
        self.add_action()
        text = self.feature.read_text(encoding='utf-8')
        before, action = text.split('\n## Add action\n', 1)
        shared = self.project / 'spec/ref/contracts/deep/counter.md'
        shared.parent.mkdir(parents=True)
        shared.write_text('# Shared counter\n## 服务层\nCounterPage.add increments count.\n## Add action\n' + action, encoding='utf-8')
        ref = 'spec/ref/contracts/deep/counter.md#Add action'
        use = {'action_id': 'F001-A01', 'contract_ref': ref, 'ac_ids': ['F001-AC01']}
        self.feature.write_text(before.replace('contract_refs:\n', 'contract_refs:\n  - ' + ref + '\n') +
                                '\n## Shared Add\n```action-use\n' + json.dumps(use) + '\n```\n', encoding='utf-8')
        report, code = check(self.project)
        self.assertEqual(code, 0, report)
        self.assertIn(shared.relative_to(self.project).as_posix(), report['inputs'])

    def test_unreferenced_scratch_does_not_create_active_action_contract(self):
        scratch = self.project / 'spec/ref/unreviewed-scratch.md'
        scratch.write_text('# Scratch example\n## Idea\n```action-contract\n{"unfinished": true}\n```\n', encoding='utf-8')
        report, code = check(self.project)
        self.assertEqual(code, 0, report)
        self.assertNotIn(scratch.relative_to(self.project).as_posix(), report['inputs'])

    def test_duplicate_definition_and_completion_conflict_are_rejected(self):
        action = self.add_action()
        action['completion_event'] = 'later-callback'
        self.feature.write_text(self.feature.read_text(encoding='utf-8') + '\n## Different Add\n```action-contract\n' + json.dumps(action) + '\n```\n', encoding='utf-8')
        self.assertIn('IOS.SPEC_ACTION_DUPLICATE', self.rules())
        self.assertIn('IOS.SPEC_ACTION_CONFLICT', self.rules())

    def test_active_use_cannot_reference_skipped_definition_or_wrong_heading(self):
        action = self.add_action()
        self.replace(self.feature, '"scope": "active"', '"scope": "skipped"')
        use = {'action_id': 'F001-A01', 'contract_ref': 'spec/baseline/features/F001-counter.md#Add action', 'ac_ids': ['F001-AC01']}
        page = self.project / 'spec/baseline/ui/page_0001_Counter.md'
        page.write_text(page.read_text(encoding='utf-8') + '\ncontract_refs: ["' + use['contract_ref'] + '"]\n## Use\n```action-use\n' + json.dumps(use) + '\n```\n', encoding='utf-8')
        self.assertIn('IOS.SPEC_ACTION_SKIPPED', self.rules())
        self.replace(page, '#Add action', '#不存在')
        self.assertIn('IOS.SPEC_ACTION_REFERENCE', self.rules())

    def test_action_owner_ac_and_source_must_resolve(self):
        self.add_action()
        self.replace(self.feature, '"owner": "F001"', '"owner": "F999"')
        self.replace(self.feature, '"F001-AC01"]', '"F001-AC99"]')
        self.assertIn('IOS.SPEC_ACTION_OWNER', self.rules())
        self.assertIn('IOS.SPEC_ACTION_AC', self.rules())

    def test_optional_json_is_validated_when_present_and_frozen(self):
        from hmigbot_ios.spec_contract import dependency_inputs
        path = self.project / 'spec/baseline/api-inventory.json'
        write_json(path, {'schema_version': 1, 'source_platform': 'ios', 'services': 'not-a-list'})
        self.assertIn('IOS.SPEC_ARTIFACT_JSON', self.rules())
        self.assertIn('spec/baseline/api-inventory.json', dependency_inputs(self.project))

    def test_optional_api_and_state_machine_resolve_true_contracts(self):
        shared = self.project / 'spec/ref/remote-contract.md'
        shared.write_text('# Remote\n## Public\nGET /count returns integer count.\n', encoding='utf-8')
        ref = 'spec/ref/remote-contract.md#Public'
        write_json(self.project / 'spec/baseline/api-inventory.json', {
            'source_platform': 'ios', 'services': [{'auth_type': 'none', 'endpoints': [
                {'id': 'API-count', 'static': {'http_method': 'GET', 'path': '/count', 'protocol': 'https'}}]}]})
        write_json(self.project / 'spec/baseline/api-contract-links.json', {
            'schema_version': 1, 'source_platform': 'ios', 'endpoints': [
                {'id': 'API-count', 'feature_ids': ['F001'], 'contract_ref': ref,
                 'source_anchors': [{'path': 'Counter.swift', 'line': 7}]}]})
        machine = {'schema_version': 1, 'source_platform': 'ios', 'feature_id': 'F001',
                   'contract_ref': ref, 'states': ['zero', 'one'], 'transitions': [
                       {'from': 'zero', 'event': 'add', 'to': 'one', 'ac_ids': ['F001-AC01'],
                        'source_anchors': [{'path': 'Counter.swift', 'line': 7}]}]}
        path = self.project / 'spec/baseline/features/F001-counter.state-machine.json'
        write_json(path, machine)
        self.assertEqual(check(self.project)[1], 0, check(self.project)[0])
        from hmigbot_ios.spec_contract import dependency_inputs
        self.assertIn('spec/ref/remote-contract.md', dependency_inputs(self.project))
        machine['transitions'][0]['to'] = 'undefined'
        write_json(path, machine)
        self.assertIn('IOS.SPEC_ARTIFACT_JSON', self.rules())

    def test_original_api_services_contract_is_preserved(self):
        path = self.project / 'spec/baseline/api-inventory.json'
        value = {'source_platform': 'ios', 'services': [{'auth_type': 'none', 'endpoints': [
            {'id': 'API-count', 'static': {'http_method': 'GET', 'path': '/count', 'protocol': 'https'}}]}]}
        write_json(path, value)
        self.assertEqual(check(self.project)[1], 0, check(self.project)[0])
        value['services'][0]['endpoints'][0]['static']['http_method'] = 7
        write_json(path, value)
        self.assertIn('IOS.SPEC_ARTIFACT_JSON', self.rules())

    def test_excluded_action_does_not_excuse_uncovered_source_obligation(self):
        from hmigbot_ios.ios_harness import check as harness_check
        self.add_action()
        self.replace(self.feature, '"scope": "active"', '"scope": "skipped"')
        self.assertIn('IOS.SPEC_ACTION_SKIPPED_SCOPE', self.rules())
        coverage_path = self.project / 'spec/baseline/ios-coverage.json'
        coverage = read_json(coverage_path); coverage['mappings'] = []
        write_json(coverage_path, coverage)
        report, code = harness_check(self.project)
        self.assertEqual(code, 2)
        self.assertIn('IOS.OBLIGATION_UNCOVERED', {f['rule'] for f in report['findings']})

    def test_meta_not_run_cannot_carry_screenshot(self):
        path = self.project / 'spec/baseline/ui-snapshots/page_0001/meta.json'
        screenshot = self.project / 'spec/baseline/ui-snapshots/page_0001/old.png'
        screenshot.write_bytes(b'fixture-existing-capture')
        metadata = read_json(path); metadata['screenshot'] = screenshot.relative_to(self.project).as_posix()
        write_json(path, metadata)
        self.assertIn('IOS.SPEC_ARTIFACT_META_EVIDENCE', self.rules())

    def test_source_reference_can_point_to_path_with_spaces(self):
        target = self.source / 'Folder With Spaces/Count View.swift'
        target.parent.mkdir(); target.write_text('struct CountView {}\n', encoding='utf-8')
        path = self.project / 'spec/baseline/feature-base.md'
        self.replace(path, 'not_applicable: no network; source: Counter.swift:1-10',
                     'not_applicable: no networking in the source view; source: Folder With Spaces/Count View.swift:1')
        self.assertEqual(check(self.project)[1], 0, check(self.project)[0])

    def test_unknown_schema_constraint_cannot_silently_be_ignored(self):
        from unittest.mock import patch
        from hmigbot_ios.artifact_contract import validate_json
        from hmigbot_ios.core import MigrationError
        with patch('hmigbot_ios.artifact_contract.read_json', return_value={'$defs': {'sample': {'type': 'object', 'unevaluatedProperties': False}}}):
            with self.assertRaises(MigrationError): validate_json({}, 'sample')

    def test_profile_must_be_integer_and_missing_keeps_legacy(self):
        path = self.project / '.migbot/config.json'
        config = read_json(path)
        config['ios_harness']['spec_contract_version'] = True
        write_json(path, config)
        self.assertIn('IOS.SPEC_ARTIFACT_PROFILE', self.rules())
        config['ios_harness'].pop('spec_contract_version')
        write_json(path, config)
        self.assertEqual(check(self.project)[1], 0, check(self.project)[0])

    def test_version_two_check_is_read_only(self):
        before = {p.relative_to(self.project): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        check(self.project)
        self.assertEqual(before, {p.relative_to(self.project): p.read_bytes() for p in self.project.rglob('*') if p.is_file()})

    def test_parser_preserves_duplicate_heading_and_escaped_table_cell(self):
        from hmigbot_ios.artifact_contract import markdown_sections, markdown_tables
        text = '# A\n## Same\nfirst\n## Same\nsecond\n```markdown\n## Fake\n| x |\n|---|\n| fake |\n```\n| A | B |\n|---|---|\n| a\\|b | c |\n'
        self.assertEqual([s['title'] for s in markdown_sections(text)], ['A', 'Same', 'Same'])
        self.assertEqual(markdown_tables(text)[0]['rows'][0], ['a|b', 'c'])

    def test_optional_feature_addendum_does_not_redeclare_main_outline(self):
        path = self.project / 'spec/baseline/features/F001-counter.impl.md'
        path.write_text('# Addendum\n## Algorithm\nCounter state remains page owned.\n', encoding='utf-8')
        self.assertEqual(check(self.project)[1], 0, check(self.project)[0])

    def test_shipped_templates_and_schema_examples_match_catalog(self):
        from hmigbot_ios.artifact_contract import catalog, markdown_sections, markdown_tables, validate_json
        templates = ROOT / 'skills/a2h-spec/templates'
        names = {'feature-base.md': 'feature-base-template.md', 'feature-index.md': 'feature-index-template.md',
                 'ui-manifest.md': 'ui-manifest-template.md', 'skip-list.md': 'skip-list-template.md',
                 'source-coverage-report.md': 'source-coverage-report-template.md',
                 'spec/baseline/features/F*.md': 'feature-spec-template.md', 'spec/baseline/ui/page_*.md': 'page-spec-template.md'}
        import re
        for entry in catalog()['spec']:
            key = entry.get('glob', Path(entry.get('path', '')).name)
            if key not in names:
                continue
            text = (templates / names[key]).read_text(encoding='utf-8-sig')
            if key == 'feature-index.md':
                text = re.search(r'```markdown\s*\n(.*?)\n```', text, re.S)[1]
            parts = markdown_sections(text)
            for rule in entry['sections']:
                with self.subTest(template=names[key], heading=rule['title']):
                    part = next((p for p in parts if p['title'] == rule['title']), None)
                    self.assertIsNotNone(part)
                    if 'headers' in rule:
                        self.assertTrue(any(t['headers'] == rule['headers'] for t in markdown_tables(part['body'])))
        for path, definition in [(templates / 'meta-json-schema.md', 'page_meta'),
                                  (ROOT / 'skills/a2h-spec/references/action-contracts.md', 'action_contract')]:
            text = path.read_text(encoding='utf-8-sig')
            info = 'json' if definition == 'page_meta' else 'action-contract'
            block = re.search(r'```' + info + r'\s*\n(.*?)\n```', text, re.S)[1]
            validate_json(json.loads(block), definition)


if __name__ == '__main__':
    unittest.main()
