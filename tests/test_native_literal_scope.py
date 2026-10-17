"""Numeric representation repair must preserve original literal failures."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.native_literal_scope import audit, canonical_ledger
from hmigbot_ios.core import digest, snapshot


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')


def fixture(project, *, text='Exact UI text', include_number=True):
    write(project / 'build-profile.json5', json.dumps({'app': {'products': [{'name': 'default'}]},
        'modules': [{'name': 'entry', 'srcPath': './entry',
                     'targets': [{'name': 'default', 'applyToProducts': ['default']}]}]}))
    write(project / 'entry/src/main/module.json5', '{"module":{"name":"entry","type":"entry"}}')
    write(project / '.migbot/config.json', '{"source_platform":"ios"}')
    ledger = {'schema_version': 2, 'source_platform': 'ios',
        'texts': [{'value': 'Exact UI text', 'page_level': True, 'sources': ['Views/Home.swift:4'],
                   'classification': 'product'}], 'colors': [],
        'dims': [{'value': 24, 'unit': 'source_point_or_context_unresolved',
                  'sources': ['Views/Home.swift:5'], 'file_sha256': 'c' * 64}],
        'durations_ms': [{'value': 1000, 'sources': ['Services/Timer.swift:3']}],
        'numeric_constants': [{'value': 24, 'sources': ['Models/Metadata.swift:2']}],
        'dynamic_texts': [{'source_expression': '"runtime \\(value)"', 'decoding_status': 'unresolved'}]}
    write(project / 'spec/baseline/literal-ledger.json', json.dumps(ledger))
    number = '.width(24)' if include_number else ''
    write(project / 'entry/src/main/ets/pages/Index.ets',
        "@Entry\n@ComponentV2\nstruct Index { build() { Text(" + json.dumps(text) + ')' + number + ' } }\n'
        'export const timerDuration: number = 1000;\n')
    # History cannot satisfy missing production UI or numbers.
    write(project / 'spec/archive/entry/src/main/ets/pages/Old.ets',
        "Text('Exact UI text').width(24);\n")
    return ledger


class NativeLiteralScopeTests(unittest.TestCase):
    def test_only_finite_numeric_values_change_and_all_items_metadata_survive(self):
        raw = {'dims': [{'value': 24, 'unit': 'source_point_or_context_unresolved',
                        'sources': ['A.swift:1'], 'classification': 'metadata'}],
               'durations_ms': [{'value': 1.5, 'sources': ['A.swift:2']}],
               'texts': [{'value': 'Exact', 'page_level': True}],
               'numeric_constants': [{'value': 24}], 'extra': {'preserve': True}}
        before = copy.deepcopy(raw)
        canonical, changes = canonical_ledger(raw)
        self.assertEqual(raw, before)
        expected = copy.deepcopy(raw)
        expected['dims'][0]['value'] = '24'
        expected['durations_ms'][0]['value'] = '1.5'
        self.assertEqual(canonical, expected)
        self.assertEqual(len(changes), 2)
        for value in (True, None, float('nan'), float('inf'), {'number': 24}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_ledger({'dims': [{'value': value}]})

    def test_actual_original_int_and_duration_execute_without_claiming_unit_coverage(self):
        with tempfile.TemporaryDirectory(prefix='native-literal-numeric-') as temporary:
            project = Path(temporary)
            raw = fixture(project)
            before = {str(path.relative_to(project)): path.read_bytes() for path in project.rglob('*') if path.is_file()}
            report = audit(project)
            self.assertTrue(report['passed'], report)
            self.assertEqual(report['original_report']['stats']['dims']['ok'], 1)
            self.assertEqual(report['original_report']['stats']['durations']['ok'], 1)
            self.assertEqual(report['stats']['dims']['ok'], 0)
            self.assertEqual(report['stats']['dims']['unresolved'], 1)
            self.assertFalse(report['native_literal_inputs']['source_units_verified'])
            self.assertEqual(report['native_literal_inputs']['unresolved_dimensions'][0]['value'], 24)
            self.assertEqual(report['native_literal_inputs']['raw_items_removed'], 0)
            self.assertEqual(raw['texts'][0]['classification'], 'product')
            self.assertEqual(before, {str(path.relative_to(project)): path.read_bytes() for path in project.rglob('*') if path.is_file()})

    def test_missing_page_text_keeps_original_failure_even_with_matching_number_and_history(self):
        with tempfile.TemporaryDirectory(prefix='native-literal-text-fail-') as temporary:
            project = Path(temporary)
            fixture(project, text='Completely different wording')
            report = audit(project)
            self.assertFalse(report['passed'], report)
            self.assertEqual(report['findings'], report['original_report']['findings'])
            self.assertEqual(report['stats']['texts'], report['original_report']['stats']['texts'])
            self.assertGreater(report['stats']['texts']['missing_page'], 0)
            self.assertTrue(any(item['severity'] == 'FAIL' for item in report['findings']))

    def test_absent_number_retains_missing_and_unresolved_instead_of_coverage_pass(self):
        with tempfile.TemporaryDirectory(prefix='native-literal-dim-missing-') as temporary:
            project = Path(temporary)
            fixture(project, include_number=False)
            report = audit(project)
            self.assertEqual(report['original_report']['stats']['dims']['missing'], 1)
            self.assertEqual(report['stats']['dims']['missing'], 1)
            self.assertEqual(report['stats']['dims']['ok'], 0)
            self.assertEqual(report['stats']['dims']['unresolved'], 1)

    def native_source_fixture(self, project, body, texts):
        fixture(project, text='Unrelated target UI')
        source = project / 'source-ios'
        write(source / 'View.swift', body)
        write(project / '.migbot/config.json', json.dumps({'source_platform': 'ios', 'ios': str(source)}))
        file_sha = digest((source / 'View.swift').read_bytes())
        ledger = {'schema_version': 2, 'source_platform': 'ios', 'source_sha256': snapshot(source)['sha256'],
            'texts': [{'value': value, 'page_level': True, 'sources': ['View.swift:' + str(line)],
                       'file_sha256': file_sha} for line, value in texts],
            'colors': [], 'dims': [], 'durations_ms': []}
        write(project / 'spec/baseline/literal-ledger.json', json.dumps(ledger))
        return source, ledger

    def test_source_argument_roles_do_not_hide_same_value_as_real_text(self):
        with tempfile.TemporaryDirectory(prefix='native-literal-role-') as temporary:
            project = Path(temporary)
            self.native_source_fixture(project,
                'import SwiftUI\nstruct ViewOne: View {\n var body: some View {\n'
                '  Image(systemName: "same-spelling")\n  Text("same-spelling")\n }\n}\n',
                [(4, 'same-spelling'), (5, 'same-spelling')])
            report = audit(project)
            self.assertFalse(report['passed'])
            self.assertEqual(report['native_literal_inputs']['classified_non_page_text_count'], 1)
            self.assertEqual(report['stats']['texts']['missing_page'], 1)
            self.assertEqual(report['original_report']['stats']['texts']['missing_page'], 2)
            roles = report['native_literal_inputs']['text_classifications']
            self.assertFalse(roles[0]['page_literal_required'])
            self.assertTrue(roles[1]['page_literal_required'])

    def test_local_shadowed_constructor_is_never_classified_as_platform_metadata(self):
        for body in ('import SwiftUI\nstruct Image { init(systemName: String) {} }\n'
                     'let example = Image(systemName: "Required custom UI")\n',
                     'import SwiftUI\nlet Image: (String) -> Text = { Text($0) }\n'
                     'let example = Image("Required custom UI")\n'):
            with self.subTest(body=body), tempfile.TemporaryDirectory(prefix='native-literal-shadow-') as temporary:
                project = Path(temporary)
                self.native_source_fixture(project, body, [(3, 'Required custom UI')])
                report = audit(project)
                self.assertFalse(report['passed'])
                self.assertEqual(report['native_literal_inputs']['classified_non_page_text_count'], 0)

    def test_reviewed_test_span_requires_exact_current_source_hash(self):
        with tempfile.TemporaryDirectory(prefix='native-literal-test-span-') as temporary:
            project = Path(temporary)
            source, raw = self.native_source_fixture(project,
                'import XCTest\nlet fixtureLabel = "Test-only value"\n', [(2, 'Test-only value')])
            disposition = {'source_sha256': raw['source_sha256'], 'files': [{'path': 'View.swift',
                'source_sha256': digest((source / 'View.swift').read_bytes()), 'line': 1, 'end_line': 2,
                'disposition': 'test', 'reason': 'Independent reviewed test-target member'}]}
            path = project / 'spec/baseline/ios-source-disposition.json'
            write(path, json.dumps(disposition))
            report = audit(project)
            self.assertTrue(report['passed'])
            self.assertFalse(report['original_report']['passed'])
            disposition['files'][0]['source_sha256'] = '0' * 64
            write(path, json.dumps(disposition))
            rejected = audit(project)
            self.assertFalse(rejected['passed'])
            self.assertEqual(rejected['native_literal_inputs']['classified_non_page_text_count'], 0)

    def test_metadata_like_calls_cannot_consume_unrelated_or_real_ui(self):
        cases = [
            ('import SwiftUI\nlet kind = "Required UI"\nText(kind)\nStaticConfiguration(kind: kind, provider: provider) {}\n', 2),
            ('import Vision\nimport SwiftUI\nlet request = VNRecognizeTextRequest()\nrequest.recognitionLanguages = ["en-US"]; Text("Required UI")\n', 4),
            ('import SwiftUI\nmodel.object(forInfoDictionaryKey: "Required UI")\n', 2),
            ('import Foundation\nstruct FileManager { static let `default` = FileManager(); func containerURL(forSecurityApplicationGroupIdentifier input: String) -> String { input } }\n'
             'enum Container {\nstatic var groupID: String { Bundle.main.object(forInfoDictionaryKey: "Meta") as? String ?? "Required UI" }\n'
             'static var fileURL: String { FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: groupID) }\n}\n', 4),
        ]
        for body, line in cases:
            with self.subTest(body=body), tempfile.TemporaryDirectory(prefix='native-literal-defuse-negative-') as temporary:
                project = Path(temporary)
                self.native_source_fixture(project, body, [(line, 'Required UI')])
                report = audit(project)
                self.assertFalse(report['passed'])
                self.assertEqual(report['native_literal_inputs']['classified_non_page_text_count'], 0)

    def test_hidden_chart_label_requires_same_chain_hidden_axis_and_aggregate_label(self):
        for hidden, expected in [(True, 1), (False, 0)]:
            with self.subTest(hidden=hidden), tempfile.TemporaryDirectory(prefix='native-literal-chart-role-') as temporary:
                project = Path(temporary)
                body = ('import SwiftUI\nimport Charts\nlet chart = Chart(values) { row in\n'
                        ' LineMark(x: .value("Dimension", row.x), y: .value("Score", row.y))\n'
                        '}.chartXAxis(.' + ('hidden' if hidden else 'visible') + ').accessibilityLabel("Summary")\n')
                self.native_source_fixture(project, body, [(4, 'Dimension')])
                report = audit(project)
                self.assertEqual(report['native_literal_inputs']['classified_non_page_text_count'], expected)
                self.assertEqual(report['passed'], hidden)

    def test_chart_later_axis_or_accessibility_override_cannot_reuse_earlier_hidden_label(self):
        for suffix in ('.chartXAxis(.hidden).chartXAxis(.automatic).accessibilityLabel("Summary")',
                       '.chartXAxis(.hidden).accessibilityLabel("Summary").accessibilityLabel(variable)'):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory(prefix='native-literal-chart-override-') as temporary:
                project = Path(temporary)
                body = ('import SwiftUI\nimport Charts\nlet chart = Chart(values) { row in\n'
                        ' LineMark(x: .value("Dimension", row.x), y: .value("Score", row.y))\n}' + suffix + '\n')
                self.native_source_fixture(project, body, [(4, 'Dimension')])
                report = audit(project)
                self.assertFalse(report['passed'])
                self.assertEqual(report['native_literal_inputs']['classified_non_page_text_count'], 0)


if __name__ == '__main__':
    unittest.main()
