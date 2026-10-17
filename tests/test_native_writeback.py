"""Native nine-column indexes remain authoritative around the original writer."""
import json
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.plan_contract import _core_index_tables, structural_digest

UI = ('# UI Manifest\n\n## 页面与覆盖层\n'
      '| 序号 | 源文件/入口/框架 | 类型 | ArkTS 目标文件/组件 | 功能归属 | 优先级 | confidence | 状态 | spec |\n'
      '|---|---|---|---|---|---|---|---|---|\n'
      '| page_0001 | Counter.swift:1 / SwiftUI | page | entry/Counter.ets / Counter | F001 | P0 | high | pending | ui/page_0001_Counter.md |\n')
FEATURE = ('# Features\n\n## 功能清单\n'
           '| ID | 功能 | 优先级 | 排序依赖 | 契约依赖 | 关联页面 | 创建页面 | complexity | tier | depth | 状态 | spec |\n'
           '|---|---|---|---|---|---|---|---|---|---|---|---|\n'
           '| F001 | Counter | P0 | - | - | page_0001 | - | simple | core | 1 | pending | features/F001-counter.md |\n')
REGISTRY = ('# Registry\n\n## 注册表\n| P-ID | location | trigger_condition | status | kind | resolve_by |\n'
            '|---|---|---|---|---|---|\n'
            '| P-FWD | entry/Counter.ets:1 | target pending | pending | forward-ref | Slice1 |\n'
            '| P-RES | entry/icon.svg | asset pending | pending | resource-pending-asset | Slice1 |\n')


class NativeWritebackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='native-writeback-')
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name)
        self.ui = self.put('spec/baseline/ui-manifest.md', UI)
        self.feature = self.put('spec/baseline/feature-index.md', FEATURE)
        self.registry = self.put('spec/placeholder-registry.md', REGISTRY)

    def put(self, relative, text):
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def run_writeback(self, manifest, dry=False):
        path = self.put('writeback.json', json.dumps(manifest, ensure_ascii=False))
        return subprocess.run([sys.executable, str(ROOT / 'skills/a2h-execute/scripts/apply_writeback.py'),
                               str(path), '--project-root', str(self.project), *(['--dry-run'] if dry else [])],
                              capture_output=True, encoding='utf-8', errors='replace', timeout=40)

    def contents(self):
        return {p.relative_to(self.project).as_posix(): p.read_bytes()
                for p in self.project.rglob('*') if p.is_file() and p.name != 'writeback.json'}

    def test_unknown_native_id_is_rejected_before_any_brief_or_index_write(self):
        before = self.contents()
        result = self.run_writeback({'mode': 'batch', 'id': '01',
            'ui_manifest': {'converted': ['page_9999']},
            'brief': {'path': 'spec/execution/briefs/batch_01_brief.md', 'content': '# Must not land'}})
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.contents(), before)

    def test_legacy_header_requires_reviewed_migration_before_writer(self):
        self.ui.write_text(UI.replace('| 序号 |', '| page_id |'), encoding='utf-8')
        before = self.contents()
        result = self.run_writeback({'mode': 'batch', 'ui_manifest': {'converted': ['page_0001']},
            'brief': {'path': 'spec/execution/briefs/batch_01_brief.md', 'content': '# No hidden migration'}})
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('review', result.stderr.lower())
        self.assertEqual(self.contents(), before)

    def test_original_binary_writes_only_native_status_cells_and_noop_replays(self):
        initial = structural_digest(UI, artifact='spec/baseline/ui-manifest.md')
        for mode, state in [('batch', 'converted'), ('group', 'verified'), ('final', 'verified')]:
            with self.subTest(mode=mode):
                result = self.run_writeback({'mode': mode, 'id': '01', 'ui_manifest': {state: ['page_0001']}})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('0 warn', result.stdout)
                self.assertIn('| ' + state + ' |', self.ui.read_text(encoding='utf-8'))
                self.assertEqual(structural_digest(self.ui.read_text(encoding='utf-8'),
                                 artifact='spec/baseline/ui-manifest.md'), initial)

    def test_duplicate_unknown_state_and_missing_columns_fail_without_side_effects(self):
        cases = [({'ui_manifest': {'converted': ['page_0001', 'page_0001']}}, UI),
                 ({'ui_manifest': {'converted': ['0001']}}, UI),
                 ({'ui_manifest': {'done': ['page_0001']}}, UI),
                 ({'ui_manifest': {'converted': ['page_0001']}}, UI.replace('| 状态 |', '| status |')),
                 ({'ui_manifest': {'converted': ['page_0001'], 'verified': ['page_0001']}}, UI),
                 ({'feature_index': {'implemented': ['F999']}}, UI),
                 ({'registry': {'retag': [{'pid': 'P-UNKNOWN', 'column': 'resolve_by', 'value': 'Slice2'}]}}, UI),
                 ({'ui_manifest': {'converted': False}}, UI)]
        for sections, text in cases:
            with self.subTest(sections=sections):
                self.ui.write_text(text, encoding='utf-8')
                before = self.contents()
                result = self.run_writeback({'mode': 'group', **sections,
                    'brief': {'path': 'spec/execution/briefs/group_01_brief.md', 'content': '# Rejected'}})
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.contents(), before)

    def test_feature_registry_claims_and_patrol_output_are_original_operations(self):
        claim = {'requirement_id': 'F001-AC01', 'packet_id': 'slice-01-F001', 'attempt': 1,
                 'files': ['entry/Counter.ets'], 'requirement_digest': 'sha256:aa'}
        manifest = {'mode': 'group', 'id': '01', 'feature_index': {'implemented': ['F001']},
                    'registry': {'resolve': ['P-FWD', 'P-RES'],
                                 'retag': [{'pid': 'P-RES', 'column': 'resolve_by', 'value': 'Slice3'}]},
                    'impl_claims': {'claims': [claim], 'executed_packets': ['slice-01-F001']},
                    'brief': {'path': 'spec/execution/briefs/group_01_brief.md', 'content': '# Group 01'}}
        before = structural_digest(FEATURE, artifact='spec/baseline/feature-index.md')
        result = self.run_writeback(manifest)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PATROL', result.stdout.upper())
        self.assertEqual(structural_digest(self.feature.read_text(encoding='utf-8'),
                         artifact='spec/baseline/feature-index.md'), before)
        self.assertNotIn('| P-FWD |', self.registry.read_text(encoding='utf-8'))
        self.assertIn('| resolved | resource-pending-asset | Slice3 |', self.registry.read_text(encoding='utf-8'))
        for _ in range(2):
            result = self.run_writeback(manifest)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('0 warn', result.stdout)
            self.assertIn('no-op', result.stdout)
        ledger = json.loads((self.project / 'spec/.a2h/impl-claims.json').read_text(encoding='utf-8'))
        self.assertEqual(ledger['claims'], [claim])
        self.assertEqual(ledger['executed_packets'], ['slice-01-F001'])

    def test_original_forward_ref_missing_is_a_noop_not_a_new_resolution(self):
        manifest = {'mode': 'group', 'id': '01', 'registry': {'resolve': ['P-FWD']}}
        self.assertEqual(self.run_writeback(manifest).returncode, 0)
        after = self.contents()
        result = self.run_writeback(manifest)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('0 applied / 1 no-op / 0 warn', result.stdout)
        self.assertEqual(self.contents(), after)

    def test_malformed_existing_claims_prevents_earlier_brief_write(self):
        self.put('spec/.a2h/impl-claims.json', '{broken')
        before = self.contents()
        result = self.run_writeback({'mode': 'final', 'impl_claims': {'claims': []},
            'brief': {'path': 'spec/execution/briefs/final_brief.md', 'content': '# Not applied'}})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.contents(), before)

    def test_dry_run_uses_original_protocol_without_writing(self):
        before = self.contents()
        result = self.run_writeback({'mode': 'batch', 'id': '02',
            'ui_manifest': {'converted': ['page_0001']},
            'brief': {'path': 'spec/execution/briefs/batch_02_brief.md', 'content': '# Dry run'}}, dry=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('DRY-RUN', result.stdout)
        self.assertIn('PATROL', result.stdout.upper())
        self.assertEqual(self.contents(), before)

    def test_original_warnings_failure_and_lying_readback_never_report_success(self):
        from hmigbot_ios import native_writeback
        manifest = self.put('writeback.json', json.dumps({'mode': 'batch',
                            'ui_manifest': {'converted': ['page_0001']}}))
        normal = b'apply_writeback: 1 applied / 0 no-op / 0 warn\n'
        for case in ('warning', 'nonzero', 'missing-result', 'no-write', 'business-change'):
            with self.subTest(case=case):
                self.ui.write_text(UI, encoding='utf-8')
                def invoke(*args, **kwargs):
                    output, code = normal, 0
                    if case == 'warning':
                        output = b'apply_writeback: 0 applied / 0 no-op / 1 warn\n'
                    elif case == 'nonzero':
                        code = 7
                    elif case == 'missing-result':
                        output = b'No canonical result\n'
                    elif case == 'business-change':
                        self.ui.write_text(UI.replace('| pending |', '| converted |').replace(
                                           'Counter.swift:1', 'Counter.swift:2'), encoding='utf-8')
                    return subprocess.CompletedProcess(args[0], code, output, b'original diagnostics\n')
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch.object(native_writeback.subprocess, 'run', side_effect=invoke) as original:
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        code = native_writeback.main([str(manifest), '--project-root', str(self.project)],
                                                     helper=Path('original-helper'))
                self.assertEqual(code, 7 if case == 'nonzero' else 2)
                self.assertEqual(original.call_count, 1)
                self.assertIn('original diagnostics', stderr.getvalue())
                self.assertIn('apply_writeback' if case != 'missing-result' else 'No canonical result', stdout.getvalue())

    def test_unrequested_progress_and_shadow_status_tables_cannot_hide_mutations(self):
        from hmigbot_ios import native_writeback
        extra = UI.splitlines()[-1].replace('page_0001', 'page_0002') + '\n'
        text = UI + extra + '\n## Business states\n| page_id | 状态 |\n|---|---|\n| page_0001 | pending |\n'
        self.ui.write_text(text, encoding='utf-8')
        manifest = {'ui_manifest': {'converted': ['page_0001']}}
        for mutated in (text.replace('| pending |', '| converted |'),
                        text.replace('| page_0001 | pending |', '| page_0001 | verified |')):
            self.ui.write_text(text, encoding='utf-8')
            checks, before, touched = native_writeback.preflight(self.project, manifest)
            self.ui.write_text(mutated, encoding='utf-8')
            with self.assertRaisesRegex(native_writeback.MigrationError, 'readback'):
                native_writeback.postflight(self.project, checks, before, touched)


class NativeCatalogAliasTests(unittest.TestCase):
    def test_alias_maps_only_complete_catalog_core_header_and_only_progress_cells(self):
        table = _core_index_tables(UI, 'spec/baseline/ui-manifest.md')
        self.assertEqual(len(table), 1)
        self.assertEqual(table[0][1]['headers'][0], 'page_id')
        for text in [UI, UI.replace('| 序号 |', '| page_id |')]:
            before = structural_digest(text, artifact='spec/baseline/ui-manifest.md')
            self.assertEqual(before, structural_digest(text.replace('| pending |', '| converted |'),
                                                     artifact='spec/baseline/ui-manifest.md'))
            self.assertNotEqual(before, structural_digest(text.replace('Counter.swift:1', 'Counter.swift:2'),
                                                         artifact='spec/baseline/ui-manifest.md'))
        wrong = UI.replace('| confidence |', '| evidence |')
        self.assertFalse(_core_index_tables(wrong, 'spec/baseline/ui-manifest.md'))
        self.assertNotEqual(structural_digest(wrong, artifact='spec/baseline/ui-manifest.md'),
                            structural_digest(wrong.replace('| pending |', '| verified |'),
                                              artifact='spec/baseline/ui-manifest.md'))

    def test_alias_preserves_native_source_gate_and_plan_consumers(self):
        from test_ios_harness import fixture
        from spec_contract_fixture import strict_contract
        from hmigbot_ios.spec_contract import check
        import test_plan_contract as plan_fixture
        with tempfile.TemporaryDirectory(prefix='native-alias-source-') as temp:
            _, project, _ = fixture(Path(temp))
            strict_contract(project)
            ui = project / 'spec/baseline/ui-manifest.md'
            ui.write_text(ui.read_text(encoding='utf-8').replace('| page_id |', '| 序号 |'), encoding='utf-8')
            report, code = check(project)
            self.assertEqual(code, 0, report)
        test = plan_fixture.PlanContractTests('test_valid_explicit_merge_and_transitive_consumer')
        test.setUp()
        try:
            ui = test.project / 'spec/baseline/ui-manifest.md'
            ui.write_text(ui.read_text(encoding='utf-8').replace('| page_id |', '| 序号 |'), encoding='utf-8')
            from hmigbot_ios.plan_contract import validate_plan
            self.assertEqual(validate_plan(test.project, test.request)['status'], 'PASS')
        finally:
            test.tearDown()


if __name__ == '__main__':
    unittest.main()
