"""Author-facing contracts must reach the already implemented prompt consumer."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import MigrationError
from hmigbot_ios.harness_schema import SCHEMA, validate
from hmigbot_ios.prompt_inputs import project_inputs


class WorkflowAuthoringContractsTests(unittest.TestCase):
    def skill(self, name):
        return (ROOT / 'skills' / name / 'SKILL.md').read_text(encoding='utf-8')

    def test_decision_ledger_has_one_canonical_authoring_path(self):
        for name in ('a2h-spec', 'a2h-plan'):
            with self.subTest(skill=name):
                text = self.skill(name)
                self.assertFalse('spec/baseline/decision-ledger.md' in text,
                                 name + ' must use the canonical ledger path')
                self.assertIn('spec/decision-ledger.md', text)

    def test_source_start_is_not_a_target_build_validation_gate(self):
        text = self.skill('a2h-init')
        self.assertFalse('validate exit 0 + spec' in text, 'Source start must not require target build tools')
        self.assertIn('harness-init --project <target>', text)
        self.assertIn('目标构建准入', text)
        self.assertIn('不阻断源分析', text)

    def test_retry_limit_does_not_waive_failed_static_contracts(self):
        for name in ('a2h-plan', 'a2h-execute', 'ios-source-analysis'):
            with self.subTest(skill=name):
                text = self.skill(name)
                self.assertFalse('记欠账放行' in text, name + ' cannot waive static failure after retries')
                self.assertIn('依赖失败输入', text)
                self.assertIn('blocked', text)

    def test_local_verify_cannot_claim_full_acceptance(self):
        text = self.skill('a2h-verify')
        self.assertIn('完整迁移验收', text)
        self.assertIn('100%', text)
        self.assertIn('not_run', text)

    def test_plan_request_example_reaches_real_prompt_consumers(self):
        path = ROOT / 'skills/a2h-plan/templates/plan-request-template.json'
        self.assertTrue(path.is_file(), 'A typed request example must be shipped to Plan authors')
        request = json.loads(path.read_text(encoding='utf-8'))
        validate(request, 'planRequest')
        facts = [{'id': 'fact-account'}, {'id': 'fact-widget'}, {'id': 'fact-shared'}]
        result = project_inputs(facts, request['tasks'], request['decisions'])
        global_decision = next(d for d in request['decisions'] if 'prompt_scope' not in d)
        account_only = next(d for d in request['decisions'] if d['id'] == 'D-ACCOUNT')
        shared = next(d for d in request['decisions'] if d['id'] == 'D-SHARED')
        for task_id in ('account', 'widget'):
            self.assertIn(global_decision, result[task_id]['decisions'])
            self.assertIn(shared, result[task_id]['decisions'])
        self.assertIn(account_only, result['account']['decisions'])
        self.assertNotIn(account_only, result['widget']['decisions'])

    def test_schema_exposes_scope_but_keeps_legacy_decision_fields(self):
        decision_rule = SCHEMA['$defs']['planRequest']['properties']['decisions']['items']
        self.assertEqual(decision_rule.get('$ref'), '#/$defs/decision')
        legacy = {'schema_version': 2, 'wave': 'understand', 'graph_sha256': '0' * 64,
                  'tasks': [{'id': 'account', 'role': 'a2h-ios-analyzer', 'goal': 'Read source',
                             'ownership': [], 'fact_ids': ['fact-account'], 'ac_ids': [], 'parents': []}],
                  'decisions': [{'reason': 'All tasks must retain this unscoped contract',
                                 'source_anchors': ['actual-source-anchor'], 'custom_existing_field': True}]}
        validate(legacy, 'planRequest')
        actual = project_inputs([{'id': 'fact-account'}], legacy['tasks'], legacy['decisions'])
        self.assertEqual(actual['account']['decisions'], legacy['decisions'])

    def test_schema_rejects_misspelled_scope_before_dispatch(self):
        request = {'schema_version': 2, 'wave': 'understand', 'graph_sha256': '0' * 64,
                   'tasks': [{'id': 'account', 'role': 'a2h-ios-analyzer', 'goal': 'Read source',
                              'ownership': [], 'fact_ids': ['fact-account'], 'ac_ids': [], 'parents': []}],
                   'decisions': [{'prompt_scope': {'tasks_ids': ['account']}}]}
        with self.assertRaises(MigrationError):
            validate(request, 'planRequest')


if __name__ == '__main__':
    unittest.main()
