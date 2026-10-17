"""E167（AIPPT_930 移植）：infra 重入与 E68 domains 同形——第二轮 impl:r2:<key>，回执/任务书 infra-r2-<key>，首轮回执保留。"""
import json
import unittest

from test_generate_plan import PlanFixture


class InfraReentryTests(PlanFixture):
    def test_reentry_new_id_receipt_and_prompt_preserve_old_receipt(self):
        self._write(self.proj / 'spec/state/journal.json', json.dumps({'operation_outputs': [
            {'workflow_id': 'infra', 'kind': 'agent', 'task_id': 'impl:core', 'status': 'OK'}]}))
        old_receipt = self.proj / 'spec/waves/results/infra/core.json'
        self._write(old_receipt, '{"old":true}\n')
        self.gen('infra')
        self.lint('infra')
        agents = [n for n in self.plan('infra')['tasks'] if n['kind'] == 'agent']
        self.assertEqual(len(agents), 1)
        node = agents[0]
        self.assertEqual(node['id'], 'impl:r2:core')
        self.assertEqual(node['resume_key'], 'infra:impl:r2:core')
        self.assertTrue(node['prompt_file'].endswith('/infra-r2-core.txt'))
        self.assertTrue(node['result_path'].endswith('/infra-r2-core.json'))
        self.assertEqual(old_receipt.read_text(), '{"old":true}\n')


if __name__ == '__main__':
    unittest.main()
