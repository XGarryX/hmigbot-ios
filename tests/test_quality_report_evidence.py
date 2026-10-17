"""Reports bind product inputs without binding the logs of their own invocation."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))

from hmigbot_ios.core import EXCLUDED, MigrationError, digest, json_bytes, read_json, write_json
from hmigbot_ios.native_pipeline import main
from hmigbot_ios import quality_views as views
from test_ios_harness import fixture
from spec_contract_fixture import strict_contract


class QualityReportEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ios-report-evidence-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source, self.project, self.graph = fixture(self.root)

    def put(self, relative, text='evidence\n'):
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def wrapped_report(self, stamp, *args):
        # Match the real pipeline wrapper: stream files are created before the
        # command, then its stdout and call record are published afterwards.
        stem = 'work/pipeline-20261017/calls/' + stamp
        stdout = self.put(stem + '.stdout.log', '')
        self.put(stem + '.stderr.log', '')
        output = StringIO()
        with redirect_stdout(output):
            code = main(['migration-report', '--project', str(self.project), *args])
        stdout.write_text(output.getvalue(), encoding='utf-8')
        write_json(self.project / (stem + '.json'), {'exit_code': code, 'argv': list(args)})
        return code, output.getvalue()

    def test_generate_then_next_wrapped_check_is_current(self):
        report = self.project / 'spec/migration-report.md'
        exclusions = set(EXCLUDED)
        code, output = self.wrapped_report('20261017T030745806531-a076fa', '--output', str(report))
        self.assertEqual(code, 0, output)
        code, output = self.wrapped_report('20261017T030801230394-f94d00', '--check', str(report))
        self.assertEqual(code, 0, output)
        self.assertTrue(views.validate_report(self.project, report.read_text(encoding='utf-8')))
        self.assertEqual(EXCLUDED, exclusions)

    def test_named_execution_support_does_not_change_target_inputs(self):
        before = views.target_inputs(self.project)
        for path in ('work/pipeline-20261017/run.py',
                     'work/pipeline-20261017/support/check-domain.mjs',
                     'work/pipeline-20261017/support/states/host-oracle.json',
                     'build_out.log', 'build_temp.bat'):
            self.put(path)
        self.assertEqual(views.target_inputs(self.project), before)

    def test_product_resources_configuration_and_unknown_work_files_invalidate_report(self):
        paths = ('entry/src/main/ets/pages/Main.ets',
                 'entry/src/main/resources/base/element/color.json',
                 'build-profile.json5', '.migbot/config.json',
                 'work/pipeline-20261017/Unowned.ets',
                 'work/pipeline-20261017/calls/Unowned.ets',
                 'work/pipeline-20261017/calls/arbitrary.json',
                 'work/pipeline-20261017/support/arbitrary.json',
                 'work/ordinary.log')
        for relative in paths:
            with self.subTest(path=relative):
                report = views.render_report(views.summary(self.project))
                path = self.project / relative
                previous = path.read_bytes() if path.exists() else None
                if relative == '.migbot/config.json':
                    value = read_json(path)
                    value['review_marker'] = 'configuration changed'
                    data = json_bytes(value)
                else:
                    data = b'new product or unclassified input\n'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                try:
                    with self.assertRaises(MigrationError):
                        views.validate_report(self.project, report)
                finally:
                    if previous is None:
                        path.unlink()
                    else:
                        path.write_bytes(previous)

    def catalog_manifest(self, cell, extra=''):
        strict_contract(self.project)
        index = self.project / 'spec/baseline/feature-index.md'
        index.write_text(index.read_text(encoding='utf-8').replace(
            '| P0 | base | base |', '| P0 | base | spec/baseline/feature-base.md#数据模型 |'), encoding='utf-8')
        self.put('spec/baseline/ui-manifest.md', '# UI\n## 页面与覆盖层\n'
                 '| page_id | 源文件/入口/框架 | 类型 | ArkTS 目标文件/组件 | 功能归属 | 优先级 | confidence | 状态 | spec |\n'
                 '|---|---|---|---|---|---|---|---|---|\n'
                 '| page_0001 | Counter.swift:2/entry/swiftui | page | ' + cell +
                 ' | F001 | P0 | high | pending | ui/page_0001_Counter.md |\n' + extra)

    def build_fixture(self):
        # This is a unit-test evidence fixture, not a real compiler execution.
        hap = self.put('entry/build/app.hap', 'unit-test build artifact')
        report = self.root / 'build.json'
        write_json(report, {'target_project': str(self.project),
                   'source_sha256': self.graph['source_sha256'],
                   'target_input_hashes': views.target_inputs(self.project),
                   'spec_input_hashes': views.spec_inputs(self.project),
                   'artifacts': [{'path': 'entry/build/app.hap', 'sha256': digest(hap.read_bytes())}],
                   'status': 'build_passed', 'exit_code': 0,
                   'hvigor_success_marker': True, 'source_changed': False})
        return report

    def test_catalog_component_cells_bind_exact_compiled_page_paths(self):
        for path, cell in (
                ('entry/Counter.ets', 'entry/Counter.ets / Counter'),
                ('entry/Counter.ets', '`entry/Counter.ets` / `Counter`'),
                ('entry/Counter.ets', '`entry/Counter.ets / Counter`'),
                ('entry/Coffee Timer.ets', '`entry/Coffee Timer.ets` / `CoffeeTimer`')):
            with self.subTest(cell=cell):
                self.put(path, 'export class Counter {}\n')
                self.catalog_manifest(cell)
                result = views.summary(self.project, build_evidence=self.build_fixture())
                self.assertEqual(result['axes']['compilation']['status'], 'passed')
                self.assertEqual(result['pages'][0]['target_paths'], [path])
                self.assertEqual(result['pages'][0]['axes']['compilation']['status'], 'passed')

    def test_unrelated_same_page_table_does_not_invalidate_compilation_mapping(self):
        self.put('entry/Counter.ets', 'export class Counter {}\n')
        self.catalog_manifest('entry/Counter.ets / Counter',
                              '\n## Runtime evidence\n| page_id | target_path |\n|---|---|\n'
                              '| page_0001 | entry/Other.ets |\n')
        result = views.summary(self.project, build_evidence=self.build_fixture())
        self.assertEqual(result['pages'][0]['target_paths'], ['entry/Counter.ets'])
        self.assertEqual(result['pages'][0]['axes']['compilation']['status'], 'passed')

    def test_ambiguous_unsafe_or_missing_catalog_targets_are_rejected(self):
        for cell in ('entry/Counter.ets / entry/Other.ets',
                     'entry/Counter.ets, entry/Other.ets',
                     '../Counter.ets / Counter', '', 'Counter'):
            with self.subTest(cell=cell):
                self.catalog_manifest(cell)
                with self.assertRaises(MigrationError):
                    views.summary(self.project)


if __name__ == '__main__':
    unittest.main()
