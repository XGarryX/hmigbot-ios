"""E167（AIPPT_930 移植）：wave_status 的 reduce 终态与 journal 尾部按本轮 run 标签取（与 next_batch/land 的 E55 同源），
重入第二轮不得显示首轮的 REDUCE_PASS/FAIL；首轮（无标签）行为不变。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import wave_status  # noqa: E402


class WaveStatusRoundTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_round_two_does_not_inherit_previous_pass_or_failure(self):
        plan = {'wave': 'infra', 'tasks': [
            {'id': 'impl:r2:core', 'kind': 'agent'},
            {'id': 'gate:compile-1', 'kind': 'reduce'}]}
        journal = {'operation_outputs': [
            {'workflow_id': 'infra', 'task_id': 'gate:compile-1', 'kind': 'reduce', 'status': 'REDUCE_FAIL'},
            {'workflow_id': 'infra', 'task_id': 'gate:compile-1', 'kind': 'reduce', 'status': 'REDUCE_PASS'}]}
        result = wave_status.collect(plan, {}, {}, journal, self.root)
        self.assertEqual(result['run_tag'], 'r2')
        self.assertEqual(result['reduces'], {'gate:compile-1': None})
        self.assertEqual(result['journal_tail'], [])
        journal['operation_outputs'].append({
            'workflow_id': 'infra', 'task_id': 'gate:compile-1', 'kind': 'reduce', 'run': 'r2', 'status': 'REDUCE_FAIL'})
        result = wave_status.collect(plan, {}, {}, journal, self.root)
        self.assertEqual(result['reduces'], {'gate:compile-1': 'REDUCE_FAIL'})
        self.assertEqual(len(result['journal_tail']), 1)

    def test_initial_round_retains_legacy_rows(self):
        plan = {'wave': 'infra', 'tasks': [{'id': 'gate:compile-1', 'kind': 'reduce'}]}
        journal = {'operation_outputs': [{
            'workflow_id': 'infra', 'task_id': 'gate:compile-1', 'kind': 'reduce', 'status': 'REDUCE_PASS'}]}
        self.assertEqual(wave_status.collect(plan, {}, {}, journal, self.root)['reduces']['gate:compile-1'], 'REDUCE_PASS')


if __name__ == '__main__':
    unittest.main()
