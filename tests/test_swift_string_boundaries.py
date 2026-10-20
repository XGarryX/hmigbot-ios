"""Boundary regression for the Swift string lexer in hmigbot_ios.swiftui.

This is the maintenance test for THEF-52 (lexer). It pins the contract that the
closed SwiftUI grammar uses for strings:

* LEGAL: raw strings (e.g. #"..."#), multiline triple-quoted strings, interpolation
  with nested strings/comments, and escaped quotes all tokenize to a single string
  token and never lose literal content or leak inner identifiers as tokens.
* LEGAL-BUT-UNSUPPORTED (stable "requires syntax provider" diagnostic): regex
  literals in interpolations, and nesting
  deeper than the supported bound. Deep nesting is legal Swift but outside this
  grammar's resolve set, so it is reported, never silently accepted or crashed on.
* ILLEGAL (genuine "Unterminated ..." / "Unterminated comment" errors): a
  single-line string cannot contain a raw or escaped newline; raw delimiters must
  balance; an unclosed interpolation is a
  specific "Unterminated string interpolation"; comments must close.

The tests load the current src package, so they track the implementation.
Syntax contract: Swift's official Lexical Structure, String Literals grammar:
https://docs.swift.org/latest/documentation/the-swift-programming-language/lexicalstructure/
"""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from hmigbot_ios.core import MigrationError
from hmigbot_ios.swiftui import (
    RequiresSyntaxProvider, _string_opening, parse_view, tokenize,
)

BS = chr(92)          # one literal backslash
NL = chr(10)          # one literal newline
DQ = chr(34)          # one double quote
HASH = chr(35)        # one hash


def lex(src):
    """Tokenize and return only the string-kind tokens."""
    return [t for t in tokenize(src) if t.kind == 'string']


