"""E166（AIPPT_930 移植）：wiring owner 别名归一——同一 owner 的多种写法（x / domain:x / infra 简写 / seed / app-entry）
只出一个任务且每条 BK 恰落一个任务；owner_obligations 多消费者按未兑现 owner 各出一个任务、各只见自己的义务。
AIPPT_930 2026-09-17：13 任务 lint 报 9 处 owner 别名重叠，一个都派不出去。"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import assemble_prompt as A  # noqa: E402
import generate_waves as G  # noqa: E402


class WiringOwnerAliasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bp = {'_dir': Path(self.tmp.name), 'domain_map': {'domains': [{'key': 'app-home'}, {'key': 'common-basis'}]}, 'ownership': {
            'owners': {'seed': ['entry/src/main/ets/pages/Index.ets'],
                       'infra:common-basis': ['entry/src/main/ets/infra/shared/common-basis/**'],
                       'domain:app-home': ['entry/src/main/ets/features/app-home/**']},
            'mainloop_owned': []}}
        self.items = [{'id': 'BK-' + str(i), 'required_owner': owner, 'summary': 'fixture'}
                      for i, owner in enumerate(('common-basis', 'infra:common-basis', 'seed', 'mainloop', 'app-home', 'domain:app-home'), 1)]
        (self.bp['_dir'] / 'wiring-backlog.json').write_text(json.dumps({'items': self.items}))

    def test_generator_has_one_task_per_real_owner(self):
        self.assertEqual(G.build_tasks(self.bp, 'wiring'), [{'key': 'app-home'}, {'key': 'infra:common-basis'}, {'key': 'mainloop'}])

    def test_all_backlog_ids_survive_in_exactly_one_task(self):
        texts = [A.brief_wiring(self.bp, task['key']) for task in G.build_tasks(self.bp, 'wiring')]
        for item in self.items:
            heading = r'- \*\*\d+\. ' + re.escape(item['id']) + r'\*\*'
            self.assertEqual(sum(len(re.findall(heading, text)) for text in texts), 1)
        self.assertEqual(len(json.loads((self.bp['_dir'] / 'wiring-backlog.json').read_text())['items']), 6)

    def test_canonical_scopes_equal_existing_owner_scopes(self):
        self.assertEqual(A._wiring_owner_files(self.bp, 'common-basis'), A._wiring_owner_files(self.bp, 'infra:common-basis'))
        self.assertEqual(A._wiring_owner_files(self.bp, 'domain:app-home'), A._wiring_owner_files(self.bp, 'app-home'))
        self.assertTrue(set(A._wiring_owner_files(self.bp, 'seed')).issubset(A._wiring_owner_files(self.bp, 'mainloop')))

    def test_multiple_consumer_tasks_have_owner_specific_obligations(self):
        item = {"id": "BK-2", "required_owner": "old-provider", "owner_obligations": [
            {"owner": "app-home", "status": "open", "skipped_reason": "home avatar must bind"},
            {"owner": "infra:common-basis", "status": "open", "skipped_reason": "shared covers must bind"},
            {"owner": "mainloop", "status": "resolved", "skipped_reason": "already done"}]}
        (self.bp['_dir'] / 'wiring-backlog.json').write_text(json.dumps({"items": [item]}))
        self.assertEqual(G.build_tasks(self.bp, 'wiring'), [{"key": "app-home"}, {"key": "infra:common-basis"}])
        home = A.brief_wiring(self.bp, "app-home")
        shared = A.brief_wiring(self.bp, "infra:common-basis")
        self.assertIn("home avatar must bind", home)
        self.assertNotIn("shared covers must bind", home)
        self.assertIn("shared covers must bind", shared)
        self.assertNotIn("home avatar must bind", shared)

    def test_unknown_owner_remains_unresolved(self):
        self.assertEqual(A._canonical_wiring_owner(self.bp, 'unknown'), 'unknown')
        self.assertEqual(A._wiring_owner_files(self.bp, 'unknown'), [])


if __name__ == '__main__':
    unittest.main()
