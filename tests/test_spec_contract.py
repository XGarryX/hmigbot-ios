"""Content gates must reject the concrete failures seen in a real migration."""
import importlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.ios_facts import extract
from hmigbot_ios.ios_harness import check as harness_check
from hmigbot_ios.core import read_json, write_json
from test_ios_harness import fixture
from spec_contract_fixture import complete_contract


class SpecContractTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='ios-spec-contract-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source, self.project, _ = fixture(self.root)
        complete_contract(self.project)
        self.feature = self.project / 'spec/baseline/features/F001-counter.md'

    def check(self):
        self.assertIsNotNone(importlib.util.find_spec('hmigbot_ios.spec_contract'), 'Missing executable content gate')
        return importlib.import_module('hmigbot_ios.spec_contract').check(self.project)

    def rules(self):
        return {f['rule'] for f in self.check()[0]['findings']}

    def edit(self, old, new):
        self.feature.write_text(self.feature.read_text(encoding='utf-8').replace(old, new), encoding='utf-8')

    def test_complete_contract_passes_without_claiming_behavior(self):
        report, code = self.check()
        self.assertEqual(code, 0, report)
        self.assertFalse(report['behavior_verified'])
        self.assertEqual(report['counts']['acceptance'], 1)

    def test_import_is_not_a_persistence_operation(self):
        p = self.source / 'Counter.swift'
        p.write_text('import CoreData\n' + p.read_text(encoding='utf-8'), encoding='utf-8')
        self.assertFalse([f for f in extract(self.source)['facts'] if f['kind'] == 'persistence'])

    def test_import_does_not_hide_production_after_a_semicolon(self):
        p = self.source / 'Counter.swift'
        p.write_text('import CoreData; struct Real { var count = 0 }\n', encoding='utf-8')
        facts = extract(self.source)['facts']
        self.assertTrue(any(f['kind'] == 'state' and f['symbol'] == 'count' for f in facts))
        self.assertFalse(any(f['kind'] == 'persistence' for f in facts))

    def test_attributed_imports_do_not_invent_persistence(self):
        p = self.source / 'Counter.swift'
        p.write_text('@preconcurrency import CoreData\n@testable import SwiftData\n' +
                     p.read_text(encoding='utf-8'), encoding='utf-8')
        self.assertFalse([f for f in extract(self.source)['facts'] if f['kind'] == 'persistence'])

    def test_attributed_import_truth_cannot_prove_business_operation(self):
        p = self.source / 'Counter.swift'
        p.write_text('@preconcurrency import CoreData\n' + p.read_text(encoding='utf-8'), encoding='utf-8')
        self.edit('真:src:Counter.swift:7', '真:src:Counter.swift:1')
        self.assertIn('IOS.SPEC_TRUTH_IMPORT', self.rules())

    def test_missing_behavior_and_target_sections_are_blocking(self):
        self.edit('## 数据流', '## Notes')
        self.edit('## 服务层（ArkTS 目标接口）', '## Misc')
        self.assertIn('IOS.SPEC_SECTION_MISSING', self.rules())

    def test_harness_cannot_accept_a_thin_signal_spec(self):
        self.feature.write_text('source_platform: ios\nsource_anchors:\n  - path: Counter.swift\n'
                                '- [ ] F001-AC01 Count becomes 1 `判:ui | Count:1` `真:src:Counter.swift:7`\n', encoding='utf-8')
        report, code = harness_check(self.project)
        self.assertEqual(code, 2, report)
        self.assertTrue(any(f['rule'].startswith('IOS.SPEC_') for f in report['findings']))

    def test_undefined_target_anchor_is_blocking(self):
        self.edit('标:CounterPage.add', '标:CounterFiltering.file')
        self.assertIn('IOS.SPEC_TARGET_UNDEFINED', self.rules())

    def test_import_truth_cannot_prove_save_reload(self):
        self.edit('真:src:Counter.swift:7', '真:src:Counter.swift:1')
        self.assertIn('IOS.SPEC_TRUTH_IMPORT', self.rules())

    def test_preview_truth_is_not_product_behavior(self):
        p = self.source / 'Counter.swift'
        original = p.read_text(encoding='utf-8')
        line = len(original.splitlines()) + 2
        p.write_text(original + '#Preview {\n let count = 99\n Text("Preview")\n}\n', encoding='utf-8')
        self.edit('真:src:Counter.swift:7', f'真:src:Counter.swift:{line}')
        self.assertIn('IOS.SPEC_TRUTH_PREVIEW', self.rules())

    def test_preview_does_not_exclude_adjacent_production(self):
        p = self.source / 'Counter.swift'
        p.write_text(p.read_text(encoding='utf-8') + '#Preview { Text("Preview") }\n', encoding='utf-8')
        self.assertEqual(self.check()[1], 0)

    def test_preview_provider_type_in_member_does_not_hide_production(self):
        from hmigbot_ios.source_scope import preview_lines
        self.assertEqual(preview_lines('struct Real { var value: PreviewProvider }\n'), set())

    def test_acceptance_section_without_assertions_is_rejected(self):
        self.edit('- [ ] F001-AC01', '- F001-AC01')
        self.assertIn('IOS.SPEC_AC_MISSING', self.rules())

    def test_deferred_expressions_are_not_atomic_acceptance(self):
        self.edit('点击后文本为Count:1', '其余20处原表达式见本AC绑定的coverage源审阅')
        self.assertIn('IOS.SPEC_AC_DEFERRED', self.rules())

    def test_empty_expected_result_is_blocking(self):
        self.edit('点击后文本为Count:1', '')
        self.assertIn('IOS.SPEC_AC_EXPECTED', self.rules())

    def test_invalid_scheduling_metadata_is_blocking(self):
        self.edit('complexity: simple', 'complexity: maybe')
        self.assertIn('IOS.SPEC_METADATA', self.rules())

    def test_unresolved_target_contract_cannot_be_deferred_to_plan(self):
        self.edit('## 服务层（ArkTS 目标接口）', '## 服务层（ArkTS 目标接口）\nTBD: choose during plan')
        self.assertIn('IOS.SPEC_UNRESOLVED', self.rules())

    def test_stateful_page_cannot_claim_stateless_to_bypass_mapping(self):
        p = self.project / 'spec/baseline/ui/page_0001_Counter.md'
        text = p.read_text(encoding='utf-8')
        start, end = text.index('## 状态接口'), text.index('## 交互与导航')
        p.write_text(text[:start] + '## 状态接口\n无状态 stateless\n' + text[end:], encoding='utf-8')
        self.assertIn('IOS.SPEC_UI_TARGET_STATE', self.rules())

    def test_source_only_page_state_is_blocking(self):
        p = self.project / 'spec/baseline/ui/page_0001_Counter.md'
        p.write_text(p.read_text(encoding='utf-8').replace('`CounterPage.count`', 'None'), encoding='utf-8')
        self.assertIn('IOS.SPEC_UI_TARGET_STATE', self.rules())

    def test_broken_and_unsafe_shared_contract_refs_are_blocking(self):
        self.edit('spec/baseline/feature-base.md#数据模型', '../outside.md#数据模型')
        self.assertIn('IOS.SPEC_REFERENCE_INVALID', self.rules())

    def test_shared_contract_section_is_resolved(self):
        self.edit('spec/baseline/feature-base.md#数据模型', 'spec/baseline/feature-base.md#不存在')
        self.assertIn('IOS.SPEC_REFERENCE_INVALID', self.rules())

    def test_inline_reference_list_is_not_silently_ignored(self):
        self.edit('contract_refs:\n  - spec/baseline/feature-base.md#数据模型', 'contract_refs: ["spec/ref/missing.md#服务层"]')
        self.assertIn('IOS.SPEC_REFERENCE_INVALID', self.rules())

    def test_template_shared_public_contract_defines_target_without_duplication(self):
        shared = self.project / 'spec/baseline/feature-base.md'
        shared.write_text(shared.read_text(encoding='utf-8') +
                          '\n## 公共服务与状态\n| 目标接口 | 输入/输出/错误 | 所有者/线程 | 初始化/释放 | 定义方/消费方 |\n'
                          '|---|---|---|---|---|\n'
                          '| `CounterService.increment(): void` | Increments by 1 | page/main | page lifetime | F001/page_0001 |\n',
                          encoding='utf-8')
        self.edit('spec/baseline/feature-base.md#数据模型', 'spec/baseline/feature-base.md#公共服务与状态')
        self.edit('标:CounterPage.add', '标:CounterService.increment')
        report, code = self.check()
        self.assertEqual(code, 0, report)

    def test_execution_resource_mapping_cannot_define_a_shared_contract(self):
        p = self.project / 'spec/baseline/plans/resource-mapping.md'
        p.parent.mkdir()
        p.write_text('# Execution mapping\n\n## 服务层\nCounterPage.add is a mutable execution note.\n', encoding='utf-8')
        self.edit('spec/baseline/feature-base.md#数据模型', 'spec/baseline/plans/resource-mapping.md#服务层')
        self.assertIn('IOS.SPEC_REFERENCE_INVALID', self.rules())

    def test_contract_ref_cannot_resolve_to_an_arbitrary_file(self):
        self.edit('spec/baseline/feature-base.md#数据模型', 'spec/decision-ledger.md#Decisions')
        self.assertIn('IOS.SPEC_REFERENCE_INVALID', self.rules())

    def test_cli_is_read_only_and_returns_nonzero_for_bad_contract(self):
        self.edit('标:CounterPage.add', '标:CounterFiltering.file')
        before = {p.relative_to(self.project): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/a2h_ios.py'), 'spec-check', '--project', str(self.project)], capture_output=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(b'IOS.SPEC_TARGET_UNDEFINED', result.stdout)
        self.assertEqual(before, {p.relative_to(self.project): p.read_bytes() for p in self.project.rglob('*') if p.is_file()})

    def test_plan_freezes_decisions_and_transitive_shared_contracts(self):
        from hmigbot_ios.ios_scheduler import baseline_inputs
        shared = self.project / 'spec/ref/interfaces.md'
        nested = self.project / 'spec/ref/types.md'
        nested.write_text('# Shared types\n\n## 数据模型\nCounter value is a number starting at 0.\n', encoding='utf-8')
        shared.write_text('contract_refs:\n  - spec/ref/types.md#数据模型\n# Interfaces\n\n## 服务层\n`CounterService.increment(): void` increments count by one.\n', encoding='utf-8')
        self.edit('contract_refs:\n', 'contract_refs:\n  - spec/ref/interfaces.md#服务层\n')
        self.edit('标:CounterPage.add', '标:CounterService.increment')
        self.assertEqual(self.check()[1], 0)
        frozen = baseline_inputs(self.project, 'domains')
        self.assertIn('spec/decision-ledger.md', frozen)
        self.assertIn('spec/ref/interfaces.md', frozen)
        self.assertIn('spec/ref/types.md', frozen)
        self.assertNotIn('spec/ref/interfaces.md', baseline_inputs(self.project, 'understand'))
        before = frozen['spec/ref/types.md']
        nested.write_text(nested.read_text(encoding='utf-8') + 'Changed default to 9.\n', encoding='utf-8')
        self.assertNotEqual(before, baseline_inputs(self.project, 'domains')['spec/ref/types.md'])

    def test_progress_indexes_remain_mutable_without_unfreezing_contracts(self):
        from hmigbot_ios.ios_scheduler import baseline_inputs
        before = baseline_inputs(self.project, 'domains')
        index = self.project / 'spec/baseline/feature-index.md'
        index.write_text(index.read_text(encoding='utf-8') + '\nExecution progress: generated.\n', encoding='utf-8')
        self.assertEqual(before, baseline_inputs(self.project, 'domains'))

    def test_shared_reference_with_index_basename_is_still_frozen(self):
        from hmigbot_ios.ios_scheduler import baseline_inputs
        shared = self.project / 'spec/ref/ui-manifest.md'
        shared.write_text('# Shared\n\n## 服务层\nCounterService.add(): void increments by 1.\n', encoding='utf-8')
        self.edit('spec/baseline/feature-base.md#数据模型', 'spec/ref/ui-manifest.md#服务层')
        self.assertIn('spec/ref/ui-manifest.md', baseline_inputs(self.project, 'domains'))

    def test_stage0_resource_mapping_is_execution_output_not_frozen_input(self):
        from hmigbot_ios.ios_scheduler import baseline_inputs, execution_files
        before = baseline_inputs(self.project, 'domains')
        mapping = self.project / 'spec/baseline/plans/resource-mapping.md'
        mapping.parent.mkdir()
        mapping.write_text('# Actual resource conversion outputs\n', encoding='utf-8')
        self.assertEqual(before, baseline_inputs(self.project, 'domains'))
        self.assertIn('spec/baseline/plans/resource-mapping.md', execution_files(self.project))

    def test_preview_obligations_need_reviewed_exclusion_not_product_acs(self):
        (self.root / 'preview-case').mkdir()
        source, project, graph = fixture(self.root / 'preview-case', '#Preview {\n Text("Preview-only")\n}\n')
        report, code = harness_check(project)
        self.assertEqual(code, 2, report)
        self.assertIn('IOS.PREVIEW_REVIEW_REQUIRED', {f['rule'] for f in report['findings']})
        coverage_path = project / 'spec/baseline/ios-coverage.json'
        coverage = read_json(coverage_path)
        by_id = {f['id']: f for f in graph['facts']}
        preview_start = next(i for i, line in enumerate((source / 'Counter.swift').read_text().splitlines(), 1) if line.startswith('#Preview'))
        for row in coverage['mappings']:
            fact = by_id['IF-' + row['obligation_id'][3:]]
            if fact['anchor']['line'] >= preview_start:
                row.update(ac_ids=[], disposition='preview-only', source_sha256=fact['anchor']['file_sha256'],
                           skip_ref='spec/baseline/skip-list.md#Preview')
        (project / 'spec/baseline/skip-list.md').write_text('# Scope\n\n## Preview\nCounter.swift #Preview is IDE-only, not an app entry.\n', encoding='utf-8')
        write_json(coverage_path, coverage)
        report, code = harness_check(project)
        self.assertEqual(code, 0, report)
        self.assertTrue(report['excluded_obligation_ids'])
        # Exclusion cannot be reused against a production signal.
        coverage['mappings'][0].update(ac_ids=[], disposition='preview-only', source_sha256=graph['facts'][0]['anchor']['file_sha256'], skip_ref='spec/baseline/skip-list.md#Preview')
        write_json(coverage_path, coverage)
        self.assertEqual(harness_check(project)[1], 2)


if __name__ == '__main__':
    unittest.main()
