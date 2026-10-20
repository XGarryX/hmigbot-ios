import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from hmigbot_ios.core import MigrationError
from hmigbot_ios.prompt_inputs import project_inputs


class PromptInputTests(unittest.TestCase):
    def setUp(self):
        self.facts = [{'id': 'f1'}, {'id': 'f2'}, {'id': 'shared'}]
        self.tasks = [
            {'id': 'account', 'fact_ids': ['shared', 'f1'], 'ac_ids': ['F001-AC01']},
            {'id': 'widget', 'fact_ids': ['f2', 'shared'], 'ac_ids': ['F002-AC01']},
        ]

    def test_shared_facts_and_global_decisions_stay_visible(self):
        shared = {'reason': 'Apply the pinned source theme'}
        result = project_inputs(self.facts, self.tasks, [shared])
        self.assertEqual([f['id'] for f in result['account']['facts']], ['f1', 'shared'])
        self.assertEqual([f['id'] for f in result['widget']['facts']], ['f2', 'shared'])
        for value in result.values():
            self.assertEqual(value['decisions'], [shared])
            self.assertEqual(value['omitted_decisions'], 0)

    def test_scoped_decisions_follow_all_explicit_consumers(self):
        account = {'id': 'account-only', 'prompt_scope': {'ac_ids': ['F001-AC01']}}
        shared = {'id': 'shared', 'prompt_scope': {'fact_ids': ['shared']}}
        union = {'id': 'union', 'prompt_scope': {'task_ids': ['account'], 'fact_ids': ['f2']}}
        result = project_inputs(self.facts, self.tasks, [account, shared, union])
        self.assertEqual(result['account']['decisions'], [account, shared, union])
        self.assertEqual(result['widget']['decisions'], [shared, union])
        self.assertEqual(result['widget']['omitted_decisions'], 1)

    def test_invalid_scope_cannot_silently_remove_constraints(self):
        for scope in [None, {}, {'task_ids': []}, {'task_ids': ['missing']},
                      {'ac_ids': ['F003-AC01']}, {'fact_ids': ['missing']},
                      {'unknown': ['account']}, {'task_ids': 'account'}, {'task_ids': [None]}]:
            with self.subTest(scope=scope), self.assertRaises(MigrationError):
                project_inputs(self.facts, self.tasks, [{'prompt_scope': scope}])

    def test_large_unrelated_decisions_are_not_repeated(self):
        decisions = [{'body': 'x' * 10000, 'prompt_scope': {'task_ids': ['account']}} for _ in range(100)]
        result = project_inputs(self.facts, self.tasks, decisions)
        self.assertEqual(len(result['account']['decisions']), 100)
        self.assertEqual(result['widget']['decisions'], [])
        self.assertEqual(result['widget']['omitted_decisions'], 100)


if __name__ == '__main__':
    unittest.main()
