"""Real original detector and native indexed profile regressions."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
WIRING = ROOT / 'skills/arkts-structural-closure/scripts/verify_slice_wiring.py'
LOOP = ROOT / 'skills/arkts-structural-closure/scripts/structural_loop.py'


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def fixture(project, native=True):
    write(project / '.migbot/config.json', json.dumps({'source_platform': 'ios', 'ios_harness': {'spec_contract_version': 2 if native else 1}}))
    write(project / 'build-profile.json5', json.dumps({'app': {'products': [{'name': 'default'}]},
        'modules': [{'name': 'entry', 'srcPath': './entry', 'targets': [{'name': 'default', 'applyToProducts': ['default']}]}]}))
    write(project / 'entry/src/main/module.json5', json.dumps({'module': {'name': 'entry', 'type': 'entry'}}))
    plans = project / 'spec/baseline/plans'
    index = '# Feature Plan\nplan_format: indexed-v1\n## Group 1\n## Slice 1: 领域与解析 (F001)\nparallel_group: 1 | complexity: complex\ndetail: plans/slices/slice-01-F001.md\n'
    write(plans / 'feature-plan.md', index)
    text = '## Slice 1: 领域与解析 (F001)\nparallel_group: 1 | complexity: complex\n\nintegration_points:\n  - ScanPage.rawText → LabelParser.parse\n  - BrewPage.now → BrewSession.remaining\n\nwires: []\n\n'
    items = []
    for step in ['3a','3b','3c','3d']:
        item = {'item_id': 'SLICE:F001:' + step, 'ac_ids': ['F001-AC01'], 'ownership': ['entry/src/main/ets/core/Domain.ets','entry/src/main/ets/model/Models.ets'], 'parents': [], 'page_ids': [], 'scope': 'product', 'verification': 'generated'}
        items.append(item)
        text += '### ' + item['item_id'] + '\n| 字段 | 值 |\n|---|---|\n' + ''.join('| ' + key + ' | ' + json.dumps(value, ensure_ascii=False) + ' |\n' for key,value in item.items())
    text += '\n```json\n' + json.dumps({'plan_items_version':2,'items':items}, ensure_ascii=False) + '\n```\n'
    write(plans / 'slices/slice-01-F001.md', text)
    write(project / 'entry/src/main/ets/core/Domain.ets', "export class LabelParser {\n  static parse(text: string): number { return text.trim().length }\n}\n")
    write(project / 'entry/src/main/ets/model/Models.ets', "export class BrewSession {\n  seconds: number = 100\n  remaining(now: number): number { return Math.max(0, this.seconds - now) }\n}\n")
    write(project / 'entry/src/main/ets/store/BrewStore.ets', "import { BrewSession } from '../model/Models'\nexport class BrewStore {\n  sessions: BrewSession[] = []\n  get pending(): BrewSession | undefined { return this.sessions.find((item: BrewSession): boolean => item.seconds > 0) }\n}\n")
    write(project / 'entry/src/main/ets/Root.ets', "import { BrewStore } from './store/BrewStore'\nexport class Root {\n  static store: BrewStore = new BrewStore()\n}\n")
    write(project / 'entry/src/main/ets/pages/ScanPage.ets', "import { LabelParser } from '../core/Domain'\n@ComponentV2\nstruct ScanPage {\n  @Local rawText: string = ''\n  scan(): number { return LabelParser.parse(this.rawText) }\n  build() { Text(this.rawText) }\n}\n")
    write(project / 'entry/src/main/ets/pages/BrewPage.ets', "import { BrewStore } from '../store/BrewStore'\nimport { Root } from '../Root'\n@ComponentV2\nstruct BrewPage {\n  @Param store: BrewStore = Root.store\n  @Local now: number = 1\n  build() { Text(this.store.pending!.remaining(this.now).toString()) }\n}\n")
    for name in ['state.json','dispatch.json','journal.json']:
        write(project / 'spec/state' / name, '{"frozen": true}\n')


class NativeStructuralTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native structural 测试 ')
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / 'project'
        fixture(self.project)
        self.output = Path(self.temp.name) / 'reports'
        self.output.mkdir()

    def snapshot(self):
        return {p.relative_to(self.project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.project.rglob('*') if p.is_file()}

    def run_cli(self, script, args, name):
        report = self.output / (name + '.json')
        result = subprocess.run([sys.executable, '-X', 'utf8', str(script), *map(str,args), '--output-json', str(report)], cwd=ROOT, capture_output=True, encoding='utf-8', timeout=60)
        return result, json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}

    def wiring(self, name='wiring'):
        return self.run_cli(WIRING, ['--slice',1,'--project-root',self.project], name)

    def update_items(self, transform):
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md'
        text=plan.read_text(encoding='utf-8')
        items=json.loads(re.search(r'```json\n(.*?)\n```',text,re.S)[1])['items']
        for item in items: transform(item)
        prefix=text[:text.index('### SLICE:')]
        body=''.join('\n### '+item['item_id']+'\n| 字段 | 值 |\n|---|---|\n'+''.join(
            '| '+key+' | '+json.dumps(value,ensure_ascii=False)+' |\n' for key,value in item.items()) for item in items)
        plan.write_text(prefix+body+'\n```json\n'+json.dumps({'plan_items_version':2,'items':items},ensure_ascii=False)+'\n```\n',encoding='utf-8')

    def point(self, description):
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md'
        text=plan.read_text(encoding='utf-8')
        plan.write_text(text.replace('ScanPage.rawText → LabelParser.parse',description),encoding='utf-8')

    def base_owner(self, path, parents=None):
        item={'item_id':'BASE:Base-6.5','ac_ids':[],'ownership':[path],'parents':parents or [],'page_ids':[],
              'scope':'product','verification':'generated'}
        text='# Base Plan\n\n### '+item['item_id']+'\n| 字段 | 值 |\n|---|---|\n'+''.join(
            '| '+key+' | '+json.dumps(value)+' |\n' for key,value in item.items())+'\n```json\n'+json.dumps({'plan_items_version':2,'items':[item]})+'\n```\n'
        write(self.project/'spec/baseline/plans/base-plan.md',text)
        index=self.project/'spec/baseline/plans/feature-plan.md'
        index.write_text(index.read_text(encoding='utf-8').replace('## Group 1','## Base\ndetail: plans/base-plan.md\n\n## Group 1'),encoding='utf-8')

    def shared_binding(self):
        domain=self.project/'entry/src/main/ets/core/Domain.ets'
        domain.write_text(domain.read_text(encoding='utf-8')+'\nexport class Reader {\n read(text: string): number { return text.trim().length }\n}\n',encoding='utf-8')
        write(self.project/'entry/src/main/ets/AppAssembly.ets',"import { Reader } from './core/Domain'\nexport interface CapabilityTable {\n reader: Reader\n}\nexport let capabilityTable: CapabilityTable\nexport function install(): void { capabilityTable = { reader: new Reader() } }\n")
        write(self.project/'entry/src/main/ets/pages/ScanPage.ets',"import { capabilityTable, install } from '../AppAssembly'\nstruct ScanPage {\n rawText: string = ''\n aboutToAppear(): void { install() }\n scan(): number { return capabilityTable.reader.read(this.rawText) }\n build() { Text(this.scan().toString()) }\n}\n")
        self.point('ScanPage.scan → Reader.read')

    def test_explicit_parent_owner_authorizes_exact_dependency_target(self):
        shared='entry/src/main/ets/core/Shared.ets'
        write(self.project/shared,'export class Shared {\n static parse(text: string): number { return text.length + 1 }\n}\n')
        self.base_owner(shared)
        self.update_items(lambda item:item.update(parents=['BASE:Base-6.5']))
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        page.write_text(page.read_text(encoding='utf-8').replace('LabelParser','Shared').replace('../core/Domain','../core/Shared'),encoding='utf-8')
        self.point('ScanPage.rawText → Shared.parse')
        result,report=self.wiring('dependency-owner')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(shared,report['scope']['allowed_target_files'])
        self.assertNotIn(shared,report['scope']['owned_files'])

    def test_exact_scalar_copy_and_same_component_field_write(self):
        store=self.project/'entry/src/main/ets/store/BrewStore.ets'
        store.write_text(store.read_text(encoding='utf-8').replace('  sessions:','  message: string | undefined = undefined\n  sessions:'),encoding='utf-8')
        self.update_items(lambda item:item['ownership'].extend(['entry/src/main/ets/store/BrewStore.ets','entry/src/main/ets/pages/ScanPage.ets']))
        write(self.project/'entry/src/main/ets/pages/ScanPage.ets',"import { BrewStore } from '../store/BrewStore'\nimport { Root } from '../Root'\nstruct ScanPage {\n store: BrewStore = Root.store\n error: string | undefined = undefined\n rawText: string = ''\n save(): void { this.error = this.store.message }\n setSearch(value: string): void { this.rawText = value }\n build() { Text(this.rawText) }\n}\n")
        self.point('ScanPage.error ← BrewStore.message')
        result,report=self.wiring('scalar-copy')
        self.assertEqual(result.returncode,0,result.stderr)
        self.point('ScanPage.setSearch → ScanPage.rawText')
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md'
        plan.write_text(plan.read_text(encoding='utf-8').replace('ScanPage.error ← BrewStore.message','ScanPage.setSearch → ScanPage.rawText'),encoding='utf-8')
        result,report=self.wiring('same-component-write')
        self.assertEqual(result.returncode,0,result.stderr)

    def test_typed_shared_capability_receiver_and_live_binding(self):
        self.shared_binding()
        result,report=self.wiring('shared-capability')
        self.assertEqual(result.returncode,0,result.stderr)
        self.cross_plan('capabilityTable','entry/src/main/ets/AppAssembly.ets')
        result,report=self.wiring('shared-binding-cross')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(report['categories']['C3_cross_slice']['pass'],1)
        self.assertEqual(report['normalized_original_C3_cross_slice']['fail'],1)

    def test_same_class_getter_and_explicit_one_hop_calls(self):
        self.update_items(lambda item:item['ownership'].append('entry/src/main/ets/pages/ScanPage.ets'))
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        write(page,"import { LabelParser } from '../core/Domain'\nstruct ScanPage {\n rawText: string = ''\n get count(): number { return this.compute(this.rawText) }\n compute(text: string): number { return text.length }\n scan(): number { return this.forward(this.rawText) }\n forward(text: string): number { return LabelParser.parse(text) }\n build() { Text(this.count.toString()) }\n}\n")
        self.point('ScanPage.count → ScanPage.compute')
        result,report=self.wiring('same-class-getter')
        self.assertEqual(result.returncode,0,result.stderr)
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md'
        plan.write_text(plan.read_text(encoding='utf-8').replace('ScanPage.count → ScanPage.compute','ScanPage.scan → LabelParser.parse'),encoding='utf-8')
        result,report=self.wiring('one-hop-static')
        self.assertEqual(result.returncode,0,result.stderr)

    def test_typed_self_provider_return_and_local_alias(self):
        self.shared_binding()
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        code="import { Reader } from '../core/Domain'\nstruct ScanPage {\n rawText: string = ''\n private snapshots: Reader | undefined = undefined\n private service(): Reader { if (this.snapshots === undefined) { this.snapshots = new Reader() }; return this.snapshots; }\n scan(): number { const snapshots = this.service(); return snapshots.read(this.rawText) }\n build() { Text(this.scan().toString()) }\n}\n"
        for name,source,expected in [('local-provider',code,0),
             ('direct-provider',code.replace('const snapshots = this.service(); return snapshots.read','return this.service().read'),0),
             ('wrong-return-type',code.replace('service(): Reader','service(): OtherReader'),1),
             ('wrong-initializer',code.replace('new Reader()','new OtherReader()'),1),
             ('wrong-alias',code.replace('snapshots.read(this.rawText)','other.read(this.rawText)'),1),
             ('dead-provider-use',code.replace('return snapshots.read(this.rawText)','const unused = (): number => snapshots.read(this.rawText); return 0'),1)]:
            with self.subTest(name=name):
                write(page,source)
                result,report=self.wiring(name)
                self.assertEqual(result.returncode,expected,result.stderr)
    def test_dependency_authority_rejects_missing_cycle_and_unreferenced_owner(self):
        shared='entry/src/main/ets/core/Shared.ets'
        write(self.project/shared,'export class Shared { static parse(text: string): number { return text.length + 1 } }\n')
        self.base_owner(shared)
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        page.write_text(page.read_text(encoding='utf-8').replace('LabelParser','Shared').replace('../core/Domain','../core/Shared'),encoding='utf-8')
        self.point('ScanPage.rawText → Shared.parse')
        result,report=self.wiring('unreferenced-owner')
        self.assertEqual(result.returncode,1,result.stderr)
        self.update_items(lambda item:item.update(parents=['BASE:Missing']))
        result,report=self.wiring('missing-authority-parent')
        self.assertEqual(result.returncode,3,result.stderr)
        self.update_items(lambda item:item.update(parents=['BASE:Base-6.5']))
        base=self.project/'spec/baseline/plans/base-plan.md'
        text=base.read_text(encoding='utf-8').replace('"parents": []','"parents": ["SLICE:F001:3a"]').replace('| parents | [] |','| parents | ["SLICE:F001:3a"] |')
        base.write_text(text,encoding='utf-8')
        result,report=self.wiring('authority-cycle')
        self.assertEqual(result.returncode,3,result.stderr)

    def test_explicit_contract_owner_allows_only_declared_target_file(self):
        shared='entry/src/main/ets/core/Shared.ets'
        write(self.project/shared,'export class Shared { static parse(text: string): number { return text.length + 1 } }\n')
        self.base_owner(shared)
        write(self.project/'spec/ref/shared.md','# Shared\n## Public\n| item_id | 目标文件 |\n|---|---|\n| BASE:Base-6.5 | '+shared+' |\n')
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md'
        plan.write_text(plan.read_text(encoding='utf-8').replace('parallel_group: 1 | complexity: complex',
            'parallel_group: 1 | complexity: complex\ncontract_refs: ["spec/ref/shared.md#Public"]'),encoding='utf-8')
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        page.write_text(page.read_text(encoding='utf-8').replace('LabelParser','Shared').replace('../core/Domain','../core/Shared'),encoding='utf-8')
        self.point('ScanPage.rawText → Shared.parse')
        result,report=self.wiring('explicit-public-contract')
        self.assertEqual(result.returncode,0,result.stderr)
        write(self.project/'spec/ref/shared.md','# Shared\n## Public\nOther text mentions '+shared+' without owner authority.\n')
        result,report=self.wiring('mere-prose-not-owner-authority')
        self.assertEqual(result.returncode,1,result.stderr)

    def test_shared_receiver_wrong_producer_binding_and_handler_fail(self):
        self.shared_binding()
        assembly=self.project/'entry/src/main/ets/AppAssembly.ets'
        code=assembly.read_text(encoding='utf-8')
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        caller=page.read_text(encoding='utf-8')
        variants=[('wrong-initializer',code.replace('new Reader()','new WrongReader()'),caller),
            ('dead-producer',code.replace('capabilityTable = {','const unused = {'),caller),
            ('uninvoked-producer',code,caller.replace('install()','void 0')),
            ('wrong-interface-type',code.replace('reader: Reader','reader: WrongReader'),caller),
            ('wrong-slot',code,caller.replace('capabilityTable.reader.read','capabilityTable.other.read')),
            ('wrong-handler',code,caller.replace('scan(): number { return capabilityTable.reader.read(this.rawText) }',
                'scan(): number { return 0 }\n unused(): number { return capabilityTable.reader.read(this.rawText) }')),
            ('shadowed-binding',code,caller.replace('scan(): number','scan(capabilityTable: WrongTable): number')),
            ('comment-call',code,caller.replace('capabilityTable.reader.read(this.rawText)','0 /* capabilityTable.reader.read(this.rawText) */'))]
        for name,provider,consumer in variants:
            with self.subTest(name=name):
                assembly.write_text(provider,encoding='utf-8');page.write_text(consumer,encoding='utf-8')
                result,report=self.wiring(name)
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertEqual(report['categories']['C2_integration_point']['details'][0]['status'],'FAIL')

    def test_live_cross_binding_needs_real_producer_and_consumer(self):
        self.shared_binding()
        self.cross_plan('capabilityTable','entry/src/main/ets/AppAssembly.ets')
        assembly=self.project/'entry/src/main/ets/AppAssembly.ets';provider=assembly.read_text(encoding='utf-8')
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets';consumer=page.read_text(encoding='utf-8')
        for name,code,caller in [('wrong-binding-initializer',provider.replace('new Reader()','new WrongReader()'),consumer),
             ('dead-binding',provider,consumer.replace('capabilityTable.reader.read(this.rawText)','0')),
             ('unused-local-binding-consumer',provider,consumer.replace('return capabilityTable.reader.read(this.rawText)',
                 'const unused = (): number => capabilityTable.reader.read(this.rawText); return 0')),
             ('uninvoked-binding-producer',provider,consumer.replace('install()','void 0')),
             ('comment-binding',provider.replace('export let capabilityTable: CapabilityTable','// export let capabilityTable: CapabilityTable'),consumer),
             ('unassigned-binding',provider.replace('capabilityTable = {','const unused = {'),consumer)]:
            with self.subTest(name=name):
                assembly.write_text(code,encoding='utf-8');page.write_text(caller,encoding='utf-8')
                result,report=self.wiring(name)
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertEqual(report['categories']['C3_cross_slice']['fail'],1)

    def test_unused_local_function_cannot_supply_handler_or_self_call_proof(self):
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        self.point('ScanPage.scan → LabelParser.parse')
        for declaration in ['const unused = (): number => { return LabelParser.parse(this.rawText) }',
                            'const unused: () => number = (): number => LabelParser.parse(this.rawText)',
                            'const unused = function(): number { return LabelParser.parse(this.rawText) }']:
            with self.subTest(declaration=declaration):
                write(page,"import { LabelParser } from '../core/Domain'\nstruct ScanPage {\n rawText: string = ''\n scan(): number { "+declaration+"; return 0 }\n build() { Text(this.rawText) }\n}\n")
                result,report=self.wiring('unused-local-callable')
                self.assertEqual(result.returncode,1,result.stderr)

    def test_scalar_copy_and_self_call_wrong_binding_remain_failures(self):
        self.update_items(lambda item:item['ownership'].extend(['entry/src/main/ets/store/BrewStore.ets','entry/src/main/ets/pages/ScanPage.ets']))
        store=self.project/'entry/src/main/ets/store/BrewStore.ets'
        store.write_text(store.read_text(encoding='utf-8').replace('  sessions:','  message: string | undefined = undefined\n  sessions:'),encoding='utf-8')
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        code="import { BrewStore } from '../store/BrewStore'\nimport { Root } from '../Root'\nstruct ScanPage {\n store: BrewStore = Root.store\n error: string | undefined = undefined\n otherError: string | undefined = undefined\n rawText: string = ''\n save(): void { this.error = this.store.message }\n unused(): void { }\n build() { Text(this.rawText) }\n}\n"
        self.point('ScanPage.error ← BrewStore.message')
        for replacement in ['this.otherError = this.store.message','this.error = this.store.otherMessage',
                            "this.error = this.store.message\n + 'suffix'",
                            'this.error = undefined /* this.error = this.store.message */']:
            page.write_text(code.replace('this.error = this.store.message',replacement),encoding='utf-8')
            result,report=self.wiring('wrong-scalar-binding')
            self.assertEqual(result.returncode,1,result.stderr)
        page.write_text(code.replace('save(): void { this.error = this.store.message }',
            'save(): void { }\n helper(): void { this.error = this.store.message }'),encoding='utf-8')
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md'
        plan.write_text(plan.read_text(encoding='utf-8').replace('ScanPage.error ← BrewStore.message','ScanPage.save → BrewStore.message'),encoding='utf-8')
        result,report=self.wiring('unused-helper-does-not-count')
        self.assertEqual(result.returncode,1,result.stderr)

    def test_native_static_and_returned_instance_are_real_connections(self):
        before = self.snapshot()
        result, report = self.wiring()
        self.assertEqual(result.returncode, 0, result.stderr + json.dumps(report,ensure_ascii=False))
        self.assertEqual(report['feature_id'], 'F001')
        self.assertEqual(len(report['scope']['owned_files']), 2)
        self.assertEqual(report['scope']['modifies_files'], [])
        self.assertTrue(all(detail['evidence'] for detail in report['categories']['C2_integration_point']['details']))
        self.assertEqual(self.snapshot(), before)

    def test_legacy_static_instantiation_rule_is_unchanged(self):
        fixture(self.project, native=False)
        result, report = self.wiring()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report['categories']['C2_integration_point']['fail'], 2)
        self.assertNotIn('owned_files', report['scope'])

    def test_group_feeds_nonempty_real_original_audit_and_loop_protocol(self):
        before = self.snapshot()
        state = self.output / 'loop-state.json'
        result, report = self.run_cli(LOOP, ['iterate','--project-root',self.project,'--mode','group','--target',1,'--slices',1,'--state-file',state,'--max-iter',8], 'loop')
        self.assertEqual(result.returncode, 0, result.stderr + json.dumps(report,ensure_ascii=False))
        audit = json.loads(Path(report['detector_json_paths']['audit']).read_text(encoding='utf-8'))
        self.assertEqual(len(audit['scope_files']), 2)
        self.assertEqual(json.loads(state.read_text())['history'][-1]['detectors_run'], ['audit','wiring'])
        self.assertEqual(self.snapshot(), before)

    def test_negative_calls_fail_even_when_names_imports_and_dead_instance_exist(self):
        path = self.project / 'entry/src/main/ets/pages/ScanPage.ets'
        original = path.read_text(encoding='utf-8')
        for replacement in ['0', '0 /* LabelParser.parse(this.rawText) */', '\"LabelParser.parse(this.rawText)\".length', 'new LabelParser() && 0']:
            with self.subTest(replacement=replacement):
                path.write_text(original.replace('LabelParser.parse(this.rawText)',replacement),encoding='utf-8')
                result, report = self.wiring('negative')
                self.assertEqual(result.returncode, 1)
                details = report['categories']['C2_integration_point']['details']
                self.assertEqual(details[0]['status'], 'FAIL')
        path.write_text(original, encoding='utf-8')

    def test_wrong_provider_type_and_foreign_or_missing_scope_are_errors(self):
        provider = self.project / 'entry/src/main/ets/store/BrewStore.ets'
        provider.write_text(provider.read_text(encoding='utf-8').replace('get pending(): BrewSession | undefined','get pending(): OtherSession | undefined'),encoding='utf-8')
        result, report = self.wiring('wrong-type')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report['categories']['C2_integration_point']['details'][1]['status'], 'FAIL')
        plan = self.project / 'spec/baseline/plans/slices/slice-01-F001.md'
        original = plan.read_text(encoding='utf-8')
        for path in ['../escape.ets','entry/src/main/ets/Missing.ets']:
            plan.write_text(original.replace('entry/src/main/ets/core/Domain.ets',path),encoding='utf-8')
            result, _ = self.wiring('bad-scope')
            self.assertEqual(result.returncode, 3, result.stderr)

    def test_original_c1_c3_c4_findings_are_preserved(self):
        vm = 'entry/src/main/ets/viewmodels/DetachedViewModel.ets'
        write(self.project / vm, 'export class DetachedViewModel {\n  value: number = 1\n  change(): void { this.value += 2 }\n}\n')
        plan = self.project / 'spec/baseline/plans/slices/slice-01-F001.md'
        original = plan.read_text(encoding='utf-8')
        plan.write_text(original.replace('wires: []',
            'wires:\n  - page: entry/src/main/ets/pages/ScanPage.ets\n    viewmodel: '+vm+
            '\n  - page: entry/src/main/ets/pages/ScanPage.ets\n    slot: missingBuilder\n    embed: ChildPage()\n    resolve_by: Slice 1 Step 3a\n\nmodifies_files:\n  - entry/src/main/ets/pages/ScanPage.ets\n  cross_slice_edits:\n    - file: entry/src/main/ets/pages/ScanPage.ets\n      handler: missingHandler\n      resolve_by: Slice 1 Step 3d'), encoding='utf-8')
        native_result, native = self.wiring('preserved-native')
        original_result, upstream = self.run_cli(ROOT / 'vendor/hmigbot/skills/arkts-structural-closure/scripts/verify_slice_wiring.py',
            ['--project-root',self.project,'--slice',1], 'preserved-original')
        self.assertEqual(native_result.returncode, 1)
        self.assertEqual(original_result.returncode, 1)
        for category in ['C1_orphan_check','C3_cross_slice','C4_parent_replacement']:
            self.assertEqual(native['categories'][category], upstream['categories'][category])
            self.assertGreater(native['categories'][category]['fail'], 0, category)

    def test_red_green_history_and_original_finalize_protocol(self):
        page = self.project / 'entry/src/main/ets/pages/ScanPage.ets'
        original = page.read_text(encoding='utf-8')
        state = self.output / 'red-green-state.json'
        args = ['iterate','--project-root',self.project,'--mode','group','--target',1,'--slices',1,'--state-file',state,'--max-iter',8]
        page.write_text(original.replace('LabelParser.parse(this.rawText)','0'),encoding='utf-8')
        result, red = self.run_cli(LOOP,args,'red')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(red['verdict'],'CONTINUE')
        page.write_text(original,encoding='utf-8')
        before = self.snapshot()
        result, green = self.run_cli(LOOP,args,'green')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(green['verdict'],'CONVERGED')
        result, finalized = self.run_cli(LOOP,['finalize','--state-file',state],'finalized')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(finalized['final_state'],'PASS')
        self.assertTrue(finalized['converged'])
        self.assertEqual(len(finalized['history']),2)
        self.assertEqual(finalized['history'][0]['wiring_repair_actions'],1)
        self.assertEqual(finalized['history'][1]['wiring_repair_actions'],0)
        self.assertEqual(self.snapshot(),before)

    def test_empty_projection_group_mismatch_and_wrong_import_fail_closed(self):
        plan = self.project / 'spec/baseline/plans/slices/slice-01-F001.md'
        original = plan.read_text(encoding='utf-8')
        for invalid in [original.replace('parallel_group: 1','parallel_group: 2'),
                        original[:original.index('### SLICE:')]+'```json\n{"plan_items_version":2,"items":[]}\n```\n']:
            plan.write_text(invalid,encoding='utf-8')
            result, report = self.wiring('invalid-plan')
            self.assertEqual(result.returncode,3,result.stderr)
            self.assertNotEqual(report.get('overall'),'PASS')
        plan.write_text(original,encoding='utf-8')
        wrong = self.project / 'entry/src/main/ets/core/WrongDomain.ets'
        write(wrong,'export class LabelParser { static parse(text: string): number { return text.length + 1 } }\n')
        page = self.project / 'entry/src/main/ets/pages/ScanPage.ets'
        page.write_text(page.read_text(encoding='utf-8').replace("../core/Domain","../core/WrongDomain"),encoding='utf-8')
        result, report = self.wiring('wrong-import')
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertEqual(report['categories']['C2_integration_point']['details'][0]['status'],'FAIL')

    def test_native_typed_parameter_and_explicit_forwarding_need_the_actual_call(self):
        plan = self.project / 'spec/baseline/plans/slices/slice-01-F001.md'
        plan.write_text(plan.read_text(encoding='utf-8').replace('ScanPage.rawText → LabelParser.parse',
            'ScanPage.session → BrewSession.remaining').replace('BrewPage.now → BrewSession.remaining',
            'BrewStore.use → BrewSession.remaining'),encoding='utf-8')
        page = self.project / 'entry/src/main/ets/pages/ScanPage.ets'
        write(page,"import { BrewStore } from '../store/BrewStore'\nimport { BrewSession } from '../model/Models'\nimport { Root } from '../Root'\n@ComponentV2\nstruct ScanPage {\n @Param store: BrewStore = Root.store\n @Local session: BrewSession = new BrewSession()\n run(): number { return this.store.use(this.session) }\n build() { Text(this.run().toString()) }\n}\n")
        store = self.project / 'entry/src/main/ets/store/BrewStore.ets'
        original = store.read_text(encoding='utf-8').replace('  sessions:',
            '  use(session: BrewSession): number { return session.remaining(4) }\n  sessions:')
        store.write_text(original,encoding='utf-8')
        result, report = self.wiring('forwarded-parameter')
        self.assertEqual(result.returncode,0,result.stderr+json.dumps(report))
        self.assertTrue(all(any(e['role']=='typed-parameter' for e in d['evidence'])
            for d in report['categories']['C2_integration_point']['details']))
        store.write_text(original.replace('session.remaining(4)','0 /* session.remaining(4) */'),encoding='utf-8')
        result, report = self.wiring('missing-parameter-call')
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertEqual(report['categories']['C2_integration_point']['fail'],2)

    def test_unrelated_method_or_input_is_not_handler_evidence(self):
        plan = self.project / 'spec/baseline/plans/slices/slice-01-F001.md'
        plan_original = plan.read_text(encoding='utf-8')
        page = self.project / 'entry/src/main/ets/pages/ScanPage.ets'
        original = page.read_text(encoding='utf-8')
        plan.write_text(plan_original.replace('ScanPage.rawText →','ScanPage.scan →'),encoding='utf-8')
        page.write_text(original.replace('scan(): number { return LabelParser.parse(this.rawText) }',
            'scan(): number { return 0 }\n  unused(): number { return LabelParser.parse(this.rawText) }'),encoding='utf-8')
        result, report = self.wiring('unrelated-handler')
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertEqual(report['categories']['C2_integration_point']['details'][0]['status'],'FAIL')
        plan.write_text(plan_original,encoding='utf-8')
        page.write_text(original.replace('LabelParser.parse(this.rawText)',"LabelParser.parse('unrelated input')"),encoding='utf-8')
        result, report = self.wiring('unrelated-input')
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertEqual(report['categories']['C2_integration_point']['details'][0]['status'],'FAIL')

    def test_shadowed_typed_parameter_does_not_prove_target_call(self):
        plan = self.project / 'spec/baseline/plans/slices/slice-01-F001.md'
        plan.write_text(plan.read_text(encoding='utf-8').replace('BrewPage.now → BrewSession.remaining',
            'BrewStore.use → BrewSession.remaining'),encoding='utf-8')
        store = self.project / 'entry/src/main/ets/store/BrewStore.ets'
        original = store.read_text(encoding='utf-8').replace('  sessions:',
            '  use(session: BrewSession): number {\n    const fake = (session: OtherSession): number => session.remaining(4)\n    return fake(new OtherSession())\n  }\n  sessions:')
        store.write_text(original,encoding='utf-8')
        result, report = self.wiring('shadowed-parameter')
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertEqual(report['categories']['C2_integration_point']['details'][1]['status'],'FAIL')

    def test_local_same_named_class_receiver_and_wrong_return_expression_fail(self):
        page = self.project / 'entry/src/main/ets/pages/ScanPage.ets'
        original = page.read_text(encoding='utf-8')
        page.write_text(original.replace('scan(): number { return',
            'scan(): number { const LabelParser: OtherParser = new OtherParser(); return'),encoding='utf-8')
        result, report = self.wiring('shadowed-static')
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertEqual(report['categories']['C2_integration_point']['details'][0]['status'],'FAIL')
        page.write_text(original,encoding='utf-8')
        store = self.project / 'entry/src/main/ets/store/BrewStore.ets'
        store.write_text(store.read_text(encoding='utf-8').replace('item.seconds > 0) }',
            'item.seconds > 0)!.remaining(1) }'),encoding='utf-8')
        result, report = self.wiring('wrong-provider-expression')
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertEqual(report['categories']['C2_integration_point']['details'][1]['status'],'FAIL')

    def test_maximum_argument_and_default_match_original_runner_protocol(self):
        page = self.project / 'entry/src/main/ets/pages/ScanPage.ets'
        page.write_text(page.read_text(encoding='utf-8').replace('LabelParser.parse(this.rawText)','0'),encoding='utf-8')
        state = self.output / 'caps-state.json'
        args = ['iterate','--project-root',self.project,'--mode','group','--target',1,'--slices',1,'--state-file',state]
        first, report = self.run_cli(LOOP,args+['--max-iter',2],'caps-first')
        self.assertEqual(first.returncode,1,first.stderr)
        self.assertEqual(json.loads(state.read_text())['max_iter'],2)
        second, report = self.run_cli(LOOP,args,'caps-default')
        self.assertEqual(second.returncode,2,second.stderr)
        self.assertEqual(report['verdict'],'STALLED')
        self.assertEqual(json.loads(state.read_text())['max_iter'],8)

    def test_product_configuration_ownership_is_kept_separate_from_ets_audit(self):
        configuration='entry/src/main/module.json5'
        write(self.project/configuration,'{"module":{"name":"entry","type":"entry"}}\n')
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md'
        plan.write_text(plan.read_text(encoding='utf-8').replace('"entry/src/main/ets/model/Models.ets"',
            '"entry/src/main/ets/model/Models.ets", "'+configuration+'"'),encoding='utf-8')
        before=self.snapshot()
        result,report=self.wiring('configuration-ownership')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(configuration,report['scope']['owned_files'])
        self.assertEqual(len(report['scope']['owned_files']),3)
        self.assertEqual(len(report['scope']['audit_scope']),2)
        self.assertNotIn(configuration,report['scope']['audit_scope'])
        self.assertEqual(report['scope']['modifies_files'],[])
        state=self.output/'configuration-state.json'
        result,report=self.run_cli(LOOP,['iterate','--project-root',self.project,'--mode','group','--target',1,'--slices',1,'--state-file',state],'configuration-loop')
        self.assertEqual(result.returncode,0,result.stderr)
        audit=json.loads(Path(report['detector_json_paths']['audit']).read_text(encoding='utf-8'))
        self.assertEqual(len(audit['scope_files']),2)
        self.assertEqual(self.snapshot(),before)
        (self.project/configuration).unlink()
        result,report=self.wiring('configuration-missing')
        self.assertEqual(result.returncode,3,result.stderr)
        self.assertEqual(report['overall'],'BLOCKED')

    def test_configured_module_source_root_ignores_history_and_test_classes(self):
        module=self.project/'packages/coffee'
        module.parent.mkdir()
        shutil.move(str(self.project/'entry'),str(module))
        write(self.project/'build-profile.json5', json.dumps({'app': {'products': [{'name': 'default'}]},
            'modules': [{'name': 'coffee', 'srcPath': './packages/coffee', 'targets': [{'name': 'default'}]}]}))
        write(module/'src/main/module.json5', '{"module":{"name":"coffee","type":"entry"}}\n')
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md'
        plan.write_text(plan.read_text(encoding='utf-8').replace('entry/src/main/','packages/coffee/src/main/'),encoding='utf-8')
        historical='export class ScanPage { rawText: string = "history"; scan(): number { return 0 } }\n'
        for relative in ['spec/state/fence-snapshot/ScanPage.ets','tests/ScanPage.ets',
            'packages/coffee/src/test/ets/ScanPage.ets','packages/coffee/src/ohosTest/ets/ScanPage.ets',
            'packages/coffee/build/cache/ScanPage.ets']:
            write(self.project/relative,historical)
        before=self.snapshot()
        result,report=self.wiring('configured-source-root')
        self.assertEqual(result.returncode,0,result.stderr+json.dumps(report))
        self.assertTrue(all(d['caller'].startswith('packages/coffee/src/main/ets/')
            for d in report['categories']['C2_integration_point']['details']))
        self.assertEqual(self.snapshot(),before)
        page=module/'src/main/ets/pages/ScanPage.ets'
        page.write_text(page.read_text(encoding='utf-8').replace('LabelParser.parse(this.rawText)','0'),encoding='utf-8')
        for relative in ['spec/state/fence-snapshot/ScanPage.ets','tests/ScanPage.ets',
            'packages/coffee/src/test/ets/ScanPage.ets','packages/coffee/src/ohosTest/ets/ScanPage.ets']:
            write(self.project/relative,"import { LabelParser } from '../core/Domain'\nstruct ScanPage {\n rawText: string = ''\n scan(): number { return LabelParser.parse(this.rawText) }\n}\n")
        result,report=self.wiring('history-cannot-supply-missing-call')
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertEqual(report['categories']['C2_integration_point']['details'][0]['status'],'FAIL')

    def test_missing_or_foreign_module_config_does_not_widen_source_index(self):
        profile=self.project/'build-profile.json5'
        profile.unlink()
        result,report=self.wiring('missing-build-profile')
        self.assertEqual(result.returncode,3,result.stderr)
        self.assertEqual(report['overall'],'BLOCKED')
        write(profile,'{"modules":[{"name":"outside","srcPath":"../outside"}]}\n')
        result,report=self.wiring('foreign-source-module')
        self.assertEqual(result.returncode,3,result.stderr)
        self.assertEqual(report['overall'],'BLOCKED')

    def cross_plan(self, handler='scan', file='entry/src/main/ets/pages/ScanPage.ets', extra=''):
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md'
        original=plan.read_text(encoding='utf-8')
        plan.write_text(original+'\nmodifies_files:\n  - entry/src/main/ets/pages/ScanPage.ets\n\ncross_slice_edits:\n  - file: '+file+'\n    handler: '+handler+'\n    resolve_by: Slice 1 Step 3d\n'+extra,encoding='utf-8')
        return plan,original

    def test_top_level_cross_reaches_original_c3_without_plan_mutation(self):
        self.cross_plan()
        before=self.snapshot()
        result,report=self.wiring('top-cross-real')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(report['categories']['C3_cross_slice']['pass'],1)
        self.assertEqual(report['original_C3_cross_slice']['pass'],0)
        self.assertEqual(report['normalized_original_C3_cross_slice']['pass'],1)
        self.assertEqual(report['native_cross_projection']['authored_count'],1)
        self.assertEqual(len(report['native_cross_projection']['field_mapping']),1)
        self.assertEqual(self.snapshot(),before)

    def test_missing_comment_and_string_cross_handlers_fail(self):
        plan,original=self.cross_plan('missingHandler')
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        code=page.read_text(encoding='utf-8')
        for fake in ['', '\n// missingHandler(): void { }\n', '\nconst fake = "missingHandler(): void { }"\n']:
            with self.subTest(fake=fake):
                page.write_text(code+fake,encoding='utf-8')
                result,report=self.wiring('top-cross-fake')
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertEqual(report['categories']['C3_cross_slice']['fail'],1)

    def test_cross_normalization_accepts_bom_and_keeps_original_crlf_bytes(self):
        plan,_=self.cross_plan()
        content=plan.read_text(encoding='utf-8').replace('\r\n','\n').replace('\n','\r\n')
        original=b'\xef\xbb\xbf'+content.encode('utf-8')
        plan.write_bytes(original)
        result,report=self.wiring('top-cross-bom-crlf')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(report['native_cross_projection']['original_sha256'],hashlib.sha256(original).hexdigest())
        self.assertEqual(plan.read_bytes(),original)

    def test_foreign_unknown_or_duplicate_cross_declarations_are_errors(self):
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md'
        original=plan.read_text(encoding='utf-8')
        for file,extra in [('../outside.ets',''),('entry/src/main/ets/pages/ScanPage.ets','    unknown: drop-me\n'),
            ('entry/src/main/ets/pages/ScanPage.ets','cross_slice_edits: []\n')]:
            with self.subTest(file=file,extra=extra):
                plan.write_text(original,encoding='utf-8')
                self.cross_plan(file=file,extra=extra)
                result,report=self.wiring('top-cross-invalid')
                self.assertEqual(result.returncode,3,result.stderr)
                self.assertEqual(report['overall'],'BLOCKED')


if __name__ == '__main__':
    unittest.main()
