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

    def declarative_feedback_fixture(self):
        paths={'preview':'entry/src/main/ets/components/PreviewChild.ets',
               'scanner':'entry/src/main/ets/pages/ScannerChild.ets',
               'parent':'entry/src/main/ets/pages/ScanPage.ets'}
        sources={
          'preview':"@ComponentV2\nexport struct PreviewChild {\n @Param input: string = ''\n @Event onText: (text: string) => void = (_text: string) => {}\n @Event onFailure: (message: string) => void = (_message: string) => {}\n emit(text: string): void { this.onText(text); }\n fail(message: string): void { this.onFailure(message); }\n build(): void { Column() { Button('text').onClick(() => { this.emit(this.input); }); Button('failure').onClick(() => { this.fail(this.input); }); } }\n}\n",
          'scanner':"import { PreviewChild } from '../components/PreviewChild'\n@ComponentV2\nexport struct ScannerChild {\n @Param text: string = ''\n @Param failure: string | undefined = undefined\n @Event onText: (text: string) => void = (_text: string) => {}\n @Event onFailure: (message: string) => void = (_message: string) => {}\n build(): void { Column() { PreviewChild({ onText: (text: string) => { this.onText(text); }, onFailure: (message: string) => { this.onFailure(message); } }); Text(this.text); } }\n}\n",
          'parent':"import { ScannerChild } from './ScannerChild'\n@ComponentV2\nstruct ScanPage {\n @Local scanningText: string = ''\n @Local otherText: string = ''\n @Local cameraFailure: string | undefined = undefined\n @Local camera: boolean = false\n @Builder liveContent(): void { ScannerChild({ text: this.scanningText, failure: this.cameraFailure, onText: (text: string) => { this.scanningText = text; }, onFailure: (message: string) => { this.cameraFailure = message; } }); }\n build(): void { Column() { Text(this.scanningText); }.bindContentCover($$this.camera, this.liveContent()); }\n}\n"}
        for name,path in paths.items(): write(self.project/path,sources[name])
        self.update_items(lambda item:item['ownership'].extend(paths.values()))
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md'
        plan.write_text(plan.read_text(encoding='utf-8').replace('  - ScanPage.rawText → LabelParser.parse',
            '  - PreviewChild.onText → ScannerChild.text\n  - PreviewChild.onFailure → ScannerChild.failure\n  - ScannerChild.text → ScanPage.scanningText\n  - ScannerChild.failure → ScanPage.cameraFailure'),encoding='utf-8')
        return paths,sources

    def test_native_two_level_events_require_same_instance_parameter_feedback(self):
        self.declarative_feedback_fixture()
        before=self.snapshot()
        result,report=self.wiring('two-level-event-feedback')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(report['categories']['C2_integration_point']['fail'],0)
        self.assertEqual(before,self.snapshot())
    def test_native_callback_contract_without_continuation_keeps_immediate_shape(self):
        write(self.project/'spec/baseline/ui/page.md','# Page\n## Navigation\nImmediate callback has no sheet continuation.\n')
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md'
        content=plan.read_text(encoding='utf-8')
        contract='\ncallback_bindings:\n  - owner: SLICE:F001:3d\n    kind: event_callback\n    producer: TastingPage.save\n    event: TastingPage.onSaved\n    binding: BrewPage.tastingContent\n    consumer: BrewPage.tastingSaved\n    input: spec/baseline/ui/page.md#Navigation\n'
        plan.write_text(content+contract,encoding='utf-8')
        before=self.snapshot();result,report=self.wiring('immediate-callback-without-continuation')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(report['categories']['C2_integration_point']['fail'],0)
        self.assertEqual(before,self.snapshot())
        for bad in [contract.replace('    event: TastingPage.onSaved\n',''),
                    contract+'    unknown_field: forbidden\n']:
            plan.write_text(content+bad,encoding='utf-8')
            result,report=self.wiring('malformed-immediate-callback')
            self.assertNotEqual(result.returncode,0)

    def test_native_event_feedback_rejects_every_broken_binding_edge(self):
        paths,sources=self.declarative_feedback_fixture()
        variants=[('no-emitter','preview',sources['preview'].replace('this.onText(text);','void text;')),
          ('wrong-event-key','scanner',sources['scanner'].replace('onText: (text:', 'otherEvent: (text:')),
          ('wrong-forwarded-argument','scanner',sources['scanner'].replace('this.onText(text);','this.onText(this.text);')),
          ('wrong-state-lhs','parent',sources['parent'].replace('this.scanningText = text','this.otherText = text')),
          ('wrong-state-rhs','parent',sources['parent'].replace('this.scanningText = text','this.scanningText = this.otherText')),
          ('wrong-param-feedback','parent',sources['parent'].replace('text: this.scanningText','text: this.otherText')),
          ('wrong-type','parent',sources['parent'].replace('onText: (text: string)','onText: (text: number)')),
          ('comment-emitter','preview',sources['preview'].replace('this.onText(text);','/* this.onText(text); */')),
          ('dead-emitter','preview',sources['preview'].replace('this.onText(text);','const unused = (): void => { this.onText(text); };')),
          ('dead-object-emitter','preview',sources['preview'].replace('this.onText(text);','const unused = { callback: (): void => { this.onText(text); } };')),
          ('ignored-inline-emitter','preview',sources['preview'].replace('build(): void',
              'ignore(work: () => void): void {}\n build(): void').replace('this.emit(this.input);','this.ignore(() => { this.emit(this.input); });')),
          ('import-only-child','scanner',sources['scanner'].replace('PreviewChild({ onText:', 'UnusedChild({ onText:')),
          ('shadowed-child','scanner',sources['scanner'].replace('Column() { PreviewChild(', 'Column() { const PreviewChild = (_args: Object): void => {}; PreviewChild(')),
          ('literal-dead-child','scanner',sources['scanner'].replace('Column() { PreviewChild(', 'Column() { if (false) { PreviewChild(').replace('Text(this.text);','} Text(this.text);')),
          ('unused-builder','parent',sources['parent'].replace('this.liveContent()','this.unrelatedContent()')),
          ('dead-object-builder','parent',sources['parent'].replace('Column() { Text(this.scanningText); }.bindContentCover($$this.camera, this.liveContent());',
              'const unused = { callback: () => { this.liveContent(); } }; Column() { Text(this.scanningText); };')),
          ('different-render-instance','parent',sources['parent'].replace('text: this.scanningText','text: this.otherText').replace('Text(this.scanningText);','Text(this.scanningText); ScannerChild({ text: this.scanningText });'))]
        for name,changed,source in variants:
            with self.subTest(name=name):
                for key,path in paths.items(): write(self.project/path,source if key==changed else sources[key])
                result,report=self.wiring(name)
                self.assertEqual(report['categories']['C2_integration_point']['details'][0]['status'],'FAIL')

    def test_native_event_source_requires_authorized_consumed_service_callback(self):
        paths,sources=self.declarative_feedback_fixture()
        service='entry/src/main/ets/core/CallbackPort.ets'
        provider='export class CallbackPort {\n start(text: string, callback: (value: string) => void): void { callback(text); }\n}\n'
        preview="import { CallbackPort } from '../core/CallbackPort'\n"+sources['preview'].replace(
            " @Param input: string = ''", " @Local port: CallbackPort = new CallbackPort()\n @Param input: string = ''").replace(
            'this.onText(text);','this.port.start(text, (value: string) => this.onText(value));')
        write(self.project/service,provider);write(self.project/paths['preview'],preview)
        self.update_items(lambda item:item['ownership'].append(service))
        result,report=self.wiring('consumed-service-event-source')
        self.assertEqual(result.returncode,0,result.stderr)
        write(self.project/service,provider.replace('callback(text);','void text;'))
        with self.subTest(name='empty-service'):
            result,report=self.wiring('empty-service-does-not-emit')
            self.assertEqual(report['categories']['C2_integration_point']['details'][0]['status'],'FAIL')
        write(self.project/service,provider)
        self.update_items(lambda item:item['ownership'].remove(service))
        with self.subTest(name='outside-owned-service'):
            result,report=self.wiring('foreign-service-does-not-authorize-emitter')
            self.assertEqual(report['categories']['C2_integration_point']['details'][0]['status'],'FAIL')

    def test_native_exact_typed_receiver_scalar_writes(self):
        domain=self.project/'entry/src/main/ets/core/Domain.ets'
        domain.write_text(domain.read_text(encoding='utf-8')+'\nexport class ActionState {\n tab: number = 0\n showBrew: boolean = false\n message: string | undefined = undefined\n}\nexport class WrongState { showBrew: boolean = false }\n',encoding='utf-8')
        self.update_items(lambda item:item['ownership'].append('entry/src/main/ets/pages/ScanPage.ets'))
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md';baseline=plan.read_text(encoding='utf-8')
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        code="import { ActionState, WrongState } from '../core/Domain'\n@ComponentV2\nstruct ScanPage {\n @Param router: ActionState = new ActionState()\n @Local other: WrongState = new WrongState()\n resume(): void { EFFECT }\n ignore(work: () => void): void {}\n build(): void { Button('go').onClick(() => { this.resume(); }); }\n}\n"
        for name,member,effect,expected in [('boolean','showBrew','this.router.showBrew = true;',0),
             ('number','tab','this.router.tab = 2;',0),('undefined','message','this.router.message = undefined;',0),
             ('wrong-receiver','showBrew','this.other.showBrew = true;',1),
             ('wrong-member','showBrew','this.router.other = true;',1),
             ('wrong-rhs','showBrew','this.router.showBrew = 2;',1),
             ('continued-rhs','tab','this.router.tab = 2\n + 1;',1),
             ('comment','showBrew','/* this.router.showBrew = true; */',1),
             ('dead-local','showBrew','const unused = (): void => { this.router.showBrew = true; };',1),
             ('ignored-inline','showBrew','this.ignore(() => { this.router.showBrew = true; });',1)]:
            with self.subTest(name=name):
                write(page,code.replace('EFFECT',effect))
                plan.write_text(baseline.replace('ScanPage.rawText → LabelParser.parse','ScanPage.resume → ActionState.'+member),encoding='utf-8')
                result,report=self.wiring('typed-scalar-'+name)
                self.assertEqual(result.returncode,expected,result.stderr)
    def test_native_navigation_requires_same_stack_route_parameter_and_target(self):
        page='entry/src/main/ets/pages/ScanPage.ets'; child='entry/src/main/ets/pages/DetailChild.ets'; root='entry/src/main/ets/RouteRoot.ets'
        caller="@ComponentV2\nexport struct ScanPage {\n @Param pathStack: NavPathStack = new NavPathStack()\n openBean(beanID: string): void { this.pathStack.pushPathByName('Detail', beanID); }\n build(): void { Button('open').onClick(() => this.openBean('id')); }\n}\n"
        destination="@ComponentV2\nexport struct DetailChild {\n @Param entityID: string = ''\n @Param pathStack: NavPathStack = new NavPathStack()\n build(): void { NavDestination() { Text(this.entityID); } }\n}\n"
        owner="import { ScanPage } from './pages/ScanPage'\nimport { DetailChild } from './pages/DetailChild'\n@ComponentV2\nexport struct RouteRoot {\n private stack: NavPathStack = new NavPathStack()\n private otherStack: NavPathStack = new NavPathStack()\n @Builder screen(): void { ScanPage({ pathStack: this.stack }); }\n @Builder destination(name: string, parameter: Object): void { if (name === 'Detail') { DetailChild({ entityID: parameter as string, pathStack: this.stack }); } }\n build(): void { Navigation(this.stack) { this.screen(); }.navDestination(this.destination); }\n}\n"
        write(self.project/page,caller);write(self.project/child,destination);write(self.project/root,owner)
        self.update_items(lambda item:item['ownership'].extend([page,child,root]))
        self.point('ScanPage.openBean → DetailChild.build')
        helper=owner.replace('DetailChild({ entityID: parameter as string, pathStack: this.stack });',
            'this.detail(parameter as string, this.stack);').replace(' build(): void',
            ' @Builder detail(value: string, stack: NavPathStack): void { DetailChild({ entityID: value, pathStack: stack }); }\n build(): void')
        for name,source,host,expected in [('direct',caller,owner,0),('one-helper',caller,helper,0),
            ('helper-key-equals-parameter',caller,helper.replace('value: string','entityID: string').replace('entityID: value','entityID: entityID'),0),
            ('shadowed-helper-parameter',caller,helper.replace('DetailChild({ entityID: value', "const value: string = 'other'; DetailChild({ entityID: value"),1),
            ('wrong-injected-stack',caller,owner.replace('ScanPage({ pathStack: this.stack })','ScanPage({ pathStack: this.otherStack })'),1),
            ('wrong-navigation-stack',caller,owner.replace('Navigation(this.stack)','Navigation(this.otherStack)'),1),
            ('wrong-route',caller,owner.replace("name === 'Detail'","name === 'Other'"),1),
            ('wrong-push-route',caller.replace("pushPathByName('Detail'","pushPathByName('Other'"),owner,1),
            ('wrong-parameter',caller,owner.replace('entityID: parameter as string',"entityID: 'other'"),1),
            ('wrong-import',caller,owner.replace('./pages/DetailChild','./pages/OtherChild'),1),
            ('unused-destination',caller,owner.replace('this.destination)','this.unrelated)'),1),
            ('wrong-helper-stack',caller,helper.replace('this.detail(parameter as string, this.stack)','this.detail(parameter as string, this.otherStack)'),1),
            ('comment-push',caller.replace("this.pathStack.pushPathByName('Detail', beanID);","/* this.pathStack.pushPathByName('Detail', beanID); */"),owner,1),
            ('dead-push',caller.replace("this.pathStack.pushPathByName('Detail', beanID);","const unused = (): void => { this.pathStack.pushPathByName('Detail', beanID); };"),owner,1),
            ('two-instance-splice',caller,owner.replace('ScanPage({ pathStack: this.stack });','ScanPage({ pathStack: this.stack }); ScanPage({ pathStack: this.otherStack });'),1)]:
            with self.subTest(name=name):
                write(self.project/page,source);write(self.project/root,host)
                result,report=self.wiring('native-navigation-'+name)
                self.assertEqual(result.returncode,expected,result.stderr)

    def test_native_two_self_hops_require_consumed_typed_promise(self):
        self.update_items(lambda item:item['ownership'].append('entry/src/main/ets/pages/ScanPage.ets'))
        self.point('ScanPage.run → LabelParser.parse')
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        source="import { LabelParser } from '../core/Domain'\n@ComponentV2\nstruct ScanPage {\n @Local rawText: string = ''\n private work: Promise<number> = Promise.resolve(0)\n run(): Promise<number> { const next = this.work.then(() => this.prepare()); this.work = next.then(() => 0); return next; }\n prepare(): number { return this.finish(); }\n finish(): number { return LabelParser.parse(this.rawText); }\n ignore(work: () => number): number { return 0; }\n build(): void { Button('go').onClick(() => { this.run(); }); }\n}\n"
        variants=[('real-two-hop',source,0),
          ('unlinked-first',source.replace('this.prepare()','this.unrelated()'),1),
          ('unlinked-second',source.replace('return this.finish();','return 0;'),1),
          ('wrong-import',source.replace('../core/Domain','../core/Other'),1),
          ('unconsumed-promise',source.replace('this.work = next.then(() => 0); return next;','return Promise.resolve(0);'),1),
          ('ignored-result-consumer',source.replace('this.work = next.then(() => 0); return next;',
              'this.ignorePromise(() => { return next; }); return Promise.resolve(0);').replace('ignore(work:',
              'ignorePromise(work: () => Promise<number>): void {}\n ignore(work:'),1),
          ('untyped-then',source.replace('work: Promise<number>','work: OtherQueue'),1),
          ('ignored-inline-helper',source.replace('() => this.prepare()','() => this.ignore(() => this.prepare())'),1),
          ('dead-local-helper',source.replace('this.work.then(() => this.prepare())','Promise.resolve(0)').replace('return next;','const unused = (): number => this.prepare(); return next;'),1)]
        for name,code,expected in variants:
            with self.subTest(name=name):
                write(page,code)
                result,report=self.wiring(name)
                self.assertEqual(result.returncode,expected,result.stderr)

    def test_native_sheet_handler_links_exact_state_builder_and_draft(self):
        domain=self.project/'entry/src/main/ets/core/Domain.ets'
        domain.write_text(domain.read_text(encoding='utf-8')+'\nexport class Draft { name: string = "" }\n',encoding='utf-8')
        child='entry/src/main/ets/pages/EditorChild.ets'
        editor="import { Draft } from '../core/Domain'\n@ComponentV2\nexport struct EditorChild { @Param initialDraft: Draft = new Draft(); build(): void { Text(this.initialDraft.name); } }\n"
        write(self.project/child,editor)
        self.update_items(lambda item:item['ownership'].extend([child,'entry/src/main/ets/pages/ScanPage.ets']))
        self.point('ScanPage.openEditor → EditorChild.build')
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        source="import { Draft } from '../core/Domain'\nimport { EditorChild } from './EditorChild'\n@ComponentV2\nstruct ScanPage {\n @Local edit: boolean = false\n @Local other: boolean = false\n @Local draft: Draft = new Draft()\n @Local otherDraft: Draft = new Draft()\n openEditor(): void { this.draft = new Draft(); this.edit = true; }\n @Builder editorContent(): void { EditorChild({ initialDraft: this.draft }); }\n @Builder unrelatedContent(): void { Text('other'); }\n build(): void { Column() { Button('edit').onClick(() => this.openEditor()); }.bindSheet($$this.edit, this.editorContent()); }\n}\n"
        for name,code,target,expected in [('real-sheet',source,editor,0),
          ('wrong-state',source.replace('this.edit = true','this.other = true'),editor,1),
          ('wrong-builder',source.replace('this.editorContent()','this.unrelatedContent()'),editor,1),
          ('wrong-draft',source.replace('initialDraft: this.draft','initialDraft: this.otherDraft'),editor,1),
          ('wrong-import',source.replace('./EditorChild','./OtherChild'),editor,1),
          ('empty-build',source,editor.replace('Text(this.initialDraft.name);',''),1),
          ('dead-child',source.replace('EditorChild({ initialDraft: this.draft });','const unused = (): void => { EditorChild({ initialDraft: this.draft }); };'),editor,1)]:
            with self.subTest(name=name):
                write(page,code);write(self.project/child,target)
                result,report=self.wiring('native-sheet-'+name)
                self.assertEqual(result.returncode,expected,result.stderr)

    def test_native_planned_method_event_binds_same_parent_typed_effects(self):
        paths,sources=self.declarative_feedback_fixture()
        sources['scanner']=sources['scanner'].replace('  ', '  ').replace(' build(): void', " @Event onConfirm: (text: string) => void = (_text: string) => {}\n @Event onDismiss: () => void = () => {}\n useText(): void { this.onConfirm(this.text); }\n cancel(): void { this.onDismiss(); }\n build(): void").replace("Column() { PreviewChild", "Column() { Button('ok').onClick(() => { this.useText(); }); Button('cancel').onClick(() => { this.cancel(); }); PreviewChild")
        sources['parent']=sources['parent'].replace(" @Local camera:", " @Local rawText: string = ''\n @Local image: string | undefined = undefined\n confirmLive(text: string): void { this.rawText = text; this.image = undefined; this.camera = false; }\n @Local camera:").replace('ScannerChild({ text:', 'ScannerChild({ onConfirm: (text: string) => { this.confirmLive(text); }, onDismiss: () => { this.camera = false; }, text:')
        for name,path in paths.items(): write(self.project/path,sources[name])
        self.point('ScannerChild.useText → ScanPage.rawText')
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md'
        text=plan.read_text(encoding='utf-8'); prefix=text[:text.index('integration_points:')]; tail=text[text.index('wires:'):]
        plan.write_text(prefix+'integration_points:\n  - ScannerChild.useText → ScanPage.rawText\n  - ScannerChild.useText → ScanPage.image\n  - ScannerChild.useText → ScanPage.camera\n  - ScannerChild.cancel → ScanPage.camera\n\n'+tail,encoding='utf-8')
        before=self.snapshot();result,report=self.wiring('method-events-positive')
        self.assertEqual(report['categories']['C2_integration_point']['pass'],4,report)
        self.assertEqual(before,self.snapshot())
        variants=[
            ('wrong-emitted-event','scanner',sources['scanner'].replace('this.onConfirm(this.text);','this.onText(this.text);'),[0,1,2]),
            ('unrelated-emitter','scanner',sources['scanner'].replace('useText(): void { this.onConfirm(this.text); }','useText(): void {} unused(): void { this.onConfirm(this.text); }'),[0,1,2]),
            ('wrong-payload','scanner',sources['scanner'].replace('this.onConfirm(this.text);',"this.onConfirm(5);"),[0,1,2]),
            ('wrong-parent-method','parent',sources['parent'].replace('this.confirmLive(text);','this.unused(text);'),[0,1,2]),
            ('wrong-parent-argument','parent',sources['parent'].replace('this.confirmLive(text);','this.confirmLive(this.otherText);'),[0,1,2]),
            ('wrong-parent-type','parent',sources['parent'].replace('confirmLive(text: string)','confirmLive(text: number)'),[0,1,2]),
            ('wrong-field','parent',sources['parent'].replace('this.rawText = text;','this.otherText = text;'),[0]),
            ('wrong-literal','parent',sources['parent'].replace('this.image = undefined;','this.image = 5;'),[1]),
            ('comment-effect','parent',sources['parent'].replace('this.rawText = text;','/* this.rawText = text; */'),[0]),
            ('dead-effect','parent',sources['parent'].replace('this.rawText = text;','if (false) { this.rawText = text; }'),[0]),
            ('idle-effect','parent',sources['parent'].replace('this.rawText = text;','const unused = (): void => { this.rawText = text; };'),[0]),
            ('wrong-render-binding','parent',sources['parent'].replace('onConfirm: (text:', 'other: (text:'),[0,1,2]),
            ('comment-cancel','scanner',sources['scanner'].replace('cancel(): void { this.onDismiss(); }','cancel(): void { /* this.onDismiss(); */ }'),[3])]
        for name,key,changed,failed in variants:
            with self.subTest(name=name):
                for original,path in paths.items(): write(self.project/path,changed if original==key else sources[original])
                before=self.snapshot();result,report=self.wiring('method-event-'+name)
                details=report['categories']['C2_integration_point']['details']
                for position in failed: self.assertEqual(details[position]['status'],'FAIL',details[position])
                self.assertEqual(before,self.snapshot())

    def native_dto_fixture(self):
        paths={'models':'entry/src/main/ets/model/RecipeModels.ets',
               'router':'entry/src/main/ets/store/RecipeRouter.ets',
               'page':'entry/src/main/ets/pages/RecipePage.ets',
               'root':'entry/src/main/ets/pages/RecipeRoot.ets'}
        sources={
          'models':"export class RecipeValues {\n dose: number = 15;\n ratio: number = 16;\n temperature: number = 92;\n duration: number = 180;\n constructor(dose: number = 15, ratio: number = 16, temperature: number = 92, duration: number = 180) { this.dose = dose; this.ratio = ratio; this.temperature = temperature; this.duration = duration; }\n clone(): RecipeValues { return new RecipeValues(this.dose, this.ratio, this.temperature, this.duration); }\n}\nexport class RecipeRecord { values: RecipeValues = new RecipeValues(); }\nexport class RecipeDestination {\n id: string;\n values?: RecipeValues;\n constructor(id: string = '', values?: RecipeValues) { this.id = id; this.values = values?.clone(); }\n}\nexport class WrongDestination { id: string = ''; values?: RecipeValues; }\n",
          'router':"import { RecipeDestination, RecipeValues } from '../model/RecipeModels';\nexport class RecipeRouter {\n recipe: RecipeDestination | undefined = undefined;\n openRecipe(id: string, values?: RecipeValues): void { this.recipe = new RecipeDestination(id, values); }\n}\n",
          'page':"import { RecipeRecord, RecipeValues } from '../model/RecipeModels';\n@ComponentV2\nexport struct RecipePage {\n @Param initialValues: RecipeValues | undefined = undefined;\n @Param recipe: RecipeRecord | undefined = undefined;\n @Local values: RecipeValues = new RecipeValues();\n aboutToAppear(): void { this.values = (this.initialValues ?? this.recipe?.values ?? new RecipeValues()).clone(); }\n build(): void { Column() { Text(this.values.dose.toString()); } }\n}\n",
          'root':"import { RecipeDestination } from '../model/RecipeModels';\nimport { RecipeRouter } from '../store/RecipeRouter';\nimport { RecipePage } from './RecipePage';\n@ComponentV2\nstruct RecipeRoot {\n @Local router: RecipeRouter = new RecipeRouter();\n @Local visible: boolean = false;\n @Builder recipeContent(): void { Column() { ForEach(this.router.recipe === undefined ? [] : [this.router.recipe], (destination: RecipeDestination) => { RecipePage({ initialValues: destination.values }); }, (destination: RecipeDestination): string => destination.id); } }\n build(): void { Column() { Text('root'); }.bindSheet($$this.visible, this.recipeContent()); }\n}\n"}
        for key,path in paths.items(): write(self.project/path,sources[key])
        self.update_items(lambda item:item['ownership'].extend(paths.values()))
        self.point('RecipePage.values ← RecipeDestination.values')
        return paths,sources

    def test_native_dto_initialization_uses_same_typed_render_and_priority_clone(self):
        self.native_dto_fixture(); before=self.snapshot()
        result,report=self.wiring('dto-initialization-positive')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(report['categories']['C2_integration_point']['details'][0]['status'],'PASS')
        self.assertEqual(before,self.snapshot())

    def test_native_dto_initialization_rejects_broken_pipeline_edges(self):
        paths,sources=self.native_dto_fixture()
        variants=[
          ('wrong-render-child','root',sources['root'].replace('RecipePage({ initialValues:', 'OtherPage({ initialValues:')),
          ('wrong-render-param','root',sources['root'].replace('initialValues: destination.values', 'values: destination.values')),
          ('wrong-render-source','root',sources['root'].replace('initialValues: destination.values', 'initialValues: new RecipeValues()')),
          ('wrong-dto-type','root',sources['root'].replace('import { RecipeDestination }', 'import { RecipeDestination, WrongDestination }').replace('(destination: RecipeDestination)', '(destination: WrongDestination)')),
          ('wrong-constructor-writer-argument','router',sources['router'].replace('new RecipeDestination(id, values)','new RecipeDestination(id, new RecipeValues())')),
          ('wrong-dto-origin','router',sources['router'].replace('recipe: RecipeDestination | undefined', 'recipe: WrongDestination | undefined').replace('RecipeDestination, RecipeValues','RecipeDestination, RecipeValues, WrongDestination')),
          ('wrong-iterable','root',sources['root'].replace('[this.router.recipe]', '[this.router.other]')),
          ('wrong-key-source','root',sources['root'].replace('=> destination.id','=> destination.values')),
          ('lower-priority-param','page',sources['page'].replace('this.initialValues ?? this.recipe?.values', 'this.recipe?.values ?? this.initialValues')),
          ('no-clone','page',sources['page'].replace('new RecipeValues()).clone()', 'new RecipeValues())')),
          ('empty-clone','models',sources['models'].replace('return new RecipeValues(this.dose, this.ratio, this.temperature, this.duration);','return new RecipeValues();')),
          ('wrong-clone','models',sources['models'].replace('return new RecipeValues(this.dose, this.ratio, this.temperature, this.duration);','return new RecipeValues(this.ratio, this.dose, this.temperature, this.duration);')),
          ('empty-dto-constructor','models',sources['models'].replace('this.values = values?.clone();','void values;')),
          ('wrong-dto-constructor','models',sources['models'].replace('this.values = values?.clone();','this.values = new RecipeValues();')),
          ('dead-builder','root',sources['root'].replace('this.recipeContent()', 'this.unusedContent()')),
          ('dead-foreach','root',sources['root'].replace('ForEach(this.router.recipe', 'if (false) { ForEach(this.router.recipe').replace('=> destination.id);','=> destination.id); }')),
          ('dead-local-foreach','root',sources['root'].replace('ForEach(this.router.recipe','const unused = (): void => { ForEach(this.router.recipe').replace('=> destination.id);','=> destination.id); };')),
          ('comment-render','root',sources['root'].replace('RecipePage({ initialValues: destination.values });','/* RecipePage({ initialValues: destination.values }); */')),
          ('import-only','root',sources['root'].replace('RecipePage({ initialValues: destination.values });','Text(destination.id);')),
          ('later-overwrite','page',sources['page'].replace('new RecipeValues()).clone();','new RecipeValues()).clone(); this.values = new RecipeValues();'))]
        for name,key,changed in variants:
            with self.subTest(name=name):
                for original,path in paths.items(): write(self.project/path,changed if original==key else sources[original])
                before=self.snapshot();result,report=self.wiring('dto-'+name)
                self.assertEqual(report['categories']['C2_integration_point']['details'][0]['status'],'FAIL')
                self.assertEqual(before,self.snapshot())

    def test_native_dto_requires_every_precise_product_owner(self):
        paths,sources=self.native_dto_fixture()
        for excluded in paths.values():
            with self.subTest(excluded=excluded):
                self.update_items(lambda item:item.update(ownership=[p for p in item['ownership'] if p not in paths.values()]+[p for p in paths.values() if p!=excluded]))
                result,report=self.wiring('dto-unauthorized-'+Path(excluded).stem)
                self.assertEqual(report['categories']['C2_integration_point']['details'][0]['status'],'FAIL')

    def native_form_route_fixture(self):
        paths={'card':'entry/src/main/ets/widget/RecipeCard.ets','service':'entry/src/main/ets/service/Snapshots.ets',
            'form':'entry/src/main/ets/form/RecipeForm.ets','entry':'entry/src/main/ets/entryability/TestAbility.ets',
            'state':'entry/src/main/ets/Assembly.ets','root':'entry/src/main/ets/pages/TestRoot.ets',
            'module':'entry/src/main/module.json5','profile':'entry/src/main/resources/base/profile/forms.json'}
        sources={
            'card':"@Entry\n@Component\nstruct RecipeCard {\n @LocalStorageProp('routeUri') routeUri: string = 'coffee://last-recipe';\n openRecipe(): void { postCardAction(this, { action: 'router', uri: this.routeUri }); }\n build() { Column() { Text('card'); }.onClick(() => this.openRecipe()); }\n}\n",
            'service':"export interface Snapshot { recipeID: string; }\nexport interface CardBinding { routeUri: string; }\nexport class Snapshots {\n toBinding(snapshot: Snapshot | undefined): CardBinding { return { routeUri: snapshot === undefined ? 'coffee://last-recipe' : `coffee://recipe/${snapshot.recipeID}` }; }\n read(): Snapshot | undefined { return undefined; }\n bindingForForm(id: string): CardBinding { return this.toBinding(this.read()); }\n}\n",
            'form':"import { FormExtensionAbility, formBindingData } from '@kit.FormKit';\nimport { Want } from '@kit.AbilityKit';\nimport { Snapshots } from '../service/Snapshots';\nexport default class RecipeForm extends FormExtensionAbility {\n snapshots: Snapshots | undefined = undefined;\n service(): Snapshots { if (this.snapshots === undefined) { this.snapshots = new Snapshots(); } return this.snapshots; }\n onAddForm(want: Want): formBindingData.FormBindingData { const snapshots = this.service(); return formBindingData.createFormBindingData(snapshots.bindingForForm('1')); }\n}\n",
            'entry':"import { UIAbility, Want } from '@kit.AbilityKit';\nimport { state } from '../Assembly';\nexport default class TestAbility extends UIAbility {\n onCreate(want: Want): void { this.receiveWant(want); }\n onNewWant(want: Want): void { this.receiveWant(want); }\n receiveWant(want: Want): void { const uri = want.uri; if (uri !== undefined) { state.pendingURL = uri; state.urlGeneration += 1; } }\n}\n",
            'state':"export class AppState {\n pendingURL: string | undefined = undefined;\n urlGeneration: number = 0;\n}\nexport const state: AppState = new AppState();\n",
            'root':"import { AppState, state } from '../Assembly';\n@ComponentV2\nstruct TestRoot {\n @Local application: AppState = state;\n onMount(): void { this.consumeURL(); }\n @Monitor('application.urlGeneration')\n onURLChanged(): void { this.consumeURL(); }\n consumeURL(): void { const url = this.application.pendingURL; this.application.pendingURL = undefined; if (url !== undefined) { this.onOpenURL(url); } }\n onOpenURL(url: string): void { Text(url); }\n build(): void { Column() { Text('root'); } }\n}\n",
            'module':json.dumps({'module':{'name':'entry','type':'entry','mainElement':'TestAbility','abilities':[{'name':'TestAbility','srcEntry':'./ets/entryability/TestAbility.ets','exported':True,'skills':[{'entities':['entity.system.browsable'],'actions':['ohos.want.action.viewData'],'uris':[{'scheme':'coffee'}]}]}],'extensionAbilities':[{'name':'RecipeForm','srcEntry':'./ets/form/RecipeForm.ets','type':'form','metadata':[{'name':'ohos.extension.form','resource':'$profile:forms'}]}]}}),
            'profile':json.dumps({'forms':[{'name':'RecipeCard','src':'./ets/widget/RecipeCard.ets','uiSyntax':'arkts'}]})}
        sources['entry']=sources['entry'].replace('import { state }', "import { window } from '@kit.ArkUI';\nimport { state }").replace(' onCreate(', " onWindowStageCreate(stage: window.WindowStage): void { stage.loadContent('pages/TestRoot'); }\n onCreate(")
        sources['root']=sources['root'].replace('@ComponentV2', '@Entry\n@ComponentV2').replace(' onMount():', ' aboutToAppear(): void { this.onMount(); }\n onMount():')
        for key,path in paths.items(): write(self.project/path,sources[key])
        self.update_items(lambda item:item['ownership'].extend(paths.values()))
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md';text=plan.read_text(encoding='utf-8')
        plan.write_text(text[:text.index('integration_points:')]+'integration_points:\n  - RecipeCard.openRecipe → TestAbility.onCreate\n  - RecipeCard.openRecipe → TestAbility.onNewWant\n\n'+text[text.index('wires:'):],encoding='utf-8')
        return paths,sources

    def test_native_form_router_dispatch_is_bound_source_evidence(self):
        self.native_form_route_fixture(); before=self.snapshot();result,report=self.wiring('native-form-route')
        self.assertEqual(report['categories']['C2_integration_point']['pass'],2,report)
        for detail in report['categories']['C2_integration_point']['details']:
            self.assertEqual(detail['proof'],'native-form-router-source')
            self.assertFalse(detail['runtime_dispatch_verified'])
            self.assertTrue(detail['target_authority'])
        self.assertEqual(before,self.snapshot())

    def test_native_form_router_dispatch_rejects_broken_source_contracts(self):
        paths,sources=self.native_form_route_fixture()
        variants=[
            ('wrong-action','card',sources['card'].replace("action: 'router'","action: 'call'")),
            ('ability-override','card',sources['card'].replace("action: 'router'","action: 'router', abilityName: 'Other'")),
            ('wrong-uri-field','card',sources['card'].replace('uri: this.routeUri','uri: this.other')),
            ('comment-dispatch','card',sources['card'].replace("postCardAction(this, { action: 'router', uri: this.routeUri });","/* postCardAction(this, { action: 'router', uri: this.routeUri }); */")),
            ('dead-dispatch','card',sources['card'].replace('postCardAction(this,', 'if (false) { postCardAction(this,').replace('this.routeUri });','this.routeUri }); }')),
            ('local-dispatch-shadow','card',sources['card'].replace('postCardAction(this,','const postCardAction = (_self: Object, _data: Object): void => {}; postCardAction(this,')),
            ('wrong-storage-key','card',sources['card'].replace("LocalStorageProp('routeUri')","LocalStorageProp('other')")),
            ('wrong-scheme','module',sources['module'].replace('coffee','other')),
            ('wrong-main-element','module',sources['module'].replace('"mainElement": "TestAbility"','"mainElement": "Other"')),
            ('foreign-entry','module',sources['module'].replace('./ets/entryability/TestAbility.ets','../../spec/TestAbility.ets')),
            ('not-exported','module',sources['module'].replace('"exported": true','"exported": false')),
            ('wrong-card-profile','profile',sources['profile'].replace('widget/RecipeCard','widget/Other')),
            ('wrong-binding-key','service',sources['service'].replace('return { routeUri:', 'return { other:')),
            ('wrong-template-source','service',sources['service'].replace('${snapshot.recipeID}','${other.recipeID}')),
            ('wrong-template-type','service',sources['service'].replace('recipeID: string','recipeID: number')),
            ('dead-binding','service',sources['service'].replace('return { routeUri:', 'const unused = (): CardBinding => { return { routeUri:').replace('snapshot.recipeID}` };','snapshot.recipeID}` }; }; return { routeUri: '' };')),
            ('unused-binding','service',sources['service'].replace('return this.toBinding(this.read());',"return { routeUri: '' };")),
            ('wrong-form-binding','form',sources['form'].replace('snapshots.bindingForForm', 'other.bindingForForm')),
            ('wrong-entry-argument','entry',sources['entry'].replace('this.receiveWant(want);','this.receiveWant(other);')),
            ('wrong-input-property','entry',sources['entry'].replace('const uri = want.uri','const uri = want.other')),
            ('wrong-state-write','entry',sources['entry'].replace('state.pendingURL = uri','state.pendingURL = undefined')),
            ('comment-generation','entry',sources['entry'].replace('state.urlGeneration += 1;','/* state.urlGeneration += 1; */')),
            ('wrong-root-state','root',sources['root'].replace('AppState = state','AppState = new AppState()')),
            ('unconsumed-root-input','root',sources['root'].replace('this.onOpenURL(url);','Text(url);')),
            ('shadow-state','entry',sources['entry'].replace('import { state }','import { AppState, state }').replace('const uri = want.uri;', 'const state: AppState = new AppState(); const uri = want.uri;')),
            ('dead-provider-initializer','form',sources['form'].replace('if (this.snapshots === undefined)', 'if (false)')),
            ('empty-root-consumer','root',sources['root'].replace('Text(url);', '')),
            ('overwritten-route','card',sources['card'].replace('postCardAction(this,', "this.routeUri = 'https://foreign'; postCardAction(this,"))]
        for name,key,changed in variants:
            with self.subTest(name=name):
                for original,path in paths.items(): write(self.project/path,changed if original==key else sources[original])
                before=self.snapshot();result,report=self.wiring('native-form-'+name)
                self.assertEqual(report['categories']['C2_integration_point']['pass'],0,report)
                self.assertEqual(before,self.snapshot())

    def test_native_form_route_requires_each_exact_product_owner(self):
        paths,sources=self.native_form_route_fixture()
        for excluded in paths.values():
            with self.subTest(excluded=excluded):
                self.update_items(lambda item:item.update(ownership=[p for p in item['ownership'] if p not in paths.values()]+[p for p in paths.values() if p!=excluded]))
                before=self.snapshot();result,report=self.wiring('form-unowned-'+Path(excluded).stem)
                self.assertEqual(report['categories']['C2_integration_point']['pass'],0,report)
                self.assertEqual(before,self.snapshot())

    def test_native_form_dispatch_requires_loaded_root_and_lifecycle(self):
        paths,sources=self.native_form_route_fixture()
        variants=[
            ('wrong-load-target','entry',sources['entry'].replace("loadContent('pages/TestRoot')", "loadContent('pages/Other')")),
            ('dead-load','entry',sources['entry'].replace("stage.loadContent('pages/TestRoot');", "if (false) { stage.loadContent('pages/TestRoot'); }")),
            ('unmounted-root','root',sources['root'].replace('aboutToAppear(): void { this.onMount(); }','aboutToAppear(): void {}')),
            ('root-without-entry','root',sources['root'].replace('@Entry\n',''))]
        for name,key,changed in variants:
            with self.subTest(name=name):
                for original,path in paths.items(): write(self.project/path,changed if original==key else sources[original])
                before=self.snapshot();result,report=self.wiring('form-loaded-root-'+name)
                self.assertEqual(report['categories']['C2_integration_point']['pass'],0,report)
                self.assertEqual(before,self.snapshot())

    def test_native_consumed_local_async_task_links_its_exact_self_helper(self):
        self.update_items(lambda item:item['ownership'].append('entry/src/main/ets/pages/ScanPage.ets'))
        self.point('ScanPage.run → LabelParser.parse')
        path=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        source="import { LabelParser } from '../core/Domain';\n@ComponentV2\nstruct ScanPage {\n pending: Promise<void> = Promise.resolve();\n ignore(work: () => void): void {}\n run(): void { let data: string = 'bean'; const task = async (): Promise<void> => { await this.recognize(data); }; task().catch((error: Error): void => {}); }\n async recognize(data: string): Promise<void> { LabelParser.parse(data); }\n build(): void { Button('run').onClick(() => { this.run(); }); }\n}\n"
        variants=[('catch',source,0),
            ('capture-with-same-object-key',source.replace('await this.recognize(data);','const prepared = { data: data }; await this.recognize(data);'),0),
            ('destructured-shadow',source.replace('await this.recognize(data);','const { data } = other; await this.recognize(data);'),1),
            ('await',source.replace('run(): void','async run(): Promise<void>').replace('task().catch((error: Error): void => {});','await task();'),0),
            ('saved-promise',source.replace('task().catch((error: Error): void => {});','this.pending = task();'),0),
            ('saved-local-promise',source.replace('task().catch((error: Error): void => {});','const work: Promise<void> = task();'),0),
            ('never-invoked',source.replace('task().catch((error: Error): void => {});',''),1),
            ('rebound',source.replace('task().catch','task = async (): Promise<void> => {}; task().catch'),1),
            ('shadowed',source.replace('task().catch((error: Error): void => {});','{ const task = async (): Promise<void> => {}; task().catch((error: Error): void => {}); }'),1),
            ('ignored-callback',source.replace('task().catch((error: Error): void => {});','this.ignore(() => { task().catch((error: Error): void => {}); });'),1),
            ('dead-invocation',source.replace('task().catch((error: Error): void => {});','if (false) { task().catch((error: Error): void => {}); }'),1),
            ('wrong-task-type',source.replace('const task = async (): Promise<void>','const task = async (): Promise<number>'),1),
            ('wrong-helper-type',source.replace('recognize(data: string): Promise<void>','recognize(data: string): Promise<number>'),1),
            ('wrong-argument-type',source.replace('let data: string','let data: number'),1),
            ('wrong-receiver',source.replace('await this.recognize(data)','await other.recognize(data)'),1),
            ('wrong-target-import',source.replace('../core/Domain','../core/Other'),1),
            ('comment-helper',source.replace('await this.recognize(data);','/* await this.recognize(data); */'),1),
            ('idle-helper-call',source.replace('await this.recognize(data);','const unused = async (): Promise<void> => { await this.recognize(data); };'),1)]
        for name,changed,expected in variants:
            with self.subTest(name=name):
                write(path,changed);before=self.snapshot();result,report=self.wiring('local-async-'+name)
                self.assertEqual(result.returncode,expected,report)
                self.assertEqual(before,self.snapshot())

    def test_native_build_entry_embedding_requires_explicit_exact_contract(self):
        child='entry/src/main/ets/components/PreviewChild.ets'
        write(self.project/child,"@ComponentV2\nexport struct PreviewChild { build(): void { Text('preview'); } }\n")
        self.update_items(lambda item:item['ownership'].extend([child,'entry/src/main/ets/pages/ScanPage.ets']))
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        original=page.read_text(encoding='utf-8')
        source="import { PreviewChild } from '../components/PreviewChild'\n"+original.replace('Text(this.rawText)','Text(this.rawText); PreviewChild({})')
        write(page,source)
        write(self.project/'spec/baseline/ui/page.md','# Page\n## Components\nPreview child is rendered directly.\n')
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md'
        text=plan.read_text(encoding='utf-8').replace('wires: []',
            'wires:\n  - page: entry/src/main/ets/pages/ScanPage.ets\n    slot: build\n    embed: PreviewChild()\n    resolve_by: Slice 1 Step 3d')
        contract='\nembed_bindings:\n  - owner: SLICE:F001:3d\n    parent: ScanPage.build\n    child: PreviewChild\n    kind: direct_declarative_child\n    input: spec/baseline/ui/page.md#Components\n'
        plan.write_text(text+contract,encoding='utf-8')
        before=self.snapshot();result,report=self.wiring('native-build-child')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(report['categories']['C4_parent_replacement']['pass'],1)
        self.assertEqual(report['original_C4_parent_replacement']['fail'],1)
        self.assertEqual(before,self.snapshot())
        for name,code,declaration in [
            ('missing-contract',source,''),
            ('wrong-contract-parent',source,contract.replace('ScanPage.build','OtherPage.build')),
            ('wrong-contract-owner',source,contract.replace('SLICE:F001:3d','SLICE:F999:3d')),
            ('import-only',source.replace('PreviewChild({})','Text(this.rawText)'),contract),
            ('comment-only',source.replace('PreviewChild({})','/* PreviewChild({}) */'),contract),
            ('dead-local',source.replace('PreviewChild({})','const unused = (): void => { PreviewChild({}); }'),contract),
            ('dead-object',source.replace('PreviewChild({})','const unused = { callback: (): void => { PreviewChild({}); } }'),contract),
            ('ignored-inline-render',source.replace('build() {','ignore(work: () => void): void {}\n  build() {').replace('PreviewChild({})','this.ignore(() => { PreviewChild({}); })'),contract),
            ('shadowed-child',source.replace('PreviewChild({})','const PreviewChild = (_args: Object): void => {}; PreviewChild({})'),contract),
            ('literal-dead-child',source.replace('PreviewChild({})','if (false) { PreviewChild({}); }'),contract),
            ('wrong-import',source.replace('../components/PreviewChild','../components/OtherChild'),contract)]:
            with self.subTest(name=name):
                write(page,code);plan.write_text(text+declaration,encoding='utf-8')
                result,report=self.wiring(name)
                self.assertNotEqual(result.returncode,0)
                if 'categories' in report: self.assertEqual(report['categories']['C4_parent_replacement']['fail'],1)
        write(page,source)
        plan.write_text(text.replace('wires:\n  - page: entry/src/main/ets/pages/ScanPage.ets\n    slot: build\n    embed: PreviewChild()\n    resolve_by: Slice 1 Step 3d','wires: []')+contract,encoding='utf-8')
        result,report=self.wiring('embed-contract-without-authored-wire')
        self.assertNotEqual(result.returncode,0)
        plan.write_text(text+contract,encoding='utf-8')
        config=self.project/'.migbot/config.json'
        config.write_text(json.dumps({'source_platform':'ios','ios_harness':{'spec_contract_version':1}}),encoding='utf-8')
        result,report=self.wiring('legacy-build-still-needs-original-builder')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(report['categories']['C4_parent_replacement']['details'][0]['failed_check'],'C4_BUILDER_NOT_FOUND')
        self.assertNotIn('native_adapter',report)

    def test_native_saved_event_needs_producer_effect_builder_and_continuation(self):
        child='entry/src/main/ets/pages/EditorChild.ets'
        child_source="@ComponentV2\nexport struct EditorChild {\n @Event onSaved: () => void = () => {}\n save(): void { this.onSaved(); }\n build(): void { Button('save').onClick(() => { this.save(); }); }\n}\n"
        page=self.project/'entry/src/main/ets/pages/ScanPage.ets'
        source="import { EditorChild } from './EditorChild'\n@ComponentV2\nstruct ScanPage {\n @Local librarySaved: boolean = false\n @Local otherSaved: boolean = false\n @Local editor: boolean = false\n @Local closed: boolean = false\n close(): void { this.closed = true; }\n @Builder editorContent(): void { EditorChild({ onSaved: () => { this.librarySaved = true; } }); }\n build(): void { Column() { Text('parent'); }.bindSheet($$this.editor, this.editorContent(), { onDisappear: () => { if (this.librarySaved) { this.close(); } } }); }\n}\n"
        write(self.project/child,child_source);write(page,source)
        self.update_items(lambda item:item['ownership'].extend([child,'entry/src/main/ets/pages/ScanPage.ets']))
        self.point('ScanPage.editorContent ← EditorChild.onSaved')
        write(self.project/'spec/baseline/ui/page.md','# Page\n## Navigation\nSaved event is consumed on dismissal.\n')
        plan=self.project/'spec/baseline/plans/slices/slice-01-F001.md';text=plan.read_text(encoding='utf-8')
        contract='\ncallback_bindings:\n  - owner: SLICE:F001:3d\n    kind: event_callback\n    producer: EditorChild.save\n    event: EditorChild.onSaved\n    binding: ScanPage.editorContent\n    consumer: ScanPage.librarySaved\n    continuation: bindSheet onDisappear callback declared in ScanPage.build -> ScanPage.close\n    input: spec/baseline/ui/page.md#Navigation\n'
        plan.write_text(text+contract,encoding='utf-8')
        before=self.snapshot();result,report=self.wiring('saved-event-continuation')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(before,self.snapshot())
        variants=[('default-only',child_source.replace('this.onSaved();','void 0;'),source,contract),
          ('dead-producer',child_source.replace('this.save();','void 0;'),source,contract),
          ('wrong-event-property',child_source,source.replace('onSaved: ()','onDismiss: ()'),contract),
          ('wrong-effect-state',child_source,source.replace('this.librarySaved = true','this.otherSaved = true'),contract),
          ('unused-builder',child_source,source.replace('this.editorContent()','this.unrelatedContent()'),contract),
          ('wrong-continuation-state',child_source,source.replace('if (this.librarySaved)','if (this.otherSaved)'),contract),
          ('dead-continuation',child_source,source.replace('this.close();','const unused = (): void => { this.close(); };'),contract),
          ('plan-only-producer',child_source,source,contract.replace('EditorChild.save','EditorChild.unused')),
          ('missing-contract',child_source,source,'')]
        for name,child_code,code,declaration in variants:
            with self.subTest(name=name):
                write(self.project/child,child_code);write(page,code);plan.write_text(text+declaration,encoding='utf-8')
                result,report=self.wiring(name)
                self.assertEqual(report['categories']['C2_integration_point']['details'][0]['status'],'FAIL')

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
