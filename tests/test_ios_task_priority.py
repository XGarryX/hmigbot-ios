"""Task.detached/Task(priority:) is concurrency scheduling, not a UI layout constraint.

These cases drive the real source-signal extractor and its machine-derived obligations.
They must not special-case a file name or drop every priority signal: a genuine layout
priority stays a constraint, and an unverifiable priority keeps the original conservative
constraint signal.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))

from hmigbot_ios.ios_facts import extract, obligations

OCR_SERVICE = '''import Foundation
import Vision

enum OCRService {
    static func recognize(data: Data) async throws -> String {
        try await Task.detached(priority: .userInitiated) {
            let request = VNRecognizeTextRequest()
            return try await Task.detached(
                priority: .background,
                operation: { "done" }
            ).value
        }.value
    }
}
'''


def extract_case(text):
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory)
        (source / 'Sample.swift').write_text(text, encoding='utf-8')
        graph = extract(source)
        return graph, obligations(graph)


def constraints(graph):
    return [f for f in graph['facts'] if f['kind'] == 'constraint']


def tasks(graph):
    return [f for f in graph['facts'] if f['kind'] == 'task']


class TaskPriorityClassificationTests(unittest.TestCase):
    def test_real_ocr_task_detached_priority_is_not_layout(self):
        graph, obs = extract_case(OCR_SERVICE)
        self.assertEqual(constraints(graph), [],
                         'Task.detached(priority:) must not be classified as a layout constraint')
        self.assertIn('Task', {f['symbol'] for f in tasks(graph)},
                      'the scheduling obligation must remain a task/concurrency fact')
        task_ob = [o for o in obs['obligations'] if o['kind'] == 'task']
        self.assertTrue(task_ob, 'a task obligation must exist')
        self.assertTrue(all(o['judgments'] == ['unit', 'device'] for o in task_ob),
                        'scheduling must carry unit/device judgments, never ui/visual')

    def test_scheduling_priority_value_is_not_silently_dropped(self):
        graph, _ = extract_case(OCR_SERVICE)
        window = ' '.join(f['value'].get('tokens', '') for f in tasks(graph))
        self.assertIn('priority', window, 'the task fact must retain the priority argument')
        self.assertIn('userInitiated', window, 'the task fact must retain the scheduling priority literal')

    def test_task_initializer_and_detached_variants_are_scheduling(self):
        graph, _ = extract_case('''func go() {
    Task(priority: .low) { }
    Task.init(priority: .high, operation: { })
    let t = await Task.detached(priority: .medium) { }
}
''')
        self.assertEqual([f for f in constraints(graph) if f['symbol'] == 'priority'], [],
                         'Task/Task.init/Task.detached priority arguments are all scheduling')

    def test_genuine_layout_priority_is_still_a_constraint(self):
        graph, obs = extract_case('''func layout() {
    let c = NSLayoutConstraint()
    c.priority = UILayoutPriority(999)
    let constraint = view.constraints.first
    stack.priority(0.5)
}
''')
        symbols = {f['symbol'] for f in constraints(graph)}
        self.assertIn('NSLayoutConstraint', symbols)
        self.assertIn('constraint', symbols)
        self.assertIn('priority', symbols, 'a layout priority property access must remain a constraint')
        self.assertTrue(all(o['judgments'] == ['ui', 'visual'] for o in obs['obligations'] if o['kind'] == 'constraint'))

    def test_mixed_task_and_layout_do_not_cross_pollute(self):
        graph, _ = extract_case('''import UIKit
class Screen: UIViewController {
    func start() {
        let c = NSLayoutConstraint()
        c.priority = .defaultHigh
        Task.detached(priority: .utility) { self.refresh() }
    }
}
''')
        priority_facts = [f for f in constraints(graph) if f['symbol'] == 'priority']
        self.assertTrue(any('c.priority' in f['anchor']['snippet'] for f in priority_facts),
                        'the c.priority layout line must stay a constraint')
        self.assertFalse(any('Task.detached' in f['anchor']['snippet'] for f in constraints(graph)),
                         'the Task.detached(priority:) line must not add a constraint')
        self.assertTrue(constraints(graph), 'the real layout constraint must remain')

    def test_unknown_or_bare_priority_keeps_original_protection(self):
        graph, _ = extract_case('''func unknown() {
    configure(priority: .high)
    let priority = 5
}
''')
        self.assertTrue([f for f in constraints(graph) if f['symbol'] == 'priority'],
                        'a non-Task priority keeps the conservative constraint signal')

    def test_comment_and_string_priority_never_fire(self):
        graph, _ = extract_case('''// priority: layout note and Task.detached(priority: .high)
func f() {
    let label = "Task.detached(priority: .high) constraint priority"
}
''')
        self.assertEqual(constraints(graph), [], 'comments and string literals must not create constraints')

    def test_unknown_qualified_task_callees_keep_constraints(self):
        graph, _ = extract_case('''func layout(layoutAPI: LayoutAPI) {
    layoutAPI.Task(priority: .required)
    layoutAPI.Task.detached(priority: .required)
    layoutAPI.Task.init(priority: .required)
    Swift.Task(priority: .high)
}
''')
        self.assertEqual(len([f for f in constraints(graph) if f['symbol'] == 'priority']), 4)

    def test_nested_unknown_call_and_later_arguments_are_isolated(self):
        graph, _ = extract_case('''func go() {
    Task.detached(operation: { configure(priority: .required) }, priority: .high)
    Task.init(operation: make([1, 2], { () }), priority: .low)
    layoutAPI.Task(operation: make([1, 2]), priority: .required)
}
''')
        priorities = [f for f in constraints(graph) if f['symbol'] == 'priority']
        self.assertEqual(len(priorities), 2)
        self.assertEqual([f['anchor']['line'] for f in priorities], [2, 4])


if __name__ == '__main__':
    unittest.main()
