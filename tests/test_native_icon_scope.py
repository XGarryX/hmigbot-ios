"""Real compiled icon detection over declared modules and Windows long files."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import io_path, write_json
from hmigbot_ios.native_helpers import icon_audit, structural_loop
from hmigbot_ios.native_icon_scope import autofix_main, projection_text

SIZED = "@ComponentV2\nstruct Good {\n  build() {\n    Image($r('app.media.icon'))\n      .width(24)\n      .height(24)\n  }\n}\n"
UNSIZED = "@ComponentV2\nstruct Bad {\n  build() {\n    Image($r('app.media.icon'))\n      .objectFit(ImageFit.Contain)\n  }\n}\n"


class NativeIconScopeTests(unittest.TestCase):
    def setUp(self):
        self.root = io_path(Path(tempfile.mkdtemp(prefix='native-icon-scope-')))
        self.addCleanup(shutil.rmtree, self.root)

    def modules(self, declarations):
        write_json(self.root / 'build-profile.json5', {'modules': [
            {'name': name, 'srcPath': './' + path} for name, path in declarations]})
        roots = []
        for name, path in declarations:
            main = self.root / path / 'src/main'
            write_json(main / 'module.json5', {'module': {'name': name, 'type': 'entry' if name == 'entry' else 'har'}})
            source = main / 'ets'
            source.mkdir()
            roots.append(source)
        return roots

    def files(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file() and path.suffix == '.ets'}

    def test_declared_multimodule_detector_ignores_history_tool_and_cache_noise(self):
        roots = self.modules([('entry', 'entry'), ('feature', 'features/coffee')])
        for source in roots:
            (source / 'Good.ets').write_text(SIZED, encoding='utf-8')
        for prefix in ('spec/.a2h/history/replan-old/spec/state/fence-snapshot',
                       '.hmigbot-ios/plugin/vendor/tool/template', 'build/generated/template'):
            noise = self.root / prefix / 'entry/src/main/ets/Noise.ets'
            noise.parent.mkdir(parents=True)
            noise.write_text(UNSIZED, encoding='utf-8')
        before = self.files()
        result = icon_audit(self.root, self.root / 'evidence/audit.json')
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['source_roots'], ['entry/src/main/ets', 'features/coffee/src/main/ets'])
        self.assertEqual(result['report']['flagged'], [])
        self.assertEqual(self.files(), before)

    def test_missing_dimensions_in_second_real_module_still_blocks_pipeline(self):
        first, second = self.modules([('entry', 'entry'), ('feature', 'features/coffee')])
        (first / 'Good.ets').write_text(SIZED, encoding='utf-8')
        (second / 'Bad.ets').write_text(UNSIZED, encoding='utf-8')
        before = self.files()
        state, output = self.root / 'evidence/state.json', self.root / 'evidence/result.json'
        with contextlib.redirect_stdout(io.StringIO()):
            code = structural_loop(['iterate', '--project-root', str(self.root), '--mode', 'pipeline',
                '--target', 'final', '--state-file', str(state), '--output-json', str(output)])
        self.assertEqual(code, 3)
        report = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(report['verdict'], 'NATIVE_INPUT_REQUIRED')
        self.assertTrue(any('Bad.ets' in json.dumps(row) for row in report['findings']))
        self.assertFalse(state.exists())
        self.assertEqual(self.files(), before)

    def test_file_coverage_and_original_image_expression_count_remain_distinct(self):
        source, = self.modules([('entry', 'entry')])
        (source / 'NoImages.ets').write_text('export class NoImages {}', encoding='utf-8')
        (source / 'ThreeImages.ets').write_text(SIZED * 3, encoding='utf-8')
        result = icon_audit(self.root, self.root / 'evidence/counts.json')
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['source_file_count'], 2)
        self.assertEqual(len(result['source_file_hashes']), 2)
        self.assertEqual(result['report']['scanned'], 3)

    def test_compact_image_width_height_preserves_the_original_multiline_result(self):
        source, = self.modules([('entry', 'entry')])
        path = source / 'Compact.ets'
        path.write_text("@ComponentV2 struct Compact { build() { Image($r('app.media.icon')).width(24).height(24) } }", encoding='utf-8')
        before = path.read_bytes()
        result = icon_audit(self.root, self.root / 'evidence/compact.json')
        self.assertEqual(result['status'], 'passed', result['report'])
        self.assertEqual(result['report']['scanned'], 1)
        self.assertEqual(path.read_bytes(), before)

    def test_compact_chain_boundaries_do_not_borrow_dimensions_and_keep_source_lines(self):
        source, = self.modules([('entry', 'entry')])
        cases = [
            ('two-dimensions', "Image($r('app.media.icon')).width(24).height(24)", [], 1),
            ('size-aspect', "Image($r('app.media.icon')).size({width:24,height:12}).aspectRatio(2)", [], 1),
            ('width-aspect', "Image($r('app.media.icon')).width(24).aspectRatio(2)", [], 1),
            ('bare', "Image($r('app.media.icon')).objectFit(ImageFit.Contain)", ['NO-DIMS'], 1),
            ('one-axis', "Image($r('app.media.icon')).width(24)", ['ONE-DIM-NO-ASPECT'], 1),
            ('optional-modifier', "Image($r('app.media.icon')).width(24)?.height(24)", ['ONE-DIM-NO-ASPECT'], 1),
            ('other-component', "Image($r('app.media.icon')); Column().width(99).height(99)", ['NO-DIMS'], 1),
            ('nested-image', "Image($r('app.media.icon')).onClick(() => { Image($r('app.media.icon')).width(24).height(24) })", ['NO-DIMS'], 2),
            ('two-images', "Image($r('app.media.icon')).width(24).height(24); Image($r('app.media.icon')).width(12)", ['ONE-DIM-NO-ASPECT'], 2),
        ]
        path = source / 'Boundary.ets'
        for label, body, kinds, count in cases:
            with self.subTest(label=label):
                path.write_text('// header\n@ComponentV2\nstruct Boundary { build() { ' + body + ' } }', encoding='utf-8')
                before = path.read_bytes()
                result = icon_audit(self.root, self.root / 'evidence/boundaries.json')
                self.assertEqual(result['report']['scanned'], count)
                self.assertEqual([row['kind'] for row in result['report']['flagged']], kinds)
                self.assertEqual([row['line'] for row in result['report']['flagged']], [3] * len(kinds))
                self.assertEqual(path.read_bytes(), before)

    def test_inconsistent_original_pass_cannot_borrow_callback_or_literal_dimensions(self):
        source, = self.modules([('entry', 'entry')])
        bodies = [
            "Image($r('app.media.icon')).onClick(() => { Column().width(99).height(99) })",
            "Image($r('app.media.icon')).accessibilityText('.width(99).height(99)') /* .width(99).height(99) */",
            "Image($r('app.media.icon')).width(24).accessibilityText('.height(99)')",
        ]
        path = source / 'Borrowed.ets'
        for body in bodies:
            with self.subTest(body=body):
                path.write_text('@ComponentV2 struct Borrowed { build() { ' + body + ' } }', encoding='utf-8')
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'borrowed dimensions outside the Image direct chain'):
                    icon_audit(self.root, self.root / 'evidence/must-not-pass.json')
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse((self.root / 'evidence/must-not-pass.json').exists())

    def test_projection_keeps_templates_regex_and_comments_opaque(self):
        text = ("const rx = /Image\\(.*\\)\\.width/;\n"
                "const raw = `Image(a).width(99) ${'literal'}`; // Image(no).height(88)\n"
                "Image($r('app.media.icon')).width(24).height(24)\n")
        projected, lines, added = projection_text(text.encode('utf-8'))
        self.assertGreater(added, 0)
        rendered = projected.decode('utf-8')
        self.assertIn('/Image\\(.*\\)\\.width/', rendered)
        self.assertIn("`Image(a).width(99) ${'literal'}`", rendered)
        self.assertIn('// Image(no).height(88)', rendered)
        self.assertEqual(lines[rendered[:rendered.rfind('.height(24)')].count('\n')], 3)
        with self.assertRaisesRegex(ValueError, 'Optional Image constructor'):
            projection_text(b'Image?.(source).width(24).height(24)')

    def test_configuration_cannot_route_detector_to_historical_or_tool_module(self):
        for name, path in [('archive', 'spec/.a2h/history/old'), ('tool', '.hmigbot-ios/plugin/template')]:
            self.modules([(name, path)])
            with self.assertRaisesRegex(ValueError, 'non-product|historical'):
                icon_audit(self.root, self.root / 'evidence/forbidden.json')
        self.assertFalse((self.root / 'evidence/forbidden.json').exists())

    def test_missing_module_configuration_fails_before_unscoped_original_scan(self):
        noise = self.root / 'tool/template/src/main/ets/Noise.ets'
        noise.parent.mkdir(parents=True)
        noise.write_text(UNSIZED, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Cannot read JSON'):
            icon_audit(self.root, self.root / 'evidence/unconfigured.json')
        self.assertFalse((self.root / 'evidence/unconfigured.json').exists())

    def test_inner_pipeline_icon_interface_is_read_only_and_ignores_historical_images(self):
        source, = self.modules([('entry', 'entry')])
        (source / 'Good.ets').write_text(SIZED, encoding='utf-8')
        noise = self.root / 'spec/archive/fence-snapshot/tool/template/entry/src/main/ets/History.ets'
        noise.parent.mkdir(parents=True)
        noise.write_text(UNSIZED, encoding='utf-8')
        before = self.files()
        output = self.root / 'evidence/pipeline-icon.json'
        with contextlib.redirect_stdout(io.StringIO()):
            code = autofix_main(['--project-root', str(self.root), '--apply', '--density', '3',
                                 '--output-json', str(output)])
        report = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(code, 0)
        self.assertTrue(report['passed'])
        self.assertEqual((report['scanned'], report['fixed_count'], report['mutated']), (1, 0, False))
        self.assertEqual(report['native_image_constraints']['source_roots'], ['entry/src/main/ets'])
        self.assertEqual(self.files(), before)

    def test_full_native_pipeline_frontend_runs_original_gates_with_scoped_read_only_icon(self):
        from test_native_pipeline_runtime import fixture
        fixture(self.root)
        before = self.files()
        state, output = self.root / 'spec/execution/loop.json', self.root / 'evidence/pipeline.json'
        with contextlib.redirect_stdout(io.StringIO()):
            code = structural_loop(['iterate', '--project-root', str(self.root), '--mode', 'pipeline',
                '--target', 'final', '--state-file', str(state), '--output-json', str(output), '--max-iter', '3'])
        self.assertIn(code, (0, 1))
        for name in ('assembly', 'binding', 'deadshell', 'carrier', 'hittest', 'resname'):
            gate = json.loads((state.parent / (name + '-pipeline-iter0.json')).read_text(encoding='utf-8'))
            self.assertFalse(gate.get('skipped'), gate)
        icon = json.loads((state.parent / 'icon-pipeline-iter0.json').read_text(encoding='utf-8'))
        self.assertTrue(icon['passed'])
        self.assertFalse(icon['mutated'])
        self.assertEqual(icon['fixed_count'], 0)
        self.assertEqual(icon['native_image_constraints']['source_file_count'], 1)
        self.assertEqual(self.files(), before)

    def test_inner_pipeline_icon_interface_fails_real_underconstrained_image_without_guessing_density(self):
        source, = self.modules([('entry', 'entry')])
        (source / 'Bad.ets').write_text(UNSIZED, encoding='utf-8')
        before = self.files()
        output = self.root / 'evidence/pipeline-icon-failed.json'
        with contextlib.redirect_stdout(io.StringIO()):
            code = autofix_main(['--project-root', str(self.root), '--apply', '--density', '3',
                                 '--output-json', str(output)])
        report = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(code, 1)
        self.assertFalse(report['passed'])
        self.assertEqual((report['flagged_before'], report['flagged_after'], report['fixed_count']), (1, 1, 0))
        self.assertFalse(report['mutated'])
        self.assertEqual(report['native_image_constraints']['report']['flagged'][0]['file'], 'entry/src/main/ets/Bad.ets')
        self.assertEqual(self.files(), before)

    @unittest.skipUnless(os.name == 'nt', 'Windows extended root spelling for long children')
    def test_original_detector_reads_real_long_child_with_short_configured_root(self):
        source, = self.modules([('entry', 'entry')])
        self.assertLess(len(str(source)), 260)
        relative = '/'.join(['real_product_subdirectory'] * 8) + '/Good.ets'
        long_file = source / relative
        self.assertGreater(len(str(long_file)), 260)
        long_file.parent.mkdir(parents=True)
        long_file.write_text(SIZED, encoding='utf-8')
        result = icon_audit(self.root, self.root / 'evidence/long-good.json')
        self.assertEqual(result['status'], 'passed')
        long_file.write_text(UNSIZED, encoding='utf-8')
        before = long_file.read_bytes()
        result = icon_audit(self.root, self.root / 'evidence/long-bad.json')
        self.assertEqual(result['status'], 'needs_source_dimensions')
        self.assertTrue(any('Good.ets' in json.dumps(row) for row in result['report']['flagged']))
        self.assertEqual(long_file.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
