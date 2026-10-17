"""Only the selected behavior handler can be diagnosed as empty."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.behavior import verify
from hmigbot_ios.core import digest, write_json
from test_ios_harness import fixture


class BehaviorNodeScopeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='behavior-node-scope-')
        self.addCleanup(temp.cleanup)
        self.source, self.project, self.graph = fixture(Path(temp.name))

    def check_node(self, text, selected_line, symbol, empty):
        target = self.project / 'entry/Counter.ets'
        target.parent.mkdir(exist_ok=True)
        target.write_text(text, encoding='utf-8')
        node = {'path': 'entry/Counter.ets', 'line': selected_line, 'symbol': symbol,
                'sha256': digest(target.read_bytes())}
        event = next(f for f in self.graph['facts'] if f['kind'] == 'event')
        write_json(self.project / 'spec/verification/ios-behavior.json', {
            'schema_version': 2, 'source_sha256': self.graph['source_sha256'],
            'chains': [{'source_fact': event['id'], **{k: node for k in ('input', 'processing', 'feedback')},
                        'review': {'status': 'reviewed', 'reviewer': 'fixture-source-reader'}}], 'cases': []})
        report, code = verify(self.project, self.source, self.graph, {'F001-AC01': {'judgment': 'ui'}})
        nodes = [f for f in report['failures'] if f['rule'] == 'IOS.BEHAVIOR_NODE']
        self.assertEqual(bool(nodes), empty, report)
        self.assertEqual(code, 2 if empty else 3, report)
        self.assertFalse(report['behavior_verified'])

    def test_unrelated_event_defaults_before_and_after_do_not_make_selected_save_empty(self):
        self.check_node('class Counter {\n  @Event onDismiss: () => void = () => {};\n'
                        '  save(): void { this.count += 1; }\n  @Event onSaved: () => void = () => {};\n}',
                        3, 'save', False)

    def test_selected_empty_method_still_fails(self):
        self.check_node('class Counter {\n  save(): void { /* no work */\n // still empty\n }\n}',
                        2, 'save', True)

    def test_selected_multiline_callback_still_fails(self):
        self.check_node('class Counter {\n  build() {\n    Button().onClick(\n      () => { /* empty */ }\n    );\n  }\n}',
                        3, 'onClick', True)

    def test_other_empty_method_and_literal_are_not_the_selected_handler(self):
        self.check_node('class Counter {\n  other(): void {}\n'
                        '  save(): void { const text = "=> {}"; this.write(text); }\n}',
                        3, 'save', False)

    def test_same_line_unrelated_empty_callback_does_not_taint_selected_call(self):
        self.check_node('class Counter {\n  build() {\n'
                        '    Button().onClick(() => { this.save(); }).onAppear(() => {});\n  }\n}',
                        3, 'onClick', False)

    def test_selected_empty_callback_is_not_hidden_by_next_nonempty_callback(self):
        self.check_node('class Counter {\n  build() {\n'
                        '    Button().onClick(() => {}).onAppear(() => { this.save(); });\n  }\n}',
                        3, 'onClick', True)

    def test_same_named_method_on_another_line_is_not_selected(self):
        self.check_node('class First { save(): void {} }\n'
                        'class Second { save(): void { this.write(); } }', 2, 'save', False)

    def test_selected_empty_duplicate_method_is_still_rejected(self):
        self.check_node('class First { save(): void { this.write(); } }\n'
                        'class Second { save(): void { /* no work */ } }', 2, 'save', True)

    def test_selected_multiline_method_signature_is_still_rejected(self):
        self.check_node('class Counter {\n  save(\n    value: number\n  ): void {\n'
                        '    // empty\n  }\n}', 2, 'save', True)

    def test_selected_named_arrow_with_multiline_body_is_still_rejected(self):
        self.check_node('const save = (value: number): void => {\n /* empty */\n};',
                        1, 'save', True)

    def test_selected_event_default_itself_is_empty(self):
        self.check_node('class Counter {\n  @Event onSaved: () => void = () => {\n'
                        '    // empty\n  };\n}', 2, 'onSaved', True)

    def test_type_arrow_and_default_parameter_are_not_the_selected_body(self):
        self.check_node('class Counter {\n  save(onDone: () => void = () => {}): void {\n'
                        '    this.write();\n  }\n}', 2, 'save', False)

    def test_callback_default_parameter_empty_arrow_does_not_taint_body(self):
        self.check_node('class Counter {\n  build() {\n'
                        '    Button().onClick((callback = () => {}) => { this.save(); });\n  }\n}',
                        3, 'onClick', False)

    def test_comment_and_all_string_kinds_do_not_supply_empty_callbacks(self):
        self.check_node('class Counter {\n  save(): void {\n'
                        '    // fake => {}\n    /* save(): void {} */\n'
                        '    const single = \'escaped \\\' => {}\';\n'
                        '    const double = "=> {}";\n'
                        '    const template = `=> {} ${() => {}}`;\n'
                        '    const pattern = /=> \\{\\}/;\n'
                        '    this.write(single + double + template + pattern);\n  }\n}',
                        2, 'save', False)

    def test_literal_expression_is_not_an_empty_body(self):
        self.check_node('class Counter {\n  save(): void { "=> {}"; }\n}',
                        2, 'save', False)

    def test_empty_nested_function_in_nonempty_selected_body_is_not_selected(self):
        self.check_node('class Counter {\n  save(): void {\n'
                        '    const unused = () => {};\n    this.write();\n  }\n}',
                        2, 'save', False)

    def test_multiline_nonempty_callback_ignores_following_empty_callback(self):
        self.check_node('class Counter {\n  build() {\n    Button().onClick(\n'
                        '      () => { this.save(); }\n    ).onAppear(\n'
                        '      () => {}\n    );\n  }\n}', 3, 'onClick', False)

    def test_comments_between_callback_tokens_do_not_hide_empty_body(self):
        self.check_node('class Counter {\n  build() {\n    Button().onClick(\n'
                        '      () /* parameter comment */ => /* body comment */ {\n'
                        '        // no work\n      }\n    );\n  }\n}',
                        3, 'onClick', True)

    def test_multiple_callback_arguments_are_not_assigned_to_the_wrong_callback(self):
        self.check_node('class Counter {\n  save(): void {\n'
                        '    this.exchange(() => { this.write(); }, () => {});\n  }\n}',
                        3, 'exchange', False)

    def test_ambiguous_same_symbol_same_line_requires_a_clearer_anchor(self):
        self.check_node('class Counter {\n  build() {\n'
                        '    Button().onClick(() => {}).onClick(() => { this.save(); });\n  }\n}',
                        3, 'onClick', True)

    def test_empty_structural_return_type_is_not_an_empty_method_body(self):
        self.check_node('class Counter {\n  save(): {} { return this.write(); }\n}',
                        2, 'save', False)

    def test_empty_method_with_structural_return_type_still_fails(self):
        self.check_node('class Counter {\n  save(): {} { /* empty */ }\n}',
                        2, 'save', True)

    def test_named_function_expression_empty_body_still_fails(self):
        self.check_node('const save = function(value: number): void {\n /* empty */\n};',
                        1, 'save', True)

    def test_template_with_nested_template_does_not_capture_the_next_method(self):
        self.check_node('class Counter {\n  value: string = `${`nested ${"=> {}"}`}`;\n'
                        '  save(): void { this.write(); }\n}', 3, 'save', False)


if __name__ == '__main__':
    unittest.main()
