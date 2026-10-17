"""E167（AIPPT_930 移植）：domains 重入（E68 rN）第二轮回执/任务书文件名带 domains-rN-，不覆盖首轮产物。"""
import json
import unittest

from test_generate_plan import PlanFixture


class DomainsReentryArtifactsTests(PlanFixture):
    def test_reentry_preserves_old_receipt_and_prompt(self):
        old_result = self.proj / 'spec/waves/results/domains/alpha.json'
        old_prompt = self.proj / 'spec/waves/prompts/domains/alpha.txt'
        self._write(old_result, '{"old":true}\n')
        self._write(old_prompt, 'original domain instructions\n')
        self._write(self.proj / 'spec/state/journal.json', json.dumps({
            'operation_outputs': [{'workflow_id': 'domains', 'kind': 'agent',
                                   'task_id': 'impl:alpha', 'status': 'OK'}]}))
        self.gen('domains', '--domain', 'alpha')
        self.assertTrue(self.lint('domains')['ok'])
        agent = next(t for t in self.plan('domains')['tasks'] if t['kind'] == 'agent')
        self.assertEqual(agent['id'], 'impl:r2:alpha')
        self.assertTrue(agent['result_path'].endswith('/domains-r2-alpha.json'))
        self.assertTrue(agent['prompt_file'].endswith('/domains-r2-alpha.txt'))
        self.assertEqual(old_result.read_text(), '{"old":true}\n')
        self.assertEqual(old_prompt.read_text(), 'original domain instructions\n')
        self.assertEqual(self.next_batch('domains')['action'], 'dispatch')


if __name__ == '__main__':
    unittest.main()
