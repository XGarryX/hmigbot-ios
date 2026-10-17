"""E167（AIPPT_930 移植）：closeout 重入（handoff-check 修后再收尾）与 E68 同形——第二轮 b4:r2:factchain，
旧 b4 回执不被覆盖，reduce 终态按轮次隔离（E55），下一拍必须重新构建而不是沿用首轮 PASS 行。"""
import json
import sys
import unittest
from pathlib import Path

from test_generate_plan import PlanFixture

sys.path.insert(0, str(Path(__file__).parents[1]))
import _wavelib  # noqa: E402


class CloseoutReentryTests(PlanFixture):
    def test_round_two_preserves_receipt_and_requires_fresh_build(self):
        journal = {'operation_outputs': [
            {'workflow_id': 'closeout', 'kind': 'agent', 'task_id': 'b4:factchain', 'status': 'OK'},
            {'workflow_id': 'closeout', 'kind': 'reduce', 'task_id': 'reduce:build-closeout', 'status': 'REDUCE_PASS'}]}
        self._write(self.proj / 'spec/state/journal.json', json.dumps(journal))
        old = self.proj / 'spec/waves/results/closeout/b4-factchain.json'
        self._write(old, '{"old":true}\n')
        self.gen('closeout')
        self.lint('closeout')
        plan = self.plan('closeout')
        agent = next(n for n in plan['tasks'] if n['kind'] == 'agent')
        self.assertEqual(agent['id'], 'b4:r2:factchain')
        self.assertTrue(agent['result_path'].endswith('/closeout-r2-b4-factchain.json'))
        self.assertTrue(agent['prompt_file'].endswith('/closeout-r2-b4-factchain.txt'))
        self.assertEqual(old.read_text(), '{"old":true}\n')
        self.assertEqual(_wavelib.plan_run_tag(plan), 'r2')
        self.assertEqual(_wavelib.journal_indexes(journal, 'closeout', 'r2')[1], {})
        self.assertEqual(self.next_batch('closeout')['action'], 'gate')
        self.assertIn('reduce:build-closeout', self.next_batch('closeout')['reason'])

    def test_digit_prefix_increments_to_round_three(self):
        self._write(self.proj / 'spec/state/journal.json', json.dumps({'operation_outputs': [
            {'workflow_id': 'closeout', 'kind': 'agent', 'task_id': 'b4:r2:factchain', 'status': 'OK'}]}))
        self.gen('closeout')
        self.assertEqual(next(n['id'] for n in self.plan('closeout')['tasks'] if n['kind'] == 'agent'), 'b4:r3:factchain')


if __name__ == '__main__':
    unittest.main()
