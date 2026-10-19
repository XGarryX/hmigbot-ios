"""Literal exclusion evidence is one contract: required at authoring and the source gate, re-checked by the view."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
from hmigbot_ios.core import MigrationError, digest, json_bytes, read_json, snapshot, write_json
from hmigbot_ios.native_contract import validate_literal_exclusion
from hmigbot_ios.native_pipeline import check_source, configure, index_source

SPAN_FIELDS = ('line', 'end_line', 'source_sha256')


class SharedEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='literal-exclusion-')
        self.addCleanup(temp.cleanup)
        self.source = Path(temp.name) / 'ios'
        self.source.mkdir()
        (self.source / 'Suite.swift').write_text('import XCTest\nlet label = "Test only"\n', encoding='utf-8')
        self.known = {f['path'] for f in snapshot(self.source)['files']}
        self.whole = snapshot(self.source)['sha256']

    def entry(self, **changes):
        item = {'path': 'Suite.swift', 'disposition': 'test', 'reason': 'Reviewed test target member',
                'line': 1, 'end_line': 2,
                'source_sha256': digest((self.source / 'Suite.swift').read_bytes())}
        item.update(changes)
        return item

    def reject(self, item, *fragments):
        with self.assertRaises(MigrationError) as caught:
            validate_literal_exclusion(self.source, self.known, item)
        message = str(caught.exception)
        for fragment in fragments:
            self.assertIn(fragment, message)
        return message

    def test_complete_reviewed_proof_is_accepted(self):
        self.assertEqual(validate_literal_exclusion(self.source, self.known, self.entry()), self.entry())

    def test_missing_evidence_names_the_entry_path_and_fields(self):
        item = {key: value for key, value in self.entry().items() if key not in SPAN_FIELDS}
        message = self.reject(item, 'Suite.swift', 'missing')
        for field in SPAN_FIELDS:
            self.assertIn(field, message)

    def test_stale_per_file_hash_is_rejected(self):
        self.reject(self.entry(source_sha256='0' * 64), 'Suite.swift', 'current bytes')

    def test_whole_source_digest_is_not_a_per_file_hash(self):
        self.reject(self.entry(source_sha256=self.whole), 'Suite.swift', 'current bytes')

    def test_out_of_range_reversed_zero_boolean_and_text_spans_are_rejected(self):
        for changes in ({'line': 3}, {'end_line': 3}, {'line': 2, 'end_line': 1},
                        {'line': 0}, {'line': True}, {'line': '1'}, {'end_line': None}):
            with self.subTest(changes=changes):
                self.reject(self.entry(**changes), 'Suite.swift')

    def test_blank_reason_and_unknown_disposition_are_rejected(self):
        self.reject(self.entry(reason='   '), 'Suite.swift', 'reason')
        self.reject(self.entry(disposition='excluded'), 'Suite.swift')

    def test_unindexed_and_escaping_paths_are_rejected(self):
        for path in ('Other.swift', '../Suite.swift', 'C:/Suite.swift'):
            with self.subTest(path=path):
                self.reject(self.entry(path=path))

    def test_entry_without_a_real_file_is_rejected(self):
        (self.source / 'Removed.swift').write_text('let value = 1\n', encoding='utf-8')
        item = self.entry(path='Removed.swift',
                          source_sha256=digest((self.source / 'Removed.swift').read_bytes()))
        self.reject(item, 'Removed.swift')
        (self.source / 'Removed.swift').unlink()
        self.known.add('Removed.swift')
        self.reject(item, 'Removed.swift')


class SourceGateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='literal-gate-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.source, self.project = root / 'ios', root / 'harmony'
        shutil.copytree(ROOT / 'tests/fixtures/uikit_interaction', self.source)
        shutil.copytree(ROOT / 'tests/fixtures/a2h-native-spec', self.project)
        configure(self.source, self.project)
        index_source(self.project)
        self.scope_path = self.project / 'spec/baseline/ios-source-disposition.json'
        body = (self.source / 'CounterViewController.swift').read_bytes()
        self.entry = {'path': 'CounterViewController.swift', 'disposition': 'test',
                      'reason': 'Reviewed fixture member', 'line': 1,
                      'end_line': len(body.decode('utf-8-sig').splitlines()),
                      'source_sha256': digest(body)}

    def rules(self):
        return [f['rule'] for f in check_source(self.project, report_only=True)[0]['findings']]

    def test_absent_scope_keeps_the_no_exclusion_behaviour(self):
        self.assertFalse(self.scope_path.exists())
        self.assertEqual(self.rules(), [])

    def test_empty_files_remain_valid_only_with_the_current_whole_source_digest(self):
        write_json(self.scope_path, {'source_sha256': snapshot(self.source)['sha256'], 'files': []})
        self.assertEqual(self.rules(), [])
        write_json(self.scope_path, {'files': []})
        self.assertIn('IOS.STALE_DISPOSITION', self.rules())

    def test_complete_proof_passes_the_gate_and_keeps_other_findings_empty(self):
        write_json(self.scope_path, {'source_sha256': snapshot(self.source)['sha256'], 'files': [self.entry]})
        self.assertEqual(self.rules(), [])

    def test_incomplete_or_stale_evidence_fails_the_gate_with_field_guidance(self):
        whole = snapshot(self.source)['sha256']
        cases = [({key: value for key, value in self.entry.items() if key not in SPAN_FIELDS}, whole,
                  'IOS.INVALID_DISPOSITION', 'missing'),
                 ({**self.entry, 'source_sha256': '0' * 64}, whole, 'IOS.INVALID_DISPOSITION', 'current bytes'),
                 ({**self.entry, 'end_line': 99999}, whole, 'IOS.INVALID_DISPOSITION', 'in-order span'),
                 ({**self.entry, 'source_sha256': whole}, whole, 'IOS.INVALID_DISPOSITION', 'current bytes'),
                 (self.entry, '0' * 64, 'IOS.STALE_DISPOSITION', 'whole-source'),
                 (self.entry, None, 'IOS.STALE_DISPOSITION', 'whole-source')]
        for item, scope_hash, rule, fragment in cases:
            with self.subTest(rule=rule, fragment=fragment, item=sorted(item)):
                scope = {'files': [item]}
                if scope_hash is not None:
                    scope['source_sha256'] = scope_hash
                write_json(self.scope_path, scope)
                findings = [f for f in check_source(self.project, report_only=True)[0]['findings'] if f['rule'] == rule]
                self.assertEqual(len(findings), 1, findings)
                self.assertIn(fragment, findings[0]['detail'])
                if rule == 'IOS.INVALID_DISPOSITION':
                    self.assertIn('CounterViewController.swift', findings[0]['subject'])

    def test_source_change_after_a_gate_pass_is_stale_for_the_scope(self):
        write_json(self.scope_path, {'source_sha256': snapshot(self.source)['sha256'], 'files': [self.entry]})
        self.assertEqual(self.rules(), [])
        (self.source / 'CounterViewController.swift').write_text(
            'class Renamed {}\n', encoding='utf-8')
        self.assertIn('IOS.STALE_SOURCE', self.rules())
        self.assertIn('IOS.STALE_DISPOSITION', self.rules())


class AuthoringBoundaryTests(unittest.TestCase):
    def setUp(self):
        from test_ios_harness import fixture
        temp = tempfile.TemporaryDirectory(prefix='literal-authoring-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source, self.project, self.graph = fixture(self.root)
        self.base = self.project / 'spec/baseline'

    def request(self):
        from hmigbot_ios.native_authoring import prepare
        plan = prepare(self.project)
        self.plan = plan
        return {**plan['input_template'],
                'documents': read_json(self.base / 'ios-semantics.json')['documents'],
                'dispositions': [], 'truth_anchors': [{'ac_id': 'F001-AC01', 'path': 'Counter.swift', 'line': 6}]}

    def proof(self):
        body = (self.source / 'Counter.swift').read_bytes()
        return {'path': 'Counter.swift', 'disposition': 'test', 'reason': 'Reviewed fixture member',
                'line': 1, 'end_line': len(body.decode('utf-8-sig').splitlines()), 'source_sha256': digest(body)}

    def render(self, request):
        from hmigbot_ios.native_authoring import render
        return render(self.project, request)

    def test_manifest_advertises_six_fields_and_distinguishes_both_digests(self):
        self.request()
        contract = self.plan['disposition_contract']
        self.assertEqual(contract['required_entry_fields'], ['path', 'disposition', 'reason'] + list(SPAN_FIELDS))
        self.assertEqual(sorted(contract['entry_example']), sorted(contract['required_entry_fields']))
        self.assertIn('whole-source', contract['source_sha256_levels'])
        self.assertEqual(self.plan['input_template']['dispositions'], [])

    def test_complete_proof_renders_unchanged_with_the_whole_source_digest(self):
        request = self.request()
        request['dispositions'] = [self.proof()]
        result = self.render(request)
        scope = result['files']['spec/baseline/ios-source-disposition.json']
        self.assertEqual(scope['files'], [self.proof()])
        self.assertEqual(scope['source_sha256'], self.graph['source_sha256'])
        self.assertNotEqual(scope['source_sha256'], self.proof()['source_sha256'])

    def test_the_original_three_field_witness_is_rejected_before_planning(self):
        request = self.request()
        request['dispositions'] = [{key: value for key, value in self.proof().items() if key not in SPAN_FIELDS}]
        with self.assertRaises(MigrationError) as caught:
            self.render(request)
        message = str(caught.exception)
        self.assertIn('Counter.swift', message)
        for field in SPAN_FIELDS:
            self.assertIn(field, message)

    def test_wrong_span_disposition_and_reason_are_rejected_before_planning(self):
        for changes in ({'source_sha256': '0' * 64}, {'end_line': 99999}, {'line': 4, 'end_line': 2},
                        {'line': 0}, {'disposition': 'excluded'}, {'reason': ' '}, {'path': 'Other.swift'}):
            with self.subTest(changes=changes):
                request = self.request()
                request['dispositions'] = [{**self.proof(), **changes}]
                with self.assertRaises(MigrationError):
                    self.render(request)

    def test_whole_source_digest_is_not_accepted_as_entry_evidence(self):
        request = self.request()
        request['dispositions'] = [{**self.proof(), 'source_sha256': self.graph['source_sha256']}]
        with self.assertRaisesRegex(MigrationError, 'current bytes'):
            self.render(request)


class LiteralViewConsumerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='literal-view-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source, self.project = self.root / 'source', self.root / 'target'
        self.source.mkdir(); self.project.mkdir()
        (self.source / 'Screen.swift').write_text('import SwiftUI\nstruct Screen: View {\n    var body: some View {\n'
                                                 ' Text("Same")\n}\n}\n', encoding='utf-8')
        (self.source / 'Support.swift').write_text('let testOracle = "Same"\n', encoding='utf-8')
        configure(self.source, self.project)
        from hmigbot_ios.ios_facts import refresh
        from hmigbot_ios.ios_literals import run as literals
        self.graph = refresh(self.project, self.source)
        literals(self.project)
        base = self.project / 'spec/baseline'
        (base / 'features').mkdir(); (base / 'ui').mkdir()
        (base / 'features/F001-screen.md').write_text(
            '# F001\n- [ ] F001-AC01 Tap `判:ui | Text stays`\n', encoding='utf-8')
        (base / 'ui-manifest.md').write_text('| page_id | 状态 |\n|---|---|\n| page_0001 | verified |\n', encoding='utf-8')
        (base / 'ui/page_0001_Screen.md').write_text('# Screen\n', encoding='utf-8')
        write_json(base / 'ios-coverage.json', {
            'schema_version': 2, 'graph_sha256': digest(json_bytes(self.graph)),
            'mappings': [{'obligation_id': 'IO-' + f['id'][3:], 'ac_ids': ['F001-AC01'],
                          'source_review': {'status': 'reviewed', 'input': 'Tap', 'processing': 'Read',
                                            'observable': 'Text', 'reviewer': 'independent-source-reader'}}
                         for f in self.graph['facts']]})
        self.scope_path = base / 'ios-source-disposition.json'

    def scope(self, entries=None, whole=None):
        body = (self.source / 'Support.swift').read_bytes()
        entry = {'path': 'Support.swift', 'disposition': 'test', 'reason': 'Independent source oracle only',
                 'line': 1, 'end_line': 1, 'source_sha256': digest(body)}
        write_json(self.scope_path, {'source_sha256': whole or snapshot(self.source)['sha256'],
                                     'files': [entry] if entries is None else entries})
        return entry

    def view(self):
        from hmigbot_ios.quality_views import product_literals
        return product_literals(self.project)

    def test_complete_evidence_excludes_only_the_reviewed_span(self):
        self.scope()
        entries = [e for e in self.view()['entries'] if e.get('value') == 'Same']
        self.assertEqual({e['classification'] for e in entries}, {'product', 'test'})

    def test_empty_files_list_remains_valid_and_excludes_nothing(self):
        self.scope(entries=[])
        self.assertEqual({e['classification'] for e in self.view()['entries'] if e.get('value') == 'Same'},
                         {'product'})

    def test_incomplete_entry_is_rejected_without_any_earlier_gate(self):
        self.scope(entries=[{'path': 'Support.swift', 'disposition': 'test', 'reason': 'Independent source oracle only'}])
        with self.assertRaises(MigrationError) as caught:
            self.view()
        self.assertIn('Support.swift', str(caught.exception))

    def test_view_rejects_stale_entry_evidence_without_any_earlier_gate(self):
        self.scope()
        scope = read_json(self.scope_path)
        scope['files'][0]['source_sha256'] = '0' * 64
        write_json(self.scope_path, scope)
        with self.assertRaisesRegex(MigrationError, 'current bytes'):
            self.view()

    def test_source_edit_never_leaves_a_frozen_scope_consumable(self):
        self.scope()
        self.assertEqual([e['classification'] for e in self.view()['entries'] if e.get('value') == 'Same'].count('test'), 1)
        (self.source / 'Support.swift').write_text('let testOracle = "Same"\nlet extra = 1\n', encoding='utf-8')
        with self.assertRaises(MigrationError):
            self.view()

    def test_whole_source_digest_is_never_taken_as_entry_evidence(self):
        whole = snapshot(self.source)['sha256']
        self.scope(entries=[{**self.scope(), 'source_sha256': whole}])
        with self.assertRaisesRegex(MigrationError, 'current bytes'):
            self.view()


if __name__ == '__main__':
    unittest.main()
