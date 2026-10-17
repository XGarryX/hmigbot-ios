"""E176（AIPPT_930 移植，部分）：emits 到模块组同名域 key 的已批决策也投递给 infra 任务书
（此前只有 domains 任务书渲染决策）；proposed / 别域决策不投递。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import assemble_prompt as A  # noqa: E402
from test_generate_plan import PlanFixture  # noqa: E402


class ScopeDeliveryTests(PlanFixture):
    def test_approved_decision_emitted_to_module_group_reaches_infra_prompt(self):
        card = {'id': 'PD-V2', 'status': 'approved', 'category': 'C7', 'emits': ['core'], 'symbols': [],
                'evidence': 'user', 'title': 'V2'}
        self._write(self.blueprint / 'decisions.json', json.dumps({'decisions': [card]}))
        self._write(self.blueprint / 'decision-ledger.md', '### PD-V2\nComponentV2 + ObservedV2/Trace\n')
        self.gen('infra')
        agent = next(n for n in self.plan('infra')['tasks'] if n['kind'] == 'agent')
        self.assertIn('ComponentV2 + ObservedV2/Trace', (self.proj / agent['prompt_file']).read_text())

    def test_proposed_or_other_domain_decisions_are_not_delivered(self):
        bp = {'contracts': {'acceptance': [], 'chains': []}, 'decisions': {'decisions': [
            {'id': 'mine', 'status': 'approved', 'emits': ['core']},
            {'id': 'other', 'status': 'approved', 'emits': ['other']},
            {'id': 'proposed', 'status': 'proposed', 'emits': ['core']}]}}
        self.assertEqual([d['id'] for d in A._domain_decisions(bp, 'core')], ['mine'])
        self.assertEqual(A._render_decisions({'decisions': {'decisions': []}}, 'core'), '')


if __name__ == '__main__':
    unittest.main()
