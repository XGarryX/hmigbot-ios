"""Swift extended delimiters must survive inventory without JSON reinterpretation."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))

from hmigbot_ios.core import MigrationError, digest, json_bytes, read_json, write_json
from hmigbot_ios.ios_facts import extract as extract_facts, refresh
from hmigbot_ios.ios_literals import extract, run as literals
from hmigbot_ios.native_pipeline import configure
from hmigbot_ios.quality_views import product_literals, validate_product_view
from hmigbot_ios.source_scope import preview_lines
from hmigbot_ios.swiftui import emit_view, parse_view, tokenize


class ExtendedStringTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ios-raw-strings-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()

    def write_source(self, text):
        path = self.source / 'Screen.swift'
        path.write_text(text, encoding='utf-8')
        return path

    def test_raw_tokens_preserve_all_delimiters_and_source_span(self):
        for hashes in ('#', '##', '####'):
            expression = hashes + '"line\\nnext"' + hashes
            with self.subTest(expression=expression):
                tokens = tokenize('let label = ' + expression + '\nlet after = 1')
                strings = [token for token in tokens if token.kind == 'string']
                self.assertEqual([token.value for token in strings], [expression])
                token = strings[0]
                self.assertEqual(token.hash_count, len(hashes))
                self.assertEqual(token.quote_count, 1)
                self.assertEqual(token.end_line, 1)
                self.assertEqual(('let label = ' + expression)[token.start:token.end], expression)
                self.assertEqual(next(t.line for t in tokens if t.value == 'after'), 2)

    def test_raw_internal_quotes_and_fake_syntax_never_escape_string_token(self):
        expression = '#"say "hello" #Preview { Text("fake") } async await"#'
        tokens = tokenize('let label = ' + expression + '\nlet after = 1')
        self.assertEqual([t.value for t in tokens if t.kind == 'string'], [expression])
        self.assertFalse(any(t.value in {'Preview', 'Text', 'async', 'await'} for t in tokens))

    def test_raw_multiline_keeps_exact_expression_and_following_line(self):
        expression = '##"""\nline \\n "quotes"\n#Preview { Text("fake") }\n"""##'
        tokens = tokenize('let label = ' + expression + '\nlet after = 1')
        token = next(t for t in tokens if t.kind == 'string')
        self.assertEqual(token.value, expression)
        self.assertEqual(token.hash_count, 2)
        self.assertEqual(token.quote_count, 3)
        self.assertEqual((token.line, token.end_line), (1, 4))
        self.assertEqual(next(t.line for t in tokens if t.value == 'after'), 5)

    def test_active_interpolation_keeps_nested_strings_and_parentheses_in_one_token(self):
        expressions = [
            '"value \\(format("x", nested(1)))"',
            '#"value \\#(format("x", nested(#"n"#)))"#',
            '##"value \\##(format("x", nested(#"n"#)))"##',
        ]
        for expression in expressions:
            with self.subTest(expression=expression):
                tokens = tokenize('let label = ' + expression + '\nlet after = 1')
                self.assertEqual([t.value for t in tokens if t.kind == 'string'], [expression])
                self.assertFalse(any(t.value in {'format', 'nested'} for t in tokens))
                self.assertEqual(next(t.line for t in tokens if t.value == 'after'), 2)

    def test_interpolation_comments_do_not_end_outer_string_or_create_tokens(self):
        expression = '#"value \\#(format(/* ) "# */ "x") // ) "#\n)"#'
        tokens = tokenize('let label = ' + expression + '\nlet after = 1')
        self.assertEqual([t.value for t in tokens if t.kind == 'string'], [expression])
        self.assertEqual(next(t.line for t in tokens if t.value == 'after'), 3)

    def test_unterminated_extended_delimiter_is_rejected(self):
        for text in ('let x = ##"value"#', 'let x = #"value \\#(format("x")"#'):
            with self.subTest(text=text), self.assertRaises(MigrationError):
                tokenize(text)

    def test_extract_plain_newline_stays_decoded_but_raw_stays_unresolved(self):
        raw_expressions = ['#"line\\nnext"#', '##"tab\\there"##', '#"say "hello""#']
        self.write_source('let plain = "line\\nnext"\n' + '\n'.join(
            f'let raw{index} = {expression}' for index, expression in enumerate(raw_expressions)))
        ledger = extract(self.source)
        self.assertEqual([item['value'] for item in ledger['texts']], ['line\nnext'])
        self.assertEqual([item['source_expression'] for item in ledger['dynamic_texts']], raw_expressions)
        self.assertTrue(all(item['decoding_status'] == 'unresolved' and
                            item['reason'] == 'extended_delimiter_requires_swift_semantic_decode'
                            and 'value' not in item for item in ledger['dynamic_texts']))

    def test_dynamic_reasons_distinguish_interpolation_multiline_and_invalid_escape(self):
        expressions = ['"value \\(count)"', '"""\nline\n"""', '"value \\u{41}"']
        self.write_source('\n'.join(f'let text{index} = {value}' for index, value in enumerate(expressions)))
        items = extract(self.source)['dynamic_texts']
        self.assertEqual([item['source_expression'] for item in items], expressions)
        self.assertEqual([item['reason'] for item in items], [
            'interpolation_requires_runtime_evaluation', 'multiline_requires_swift_semantic_decode',
            'unsupported_swift_string_escape'])

    def test_preview_scope_ignores_fake_markers_and_braces_in_raw_strings(self):
        text = ('let label = #"#Preview { Text("fake") }"#\n'
                '#Preview {\n'
                '    Text(##"quotes " } #Preview { " and \\(inactive)"##)\n'
                '}\n'
                'let after = "outside"\n')
        self.assertEqual(preview_lines(text), {2, 3, 4})

    def test_facts_do_not_invent_events_or_services_from_raw_contents(self):
        self.write_source('let label = #"say "x" Button("fake") { URLSession async await }"#\n')
        graph = extract_facts(self.source)
        self.assertFalse(any(f['kind'] in {'event', 'service', 'task', 'composition'} for f in graph['facts']))
        self.assertFalse(any(i['rule'] == 'IOS.TOKEN_BALANCE' for i in graph['issues']))

    def test_limited_parser_rejects_raw_explicitly_and_preserves_plain_codegen(self):
        for expression in ('#"hello"#', '##"hello"##', '#"""\nhello\n"""#'):
            with self.subTest(expression=expression), self.assertRaisesRegex(MigrationError, 'extended-delimiter'):
                parse_view('import SwiftUI\nstruct Screen: View { var body: some View { Text(' + expression + ') } }')
        view = parse_view('import SwiftUI\nstruct Screen: View { @State var count = 1 '
                          'var body: some View { Text("line\\nnext \\(count)") } }')
        self.assertEqual(view['root']['text'], [{'literal': 'line\nnext '}, {'state': 'count'}, {'literal': ''}])
        self.assertIn('Text("line\\nnext " + this.count.toString())', emit_view(view))

    def test_product_view_reextracts_same_raw_without_promoting_decoded_product_label(self):
        expression = '#"line\\nnext with "quote""#'
        self.write_source('import SwiftUI\nstruct Screen: View {\n'
                          ' var body: some View { Text(' + expression + ') }\n}\n')
        project = self.root / 'target'
        project.mkdir()
        configure(self.source, project)
        graph = refresh(project, self.source)
        literals(project)
        base = project / 'spec/baseline'
        (base / 'features').mkdir()
        (base / 'features/F001-label.md').write_text(
            '# F001\n- [ ] F001-AC01 Label preserves the source text `判:ui | Label stays exact`\n', encoding='utf-8')
        write_json(base / 'ios-coverage.json', {
            'schema_version': 2, 'graph_sha256': digest(json_bytes(graph)),
            'mappings': [{'obligation_id': 'IO-' + fact['id'][3:], 'ac_ids': ['F001-AC01'],
                          'source_review': {'status': 'reviewed', 'input': 'Read source label',
                              'processing': 'Keep literal semantics', 'observable': 'Exact visible label',
                              'reviewer': 'independent-source-reader'}} for fact in graph['facts']]})
        ledger = read_json(base / 'literal-ledger.json')
        self.assertEqual(ledger, extract(self.source))
        view = product_literals(project)
        candidates = [item for item in view['entries'] if item['raw_ref']['collection'] == 'dynamic_texts']
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['classification'], 'product')
        self.assertEqual(candidates[0]['source_expression'], expression)
        self.assertEqual(candidates[0]['decoding_status'], 'unresolved')
        self.assertEqual(candidates[0]['usage'], 'unresolved')
        self.assertNotIn('value', candidates[0])
        self.assertFalse(any(item.get('value') == 'line\nnext with ' for item in view['entries']))
        self.assertTrue(validate_product_view(project, view))


if __name__ == '__main__':
    unittest.main()
