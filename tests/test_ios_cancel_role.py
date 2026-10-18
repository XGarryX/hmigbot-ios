"""A ButtonRole value is not cancellation; unknown cancel values remain protected."""
from test_ios_task_priority import extract_case, tasks
import unittest


class ButtonCancelRoleTests(unittest.TestCase):
    def test_button_role_preserves_event_role_and_synchronous_write(self):
        graph, obs = extract_case('''struct Screen {
    func alert() {
        Button("知道了", role: .cancel) { store.message = nil }
    }
}
''')
        self.assertEqual(tasks(graph), [])
        events = [f for f in graph['facts'] if f['kind'] == 'event']
        self.assertEqual(len(events), 1)
        self.assertIn('role : . cancel', events[0]['value']['tokens'])
        self.assertTrue(any(f['kind'] == 'write' and f['symbol'] == 'message'
                            and 'nil' in f['value']['tokens'] for f in graph['facts']))
        self.assertFalse([o for o in obs['obligations'] if o['kind'] == 'task'])

    def test_role_and_real_cancel_in_same_button_are_separate(self):
        graph, obs = extract_case('Button(role: .cancel) { task.cancel() }')
        self.assertEqual([f['symbol'] for f in tasks(graph)], ['task', 'cancel'])
        self.assertEqual(len([o for o in obs['obligations'] if o['kind'] == 'task']), 2)

    def test_unknown_values_task_references_and_cancel_calls_stay_protected(self):
        graph, _ = extract_case('''func run() {
    configure(role: .cancel)
    let unknown = Widget.cancel
    let reference = task.cancel
    register(handler: .cancel)
    handle?.cancel()
    cancel()
    api.Button(role: .cancel) { }
}
''')
        self.assertEqual(len([f for f in tasks(graph) if f['symbol'] == 'cancel']), 7)

    def test_balanced_button_arguments_do_not_exempt_nested_role_or_handler(self):
        graph, _ = extract_case('''func run() {
    Button(makeLabel([1, 2], { () }), role: .cancel, action: { task.cancel() })
    Button(makeLabel(role: .cancel)) { }
    Button(role: factory.cancel) { }
}
''')
        self.assertEqual(len([f for f in tasks(graph) if f['symbol'] == 'cancel']), 3)


if __name__ == '__main__':
    unittest.main()
