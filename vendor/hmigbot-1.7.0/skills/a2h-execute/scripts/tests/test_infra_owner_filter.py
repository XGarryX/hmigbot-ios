"""E167（AIPPT_930 移植）：infra 波 --domain 按模块组 key 过滤（此前警告后忽略、派出全部模块组）；未知 key 响亮失败。"""
import json
import unittest

from test_generate_plan import PlanFixture


class InfraOwnerFilterTests(PlanFixture):
    def test_single_owner_filters_instead_of_dispatching_all_modules(self):
        ownership = json.loads((self.blueprint / 'ownership.json').read_text())
        ownership['owners']['infra:other'] = ['other/**']
        self._write(self.blueprint / 'ownership.json', json.dumps(ownership))
        contracts = json.loads((self.blueprint / 'contracts.json').read_text())
        contracts['modules'].append({'file': 'other/Extra.ets', 'owner': 'infra:other',
                                     'status': 'planned', 'exports': []})
        self._write(self.blueprint / 'contracts.json', json.dumps(contracts))
        self.gen('infra', '--domain', 'core')
        self.assertTrue(self.lint('infra')['ok'])
        agents = [t for t in self.plan('infra')['tasks'] if t['kind'] == 'agent']
        self.assertEqual([t['id'] for t in agents], ['impl:core'])

    def test_unknown_single_owner_fails_loudly(self):
        self.gen('infra', '--domain', 'missing', expect=1)


if __name__ == '__main__':
    unittest.main()
