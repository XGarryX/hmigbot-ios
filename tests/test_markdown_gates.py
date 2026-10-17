"""Regression boundaries for authored Markdown, independent of example wording."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.artifact_contract import markdown_tables
from hmigbot_ios.spec_contract import check, declared_symbols, sections
from spec_contract_fixture import complete_contract, strict_contract
from test_ios_harness import fixture


class MarkdownParserTests(unittest.TestCase):
    def test_adjacent_tables_have_independent_headers_and_row_positions(self):
        text = ('intro\n| 源 | 目标实现 |\n|---|---|\n| 目标描述 | Page.build |\n'
                '| 目标接口 | 说明 |\n|---|---|\n| VM.observe | status |\n')
        tables = markdown_tables(text)
        self.assertEqual(len(tables), 2)
        self.assertEqual(tables[0]['rows'], [['目标描述', 'Page.build']])
        self.assertEqual(tables[1]['headers'], ['目标接口', '说明'])
        self.assertEqual(tables[0]['row_lines'], [4])
        self.assertEqual(tables[1]['row_lines'], [7])
        self.assertEqual(tables[1]['delimiter_line'], 6)
        self.assertEqual(tables[1]['end_line'], 7)

    def test_inline_code_escaped_pipes_and_fences_keep_columns(self):
        text = ('```md\n| 目标接口 |\n|---|\n| Fake.call |\n```\n'
                '| 源 | 目标实现 | 说明 |\n|---|---|---|\n'
                '| `source|part` | `Page.build` | a\\|b |\n')
        table, = markdown_tables(text)
        self.assertEqual(table['rows'], [['`source|part`', '`Page.build`', 'a|b']])
        self.assertEqual(table['row_lines'], [8])
        raw_line = text.splitlines()[7]
        self.assertEqual([raw_line[start:end] for start, end in table['row_cell_spans'][0]],
                         [' `source|part` ', ' `Page.build` ', ' a\\|b '])

    def test_even_backslashes_do_not_escape_a_table_delimiter(self):
        table, = markdown_tables('| 源 | 目标实现 |\n|---|---|\n| path\\\\| `Page.load` |\n')
        self.assertEqual(table['rows'], [['path\\\\', '`Page.load`']])

    def test_table_without_outer_pipes_is_valid(self):
        table, = markdown_tables('源 | 目标实现\n--- | ---\nSource.load | Page.load\n')
        self.assertEqual(table['rows'], [['Source.load', 'Page.load']])

    def test_data_words_cannot_change_the_target_column(self):
        body = ('| 源机制 | 目标实现 | 契约 |\n|---|---|---|\n'
                '| 目标视图构建 | Page.build | source says status |\n'
                '| SourceOther.load | VM.observe | 目标接口 |\n')
        self.assertEqual(declared_symbols({'实现映射': body}), {'Page.build', 'VM.observe'})

    def test_source_tables_fences_and_untyped_columns_do_not_declare(self):
        body = ('| 源接口 | 源说明 |\n|---|---|\n| Source.call | Source.state |\n'
                '\n| Some column | Description |\n|---|---|\n| Wrong.call | Wrong.state |\n'
                '\n```text\nFenced.call\n| 目标接口 |\n|---|\n| Fenced.state |\n```\n')
        self.assertEqual(declared_symbols({'服务层（ArkTS 目标接口）': body}), set())

    def test_prose_target_state_and_interface_declarations_remain_supported(self):
        body = ('CounterPage.count: number = 0; page owns writes.\n'
                '目标接口: CounterVM.add(): void\n'
                '源: Counter.count maps into the page.\n'
                'The source Counter.unrelated does work.\n')
        self.assertEqual(declared_symbols({'状态管理': body}), {'CounterPage.count', 'CounterVM.add'})

    def test_sections_keep_both_bodies_without_silent_overwrite(self):
        parts = sections('## 数据流\nfirst\n## 数据流\nsecond\n')
        self.assertIn('first', parts['数据流'])
        self.assertIn('second', parts['数据流'])

    def test_indented_code_tables_and_prose_never_declare_targets(self):
        for indent in ('    ', '\t'):
            with self.subTest(indent=repr(indent)):
                body = '\n'.join(indent + line for line in (
                    '| 目标接口 | 说明 |', '|---|---|', '| FakeOwner.fake | example only |',
                    'FakeOwner.state: number = 0')) + '\n'
                self.assertEqual(markdown_tables(body), [])
                self.assertEqual(declared_symbols({'服务层': body}), set())

    def test_section_body_preserves_first_line_indented_code(self):
        parts = sections('## 服务层\n\n    FakeOwner.fake: number = 0\n')
        self.assertTrue(parts['服务层'].startswith('    '))
        self.assertEqual(declared_symbols(parts), set())

    def test_list_body_indentation_is_not_automatically_code(self):
        body = ('- Public contract\n\n'
                '    CounterPage.count: number = 0\n\n'
                '    | 目标接口 | 说明 |\n    |---|---|\n'
                '    | CounterPage.add | synchronous |\n')
        self.assertEqual(declared_symbols({'服务层': body}), {'CounterPage.count', 'CounterPage.add'})
        table, = markdown_tables(body)
        self.assertEqual(table['row_lines'], [7])

    def test_fenced_and_indented_code_within_list_do_not_declare(self):
        body = ('- Examples\n\n'
                '    ```text\n    FakeOwner.fenced\n    ```\n\n'
                '      FakeOwner.indented\n\n'
                'CounterPage.real: number = 0\n')
        self.assertEqual(declared_symbols({'服务层': body}), {'CounterPage.real'})

    def test_excess_list_marker_spacing_starts_code(self):
        self.assertEqual(declared_symbols({'服务层': '-     FakeOwner.fake\n'}), set())

    def test_blockquote_examples_cannot_supply_tables_or_declarations(self):
        body = ('>     FakeOwner.indented\n>\n> ```text\n> FakeOwner.fenced\n> ```\n'
                '> | 目标接口 | 说明 |\n> |---|---|\n> | FakeOwner.table | example |\n'
                '\nCounterPage.real: number = 0\n')
        self.assertEqual(markdown_tables(body), [])
        self.assertEqual(declared_symbols({'服务层': body}), {'CounterPage.real'})


class MarkdownGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='markdown-gate-')
        self.addCleanup(temporary.cleanup)
        self.source, self.project, _ = fixture(Path(temporary.name))
        complete_contract(self.project)
        self.base = self.project / 'spec/baseline'
        self.feature = self.base / 'features/F001-counter.md'
        self.page = self.base / 'ui/page_0001_Counter.md'

    def replace(self, path, old, new):
        text = path.read_text(encoding='utf-8')
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding='utf-8')

    def findings(self):
        return check(self.project)[0]['findings']

    def rules(self):
        return {row['rule'] for row in self.findings()}

    def test_source_description_cannot_break_valid_spec_or_action_target(self):
        strict_contract(self.project)
        self.replace(self.feature, '| Counter state and Button |', '| 目标视图构建 |')
        self.replace(self.feature, 'action_contracts: not_applicable', 'action_contracts: required')
        value = {'action_id': 'F001-A01', 'owner': 'F001', 'target': 'CounterPage.add',
                 'source_anchors': [{'path': 'Counter.swift', 'line': 7}],
                 'immediate_effect': 'count increments by one', 'completion_event': 'handler-return',
                 'final_effect': 'Text displays Count:1', 'failure_cancel': 'No async work',
                 'scope': 'active', 'ac_ids': ['F001-AC01']}
        self.feature.write_text(self.feature.read_text(encoding='utf-8') +
                                '\n## Add action\n```action-contract\n' + json.dumps(value) + '\n```\n', encoding='utf-8')
        report, code = check(self.project)
        self.assertEqual(code, 0, report)

    def test_source_cell_cannot_supply_a_missing_ac_target(self):
        self.replace(self.feature, '标:CounterPage.add', '标:SourceOnly.fake')
        self.replace(self.feature, '| Counter state and Button | `CounterPage.add` |',
                     '| SourceOnly.fake | no-target-symbol |')
        self.assertIn('IOS.SPEC_TARGET_UNDEFINED', self.rules())

    def test_valid_ui_mapping_survives_source_word_target(self):
        self.replace(self.page, '| Counter.count |', '| 目标计数状态 |')
        self.assertNotIn('IOS.SPEC_UI_TARGET_STATE', self.rules())

    def test_invalid_ui_mapping_cannot_borrow_source_symbol(self):
        self.replace(self.page, '| Counter.count | `CounterPage.count` |',
                     '| 目标计数状态 | `CounterPage.count` |\n| SourceOnly.fake | no-target-symbol |')
        self.assertIn('IOS.SPEC_UI_TARGET_STATE', self.rules())

    def test_state_prose_declaration_is_compatible(self):
        self.replace(self.page,
                     '| 源状态 | 目标状态 | 类型 | 初值/所有者/读写与UI影响 |\n|---|---|---|---|\n| Counter.count | `CounterPage.count` | number | 0; page owned; Add writes and Text reads |',
                     '目标状态: CounterPage.count: number = 0; page owns writes and Text reads.')
        self.assertNotIn('IOS.SPEC_UI_TARGET_STATE', self.rules())

    def test_same_missing_document_has_one_finding_and_keeps_both_rules(self):
        strict_contract(self.project)
        missing = 'spec/baseline/feature-base.md'
        (self.project / missing).unlink()
        rows = [row for row in self.findings() if row['subject'] == missing]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(set(rows[0]['rules']), {'IOS.SPEC_ARTIFACT_MISSING', 'IOS.SPEC_DOCUMENT_MISSING'})

    def test_missing_dedup_does_not_hide_other_contract_failures(self):
        strict_contract(self.project)
        (self.base / 'skip-list.md').unlink()
        self.replace(self.feature, '标:CounterPage.add', '标:Missing.call')
        self.replace(self.feature, '点击后文本为Count:1', '')
        rules = self.rules()
        self.assertIn('IOS.SPEC_TARGET_UNDEFINED', rules)
        self.assertIn('IOS.SPEC_AC_EXPECTED', rules)

    def test_session_phrases_with_concrete_results_are_not_deferred(self):
        self.replace(self.feature, '点击后文本为Count:1',
                     '对源赋值/运算的边界输入：count=0点击Add，期望文本Count:1；按源modifier调用顺序检查后结果仍为Count:1')
        self.assertNotIn('IOS.SPEC_AC_DEFERRED', self.rules())

    def test_explicit_unfinished_expected_is_deferred_without_old_phrase(self):
        self.replace(self.feature, '点击后文本为Count:1', 'TODO: acceptance result will be supplied later')
        self.assertIn('IOS.SPEC_AC_DEFERRED', self.rules())

    def test_todo_is_a_legitimate_displayed_literal_when_expected_is_concrete(self):
        self.replace(self.feature, '点击后文本为Count:1', '点击后文本为"TODO"')
        self.assertNotIn('IOS.SPEC_AC_DEFERRED', self.rules())

    def test_old_unspecified_remainder_is_still_a_deferred_promise(self):
        self.replace(self.feature, '点击后文本为Count:1', '其余20处原表达式见本AC绑定的coverage源审阅')
        self.assertIn('IOS.SPEC_AC_DEFERRED', self.rules())

    def test_legacy_duplicate_core_heading_blocks_instead_of_overwriting(self):
        self.feature.write_text(self.feature.read_text(encoding='utf-8') +
                                '\n## 数据流\nAdd now decrements; contradictory behavior.\n', encoding='utf-8')
        self.assertIn('IOS.SPEC_HEADING_AMBIGUOUS', self.rules())

    def test_unrelated_child_headings_can_repeat_in_both_profiles(self):
        for strict in (False, True):
            if strict:
                strict_contract(self.project)
            self.feature.write_text(self.feature.read_text(encoding='utf-8') +
                                    '\n## Appendix A\n### Notes\nfirst\n## Appendix B\n### Notes\nsecond\n', encoding='utf-8')
            report, code = check(self.project)
            self.assertEqual(code, 0, report)

    def test_referenced_duplicate_heading_remains_ambiguous(self):
        shared = self.base / 'feature-base.md'
        shared.write_text(shared.read_text(encoding='utf-8') + '\n## 数据模型\nContradiction\n', encoding='utf-8')
        self.assertIn('IOS.SPEC_REFERENCE_INVALID', self.rules())

    def test_unreferenced_common_core_heading_is_ambiguous_in_legacy_profile(self):
        path = self.base / 'feature-base.md'
        path.write_text(path.read_text(encoding='utf-8') +
                        '\n## 跨栈映射基线\nCounter uses a global unowned count.\n', encoding='utf-8')
        self.assertIn('IOS.SPEC_HEADING_AMBIGUOUS', self.rules())

    def test_full_gate_rejects_ac_target_declared_only_in_indented_example(self):
        self.replace(self.feature, '标:CounterPage.add', '标:FakeOwner.fake')
        self.feature.write_text(self.feature.read_text(encoding='utf-8') +
                                '\n## 目标接口示例\n\n'
                                '    | 目标接口 | 说明 |\n    |---|---|\n'
                                '    | FakeOwner.fake | illustrative only |\n', encoding='utf-8')
        self.assertIn('IOS.SPEC_TARGET_UNDEFINED', self.rules())

    def test_full_gate_rejects_ui_mapping_that_is_only_indented_code(self):
        self.replace(self.page,
                     '| 源状态 | 目标状态 | 类型 | 初值/所有者/读写与UI影响 |\n|---|---|---|---|\n| Counter.count | `CounterPage.count` | number | 0; page owned; Add writes and Text reads |',
                     '    | 源状态 | 目标状态 |\n    |---|---|\n    | Counter.count | CounterPage.count |')
        self.assertIn('IOS.SPEC_UI_TARGET_STATE', self.rules())

    def test_code_example_acs_do_not_pollute_any_inventory(self):
        from hmigbot_ios.ios_harness import ac_inventory
        from hmigbot_ios.native_pipeline import check_source
        from hmigbot_ios.plan_contract import _inventory
        example = '- [ ] F009-AC01 Example only `标:Fake.call` `判:ui | example`'
        self.feature.write_text(self.feature.read_text(encoding='utf-8') +
                                '\n## Examples\n```md\n' + example + '\n```\n\n'
                                '    ' + example + '\n\n> ' + example + '\n', encoding='utf-8')
        report, code = check(self.project)
        self.assertEqual(code, 0, report)
        self.assertEqual(report['counts']['acceptance'], 1)
        self.assertEqual(set(ac_inventory(self.project)), {'F001-AC01'})
        self.assertEqual(set(_inventory(self.project)[0]), {'F001-AC01'})
        source_report, _ = check_source(self.project, report_only=True)
        self.assertFalse([row for row in source_report['findings'] if row['rule'].startswith('IOS.AC_')], source_report)

    def test_example_duplicate_is_ignored_but_real_duplicate_still_blocks(self):
        from hmigbot_ios.core import MigrationError
        from hmigbot_ios.ios_harness import ac_inventory
        from hmigbot_ios.native_pipeline import check_source
        from hmigbot_ios.plan_contract import _inventory
        text = self.feature.read_text(encoding='utf-8')
        assertion = next(line for line in text.splitlines() if line.startswith('- [ ] F001-AC01'))
        self.feature.write_text(text + '\n## Example\n```md\n' + assertion + '\n```\n', encoding='utf-8')
        self.assertEqual(check(self.project)[1], 0)
        self.assertEqual(set(ac_inventory(self.project)), {'F001-AC01'})
        self.feature.write_text(self.feature.read_text(encoding='utf-8') + '\n' + assertion + '\n', encoding='utf-8')
        self.assertIn('IOS.SPEC_AC_DUPLICATE', self.rules())
        with self.assertRaises(MigrationError):
            ac_inventory(self.project)
        with self.assertRaises(MigrationError):
            _inventory(self.project)
        source_report, _ = check_source(self.project, report_only=True)
        self.assertIn('IOS.AC_DUPLICATE', {row['rule'] for row in source_report['findings']})

    def test_example_acs_cannot_substitute_for_real_acceptance(self):
        from hmigbot_ios.core import MigrationError
        from hmigbot_ios.ios_harness import ac_inventory
        text = self.feature.read_text(encoding='utf-8')
        assertion = next(line for line in text.splitlines() if line.startswith('- [ ] F001-AC01'))
        self.feature.write_text(text.replace(assertion, '```md\n' + assertion + '\n```'), encoding='utf-8')
        self.assertIn('IOS.SPEC_AC_MISSING', self.rules())
        with self.assertRaises(MigrationError):
            ac_inventory(self.project)


if __name__ == '__main__':
    unittest.main()
