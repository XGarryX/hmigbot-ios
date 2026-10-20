"""Regression cases for PLUGIN-001; source examples, not a Swift compiler oracle."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from hmigbot_ios.core import MigrationError
from hmigbot_ios.ios_facts import extract
from hmigbot_ios.swiftui import parse_view, tokenize


class StringBoundaryTests(unittest.TestCase):
    def assert_literal(self, literal):
        # The following statement must stay outside the literal, at the right line.
        text = 'let value = ' + literal + '\nlet after = 7'
        tokens = tokenize(text)
        strings = [t for t in tokens if t.kind == 'string']
        self.assertEqual([(t.value, t.line) for t in strings], [(literal, 1)])
        self.assertEqual([t.value for t in tokens[-4:]], ['let', 'after', '=', '7'])
        self.assertEqual(tokens[-4].line, literal.count('\n') + 2)

    def test_plain_unicode_text(self):
        self.assert_literal('"中文、emoji 🐕 and symbols () {}"')

    def test_empty_string(self):
        self.assert_literal('""')

    def test_real_apns_localized_ternary(self):
        self.assert_literal(r'"已同步服务端: \(lastSynced ? String(localized: "是") : String(localized: "否"))"')

    def test_joined_separator_and_fallback(self):
        self.assert_literal(r'"名单: \(names.joined(separator: "、")); 品种: \(breed ?? "未知")"')

    def test_nested_interpolated_string(self):
        self.assert_literal(r'"外层 \(format("中层 \(flag ? "是" : "否")")) 结束"')

    def test_parentheses_inside_nested_text(self):
        self.assert_literal(r'"结果 \(render("右括号 ) ( 引号 \"", item: (1 + (2))))"')

    def test_multiple_interpolations_and_empty_nested_string(self):
        self.assert_literal(r'"\(a ?? "") / \(b ?? "无")"')

    def test_escaped_backslash_does_not_open_interpolation(self):
        self.assert_literal(r'"文字 \\(literal) 结束"')

    def test_escaped_quotes_and_unicode_scalar(self):
        self.assert_literal(r'"引号 \"、反斜杠 \\、字符 \u{1F415}"')

    def test_nested_block_comments_do_not_close_interpolation(self):
        self.assert_literal(r'"\(value /* ) \" /* nested ) */ end */ ?? "无")"')

    def test_multiline_literal_and_nested_quotes(self):
        self.assert_literal('"""\n首行\n状态：\\(flag ? "是" : "否")\n尾行\n"""')

    def test_multiline_nested_literal(self):
        self.assert_literal('"""\n外层 \\(render("""\n嵌套\n"""))\n"""')

    def test_line_comment_in_multiline_interpolation(self):
        self.assert_literal('"""\n\\(render( // ) " ignored\n"实参"))\n"""')

    def test_extended_string_delimiters(self):
        self.assert_literal(r'#"文字 "引号" \(notInterpolation)；\#(flag ? "是" : "否")"#')

    def test_multiple_extended_delimiters(self):
        self.assert_literal(r'##"文字 "# \#(notInterpolation)；\##(render(#"中文 )"#))"##')

    def test_extended_multiline_literal(self):
        self.assert_literal('#"""\n文字 """ 不结束\n\\#(flag ? "是" : "否")\n"""#')

    def test_mismatched_raw_delimiter_is_not_silently_accepted(self):
        with self.assertRaisesRegex(MigrationError, 'Unterminated string'):
            tokenize('##"缺少匹配结束"#')

    def test_unterminated_string_is_not_silently_accepted(self):
        with self.assertRaisesRegex(MigrationError, 'Unterminated string'):
            tokenize('let value = "未结束')

    def test_unterminated_interpolation_is_not_silently_accepted(self):
        with self.assertRaisesRegex(MigrationError, 'Unterminated interpolation'):
            tokenize('let value = "值 \\(call(1)')

    def test_unterminated_nested_comment_is_not_silently_accepted(self):
        with self.assertRaisesRegex(MigrationError, 'Unterminated comment'):
            tokenize('let value = "值 \\(call(/* never closed')

    def test_unterminated_nested_string_is_not_silently_accepted(self):
        with self.assertRaisesRegex(MigrationError, 'Unterminated string'):
            tokenize('let value = "值 \\(call("未结束')

    def test_newline_does_not_hide_unterminated_single_line_string(self):
        with self.assertRaisesRegex(MigrationError, 'Unterminated string'):
            tokenize('let value = "未结束\nlet after = "第二行"')

    def test_backslash_cannot_continue_single_line_string(self):
        with self.assertRaisesRegex(MigrationError, 'Unterminated string'):
            tokenize('let value = "首行\\\n次行"')

    def test_unterminated_multiline_string_keeps_start_line(self):
        with self.assertRaisesRegex(MigrationError, 'Unterminated string at line 3'):
            tokenize('\n\nlet value = """\n未结束')

    def test_extended_regex_in_interpolation_requires_provider(self):
        with self.assertRaisesRegex(MigrationError, 'Regex literal.*syntax provider'):
            tokenize(r'"\(matches(#/[(]/#, text))"')

    def test_deep_nesting_has_diagnostic_instead_of_recursion_error(self):
        literal = '"末层"'
        for _ in range(80):
            literal = '"\\(format(' + literal + '))"'
        with self.assertRaisesRegex(MigrationError, 'Deep string interpolation.*syntax provider'):
            tokenize(literal)

    def test_line_tracking_after_multiline_comment_and_literal(self):
        tokens = tokenize('/* 前言\n /* 内层 */ */\nlet s = """\n\\(f("文字"))\n"""\nlet next = 1')
        strings = [t for t in tokens if t.kind == 'string']
        self.assertEqual(strings[0].line, 3)
        self.assertEqual(tokens[-4].value, 'let')
        self.assertEqual(tokens[-4].line, 6)

    def test_hash_directives_are_not_string_openers(self):
        tokens = tokenize('#if DEBUG\nlet value = "中文"\n#endif')
        self.assertEqual([t.value for t in tokens[:3]], ['#', 'if', 'DEBUG'])
        self.assertEqual([t.value for t in tokens if t.kind == 'string'], ['"中文"'])

    def test_known_closed_grammar_still_parses_simple_view(self):
        view = parse_view('struct Greeting: View { var body: some View { Text("你好") } }')
        self.assertEqual(view['root']['text'], [{'literal': '你好'}])

    def test_closed_grammar_still_rejects_complex_interpolation(self):
        with self.assertRaises(MigrationError):
            parse_view(r'struct Greeting: View { var body: some View { Text("\(flag ? "是" : "否")") } }')


class FactExtractionTests(unittest.TestCase):
    def test_text_does_not_become_code_but_real_unicode_identifier_stays_unresolved(self):
        with tempfile.TemporaryDirectory(prefix='plugin-001-facts-') as directory:
            source = Path(directory)
            (source / 'Example.swift').write_text(
                'let value = "状态 \\(flag ? "是" : "否")"\n', encoding='utf-8')
            graph = extract(source)
            self.assertFalse(any(i.get('rule') == 'IOS.TOKEN_IDENTIFIER_UNRESOLVED' for i in graph['issues']))
            (source / 'Example.swift').write_text('let 中文变量 = 1\n', encoding='utf-8')
            graph = extract(source)
            self.assertTrue(any(i.get('rule') == 'IOS.TOKEN_IDENTIFIER_UNRESOLVED' for i in graph['issues']))

    def test_unrelated_conditional_build_diagnostic_remains(self):
        with tempfile.TemporaryDirectory(prefix='plugin-001-conditional-') as directory:
            source = Path(directory)
            (source / 'Example.swift').write_text(
                '#if DEBUG\nlet value = "状态 \\(flag ? "是" : "否")"\n#endif\n', encoding='utf-8')
            issues = extract(source)['issues']
            self.assertEqual([i.get('rule') for i in issues], ['IOS.CONDITIONAL_BUILD'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