class StringBoundaryTests(unittest.TestCase):
    # ------------------------------------------------------------------
    # 18 LEGAL cases: must tokenize and preserve the single string token.
    # ------------------------------------------------------------------
    def test_plain_string(self):
        tokens = lex('let label = "hello"')
        self.assertEqual([t.value for t in tokens], ['"hello"'])

    def test_extended_string_single_hash(self):
        tokens = lex('let label = #"hello"#')
        self.assertEqual([t.value for t in tokens], ['#"hello"#'])

    def test_extended_string_two_hashes(self):
        tokens = lex('let label = ##"hi"##')
        self.assertEqual([t.value for t in tokens], ['##"hi"##'])

    def test_extended_string_four_hashes(self):
        tokens = lex('let label = ####"x"####')
        self.assertEqual([t.value for t in tokens], ['####"x"####'])

    def test_multiline_triple_quote(self):
        tokens = lex('let label = ' + DQ * 3 + NL + 'line' + NL + DQ * 3)
        self.assertEqual(tokens[0].quote_count, 3)
        self.assertEqual(tokens[0].value, DQ * 3 + NL + 'line' + NL + DQ * 3)

    def test_extended_multiline(self):
        expr = '##' + DQ * 3 + NL + 'line' + NL + DQ * 3 + '##'
        tokens = lex('let label = ' + expr)
        self.assertEqual(tokens[0].value, expr)
        self.assertEqual((tokens[0].line, tokens[0].end_line), (1, 3))

    def test_interpolation_nested_plain_string(self):
        expr = '"a' + BS + '(b("c"))d"'
        tokens = lex('let label = ' + expr)
        self.assertEqual([t.value for t in tokens], [expr])
        self.assertFalse(any(t.value == 'c' for t in tokens))

    def test_interpolation_nested_extended_string(self):
        expr = '"a' + BS + '(#"bc"#)d"'
        tokens = lex('let label = ' + expr)
        self.assertEqual([t.value for t in tokens], [expr])

    def test_extended_interpolation_mixed_nesting(self):
        # inside #"..."#, an interpolation holds a plain and an extended string.
        expr = '#"v' + BS + HASH + '(f("x", #"y"#))w"#'
        tokens = lex('let label = ' + expr)
        self.assertEqual([t.value for t in tokens], [expr])
        self.assertFalse(any(t.value in {'f', 'x', 'y'} for t in tokens))

    def test_comments_inside_interpolation_do_not_break_outer(self):
        expr = ('#"v' + BS + HASH + '(f(/* ) "' + HASH + ' */ "x") // ) "' + HASH
               + NL + ')"#')
        tokens = lex('let label = ' + expr)
        self.assertEqual([t.value for t in tokens], [expr])
        self.assertEqual(next(t.line for t in tokenize('let label = ' + expr)
                             if t.value == 'label'), 1)

    def test_raw_internal_quotes_and_fake_syntax(self):
        expr = '#"say "hello" #Preview { Text("fake") }"#'
        tokens = lex('let label = ' + expr)
        self.assertEqual([t.value for t in tokens], [expr])
        self.assertFalse(any(t.value in {'Preview', 'Text'} for t in tokens))

    def test_escaped_quote_in_plain_string(self):
        expr = '"a' + BS + '"b"'
        tokens = lex('let label = ' + expr)
        self.assertEqual([t.value for t in tokens], [expr])

    def test_unicode_preserved_in_string(self):
        expr = '"中文与emoji😀end"'
        tokens = lex('let label = ' + expr)
        self.assertEqual(tokens[0].value, expr)

    def test_backslash_n_escape_preserved_in_extended(self):
        # backslash + n is literal inside an extended delimiter (no real newline)
        expr = '#"line' + BS + 'nnext"#'
        tokens = lex('let label = ' + expr)
        self.assertEqual(tokens[0].value, expr)

    def test_triple_quote_internal_double_quotes(self):
        expr = DQ * 3 + 'he said "hi" there' + DQ * 3
        tokens = lex('let label = ' + expr)
        self.assertEqual(tokens[0].value, expr)

    def test_consecutive_strings_make_two_tokens(self):
        tokens = lex('let a = "x" let b = "y"')
        self.assertEqual([t.value for t in tokens], ['"x"', '"y"'])

    def test_interpolation_at_supported_bound_is_legal(self):
        expr = DQ + BS + '(' + '(' * 63 + 'v' + ')' * 64 + DQ
        tokens = lex('let label = ' + expr)
        self.assertEqual([t.value for t in tokens], [expr])

    def test_deep_string_interp_recursion_within_bound_is_legal(self):
        s = DQ + 'v' + DQ
        for _ in range(50):
            s = DQ + BS + '(' + s + ')' + DQ
        tokens = lex('let label = ' + s)
        self.assertEqual([t.value for t in tokens], [s])

    # ------------------------------------------------------------------
    # Malformed strings remain syntax errors, including extended delimiters.
    # ------------------------------------------------------------------
    def test_unterminated_extended_is_unterminated(self):
        with self.assertRaises(MigrationError) as ctx:
            tokenize('let x = #"abc"')
        self.assertIn('Unterminated string', str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, RequiresSyntaxProvider)

    def test_mismatched_hash_extended_is_unterminated(self):
        with self.assertRaises(MigrationError) as ctx:
            tokenize('let x = ##"abc"#')
        self.assertIn('Unterminated string', str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, RequiresSyntaxProvider)

    def test_unterminated_extended_inside_interpolation_is_unterminated(self):
        with self.assertRaises(MigrationError) as ctx:
            tokenize('let x = "' + BS + '(#"abc")')
        self.assertIn('Unterminated string', str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, RequiresSyntaxProvider)

    def test_single_line_backslash_newline_is_unterminated(self):
        # Swift lexicalstructure: escaped-newline is multiline-only.
        with self.assertRaises(MigrationError) as ctx:
            tokenize('let x = "abc' + BS + NL + 'def"')
        self.assertIn('Unterminated string', str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, RequiresSyntaxProvider)

    def test_interpolation_nesting_80_exceeds_support(self):
        expr = DQ + BS + '(' + '(' * 79 + 'v' + ')' * 80 + DQ
        with self.assertRaises(RequiresSyntaxProvider) as ctx:
            tokenize('let x = ' + expr)
        self.assertIn('requires syntax provider', str(ctx.exception))

    def test_interpolation_nesting_bound_plus_one_exceeds_support(self):
        expr = DQ + BS + '(' + '(' * 64 + 'v' + ')' * 65 + DQ
        with self.assertRaises(RequiresSyntaxProvider) as ctx:
            tokenize('let x = ' + expr)
        self.assertIn('requires syntax provider', str(ctx.exception))

    def test_string_interp_recursion_above_bound_is_syntax_provider(self):
        s = DQ + 'v' + DQ
        for _ in range(450):
            s = DQ + BS + '(' + s + ')' + DQ
        with self.assertRaises(RequiresSyntaxProvider) as ctx:
            tokenize('let x = ' + s)
        self.assertIn('requires syntax provider', str(ctx.exception))

    def test_deep_nesting_never_recursion_errors(self):
        # 300 levels of interpolation nesting must report, not crash.
        expr = DQ + BS + '(' + '(' * 299 + 'v' + ')' * 300 + DQ
        try:
            tokenize('let x = ' + expr)
        except RecursionError:
            self.fail('deep nesting raised RecursionError instead of a stable diagnostic')
        except RequiresSyntaxProvider:
            pass

    # ------------------------------------------------------------------
    # 6 ILLEGAL cases: genuine unterminated / comment errors.
    # ------------------------------------------------------------------
    def test_unterminated_plain_string_at_eof(self):
        with self.assertRaises(MigrationError) as ctx:
            tokenize('let x = "abc')
        self.assertIn('Unterminated string', str(ctx.exception))

    def test_single_line_raw_newline_is_unterminated(self):
        with self.assertRaises(MigrationError) as ctx:
            tokenize('let x = "abc' + NL + 'def"')
        self.assertIn('Unterminated string', str(ctx.exception))

    def test_unterminated_interpolation_outer_open(self):
        with self.assertRaises(MigrationError) as ctx:
            tokenize('let x = "abc' + BS + '(def')
        self.assertIn('Unterminated interpolation', str(ctx.exception))

    def test_unterminated_comment(self):
        with self.assertRaises(MigrationError) as ctx:
            tokenize('let x = /* open')
        self.assertIn('Unterminated comment', str(ctx.exception))

    def test_unclosed_interpolation_outer_closes_is_specific(self):
        # The outer string closes but \( was never closed: the specific,
        # stable diagnostic is "Unterminated string interpolation", not the
        # phantom nested string's "Unterminated string".
        with self.assertRaises(MigrationError) as ctx:
            tokenize('let x = "abc' + BS + '(def"')
        self.assertIn('Unterminated string interpolation', str(ctx.exception))
        self.assertNotIn('Unterminated string at', str(ctx.exception))

    def test_lone_opening_quote_is_unterminated(self):
        with self.assertRaises(MigrationError) as ctx:
            tokenize('let x = "')
        self.assertIn('Unterminated string', str(ctx.exception))

    def test_single_line_cr_and_crlf_are_unterminated(self):
        # Both line-break scalars are excluded from Swift quoted-text-item.
        for delimiter in ('', '#', '##'):
            for newline in ('\r', '\r\n'):
                for escape in ('', BS + delimiter):
                    with self.subTest(delimiter=delimiter, newline=newline, escape=escape):
                        with self.assertRaisesRegex(MigrationError, 'Unterminated string') as ctx:
                            tokenize(delimiter + DQ + 'a' + escape + newline + 'b' + DQ + delimiter)
                        self.assertNotIsInstance(ctx.exception, RequiresSyntaxProvider)

    def test_multiline_escaped_newline_remains_supported(self):
        for delimiter in ('', '#', '##'):
            expr = delimiter + DQ * 3 + NL + 'a' + BS + delimiter + NL + 'b' + NL + DQ * 3 + delimiter
            with self.subTest(delimiter=delimiter):
                self.assertEqual([t.value for t in lex(expr)], [expr])

    def test_extended_regex_is_identified_before_its_contents(self):
        for pattern in ('#/abc/#', '##/a"b(//c/##'):
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(RequiresSyntaxProvider, 'Regex literal.*syntax provider'):
                    tokenize(DQ + BS + '(matches(' + pattern + ', text))' + DQ)

    def test_regex_like_text_inside_nested_string_stays_text(self):
        expr = DQ + BS + '(render("#/[(]/#"))' + DQ
        self.assertEqual([t.value for t in lex(expr)], [expr])

    # ------------------------------------------------------------------
    # Contract: positive parse path still works (Text with interpolation).
    # ------------------------------------------------------------------
    def test_parse_view_positive_interpolation_unchanged(self):
        view = parse_view(
            'import SwiftUI\nstruct Screen: View { @State var count = 1 '
            'var body: some View { Text("line' + BS + 'nnext ' + BS + '(count)") } }')
        self.assertEqual(
            view['root']['text'],
            [{'literal': 'line\nnext '}, {'state': 'count'}, {'literal': ''}])


if __name__ == '__main__':
    unittest.main()
