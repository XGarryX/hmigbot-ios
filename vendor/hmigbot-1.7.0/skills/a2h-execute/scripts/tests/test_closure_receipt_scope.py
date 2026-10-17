"""E176（AIPPT_930 移植）：closure 白名单 = 产物 ownership + 本域各页 E39 主题回执分片；不给别域分片、infra 不给 UI 回执、
不凭分片为无白名单 owner 造白名单；plan 节点与任务书共用同一函数。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import assemble_prompt as A  # noqa: E402
import generate_waves as G  # noqa: E402


class ClosureReceiptScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bp = {
            '_dir': Path(self.tmp.name), 'workflow_params': {},
            'domain_map': {'domains': [
                {'key': 'app-one', 'pages': ['FirstPage', '_promoted_FirstPage', '../bad']},
                {'key': 'app-two', 'pages': ['SecondPage']}]},
            'ownership': {'owners': {
                'domain:app-one': ['entry/src/main/ets/features/app-one/**'],
                'domain:app-two': ['entry/src/main/ets/features/app-two/**'],
                'infra:app-one': ['entry/src/main/ets/infra/app-one/**']},
                'mainloop_owned': []}}
        self.backlog = {'round': 3, 'max_iter': 8, 'items': [
            {'id': 'CL-1', 'owner': 'domain:app-one', 'code': 'theme-receipt-mismatch',
             'layer': 'ui', 'summary': 'stale receipt', 'suggested_action': 'correct the real binding location'}]}
        (self.bp['_dir'] / 'closure-backlog.json').write_text(json.dumps(self.backlog))

    def test_only_own_exact_shards_and_original_product_scope(self):
        actual = A._closure_owner_files(self.bp, 'domain:app-one')
        self.assertEqual(actual, ['entry/src/main/ets/features/app-one/**',
                                  'spec/execution/theme-receipts/FirstPage.json',
                                  'spec/execution/theme-receipts/_promoted_FirstPage.json'])
        self.assertNotIn('spec/execution/theme-receipts/SecondPage.json', actual)
        self.assertEqual(self.bp['ownership']['owners']['domain:app-one'],
                         ['entry/src/main/ets/features/app-one/**'])

    def test_infra_never_gets_ui_shards(self):
        self.assertEqual(A._closure_owner_files(self.bp, 'infra:app-one'),
                         ['entry/src/main/ets/infra/app-one/**'])
        self.assertEqual(A._closure_owner_files(self.bp, 'unknown'), [])

    def test_receipts_do_not_create_a_missing_owner(self):
        self.bp['domain_map']['domains'].append({'key': 'unowned', 'pages': ['OtherPage']})
        self.assertEqual(A._closure_owner_files(self.bp, 'domain:unowned'), [])

    def test_plan_and_prompt_agree_on_receipt_scope(self):
        node = G.build_agent_skeletons(self.bp, 'closure',
                                       [{'key': 'domain:app-one', 'round': 3, 'layers': ['ui']}], 'spec/waves')[0]
        brief = A.brief_closure(self.bp, 'domain:app-one')
        self.assertEqual(node['ownership'], A._closure_owner_files(self.bp, 'domain:app-one'))
        for path in node['ownership']:
            self.assertIn(path, brief)
        self.assertEqual(json.loads((self.bp['_dir'] / 'closure-backlog.json').read_text()), self.backlog)


if __name__ == '__main__':
    unittest.main()
