"""Authoring output must use checker contracts without inventing source facts."""
from copy import deepcopy
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
from hmigbot_ios.core import MigrationError, read_json, write_json, snapshot
from hmigbot_ios.native_authoring import prepare, render
from hmigbot_ios.native_pipeline import check_source
from test_ios_harness import fixture


class NativeAuthoringTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source, self.project, self.graph = fixture(self.root)
        self.base = self.project / 'spec/baseline'

    def request(self):
        plan = prepare(self.project)
        return {**plan['input_template'],
                'documents': read_json(self.base / 'ios-semantics.json')['documents'],
                'dispositions': [], 'truth_anchors': [{'ac_id': 'F001-AC01', 'path': 'Counter.swift', 'line': 6}]}

    def test_manifest_lists_all_documents_required_fields_and_exact_source_options(self):
        plan = prepare(self.project)
        self.assertEqual({x['id'] for x in plan['documents']}, {'F001', 'page_0001'})
        self.assertFalse(plan['spec_complete'])
        self.assertEqual(plan['status'], 'needs_authoring')
        for doc in plan['input_template']['documents']:
            self.assertTrue(doc['facts'])
            self.assertTrue(all(x['status'] == 'unknown' for x in doc['facts'].values()))
        self.assertEqual(plan['acceptance'][0]['allowed_sources'][0]['path'], 'Counter.swift')

    def test_renderer_emits_canonical_fields_and_truth_tokens_without_writing_baseline(self):
        before = snapshot(self.project)
        result = render(self.project, self.request())
        self.assertEqual(result['files']['spec/baseline/ios-source-disposition.json']['files'], [])
        self.assertEqual(result['files']['spec/baseline/ios-semantics.json']['schema_version'], 2)
        feature = next(v for p, v in result['files'].items() if p.endswith('F001-counter.md'))
        self.assertIn('真:src:Counter.swift:6', feature)
        self.assertEqual(before, snapshot(self.project))
        self.assertFalse(result['spec_complete'])

    def test_owner_mapping_is_not_a_disposition_and_unknown_never_becomes_known(self):
        request = self.request()
        request['dispositions'] = [{'path': 'Counter.swift', 'owner': 'F001'}]
        with self.assertRaisesRegex(MigrationError, 'disposition'):
            render(self.project, request)
        with self.assertRaises(MigrationError):
            render(self.project, prepare(self.project)['input_template'])

    def test_missing_duplicate_and_extra_native_documents_are_rejected(self):
        for update in (lambda d: d.pop(), lambda d: d.append(deepcopy(d[0])),
                       lambda d: d.append({**deepcopy(d[0]), 'id': 'F999'})):
            request = self.request()
            update(request['documents'])
            with self.assertRaises(MigrationError):
                render(self.project, request)

    def test_missing_dimensions_and_unlinked_known_claims_are_rejected(self):
        for change in ('dimension', 'fact_ids'):
            request = self.request()
            if change == 'dimension':
                request['documents'][0]['facts'].pop('entrypoints')
            else:
                claim = next(x for x in request['documents'][0]['facts'].values() if x['status'] == 'known')
                claim['fact_ids'] = ['IF-not-current']
            with self.assertRaises(MigrationError):
                render(self.project, request)

    def test_truth_requires_current_feature_membership_and_real_line(self):
        for path, line in (('Other.swift', 1), ('../outside.swift', 1), ('Counter.swift', 999), ('Counter.swift', True)):
            request = self.request()
            request['truth_anchors'][0].update(path=path, line=line)
            with self.assertRaises(MigrationError):
                render(self.project, request)

    def test_missing_duplicate_and_unowned_truths_are_rejected(self):
        for truths in ([], [{'ac_id': 'F999-AC01', 'path': 'Counter.swift', 'line': 6}],
                       [{'ac_id': 'F001-AC01', 'path': 'Counter.swift', 'line': 6}] * 2):
            request = self.request()
            request['truth_anchors'] = truths
            with self.assertRaises(MigrationError):
                render(self.project, request)

    def test_inventory_is_bound_to_source_and_markdown(self):
        request = self.request()
        feature = self.base / 'features/F001-counter.md'
        feature.write_text(feature.read_text(encoding='utf-8') + '\nSource contract changed.\n', encoding='utf-8')
        with self.assertRaisesRegex(MigrationError, 'inventory'):
            render(self.project, request)
        (self.source / 'Counter.swift').write_text('struct Changed {}', encoding='utf-8')
        with self.assertRaises(MigrationError):
            prepare(self.project)

    def test_eight_pages_and_five_features_cannot_render_two_native_documents(self):
        feature = (self.base / 'features/F001-counter.md').read_text(encoding='utf-8')
        page_path = next((self.base / 'ui').glob('page_0001*.md'))
        page = page_path.read_text(encoding='utf-8')
        for n in range(2, 6):
            (self.base / f'features/F{n:03d}-counter.md').write_text(feature.replace('F001', f'F{n:03d}'), encoding='utf-8')
        for n in range(2, 9):
            (self.base / f'ui/page_{n:04d}_Counter.md').write_text(page.replace('page_0001', f'page_{n:04d}'), encoding='utf-8')
        plan = prepare(self.project)
        self.assertEqual(len(plan['documents']), 13)
        request = self.request()
        with self.assertRaisesRegex(MigrationError, 'documents'):
            render(self.project, request)
        seeds = {d['kind']: d for d in request['documents']}
        request['documents'] = [{**deepcopy(seeds[d['kind']]), 'id': d['id']} for d in plan['documents']]
        request['truth_anchors'] = [{'ac_id': a['ac_id'], 'path': 'Counter.swift', 'line': 7} for a in plan['acceptance']]
        candidate = render(self.project, request)
        self.assertEqual(len(candidate['files']['spec/baseline/ios-semantics.json']['documents']), 13)

    def test_generated_workspace_does_not_make_current_source_or_authoring_stale(self):
        request = self.request()
        path = self.source / 'Counter.xcodeproj/project.xcworkspace/contents.xcworkspacedata'
        path.parent.mkdir(parents=True)
        path.write_text('<Workspace version="1.0"><FileRef location="self:"/></Workspace>', encoding='utf-8')
        self.assertNotIn('IOS.STALE_SOURCE', [x['rule'] for x in check_source(self.project, report_only=True)[0]['findings']])
        render(self.project, request)

    def test_cli_emits_read_only_manifest(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/a2h_ios.py'), 'spec-authoring', '--project', str(self.project)], capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('needs_authoring', result.stdout)

    def test_candidate_is_consumed_by_unchanged_formal_gates(self):
        from hmigbot_ios.ios_harness import check
        request = self.request()
        request['truth_anchors'][0]['line'] = 7
        result = render(self.project, request)
        for relative, value in result['files'].items():
            path = self.project / relative
            if isinstance(value, str):
                path.write_text(value, encoding='utf-8')
            else:
                write_json(path, value)
        self.assertEqual(check_source(self.project, report_only=True)[0]['findings'], [])
        result, code = check(self.project, report_only=True)
        self.assertEqual(code, 0, result)

    def test_not_applicable_cannot_replace_detected_source_signals(self):
        request = self.request()
        page = next(d for d in request['documents'] if d['kind'] == 'page')
        page['facts']['state_ownership'] = {'status': 'not_applicable', 'reason': 'No state owner claimed'}
        with self.assertRaisesRegex(MigrationError, 'NA_CONTRADICTION'):
            render(self.project, request)

    def test_indexed_document_missing_from_disk_is_reported(self):
        path = self.base / 'ui-manifest.md'
        path.write_text(path.read_text(encoding='utf-8') + '\n| page_id | 目标页面 | 功能 |\n|---|---|---|\n| page_9999 | Missing | F001 |\n', encoding='utf-8')
        with self.assertRaisesRegex(MigrationError, 'page_9999'):
            prepare(self.project)

    def test_addendum_acceptance_uses_main_anchors_and_is_bound_to_inventory(self):
        path = self.base / 'features/F001-counter.more.md'
        path.write_text('# Extra contract\n- [ ] F001-AC02 Visible count updates `判:ui | value is 1` `真:src:Other.swift:999`\n', encoding='utf-8')
        plan = prepare(self.project)
        self.assertEqual(len(plan['documents']), 2)
        self.assertEqual({a['ac_id'] for a in plan['acceptance']}, {'F001-AC01', 'F001-AC02'})
        request = self.request()
        request['truth_anchors'].append({'ac_id': 'F001-AC02', 'path': 'Counter.swift', 'line': 7})
        result = render(self.project, request)
        self.assertIn('真:src:Counter.swift:7', result['files'][path.relative_to(self.project).as_posix()])
        path.write_text(path.read_text(encoding='utf-8') + '\nChanged addendum\n', encoding='utf-8')
        with self.assertRaisesRegex(MigrationError, 'inventory'):
            render(self.project, request)

    def test_invalid_cli_input_cannot_replace_a_canonical_artifact(self):
        request = self.root / 'request.json'
        write_json(request, self.request())
        canonical = self.base / 'ios-semantics.json'
        before = canonical.read_bytes()
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/a2h_ios.py'), 'spec-authoring', '--project', str(self.project),
            '--input', str(request), '--output', str(canonical)], capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(canonical.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
