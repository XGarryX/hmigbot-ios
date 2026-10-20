"""Target-specific extraction subjects must survive independent queue repair."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import digest, json_bytes, read_json, write_json
from hmigbot_ios.finding_identity import extraction_finding
from hmigbot_ios.native_pipeline import findings_module


class ExtractionIdentityTests(unittest.TestCase):
    def setUp(self):
        self.queue = findings_module()
        self.issue = {'code': 'build_script_not_executed', 'path': 'App.xcodeproj/project.pbxproj', 'target': 'App'}

    def finding(self, **changes):
        return extraction_finding(self.queue, {**self.issue, **changes})

    def test_app_and_widget_have_independent_keys_and_paths_remain_visible(self):
        app, widget = self.finding(), self.finding(target='Widget')
        self.assertNotEqual(app['finding_key'], widget['finding_key'])
        self.assertEqual(app['subject_ref'], self.issue['path'])
        self.assertEqual(widget['subject_ref'], self.issue['path'])
        self.assertIn('Widget', widget['display_subject'])
        self.assertEqual(widget['extraction_subject']['issue_code'], self.issue['code'])

    def test_diagnostic_wording_and_dictionary_order_do_not_change_key(self):
        original = self.finding()
        changed = extraction_finding(self.queue, {'target': 'App', 'path': self.issue['path'],
                                                'message': 'Different diagnostic wording', 'code': self.issue['code']})
        self.assertEqual(original['finding_key'], changed['finding_key'])
        self.assertNotEqual(original['detail'], changed['detail'])

    def test_code_project_and_explicit_configuration_distinguish_subject(self):
        original = self.finding()
        for changes in ({'code': 'synchronized_groups_need_xcode_resolution'},
                        {'path': 'Other.xcodeproj/project.pbxproj'},
                        {'project_path': 'Other.xcodeproj/project.pbxproj'},
                        {'configuration': 'Release'}):
            with self.subTest(changes=changes):
                self.assertNotEqual(original['finding_key'], self.finding(**changes)['finding_key'])
        self.assertNotEqual(self.finding(configuration='Debug')['finding_key'], self.finding(configuration='Release')['finding_key'])

    def test_unscoped_issue_preserves_legacy_path_key_and_shape(self):
        issue = {'code': 'project_parse_failed', 'path': self.issue['path'], 'message': 'Malformed project'}
        expected = self.queue.make('IOS.EXTRACTION_UNRESOLVED', 'spec', issue['path'], str(issue))
        self.assertEqual(extraction_finding(self.queue, issue), expected)

    def test_real_extraction_of_app_and_widget_scripts_preserves_both_issues(self):
        from hmigbot_ios.ios_facts import extract
        from test_project_scope import openstep
        temp = tempfile.TemporaryDirectory(prefix='two target extraction ')
        self.addCleanup(temp.cleanup)
        source = Path(temp.name)
        project_path = source / self.issue['path']
        project_path.parent.mkdir()
        objects = {}
        for target in ('App', 'Widget'):
            objects[target] = {'isa': 'PBXNativeTarget', 'name': target,
                               'productType': 'com.apple.product-type.application',
                               'buildPhases': [target + 'Script']}
            objects[target + 'Script'] = {'isa': 'PBXShellScriptBuildPhase', 'files': [], 'shellScript': 'echo generated'}
        project_path.write_text(openstep({'objects': objects}), encoding='utf-8')
        issues = [issue for issue in extract(source)['issues'] if issue.get('code') == self.issue['code']]
        self.assertEqual({issue['target'] for issue in issues}, {'App', 'Widget'})
        self.assertEqual(len({extraction_finding(self.queue, issue)['finding_key'] for issue in issues}), 2)

    def test_target_keys_do_not_inherit_ambiguous_legacy_occurrences_or_decisions(self):
        temp = tempfile.TemporaryDirectory(prefix='finding identity queue ')
        self.addCleanup(temp.cleanup)
        project = Path(temp.name)
        legacy = self.queue.make('IOS.EXTRACTION_UNRESOLVED', 'spec', self.issue['path'], 'legacy collision')
        legacy['occurrences'], legacy['decision_ref'] = 7, 'old ambiguous decision'
        self.queue.replace_section(str(project), 'spec.ios-harness', [legacy])
        app, widget = self.finding(), self.finding(target='Widget')
        self.queue.replace_section(str(project), 'spec.ios-harness', [app, widget])
        state = self.queue.load(str(project))
        findings = state['sections']['spec.ios-harness']['findings']
        self.assertEqual(len(findings), 2)
        self.assertTrue(all(f['occurrences'] == 1 and f['decision_ref'] is None for f in findings))
        self.queue.replace_section(str(project), 'spec.ios-harness', [widget])
        remaining = self.queue.load(str(project))['sections']['spec.ios-harness']['findings']
        self.assertEqual([f['finding_key'] for f in remaining], [widget['finding_key']])

    def test_harness_emits_two_scoped_issues_for_one_project(self):
        from test_ios_harness import fixture
        from hmigbot_ios.ios_harness import check
        temp = tempfile.TemporaryDirectory(prefix='extraction identity harness ')
        self.addCleanup(temp.cleanup)
        _, project, graph = fixture(Path(temp.name))
        graph['issues'] = [self.issue, {**self.issue, 'target': 'Widget'}]
        coverage_path = project / 'spec/baseline/ios-coverage.json'
        coverage = read_json(coverage_path)
        coverage['graph_sha256'] = digest(json_bytes(graph))
        write_json(coverage_path, coverage)
        obligations = read_json(project / 'spec/baseline/ios-obligations.json')
        with patch('hmigbot_ios.ios_harness.validate_graph', return_value=(graph, obligations)):
            report, code = check(project, report_only=True)
        findings = [f for f in report['findings'] if f['rule'] == 'IOS.EXTRACTION_UNRESOLVED']
        self.assertEqual(code, 2)
        self.assertEqual(len(findings), 2)
        self.assertEqual(len({f['finding_key'] for f in findings}), 2)


if __name__ == '__main__':
    unittest.main()
