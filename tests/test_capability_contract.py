"""Plan-time provider references using the real complete plan fixture."""
import copy
import json
from pathlib import Path
import unittest

import test_plan_contract as plan_fixture
from hmigbot_ios.core import MigrationError
from hmigbot_ios.plan_contract import validate_plan, _projection
from hmigbot_ios.capability_contract import validate_declarations


class CapabilityContractTests(unittest.TestCase):
    task = plan_fixture.PlanContractTests.task
    write_plans = plan_fixture.PlanContractTests.write_plans
    responsibility = plan_fixture.PlanContractTests.responsibility
    tearDown = plan_fixture.PlanContractTests.tearDown

    def setUp(self):
        plan_fixture.PlanContractTests.setUp(self)
        replacements = {'BASE:Base-0': 'BASE:Base-1', 'SLICE:F001:3a': 'SLICE:F001:3c'}
        for item in self.items:
            item['item_id'] = replacements.get(item['item_id'], item['item_id'])
            item['parents'] = [replacements.get(ref, ref) for ref in item['parents']]
        for task in self.request['tasks']:
            task['plan_item_refs'] = [replacements.get(ref, ref) for ref in task['plan_item_refs']]
        self.write_plans()
        self.index = self.base / 'plans/feature-plan.md'
        self.index_text = self.index.read_text(encoding='utf-8')

    def declaration(self, **changes):
        return {'key': 'base.service', 'kind': 'runtime-slot', 'symbol': 'BaseService',
                'path': 'entry/Base.ets', 'slot': 'store', 'lifecycle': 'open/dispose',
                'provider': 'spec/baseline/plans/base-plan.md#BASE:Base-1',
                'provenance': 'source:BaseService', **changes}

    def install(self, entries=None, raw=None, **top):
        body = raw if raw is not None else json.dumps({'declarations': entries or [self.declaration()], 'seams': 'none', **top})
        self.index.write_text(self.index_text + '\n```capability-declarations\n' + body + '\n```\n', encoding='utf-8')

    def check(self, expected=None, label=''):
        before = {p.relative_to(self.project).as_posix(): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        if expected:
            with self.assertRaisesRegex(MigrationError, expected) as caught:
                validate_plan(self.project, self.request)
            actual = str(caught.exception)
        else:
            result = validate_plan(self.project, self.request)
            self.assertEqual(result['status'], 'PASS')
            self.assertIs(result['behavior_verified'], False)
            actual = result.get('capability_declarations', 'optional block absent')
        after = {p.relative_to(self.project).as_posix(): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        self.assertEqual(before, after, 'validation must not write state or inputs')
        print(json.dumps({'case': self._testMethodName + ':' + label, 'expected': expected or 'PASS/static only', 'actual': actual}, ensure_ascii=True))
        return actual

    def test_absent_block_compatible(self):
        self.assertEqual(self.check(), 'optional block absent')

    def test_legal_base_exact_file_and_slot(self):
        self.install(); actual = self.check()
        self.assertEqual(actual['declarations'], 1)
        self.assertIs(actual['runtime_verified'], False)

    def test_legal_slice_exact_file(self):
        self.install([self.declaration(key='slice.service', path='entry/CounterService.ets', provider='spec/baseline/plans/slices/slice-01-F001.md#SLICE:F001:3c')])
        self.check()

    def test_unique_basename(self):
        self.install([self.declaration(provider='base-plan.md#BASE:Base-1')]); self.check()

    def test_unknown_anchor_and_no_prefix_or_case_guess(self):
        for ref in ['base-plan.md#BASE:Base-999', 'base-plan.md#BASE:Base-1-more', 'Base-plan.md#BASE:Base-1', 'base-plan.md#base:Base-1']:
            with self.subTest(ref=ref):
                self.install([self.declaration(provider=ref)]); self.check('capability-provider-unknown', ref)

    def test_wrong_owner_not_global_ownership(self):
        self.install([self.declaration(path='entry/CounterService.ets')]); self.check('capability-provider-owner-mismatch')

    def test_slice_wrong_file(self):
        self.install([self.declaration(path='entry/CounterService.ets', provider='base-plan.md#SLICE:F001:3c')]); self.check('capability-provider-unknown')

    def test_unknown_fields_and_invalid_shapes(self):
        mutations = [dict(phase='Entry'), dict(slot=None), dict(kind='singleton'), dict(lifecycle=''), dict(slot='')]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.install([self.declaration(**mutation)]); self.check('capability-declaration-invalid', str(mutation))
        self.install(extra='unknown'); self.check('capability-declaration-invalid', 'unknown top field')
        self.install(raw='{"declarations": [], "seams": "none"}'); self.check('capability-declaration-invalid', 'empty array')
        entry=self.declaration(); entry.pop('provider')
        self.install([entry]); self.check('capability-declaration-invalid', 'missing field')

    def test_nonruntime_slot_may_be_empty(self):
        for kind in ['scoped', 'artifact-only']:
            self.install([self.declaration(kind=kind, slot='')]); self.check(label=kind)

    def test_unsupported_seams_explicit(self):
        for seams in [[], {}, 'unknown', None]:
            self.install(seams=seams); self.check('only seams=', str(seams))

    def test_duplicate_keys_and_bad_json(self):
        for raw in ['{"declarations": [], "declarations": [], "seams":"none"}',
                    '{"declarations": [{"key":"a", "key":"b"}], "seams":"none"}',
                    '{not JSON}', '{"declarations": NaN, "seams":"none"}']:
            self.install(raw=raw); self.check('capability-declaration-invalid', raw)
        self.install([self.declaration(), self.declaration()]); self.check('duplicate key', 'duplicate declaration key')

    def test_multiple_and_unclosed_fences(self):
        self.install(); valid=self.index.read_text(encoding='utf-8')
        block=valid[len(self.index_text):]
        self.index.write_text(valid+block, encoding='utf-8'); self.check('capability-declaration-ambiguous', 'two blocks')
        self.index.write_text(valid.rsplit('```',1)[0], encoding='utf-8'); self.check('unclosed fence', 'unclosed block')
        self.index.write_text(valid+'\n```capability-declarations\n{}\n', encoding='utf-8'); self.check('unclosed fence', 'second block unclosed')

    def test_nested_example_is_not_a_declaration(self):
        self.index.write_text(self.index_text+'\n````markdown\n```capability-declarations\n{bad JSON}\n```\n````\n', encoding='utf-8')
        self.assertEqual(self.check(), 'optional block absent')
        self.index_text=self.index.read_text(encoding='utf-8'); self.install(); self.check(label='real block after example')

    def test_tilde_fence(self):
        self.install(); text=self.index.read_text(encoding='utf-8')
        self.index.write_text(text[:len(self.index_text)]+text[len(self.index_text):].replace('```','~~~'), encoding='utf-8'); self.check()

    def test_path_escape_and_noncanonical_paths(self):
        for output in ['../escape.ets', '/absolute.ets', 'C:/escape.ets', 'entry/../Base.ets', 'entry//Base.ets', 'entry/./Base.ets', 'entry/*.ets', 'entry\\Base.ets']:
            self.install([self.declaration(path=output)]); self.check('relative|Unsafe|portable|escape', output)
        for source in ['../base-plan.md', '/base-plan.md', 'spec/baseline/plans/../base-plan.md', 'base-plan.md#extra']:
            self.install([self.declaration(provider=source+'#BASE:Base-1')]); self.check('relative|Unsafe|portable|provider-unknown', source)

    def test_excluded_responsibility_not_provider(self):
        self.items.append({'item_id':'BASE:Base-2','ac_ids':[],'ownership':['entry/Excluded.ets'],'parents':[],'page_ids':[],'scope':'excluded','verification':'generated'})
        self.write_plans(); self.index_text=self.index.read_text(encoding='utf-8')
        self.install([self.declaration(path='entry/Excluded.ets', provider='base-plan.md#BASE:Base-2')]); self.check('capability-provider-unknown')

    def test_bad_responsibility_still_fails(self):
        path=self.base/'plans/base-plan.md'
        text=path.read_text(encoding='utf-8').replace('| ownership | ["entry/Base.ets"] |', '| ownership | ["entry/Different.ets"] |')
        path.write_text(text, encoding='utf-8'); self.install(); self.check('responsibility fields differ')

    def test_missing_detail_still_fails(self):
        self.index_text=self.index_text.replace('detail: plans/base-plan.md','detail: plans/missing.md')
        self.install(); self.check('missing file')

    def test_ambiguous_basename_with_real_projection_units(self):
        # The shipped catalog has disjoint file basenames. Exercise ambiguity
        # separately with two real _projection results, never mocked authority.
        self.install(); self.check(label='real validate_plan baseline')
        path=self.project/'other/slice-01-F001.md'; path.parent.mkdir()
        item=copy.deepcopy(self.items[2]); item.update(item_id='SLICE:F001:3b', ownership=['entry/Other.ets'])
        path.write_text('# Other\n'+self.responsibility(item)+'\n```json\n'+json.dumps({'plan_items_version':2,'items':[item]})+'\n```\n', encoding='utf-8')
        units={item['item_id']:item for source in [self.base/'plans/slices/slice-01-F001.md',path] for item in _projection(self.project, source)}
        self.install([self.declaration(path='entry/CounterService.ets', provider='slice-01-F001.md#SLICE:F001:3c')])
        with self.assertRaisesRegex(MigrationError, 'capability-provider-ambiguous') as caught:
            validate_declarations(self.project,[self.index],units)
        print(json.dumps({'case':self._testMethodName,'expected':'capability-provider-ambiguous','actual':str(caught.exception),'scope':'isolated resolver using real validated projections; catalog integration cannot currently have basename collisions'}))


if __name__ == '__main__':
    unittest.main()


class PlanLocationContractTests(unittest.TestCase):
    # Reuse the same complete valid fixture; do not inherit/re-run the old 19.
    setUp = CapabilityContractTests.setUp
    tearDown = CapabilityContractTests.tearDown
    task = CapabilityContractTests.task
    write_plans = CapabilityContractTests.write_plans
    responsibility = CapabilityContractTests.responsibility
    declaration = CapabilityContractTests.declaration
    install = CapabilityContractTests.install
    check = CapabilityContractTests.check

    def place(self, filename, entries=None, close=True, keep_index=False):
        self.install(entries)
        block = self.index.read_text(encoding='utf-8')[len(self.index_text):]
        if not close:
            block = block.rsplit('```', 1)[0]
        if not keep_index:
            self.index.write_text(self.index_text, encoding='utf-8')
        target = self.base / 'plans' / filename
        target.write_text(target.read_text(encoding='utf-8') + block, encoding='utf-8')

    def test_location_base_legal_declaration(self):
        self.place('base-plan.md')
        self.assertEqual(self.check()['declarations'], 1)

    def test_location_base_unknown_provider(self):
        self.place('base-plan.md', [self.declaration(provider='base-plan.md#BASE:Base-999')])
        self.check('capability-provider-unknown')

    def test_location_base_wrong_owner(self):
        self.place('base-plan.md', [self.declaration(path='entry/CounterService.ets')])
        self.check('capability-provider-owner-mismatch')

    def test_location_indexed_slice_legal_declaration(self):
        self.place('slices/slice-01-F001.md')
        self.assertEqual(self.check()['declarations'], 1)

    def test_location_indexed_slice_bad_declaration(self):
        self.place('slices/slice-01-F001.md', [self.declaration(provider='base-plan.md#BASE:Base-999')])
        self.check('capability-provider-unknown')

    def test_location_index_and_base_duplicate(self):
        self.place('base-plan.md', keep_index=True)
        self.check('capability-declaration-ambiguous')

    def test_location_base_unclosed_fence(self):
        self.place('base-plan.md', close=False)
        self.check('unclosed fence')

    def test_location_no_declaration_compatible(self):
        self.assertEqual(self.check(), 'optional block absent')
