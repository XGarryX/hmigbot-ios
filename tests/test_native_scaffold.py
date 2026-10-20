"""native_scaffold: derive spec candidates from a reviewed source index.

Proves the F001 deadlock is broken: a clean fixture scaffolded by this module is
discovered by ``native_authoring.prepare`` (no "missing indexed doc"), while unknown
templates are excluded from the UI manifest so the harness cannot enter them as plans.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))

from hmigbot_ios.core import MigrationError, snapshot
from hmigbot_ios.native_pipeline import configure, index_source
from hmigbot_ios.native_authoring import prepare
from hmigbot_ios.native_scaffold import (
    scaffold, apply_scaffold, classify_type, _top_level_types,
)


def build_fixture(root):
    source = root / 'source'
    project = root / 'target'
    source.mkdir()
    project.mkdir()
    files = {
        'CounterViewController.swift': (
            'import UIKit\n'
            'class CounterViewController: UIViewController {\n'
            '    var count = 0\n'
            '    @IBAction func onAdd(_ sender: Any) { count += 1 }\n'
            '}\n'
        ),
        'HomeScreen.swift': (
            'import SwiftUI\n'
            'struct HomeScreen: View {\n'
            '    @State private var name = ""\n'
            '    var body: some View { VStack { Text(name) } }\n'
            '}\n'
        ),
        'ChartBridge.swift': (
            'import SwiftUI\n'
            'import UIKit\n'
            'struct ChartBridge: UIViewRepresentable {\n'
            '    func makeUIView(context: Context) -> UIView { UIView() }\n'
            '}\n'
        ),
        'CounterViewModel.swift': (
            'struct CounterViewModel {\n'
            '    var count: Int = 0\n'
            '    func reset() { count = 0 }\n'
            '}\n'
        ),
        'Theme+Colors.swift': (
            'extension UIColor {\n'
            '    static let brand = UIColor.red\n'
            '}\n'
        ),
    }
    for name, text in files.items():
        (source / name).write_text(text, encoding='utf-8')
    configure(source.resolve(), project.resolve())
    index_source(project)
    return source, project


class ClassificationTests(unittest.TestCase):
    def test_top_level_types_ignore_nested(self):
        text = 'struct Outer { struct Inner { } }\nclass Foo: UIView { }\n'
        names = {n for n, _, _ in _top_level_types(text)}
        self.assertEqual(names, {'Outer', 'Foo'})  # Inner is nested, ignored

    def test_classify_variants(self):
        self.assertEqual(classify_type('C', 'class', 'import UIKit\nclass C: UIViewController {\n}\n')[0], 'page')
        component = classify_type('S', 'struct', 'import SwiftUI\nstruct S: View {\nvar body: some View { Text("") }\n}\n')
        self.assertEqual(component[0], 'component')
        self.assertEqual(classify_type('HomeScreen', 'struct',
                          'import SwiftUI\nstruct HomeScreen: View {\nvar body: some View { Text("") }\n}\n')[0], 'page')
        self.assertEqual(classify_type('B', 'struct', 'import SwiftUI\nstruct B: UIViewRepresentable {\n}\n')[0], 'bridge')
        self.assertEqual(classify_type('UIColor', 'extension', 'extension UIColor {\n}\n')[0], 'extension')
        model = classify_type('M', 'struct', 'struct M {\nvar x: Int = 0\n}\n')
        self.assertEqual(model[0], 'unknown')
        self.assertTrue(model[6])  # unknown_template


class ScaffoldIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source, self.project = build_fixture(self.root)
        self.base = self.project / 'spec/baseline'

    def tearDown(self):
        self.temp.cleanup()

    def test_scaffold_flags_and_classification(self):
        cand = scaffold(self.project)
        self.assertTrue(cand['candidate'])
        self.assertTrue(cand['needs_review'])
        self.assertFalse(cand['spec_complete'])
        self.assertFalse(cand['behavior_verified'])
        self.assertFalse(cand['enterable_plan'])
        self.assertFalse(cand['source_change_detected'])
        types = {c['name']: c['candidate_type'] for c in cand['candidates']}
        self.assertEqual(types['CounterViewController'], 'page')
        self.assertEqual(types['HomeScreen'], 'page')
        self.assertEqual(types['ChartBridge'], 'bridge')
        self.assertEqual(types['CounterViewModel'], 'unknown')
        self.assertEqual(types['UIColor'], 'extension')
        ui_names = {c['name'] for c in cand['candidates'] if c['is_ui']}
        self.assertNotIn('CounterViewModel', ui_names)
        self.assertNotIn('UIColor', ui_names)
        self.assertIn('CounterViewModel', cand['inventory_diff']['unknown_templates'])
        self.assertIn('UIColor', cand['inventory_diff']['extensions'])

    def test_apply_then_prepare_discovers(self):
        cand = scaffold(self.project)
        result = apply_scaffold(self.project, cand)
        self.assertTrue(result['created'])
        self.assertEqual(result['skipped'], [])
        prepare(self.project)  # must NOT raise "Indexed authoring document is missing"
        # idempotent: re-apply skips already-created docs
        result2 = apply_scaffold(self.project, cand)
        self.assertEqual(result2['created'], [])
        self.assertEqual(set(result2['skipped']), set(result['created']))

    def test_unknown_excluded_from_manifest(self):
        cand = scaffold(self.project)
        apply_scaffold(self.project, cand)
        manifest = (self.base / 'ui-manifest.md').read_text(encoding='utf-8')
        self.assertNotIn('CounterViewModel', manifest)
        self.assertNotIn('UIColor', manifest)
        index = (self.base / 'feature-index.md').read_text(encoding='utf-8')
        self.assertIn('CounterViewController', index)
        # every indexed page id resolves to a written page document
        for pid in cand['inventory_diff']['new_pages']:
            self.assertTrue(list(self.base.glob(f'ui/{pid}_*.md')))

    def test_stable_ids_across_calls(self):
        a = scaffold(self.project)
        b = scaffold(self.project)
        self.assertEqual([c['page_id'] for c in a['candidates'] if c['is_ui']],
                         [c['page_id'] for c in b['candidates'] if c['is_ui']])
        self.assertEqual([c['feature_id'] for c in a['candidates'] if c['feature_id']],
                         [c['feature_id'] for c in b['candidates'] if c['feature_id']])

    def test_apply_refuses_source_change(self):
        cand = scaffold(self.project)
        (self.source / 'CounterViewController.swift').write_text(
            'import UIKit\nclass CounterViewController: UIViewController {\n    var x = 1\n}\n', encoding='utf-8')
        with self.assertRaises(MigrationError):
            apply_scaffold(self.project, cand)


if __name__ == '__main__':
    unittest.main()
