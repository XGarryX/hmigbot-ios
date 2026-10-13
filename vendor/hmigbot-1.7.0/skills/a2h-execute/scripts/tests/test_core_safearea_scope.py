"""E168（AIPPT_930 移植）：safearea_layers 机器收紧的适用性——生成侧核心任务（写权全在 features/components）不带
safearea_layers 收紧、页面块仍带；落账侧对已冻结计划里仍带收紧的核心任务允许显式 []（缺失仍拒绝，非委托任务空数组仍拒绝）。
判据函数本身的回归见 test_task_scope.py。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
import land_results as L  # noqa: E402
from test_generate_plan import PlanFixture  # noqa: E402


class CoreSafeareaValidatorTests(unittest.TestCase):
    def test_validator_rejects_missing_but_accepts_empty_only_when_delegated(self):
        class Proc:
            returncode = 0
            stderr = ''

            def __init__(self, data):
                self.stdout = json.dumps(data)

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'result.json'
            p.write_text('{}')
            cases = [({}, True, False), ({'safearea_layers': []}, False, False),
                     ({'safearea_layers': []}, True, True), ({'safearea_layers': ['file:1']}, False, True)]
            for data, delegated, expected in cases:
                with patch.object(L, '_run', return_value=Proc(data)):
                    _, err, notes = L.parse_result(p, 'domainImpl', ['safearea_layers'], 'impl:home', delegated_safearea=delegated)
                    self.assertEqual(err is None, expected, (data, delegated, err))
                    if expected and data['safearea_layers'] == []:
                        self.assertTrue(any(n.startswith('safearea-page-delegated') for n in notes))


class CoreSafeareaPlanTests(PlanFixture):
    def test_core_task_is_not_tightened_but_page_block_is(self):
        pages = ['HomeActivity', 'GuideActivity', 'MineActivity', 'AboutActivity']   # > PAGE_CHUNK → 触发分块
        names = {p: p.replace('Activity', 'Page') for p in pages}
        dm = json.loads((self.blueprint / 'domain-map.json').read_text())
        dm['domains'][0]['pages'] = pages
        self._write(self.blueprint / 'domain-map.json', json.dumps(dm))
        self._write(self.blueprint / 'page-names.json', json.dumps({'domains': {'alpha': names}}))
        wp = json.loads((self.blueprint / 'workflow-params.json').read_text(encoding='utf-8'))
        wp.setdefault('gates', {}).update({'single_block_domain': False, 'page_chunk': 3})   # 本用例验证「核心任务 + 页面块」旧口径（E194 缺省为单块）
        self._write(self.blueprint / 'workflow-params.json', json.dumps(wp))
        own = json.loads((self.blueprint / 'ownership.json').read_text())
        own['owners']['domain:alpha'] = ['entry/src/main/ets/features/alpha/**'] + \
            ['entry/src/main/ets/pages/%s.ets' % h for h in names.values()]
        self._write(self.blueprint / 'ownership.json', json.dumps(own))
        self._write(self.proj / 'spec/domains/alpha.md', '# alpha\n')
        for p in pages:   # 三源数据目录：spec/ui/<page>/meta.json（page_dir 探测顺序的最后一档）
            self._write(self.proj / 'spec/ui' / p / 'meta.json',
                        json.dumps({'page_id': p, 'needs_immersive_safearea': p == 'HomeActivity'}))
        self.gen('domains', '--domain', 'alpha')
        tasks = {t['id']: t for t in self.plan('domains')['tasks'] if t['kind'] == 'agent'}
        core = tasks['impl:alpha']
        blocks = [t for tid, t in tasks.items() if tid.startswith('impl:alpha:p')]
        self.assertTrue(blocks)
        self.assertEqual(core['ownership'], ['entry/src/main/ets/features/alpha/**'])
        self.assertNotIn('safearea_layers', core.get('schema_required_extra') or [])
        self.assertTrue(any('safearea_layers' in (b.get('schema_required_extra') or []) for b in blocks))


if __name__ == '__main__':
    unittest.main()
