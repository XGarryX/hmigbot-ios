"""E167（AIPPT_930 移植）：--resume/--retry-failed 裁剪按逻辑任务 id 跨轮对账（impl:r3:a ↔ impl:a / impl:r2:a），
取 state 最新一轮状态——此前重入轮次先打 rN 再裁剪，--resume 把已 done 的全部重做、--retry-failed 裁成空集。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import generate_waves as G  # noqa: E402


class ResumeRoundTrimTests(unittest.TestCase):
    def trim(self, rows, resume=True, retry=False):
        nodes = [{'id': 'impl:r3:' + key} for key in ('a', 'a:p1', 'b', 'c')]
        state = {'waves': {'domains': {'tasks': rows}}}
        return [n['id'] for n in G.trim_nodes_by_state(nodes, state, 'domains', resume, retry)]

    def test_resume_preserves_completed_core_and_page(self):
        rows = [{'id': 'impl:a', 'status': 'done'}, {'id': 'impl:r2:a:p1', 'status': 'done'}]
        self.assertEqual(self.trim(rows), ['impl:r3:b', 'impl:r3:c'])

    def test_retry_selects_failed_across_old_and_tagged_rounds(self):
        rows = [{'id': 'impl:a', 'status': 'failed'}, {'id': 'impl:r2:b', 'status': 'failed'}]
        self.assertEqual(self.trim(rows, False, True), ['impl:r3:a', 'impl:r3:b'])

    def test_latest_round_wins_independent_of_state_order(self):
        rows = [{'id': 'impl:r2:a', 'status': 'done'}, {'id': 'impl:a', 'status': 'failed'}]
        self.assertEqual(self.trim(rows, False, True), [])

    def test_newer_failure_is_not_hidden_by_old_completion(self):
        rows = [{'id': 'impl:a', 'status': 'done'}, {'id': 'impl:r2:a', 'status': 'failed'}]
        self.assertEqual(self.trim(rows, False, True), ['impl:r3:a'])

    def test_plain_task_names_and_unknown_tasks(self):
        rows = [{'id': 'impl:a', 'status': 'done'}, {'id': 'impl:b', 'status': 'pending'}]
        self.assertEqual(self.trim(rows), ['impl:r3:a:p1', 'impl:r3:b', 'impl:r3:c'])


if __name__ == '__main__':
    unittest.main()
