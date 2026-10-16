"""Read-only v2 plan correspondence, freeze and consumer regression cases."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import shutil
from contextlib import redirect_stdout
from io import StringIO

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import MigrationError, digest, json_bytes, read_json, write_json
from hmigbot_ios.harness_schema import validate
from hmigbot_ios.plan_contract import validate_plan, structural_digest, task_inputs, assert_pinned


class PlanContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        write_json(self.project / '.migbot/config.json', {'ios_harness': {'spec_contract_version': 2}})
        self.base = self.project / 'spec/baseline'
        (self.base / 'plans/slices').mkdir(parents=True)
        (self.base / 'features').mkdir()
        (self.base / 'ui').mkdir()
        (self.project / 'spec/ref').mkdir()
        (self.base / 'features/F001-counter.md').write_text('# F001\ncontract_refs: ["spec/ref/shared.md#Public"]\n## Acceptance\n- [ ] F001-AC01 Add `判:ui | Count:1`\n', encoding='utf-8')
        (self.base / 'ui/page_0001_Counter.md').write_text('# page_0001\n## State\nF001-AC01\n', encoding='utf-8')
        (self.project / 'spec/ref/shared.md').write_text('# Contract\ncontract_refs: ["spec/ref/deeper.md#Cancel"]\n## Public\nCounter.add returns Count:1\n', encoding='utf-8')
        (self.project / 'spec/ref/deeper.md').write_text('# Async\n## Cancel\nWait for completion callback.\n', encoding='utf-8')
        (self.base / 'feature-index.md').write_text('# Features\n## 功能清单\n| ID | 功能 | 优先级 | 排序依赖 | 契约依赖 | 关联页面 | 创建页面 | complexity | tier | depth | 状态 | spec |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n| F001 | Counter | P0 | Base | 无 | page_0001 | page_0001 | simple | standard | full | pending | features/F001-counter.md |\n', encoding='utf-8')
        (self.base / 'ui-manifest.md').write_text('# UI\n## 页面与覆盖层\n| page_id | 源文件/入口/框架 | 类型 | ArkTS 目标文件/组件 | 功能归属 | 优先级 | confidence | 状态 | spec |\n|---|---|---|---|---|---|---|---|---|\n| page_0001 | Counter.swift:2/entry/swiftui | page | entry/Counter.ets | F001 | P0 | high | pending | spec/baseline/ui/page_0001_Counter.md |\n', encoding='utf-8')
        self.items = [
            {'item_id': 'BASE:Base-0', 'ac_ids': [], 'ownership': ['entry/Base.ets'], 'parents': [], 'page_ids': [], 'scope': 'product', 'verification': 'generated'},
            {'item_id': 'UI:PAGE-0001', 'ac_ids': ['F001-AC01'], 'ownership': ['entry/Counter.ets'], 'parents': ['BASE:Base-0'], 'page_ids': ['page_0001'], 'scope': 'product', 'verification': 'generated'},
            {'item_id': 'SLICE:F001:3a', 'ac_ids': ['F001-AC01'], 'ownership': ['entry/CounterService.ets'], 'parents': ['BASE:Base-0'], 'page_ids': ['page_0001'], 'scope': 'product', 'verification': 'generated'},
            {'item_id': 'FV:FV-1', 'ac_ids': ['F001-AC01'], 'ownership': [], 'parents': ['UI:PAGE-0001', 'SLICE:F001:3a'], 'page_ids': [], 'scope': 'product', 'verification': 'compile'},
            {'item_id': 'FV:FV-2', 'ac_ids': ['F001-AC01'], 'ownership': [], 'parents': ['FV:FV-1'], 'page_ids': [], 'scope': 'product', 'verification': 'compile'},
        ]
        self.write_plans()
        self.request = {'schema_version': 2, 'wave': 'domains', 'graph_sha256': 'a' * 64, 'tasks': [
            self.task('base', self.items[:1]),
            self.task('counter', self.items[1:3], parents=['base'], mapping_reason='UI and service share one owner'),
            self.task('final', self.items[3:], parents=['counter'], mapping_reason='One read-only owner runs structural check before final compilation'),
        ]}

    def tearDown(self):
        self.temp.cleanup()

    def task(self, ident, items, parents=None, **extra):
        return {'id': ident, 'role': 'a2h-ios-converter', 'goal': 'Implement ' + ident,
                'fact_ids': ['fact-counter'], 'ac_ids': sorted({a for item in items for a in item['ac_ids']}),
                'ownership': sorted({p for item in items for p in item['ownership']}), 'parents': parents or [],
                'plan_item_refs': [i['item_id'] for i in items], 'verification': items[-1]['verification'], **extra}

    def write_plans(self):
        for prefix, name in [('BASE:', 'base-plan.md'), ('UI:', 'ui-plan.md'), ('SLICE:', 'slices/slice-01-F001.md'), ('FV:', 'feature-plan.md')]:
            subset = [i for i in self.items if i['item_id'].startswith(prefix)]
            text = '# Plan\nplan_format: indexed-v1\n'
            if prefix == 'FV:':
                text += '\n## Base\ndetail: plans/base-plan.md\n\n## Slice F001\ndetail: plans/slices/slice-01-F001.md\n'
            if prefix == 'UI:':
                text += '\n## Batch 1\n| item_id | 目标文件 | ac_ids | owning_slice |\n|---|---|---|---|\n'
                for item in subset:
                    text += '| ' + item['item_id'].split(':', 1)[1] + ' | ' + item['ownership'][0] + ' | ' + json.dumps(item['ac_ids']) + ' | F001 |\n'
            for item in subset:
                text += self.responsibility(item)
            text += '\n```json\n' + json.dumps({'plan_items_version': 2, 'items': subset}) + '\n```\n'
            (self.base / 'plans' / name).write_text(text, encoding='utf-8')

    def responsibility(self, item):
        return '\n### ' + item['item_id'] + '\n| 字段 | 值 |\n|---|---|\n' + ''.join(
            '| ' + field + ' | ' + json.dumps(value) + ' |\n' for field, value in item.items())

    def test_valid_explicit_merge_and_transitive_consumer(self):
        result = validate_plan(self.project, self.request)
        self.assertEqual(result['status'], 'PASS')
        refs = result['task_inputs']['counter']
        self.assertTrue(any(r['path'] == 'spec/ref/deeper.md' and r['heading'] == 'Cancel' for r in refs))
        self.assertTrue(all(len(r['sha256']) == 64 for r in refs))

    def test_missing_mapping_is_rejected(self):
        self.request['tasks'][1].pop('plan_item_refs')
        with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_merge_requires_reason(self):
        self.request['tasks'][1].pop('mapping_reason')
        with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_ownership_and_acceptance_cannot_drift(self):
        for field, values in [('ownership', ['entry/Other.ets']), ('ac_ids', ['F002-AC01'])]:
            with self.subTest(field=field):
                request = copy.deepcopy(self.request); request['tasks'][1][field] = values
                with self.assertRaises(MigrationError): validate_plan(self.project, request)

    def test_missing_md_item_cannot_be_hidden(self):
        self.request['tasks'].pop()
        with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_excluded_scope_cannot_enter_execution(self):
        self.items[1]['scope'] = 'excluded'; self.write_plans()
        with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_unknown_dependency_and_dependency_drift_fail(self):
        self.request['tasks'][1]['parents'] = []
        with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_final_verification_obligation_cannot_be_weakened(self):
        self.request['tasks'][-1]['verification'] = 'generated'
        with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_body_missing_item_cannot_be_only_json(self):
        path = self.base / 'plans/ui-plan.md'
        path.write_text('```json\n' + json.dumps({'plan_items_version': 2, 'items': self.items[1:2]}) + '\n```\n', encoding='utf-8')
        with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_ui_manifest_target_must_match_plan(self):
        path = self.base / 'ui-manifest.md'; path.write_text(path.read_text(encoding='utf-8').replace('entry/Counter.ets', 'entry/Other.ets'), encoding='utf-8')
        with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_duplicate_plan_json_item_fails(self):
        self.items.append(copy.deepcopy(self.items[1])); self.write_plans()
        with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_progress_projection_preserves_scope_dependencies_owner(self):
        path = self.base / 'feature-index.md'; original = path.read_text(encoding='utf-8'); before = structural_digest(original, artifact='spec/baseline/feature-index.md')
        self.assertEqual(before, structural_digest(original.replace('pending', 'implemented'), artifact='spec/baseline/feature-index.md'))
        for old, new in [('Base', 'F002'), ('page_0001', 'page_0002'), ('pending', 'skipped')]:
            self.assertNotEqual(before, structural_digest(original.replace(old, new), artifact='spec/baseline/feature-index.md'))

    def test_managed_progress_block_only(self):
        original = '# Index\n<!-- hmigbot-progress:begin -->\n0 of 1\n<!-- hmigbot-progress:end -->\nOwner: core\n'
        self.assertEqual(structural_digest(original), structural_digest(original.replace('0 of 1', '1 of 1')))
        self.assertNotEqual(structural_digest(original), structural_digest(original.replace('core', 'other')))
        with self.assertRaises(MigrationError): structural_digest(original.replace('<!-- hmigbot-progress:end -->', ''))

    def test_managed_progress_cannot_hide_structural_contract(self):
        for content in ['owner: other', 'scope: excluded', 'parents: [other]', 'F001-AC01 now changes',
                        'page_0001 now belongs to another feature', '| ID | 依赖 |\n|---|---|\n| F001 | F002 |',
                        'Counter.reset() clears disk after callback']:
            with self.subTest(content=content):
                with self.assertRaises(MigrationError):
                    structural_digest('# Index\n<!-- hmigbot-progress:begin -->\n' + content + '\n<!-- hmigbot-progress:end -->\n')

    def test_contract_profile_downgrade_is_rejected(self):
        write_json(self.project / '.migbot/config.json', {'ios_harness': {'spec_contract_version': 1}})
        with self.assertRaises(MigrationError): assert_pinned(self.project, {'spec_contract_version': 2, 'contract_revision': 'old'})

    def test_legacy_profile_does_not_require_new_md(self):
        write_json(self.project / '.migbot/config.json', {'ios_harness': {}})
        self.request['tasks'][1].pop('plan_item_refs')
        self.assertEqual(validate_plan(self.project, self.request)['spec_contract_version'], 1)

    def test_schema_rejects_unknown_field_and_nonboolean(self):
        with self.assertRaises(MigrationError): validate({**self.request, 'max_paralell': 2}, 'planRequest')
        with self.assertRaises(MigrationError): validate({**self.request, 'behavior_verified': 0}, 'planRequest')

    def test_schema_requires_explicit_root_parents(self):
        self.request['tasks'][0].pop('parents')
        with self.assertRaises(MigrationError): validate(self.request, 'planRequest')

    def test_schema_replan_review_is_supported_and_strict(self):
        value = {**self.request, 'replan_review': {'reviewer': 'independent', 'reason': 'Reviewed revised scope'}}
        self.assertEqual(validate(value, 'planRequest'), value)
        value['replan_review']['typo'] = True
        with self.assertRaises(MigrationError): validate(value, 'planRequest')

    def test_complete_baseline_freeze_uses_projection_and_keeps_stage0_exception(self):
        from hmigbot_ios.ios_scheduler import baseline_inputs
        path = self.base / 'feature-index.md'
        initial = baseline_inputs(self.project, 'domains')
        text = path.read_text(encoding='utf-8')
        path.write_text(text.replace('pending', 'implemented'), encoding='utf-8')
        self.assertEqual(initial, baseline_inputs(self.project, 'domains'))
        (self.base / 'plans/resource-mapping.md').write_text('Stage 0 produced mapping', encoding='utf-8')
        self.assertEqual(initial, baseline_inputs(self.project, 'domains'))
        path.write_text(text.replace('Base', 'F002'), encoding='utf-8')
        self.assertNotEqual(initial, baseline_inputs(self.project, 'domains'))

    def test_schema_checks_booleans_and_refs_sibling_bounds(self):
        from hmigbot_ios.harness_schema import SCHEMA
        with patch.dict(SCHEMA['$defs'], {'boolProbe': {'type': 'boolean'}, 'boundProbe': {'$ref': '#/$defs/strings', 'minItems': 1}}):
            self.assertTrue(validate(True, 'boolProbe'))
            with self.assertRaises(MigrationError): validate(1, 'boolProbe')
            with self.assertRaises(MigrationError): validate([], 'boundProbe')

    def test_index_scope_can_not_silently_drop_active_feature(self):
        path = self.base / 'feature-index.md'
        path.write_text(path.read_text(encoding='utf-8').replace('F001', 'F002'), encoding='utf-8')
        with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_split_is_explicit_and_covers_the_original_unit(self):
        self.items[2]['ownership'].append('entry/ExtraService.ets'); self.write_plans()
        extra = self.task('extra', self.items[2:3], parents=['base'], mapping_reason='Service output split by owned file')
        extra['ownership'] = ['entry/ExtraService.ets']
        self.request['tasks'].insert(2, extra)
        self.request['tasks'][-1]['parents'].append('extra')
        self.assertEqual(validate_plan(self.project, self.request)['status'], 'PASS')
        self.request['tasks'][2].pop('mapping_reason')
        with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_bounded_markdown_item_cannot_borrow_other_item_files(self):
        other = copy.deepcopy(self.items[0]); other.update(item_id='BASE:Base-1', ownership=['entry/OtherBase.ets'])
        self.items.append(other); self.write_plans()
        path = self.base / 'plans/base-plan.md'
        text = path.read_text(encoding='utf-8'); start = text.index('```json\n') + len('```json\n')
        value = json.loads(text[start:text.index('\n```', start)])
        value['items'][0]['ownership'], value['items'][1]['ownership'] = value['items'][1]['ownership'], value['items'][0]['ownership']
        path.write_text(text[:start] + json.dumps(value) + '\n```\n', encoding='utf-8')
        self.request['tasks'][0] = self.task('base', [self.items[0], other], mapping_reason='Single shared base owner')
        with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_ui_table_row_and_projection_are_the_same_plan(self):
        path = self.base / 'plans/ui-plan.md'
        row = '| item_id | 目标文件 | ac_ids | owning_slice |\n|---|---|---|---|\n| PAGE-0001 | entry/Counter.ets | ["F001-AC01"] | F001 |\n'
        projection = '```json\n' + json.dumps({'plan_items_version': 2, 'items': self.items[1:2]}) + '\n```\n'
        path.write_text('# UI\n## Batch 1\n' + row + self.responsibility(self.items[1]) + projection, encoding='utf-8')
        self.assertEqual(validate_plan(self.project, self.request)['status'], 'PASS')
        path.write_text('# UI\n## Batch 1\n' + row.replace('entry/Counter.ets', 'entry/Other.ets') + self.responsibility(self.items[1]) + projection, encoding='utf-8')
        with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_mixed_merge_preserves_highest_verification_obligation(self):
        self.items[2]['verification'] = 'compile'; self.write_plans()
        self.request['tasks'][1]['verification'] = 'compile'
        self.assertEqual(validate_plan(self.project, self.request)['status'], 'PASS')
        self.request['tasks'][1]['verification'] = 'generated'
        with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_readonly_final_obligation_has_no_invented_outputs(self):
        self.items[-1]['ownership'] = []; self.write_plans()
        self.request['tasks'][-1]['ownership'] = []
        self.assertEqual(validate_plan(self.project, self.request)['status'], 'PASS')

    def test_contract_revision_change_requires_replan(self):
        with self.assertRaises(MigrationError):
            assert_pinned(self.project, {'spec_contract_version': 2, 'contract_revision': '0' * 64})

    def test_index_detail_pointer_must_cover_real_base_and_slices(self):
        path = self.base / 'plans/feature-plan.md'
        text = path.read_text(encoding='utf-8')
        for mutation in [text.replace('detail: plans/base-plan.md', ''), text.replace('slice-01-F001.md', 'missing-F001.md'),
                         text + '\ndetail: plans/base-plan.md\n']:
            path.write_text(mutation, encoding='utf-8')
            with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def rewrite_projection(self, path, update):
        text = path.read_text(encoding='utf-8'); start = text.index('```json\n') + len('```json\n')
        stop = text.index('\n```', start); value = json.loads(text[start:stop])
        update(value['items'])
        path.write_text(text[:start] + json.dumps(value) + text[stop:], encoding='utf-8')

    def test_all_responsibility_fields_are_checked_against_projection(self):
        path = self.base / 'plans/slices/slice-01-F001.md'; text = path.read_text(encoding='utf-8')
        for field, value in [('parents', []), ('scope', 'excluded'), ('verification', 'behavior'), ('page_ids', [])]:
            with self.subTest(field=field):
                old = '| ' + field + ' | ' + json.dumps(self.items[2][field]) + ' |'
                new = '| ' + field + ' | ' + json.dumps(value) + ' |'
                path.write_text(text.replace(old, new), encoding='utf-8')
                with self.assertRaisesRegex(MigrationError, 'responsibility fields differ'):
                    validate_plan(self.project, self.request)
        path.write_text(text, encoding='utf-8')

    def test_projection_and_task_cannot_jointly_weaken_markdown_verification(self):
        self.items[2]['verification'] = 'behavior'; self.write_plans()
        self.request['tasks'][1]['verification'] = 'behavior'
        self.assertEqual(validate_plan(self.project, self.request)['status'], 'PASS')
        path = self.base / 'plans/slices/slice-01-F001.md'
        self.rewrite_projection(path, lambda rows: rows[0].update(verification='generated'))
        self.request['tasks'][1]['verification'] = 'generated'
        with self.assertRaisesRegex(MigrationError, 'responsibility fields differ'):
            validate_plan(self.project, self.request)

    def test_projection_and_task_cannot_jointly_drop_markdown_dependency(self):
        for path in [self.base / 'plans/ui-plan.md', self.base / 'plans/slices/slice-01-F001.md']:
            self.rewrite_projection(path, lambda rows: rows[0].update(parents=[]))
        self.request['tasks'][1]['parents'] = []
        self.request['tasks'][-1]['parents'].append('base')
        with self.assertRaisesRegex(MigrationError, 'responsibility fields differ'):
            validate_plan(self.project, self.request)

    def test_exact_prompt_heading_comes_from_the_item_table_location(self):
        path = self.base / 'plans/slices/slice-01-F001.md'
        text = path.read_text(encoding='utf-8')
        text = text.replace('```json', '## Unrelated later notes\n3a is mentioned here for context.\n```json', 1)
        path.write_text(text, encoding='utf-8')
        inputs = validate_plan(self.project, self.request)['task_inputs']['counter']
        headings = [item['heading'] for item in inputs if item['path'] == 'spec/baseline/plans/slices/slice-01-F001.md']
        self.assertEqual(headings, ['SLICE:F001:3a'])

    def test_final_structure_and_compile_items_cannot_be_removed_or_weakened(self):
        for mutation in ('omit', 'excluded', 'generated', 'writable', 'reorder'):
            with self.subTest(mutation=mutation):
                original = copy.deepcopy(self.items)
                if mutation == 'omit': self.items.pop()
                elif mutation == 'excluded': self.items[-1]['scope'] = 'excluded'
                elif mutation == 'generated': self.items[-1]['verification'] = 'generated'
                elif mutation == 'writable': self.items[-1]['ownership'] = ['entry/Counter.ets']
                elif mutation == 'reorder': self.items[-1]['parents'] = []
                self.write_plans()
                with self.assertRaises(MigrationError): validate_plan(self.project, self.request)
                self.items = original

    def test_ui_overview_owner_must_match_spec_creation_owner(self):
        path = self.base / 'plans/ui-plan.md'
        text = path.read_text(encoding='utf-8').replace(' | F001 |', ' | F002 |')
        path.write_text(text, encoding='utf-8')
        with self.assertRaisesRegex(MigrationError, 'unique feature-index page creator'):
            validate_plan(self.project, self.request)

    def second_feature(self, ordering='无', contract='无', parents=None):
        path = self.base / 'feature-index.md'; text = path.read_text(encoding='utf-8')
        text += '| F002 | Extra | P0 | ' + ordering + ' | ' + contract + ' | N/A | 无 | simple | standard | full | pending | features/F002-extra.md |\n'
        path.write_text(text, encoding='utf-8')
        (self.base / 'features/F002-extra.md').write_text('# F002\n## Public\nExtra public contract.\n- [ ] F002-AC01 Extra `判:unit | Value is ready`\n', encoding='utf-8')
        item = {'item_id': 'SLICE:F002:3a', 'ac_ids': ['F002-AC01'], 'ownership': ['entry/Extra.ets'],
                'parents': parents or [], 'page_ids': [], 'scope': 'product', 'verification': 'generated'}
        extra = self.base / 'plans/slices/slice-02-F002.md'
        extra.write_text('# Extra\n' + self.responsibility(item) + '\n```json\n' + json.dumps({'plan_items_version': 2, 'items': [item]}) + '\n```\n', encoding='utf-8')
        index = self.base / 'plans/feature-plan.md'
        index.write_text(index.read_text(encoding='utf-8') + '\ndetail: plans/slices/slice-02-F002.md\n', encoding='utf-8')
        self.request['tasks'].insert(2, self.task('extra', [item], parents=['counter'] if parents else []))
        self.request['tasks'][-1]['parents'].append('extra')

    def test_spec_ordering_dependency_must_survive_into_markdown_dag(self):
        self.second_feature(ordering='F001')
        with self.assertRaisesRegex(MigrationError, 'feature-index ordering dependency'):
            validate_plan(self.project, self.request)

    def test_contract_dependency_is_read_without_inventing_execution_parent(self):
        self.second_feature(contract='F001')
        result = validate_plan(self.project, self.request)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(self.request['tasks'][2]['parents'], [])
        self.assertTrue(any(item['path'] == 'spec/baseline/features/F001-counter.md' for item in result['task_inputs']['extra']))

    def test_merged_task_cannot_hide_a_markdown_dependency_cycle(self):
        self.items[1]['parents'] = ['SLICE:F001:3a']
        self.items[2]['parents'] = ['UI:PAGE-0001']; self.write_plans()
        with self.assertRaisesRegex(MigrationError, 'Markdown plan dependency cycle'):
            validate_plan(self.project, self.request)

    def test_index_path_heading_contract_is_consumed_without_yaml_duplication(self):
        self.second_feature(contract='spec/ref/deeper.md#Cancel')
        result = validate_plan(self.project, self.request)
        self.assertTrue(any(item['path'] == 'spec/ref/deeper.md' and item['heading'] == 'Cancel' for item in result['task_inputs']['extra']))

    def test_index_only_shared_contracts_are_frozen_transitively(self):
        from hmigbot_ios.ios_scheduler import baseline_inputs
        shared = self.project / 'spec/ref/only-index.md'
        shared.write_text('# Only index\ncontract_refs: ["spec/ref/deeper.md#Cancel"]\n## Public\nShared target boundary.\n', encoding='utf-8')
        self.second_feature(contract='spec/ref/only-index.md#Public')
        initial = baseline_inputs(self.project, 'domains')
        self.assertIn('spec/ref/only-index.md', initial)
        shared.write_text(shared.read_text(encoding='utf-8') + '\nUpdated boundary.\n', encoding='utf-8')
        self.assertNotEqual(initial, baseline_inputs(self.project, 'domains'))

    def test_index_missing_contract_file_or_heading_is_rejected(self):
        path = self.base / 'feature-index.md'; text = path.read_text(encoding='utf-8')
        for ref in ['spec/ref/missing.md#No', 'spec/ref/deeper.md#Missing']:
            path.write_text(text.replace('| Base | 无 |', '| Base | ' + ref + ' |'), encoding='utf-8')
            with self.assertRaises(MigrationError): validate_plan(self.project, self.request)

    def test_base_ordering_dependency_cannot_be_dropped_from_both_plans(self):
        self.items[2]['parents'] = []; self.write_plans()
        with self.assertRaisesRegex(MigrationError, 'feature-index ordering dependency'):
            validate_plan(self.project, self.request)

    def test_slice_associated_page_set_matches_index(self):
        self.items[2]['page_ids'] = []; self.write_plans()
        with self.assertRaisesRegex(MigrationError, 'associated pages'):
            validate_plan(self.project, self.request)

    def test_native_scheduler_pins_profile_and_closure_before_dispatch(self):
        from test_ios_harness import fixture
        from hmigbot_ios.ios_scheduler import generate, step
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target, graph = fixture(root)
            shutil.copytree(self.base, target / 'spec/baseline', dirs_exist_ok=True)
            shutil.copytree(self.project / 'spec/ref', target / 'spec/ref', dirs_exist_ok=True)
            config_path = target / '.migbot/config.json'; config = read_json(config_path)
            config['ios_harness']['spec_contract_version'] = 2; write_json(config_path, config)
            request = copy.deepcopy(self.request)
            request['graph_sha256'] = digest(json_bytes(graph))
            for task in request['tasks']: task['fact_ids'] = [f['id'] for f in graph['facts']]
            request_path = root / 'request.json'; write_json(request_path, request)
            # Source-content checks have separate adversarial tests. Exercise the
            # actual scheduler and frozen input boundary with the content gate isolated.
            with patch('hmigbot_ios.ios_scheduler.check', return_value=({'excluded_obligation_ids': []}, 0)):
                before = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob('*') if p.is_file()}
                checked = generate(target, request_path, validate_only=True)
                self.assertEqual(checked['status'], 'request_validated')
                from hmigbot_ios.native_pipeline import main
                with redirect_stdout(StringIO()) as output:
                    self.assertEqual(main(['plan-check', '--project', str(target), '--input', str(request_path)]), 0)
                    self.assertIn('request_validated', output.getvalue())
                self.assertEqual(before, {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob('*') if p.is_file()})
                self.assertFalse((target / 'spec/state').exists())
                self.assertFalse((target / 'spec/blueprint').exists())
                self.assertFalse((target / 'spec/waves').exists())
                result = generate(target, request_path)
                self.assertEqual(result['status'], 'plan_generated')
                prompt = (target / 'spec/waves/prompts/domains/counter.txt').read_text(encoding='utf-8')
                self.assertIn('spec/ref/deeper.md', prompt)
                self.assertIn('Cancel', prompt)
                index = target / 'spec/baseline/feature-index.md'
                index.write_text(index.read_text(encoding='utf-8').replace('pending', 'implemented'), encoding='utf-8')
                self.assertEqual(step(target, 'domains')[0]['action'], 'dispatch')
                config['ios_harness']['spec_contract_version'] = 1; write_json(config_path, config)
                with self.assertRaises(MigrationError): step(target, 'domains')
                with self.assertRaises(MigrationError): generate(target, request_path, validate_only=True)
                config['ios_harness']['spec_contract_version'] = 2; write_json(config_path, config)
                index.write_text(index.read_text(encoding='utf-8').replace('Base', 'F002'), encoding='utf-8')
                with self.assertRaises(MigrationError): step(target, 'domains')

    def test_real_source_gate_dispatch_allows_core_progress_and_rejects_business_state_drift(self):
        from test_ios_harness import fixture
        from spec_contract_fixture import strict_contract
        from hmigbot_ios.ios_harness import check
        from hmigbot_ios.ios_scheduler import generate, step
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target, graph = fixture(root)
            strict_contract(target)
            index = target / 'spec/baseline/feature-index.md'
            text = index.read_text(encoding='utf-8').replace('| base | base |', '| base | 无 |')
            # This business table is deliberately adjacent and as wide as the
            # core index. It may never inherit the preceding progress mask.
            text = text.replace('## 依赖图',
                '| audit | business | priority | order | contract | page | creator | complexity | tier | depth | result | evidence |\n'
                '|---|---|---|---|---|---|---|---|---|---|---|---|\n'
                '| audit-1 | API | P0 | base | none | none | none | simple | standard | full | failed | review |\n'
                '## 依赖图')
            index.write_text(text, encoding='utf-8')
            self.items[1]['ownership'] = ['entry/src/main/ets/pages/CounterPage.ets']
            self.write_plans()
            shutil.copytree(self.base / 'plans', target / 'spec/baseline/plans', dirs_exist_ok=True)
            request = copy.deepcopy(self.request)
            request['tasks'][1] = self.task('counter', self.items[1:3], parents=['base'], mapping_reason='UI and service share one owner')
            request['graph_sha256'] = digest(json_bytes(graph))
            for task in request['tasks']:
                task['fact_ids'] = [fact['id'] for fact in graph['facts']]
            request_path = root / 'request.json'
            write_json(request_path, request)
            report, code = check(target, report_only=True)
            self.assertEqual(code, 0, report['findings'])
            self.assertEqual(generate(target, request_path)['status'], 'plan_generated')
            index.write_text(text.replace('| pending |', '| implemented |'), encoding='utf-8')
            manifest = target / 'spec/baseline/ui-manifest.md'
            manifest.write_text(manifest.read_text(encoding='utf-8').replace('| pending |', '| converted |'), encoding='utf-8')
            self.assertEqual(step(target, 'domains')[0]['action'], 'dispatch')
            progress = index.read_text(encoding='utf-8')
            for old, new in [('| failed |', '| passed |'), ('Counter | P0', 'Counter | P1'),
                             ('| base | 无 |', '| F002 | 无 |'),
                             ('| page_0001 | page_0001 |', '| page_0002 | page_0001 |'),
                             ('| implemented |', '| skipped |'), ('| implemented |', '| excluded |')]:
                with self.subTest(change=(old, new)):
                    self.assertIn(old, progress)
                    index.write_text(progress.replace(old, new), encoding='utf-8')
                    with self.assertRaisesRegex(MigrationError, 'baseline changed'):
                        step(target, 'domains')
                    index.write_text(progress, encoding='utf-8')
            ui_progress = manifest.read_text(encoding='utf-8')
            for old, new in [('| F001 | P0 |', '| F002 | P0 |'),
                             ('entry/src/main/ets/pages/CounterPage.ets', 'entry/OtherPage.ets'),
                             ('| page_0001 | Counter.swift', '| page_0002 | Counter.swift'),
                             ('| converted |', '| excluded |')]:
                with self.subTest(manifest_change=(old, new)):
                    self.assertIn(old, ui_progress)
                    manifest.write_text(ui_progress.replace(old, new), encoding='utf-8')
                    with self.assertRaisesRegex(MigrationError, 'baseline changed'):
                        step(target, 'domains')
                    manifest.write_text(ui_progress, encoding='utf-8')

    def test_readonly_cli_preserves_findings_without_preexisting_gate_report(self):
        from test_ios_harness import fixture
        from hmigbot_ios.native_pipeline import main, findings_module
        from hmigbot_ios.ios_scheduler import generate
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source, target, graph = fixture(root)
            request = {'schema_version': 2, 'wave': 'domains', 'graph_sha256': digest(json_bytes(graph)),
                       'tasks': [{'id': 'counter', 'role': 'a2h-ios-converter', 'goal': 'Implement Counter',
                                  'ownership': ['entry/Counter.ets'], 'ac_ids': ['F001-AC01'],
                                  'fact_ids': [fact['id'] for fact in graph['facts']], 'parents': []}]}
            request_path = root / 'request.json'; write_json(request_path, request)
            report_path = target / 'spec/reports/ios-harness-check.json'
            report_path.unlink(missing_ok=True)
            queue = findings_module()
            queue.replace_section(str(target), 'spec.ios-harness', [
                queue.make('IOS.READONLY_SENTINEL', 'spec', 'dry-run', 'Read-only validation must preserve this finding')])
            before = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob('*') if p.is_file()}
            with redirect_stdout(StringIO()):
                self.assertEqual(main(['plan-check', '--project', str(target), '--input', str(request_path)]), 0)
            self.assertEqual(before, {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob('*') if p.is_file()})
            self.assertFalse(report_path.exists())
            generate(target, request_path)
            self.assertTrue(report_path.exists())
            self.assertNotEqual(before['spec/.a2h/open-findings.json'], (target / 'spec/.a2h/open-findings.json').read_bytes())


if __name__ == '__main__': unittest.main()
