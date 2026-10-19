"""Portable v2 contract examples; no private app snapshot or D: path needed."""
import copy
from contextlib import redirect_stdout
from io import StringIO
import json
import unittest

import test_plan_contract as fixture
from hmigbot_ios.core import write_json, MigrationError
from hmigbot_ios.capability_manifest import derive, main
from hmigbot_ios.capability_runtime import ClosureError
from hmigbot_ios.plan_contract import validate_plan


class PortableCapabilityTests(unittest.TestCase):
    task=fixture.PlanContractTests.task
    write_plans=fixture.PlanContractTests.write_plans
    responsibility=fixture.PlanContractTests.responsibility
    tearDown=fixture.PlanContractTests.tearDown

    def setUp(self):
        fixture.PlanContractTests.setUp(self)
        self.root='entry/src/main/ets/'
        sources={
          'Settings.ets': 'export class Settings { ready: boolean = false; open(ctx: Object): void { this.ready = true; } }',
          'Library.ets': """import { Settings } from './Settings';
export class Library {
  private settings: Settings; error: string | null = null; private opened: boolean = false;
  constructor(settings: Settings) { this.settings = settings; }
  open(ctx: Object): boolean {
    if (this.opened) { return this.error === null; }
    try { this.settings.open(ctx); this.error = null; this.opened = true; return true; }
    catch (error) { this.error = this.describe(error); return false; }
  }
  private describe(error: Object): string { return String(error); }
}""",
          'Coordinator.ets': """import { Library } from './Library';
export class Coordinator { private library: Library; active: boolean = false;
 constructor(library: Library) { this.library = library; }
 attach(): void { this.active = true; } detach(): void { this.active = false; }
}""",
          'Assembly.ets': """import { Settings as Prefs } from './Settings';
import { Library } from './Library';
import { Coordinator } from './Coordinator';
const settings: Prefs = new Prefs(); const library: Library = new Library(settings);
const coordinator: Coordinator = new Coordinator(library);
export const capabilityTable = { settings: settings, library: library, coordinator: coordinator };
export function initialize(ctx: Object): boolean { return library.open(ctx); }
""",
          'Host.ets': """import { capabilityTable } from './Assembly';
import { Library } from './Library';
import { Coordinator } from './Coordinator';
export class Host { private library: Library = capabilityTable.library;
 private coordinator: Coordinator = capabilityTable.coordinator;
 get ready(): boolean { return this.library.error === null; }
 start(): void { if (!this.ready) { return; } this.coordinator.attach(); }
 stop(): void { this.coordinator.detach(); }
}""",
          'Launcher.ets': """import { initialize } from './Assembly';
export class Launcher { done: boolean = false;
 onCreate(ctx: Object): void { if (initialize(ctx)) { this.consume(); } }
 private consume(): void { this.done = true; }
}""",
          'Artifacts.ets':'export enum Mode { Idle, Ready }\nexport interface Value { count: number; }\n@Builder\nexport function Label() { Text("value"); }',
          'Scoped.ets':'export class LocalModel { value: number = 1; }',
          'Consumer.ets':"import { LocalModel } from './Scoped';\nexport class Consumer { model: LocalModel = new LocalModel(); }",
        }
        for relative,text in sources.items():
            path=self.project/(self.root+relative); path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
        write_json(self.project/'build-profile.json5',{'modules':[{'name':'entry','srcPath':'./entry'}]})
        write_json(self.project/'entry/src/main/module.json5',{'module':{'name':'entry','type':'entry'}})
        base=copy.deepcopy(self.items[0]);base.update(item_id='BASE:Base-1',ownership=[self.root+f for f in ('Settings.ets','Library.ets','Coordinator.ets','Artifacts.ets')],parents=['BASE:Base-0'])
        assembly=copy.deepcopy(base);assembly.update(item_id='BASE:Base-6.5',ownership=[self.root+'Assembly.ets',self.root+'Launcher.ets',self.root+'Consumer.ets'],parents=['BASE:Base-1'])
        self.items[0]['ownership']=['build-profile.json5','entry/src/main/module.json5']
        self.items[1]['ownership']=[self.root+'Host.ets']
        self.items[2].update(item_id='SLICE:F001:3c',ownership=[self.root+'Scoped.ets'],parents=['BASE:Base-6.5'])
        self.items[3]['parents']=['UI:PAGE-0001','SLICE:F001:3c','BASE:Base-6.5'];self.items += [base,assembly]
        ui=self.base/'ui-manifest.md';ui.write_text(ui.read_text(encoding='utf-8').replace('entry/Counter.ets',self.root+'Host.ets'),encoding='utf-8')
        self.request['tasks']=[self.task('base',[i for i in self.items if i['item_id'].startswith('BASE:')],mapping_reason='base and assembly same owner'),self.task('counter',[i for i in self.items if i['item_id'].startswith(('UI:','SLICE:'))],parents=['base'],mapping_reason='page and local provider same owner'),self.task('final',[i for i in self.items if i['item_id'].startswith('FV:')],parents=['counter'],mapping_reason='readonly checks')]
        c=lambda receiver,method,args=(),slot='':{'receiver':receiver,'method':method,'arguments':list(args),'slot':slot}
        r=lambda path,owner,method,calls=(),guards=(),result='none':{'path':self.root+path,'owner':owner,'method':method,'calls':list(calls),'guards':list(guards),'result':result}
        entries=[]
        for slot,symbol,file,life in [('settings','Settings','Settings.ets',['open']),('library','Library','Library.ets',['open']),('coordinator','Coordinator','Coordinator.ets',['attach','detach'])]:
            entries.append({'key':'service.'+slot,'kind':'runtime-slot','symbol':symbol,'path':self.root+file,'slot':slot,'lifecycle':life,'provider':'base-plan.md#BASE:Base-1','provenance':'portable reviewed example','materialization':'materialized'})
        for symbol in ('Mode','Value','Label'):
            entries.append({'key':'artifact.'+symbol,'kind':'artifact-only','symbol':symbol,'path':self.root+'Artifacts.ets','slot':'','lifecycle':[],'provider':'base-plan.md#BASE:Base-1','provenance':'portable real export','materialization':'materialized'})
        entries.append({'key':'local','kind':'scoped','symbol':'LocalModel','path':self.root+'Scoped.ets','slot':'','lifecycle':[],'provider':'slice-01-F001.md#SLICE:F001:3c','provenance':'instance field consumer','materialization':'materialized'})
        self.contract={'capability_schema':2,'declarations':entries,'seams':'none','absence':'none','initialization':{
          'hosts':[r('Host.ets','Host','ready',result={'mode':'expression','expression':'this.library.error === null'}),
            r('Host.ets','Host','start',[c('this.coordinator','attach',slot='coordinator')],[{'mode':'early-return','condition':'!this.ready'}]),
            r('Host.ets','Host','stop',[c('this.coordinator','detach',slot='coordinator')]),
            r('Launcher.ets','Launcher','onCreate',[c('this','consume')],[{'mode':'if','condition':'initialize(ctx)'}]),r('Launcher.ets','Launcher','consume')],
          'chains':[r('Assembly.ets','','initialize',result={'mode':'return-call','call':c('library','open',['ctx'],'library')}),
            r('Library.ets','Library','open',[c('this.settings','open',['ctx'],'settings')],result={'mode':'boolean-state','field':'error','error_method':'describe','early_returns':[{'condition':'this.opened','expression':'this.error === null'}]})],
          'injections':[{'slot':'library','dependency':'settings','parameter':0,'field':'settings'},{'slot':'coordinator','dependency':'library','parameter':0,'field':'library'}]}}
        self.attach()

    def attach(self):
        self.write_plans();p=self.base/'plans/base-plan.md';p.write_text(p.read_text(encoding='utf-8')+'\n```capability-declarations\n'+json.dumps(self.contract)+'\n```\n',encoding='utf-8')

    def test_portable_complete_generic_contract(self):
        self.assertEqual(validate_plan(self.project,self.request)['status'],'PASS')
        result=derive(self.project);self.assertEqual(result['counts']['runtime_slots'],3);self.assertFalse(result['runtime_verified'])
        with redirect_stdout(StringIO()):
            self.assertEqual(main('gen',argv=['--project-root',str(self.project)]),0)
            self.assertEqual(main('gate',argv=['--project-root',str(self.project)]),0)

    def test_scoped_instance_field_supported(self):
        self.assertEqual(derive(self.project)['counts']['pending'],0)

    def test_scoped_static_field_rejected(self):
        path=self.project/(self.root+'Consumer.ets');path.write_text(path.read_text(encoding='utf-8').replace('model: LocalModel','static model: LocalModel'),encoding='utf-8')
        with self.assertRaisesRegex(MigrationError,'capability-scoped-global-instance'):derive(self.project)

    def test_artifact_self_factory_without_new_rejected(self):
        path=self.project/(self.root+'Artifacts.ets');path.write_text(path.read_text(encoding='utf-8')+'\nexport class FakeArtifact { static shared(): FakeArtifact { return {} as FakeArtifact; } }',encoding='utf-8')
        extra=copy.deepcopy(self.contract['declarations'][3]);extra.update(key='fake',symbol='FakeArtifact');self.contract['declarations'].append(extra);self.attach()
        with self.assertRaisesRegex(MigrationError,'capability-artifact-factory'):derive(self.project)

    def test_unknown_pending_result_shape_rejected(self):
        self.contract['initialization']['chains'][0]['result']['phase']='unknown';self.attach()
        with self.assertRaisesRegex(MigrationError,'capability-schema-invalid'):derive(self.project)

    def test_unmaterialized_canonical_generation_is_pending(self):
        (self.project/(self.root+'Settings.ets')).unlink()
        result=derive(self.project);self.assertIn('service.settings',result['pending']);self.assertIn('pending',result['verification'])
        with redirect_stdout(StringIO()):self.assertEqual(main('gate',argv=['--project-root',str(self.project)]),1)

    def test_dead_branch_call_rejected(self):
        path=self.project/(self.root+'Host.ets');path.write_text(path.read_text(encoding='utf-8').replace('this.coordinator.attach();','if (false) { this.coordinator.attach(); }'),encoding='utf-8')
        with self.assertRaisesRegex(MigrationError,'capability-init-call-control-unsupported'):derive(self.project)

    def test_wrong_canonical_host_field_rejected(self):
        path=self.project/(self.root+'Host.ets');path.write_text(path.read_text(encoding='utf-8').replace('= capabilityTable.library','= capabilityTable.coordinator'),encoding='utf-8')
        with self.assertRaisesRegex(MigrationError,'capability-init-receiver-mismatch'):derive(self.project)


class PortableFrameworkTests(unittest.TestCase):
    task=PortableCapabilityTests.task
    write_plans=PortableCapabilityTests.write_plans
    responsibility=PortableCapabilityTests.responsibility
    tearDown=PortableCapabilityTests.tearDown
    attach=PortableCapabilityTests.attach
    def setUp(self):
        PortableCapabilityTests.setUp(self)
        sources={
          'Widget.ets':"import { FormExtensionAbility as WidgetBase } from '@kit.FormKit';\nexport default class Widget extends WidgetBase { onAddForm(): Object { return {}; } }",
          'Executor.ets':"import { InsightIntentEntry as Tag, InsightIntentEntryExecutor as EntryBase } from '@kit.AbilityKit';\n@Tag({intentName:'Open'})\nexport default class Executor extends EntryBase<void> { async onExecute(): Promise<Object> { return {code:0}; } }"}
        for file,text in sources.items():
            (self.project/(self.root+file)).write_text(text,encoding='utf-8')
            self.items[2]['ownership'].append(self.root+file)
            self.contract['declarations'].append({'key':'framework.'+file,'kind':'framework-created','symbol':file[:-4],
              'path':self.root+file,'slot':'','lifecycle':[],'provider':'slice-01-F001.md#SLICE:F001:3c','provenance':'SDK registration proof','materialization':'materialized'})
        module=self.project/'entry/src/main/module.json5';data=json.loads(module.read_text(encoding='utf-8'));data['module']['extensionAbilities']=[{'name':'WidgetComponent','srcEntry':'./ets/Widget.ets','type':'form'}];write_json(module,data)
        write_json(self.project/'entry/src/main/resources/base/profile/insight_intent.json',{'insightIntentsSrcEntry':[{'srcEntry':'./ets/Executor.ets'}]})
        self.request['tasks'][1]=self.task('counter',[i for i in self.items if i['item_id'].startswith(('UI:','SLICE:'))],parents=['base'],mapping_reason='page/local/framework share owner')
        self.attach()

    def test_portable_framework_registration_evidence(self):
        result=derive(self.project)
        self.assertIn('entry/src/main/module.json5',result['source_evidence'])
        self.assertIn('entry/src/main/resources/base/profile/insight_intent.json',result['source_evidence'])

    def test_portable_missing_registration_rejected(self):
        (self.project/'entry/src/main/resources/base/profile/insight_intent.json').unlink()
        with self.assertRaisesRegex(MigrationError,'capability-registration-unreadable'):derive(self.project)


class PortableGuardBoundaryTests(unittest.TestCase):
    task=PortableCapabilityTests.task
    write_plans=PortableCapabilityTests.write_plans
    responsibility=PortableCapabilityTests.responsibility
    tearDown=PortableCapabilityTests.tearDown
    attach=PortableCapabilityTests.attach
    setUp=PortableCapabilityTests.setUp

    def test_declared_constant_guard_cannot_be_a_green_fixture(self):
        path=self.project/(self.root+'Host.ets')
        path.write_text(path.read_text(encoding='utf-8').replace('if (!this.ready)','if (false)'),encoding='utf-8')
        self.contract['initialization']['hosts'][1]['guards'][0]['condition']='false';self.attach()
        with self.assertRaisesRegex(MigrationError,'capability-init-constant-guard-unsupported'):derive(self.project)

    def test_malformed_old_manifest_cannot_replace_authority(self):
        write_json(self.project/'spec/execution/capability-manifest.json',[])
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(main('gate',argv=['--project-root',str(self.project)]),1)
        self.assertIn('capability-digest-mismatch',output.getvalue())


    def test_post_literal_table_mutation_rejected(self):
        path=self.project/(self.root+'Host.ets')
        path.write_text(path.read_text(encoding='utf-8')+'\nexport function mutateTable(): void { capabilityTable.library = capabilityTable.library; }',encoding='utf-8')
        with self.assertRaisesRegex(MigrationError,'capability-table-mutated'):derive(self.project)


    def test_reflective_construction_cannot_hide_a_second_instance(self):
        path=self.project/(self.root+'Host.ets')
        path.write_text(path.read_text(encoding='utf-8')+'\nexport function reflective(): Object { return Reflect.construct(Library, []); }',encoding='utf-8')
        with self.assertRaisesRegex(MigrationError,'capability-reflective-construction-unsupported'):derive(self.project)


class PortableDirectedReworkTests(unittest.TestCase):
    task=PortableCapabilityTests.task
    write_plans=PortableCapabilityTests.write_plans
    responsibility=PortableCapabilityTests.responsibility
    tearDown=PortableCapabilityTests.tearDown
    attach=PortableCapabilityTests.attach
    setUp=PortableCapabilityTests.setUp

    def rejected(self, expected):
        for kind in ('gen','gate'):
            with redirect_stdout(StringIO()) as output:
                code=main(kind,argv=['--project-root',str(self.project)])
            print(json.dumps({'probe':self._testMethodName,'mode':kind,'project_root':str(self.project),
                'function_returncode':code,'stdout':output.getvalue()}))
            self.assertNotEqual(code,0,output.getvalue())
            self.assertIn(expected,output.getvalue())
            self.assertNotIn('capability-digest-mismatch',output.getvalue())

    def test_rework_constructor_no_early_return_or_replaced_parameter(self):
        path=self.project/(self.root+'Library.ets'); original=path.read_text(encoding='utf-8')
        for body in ('return; this.settings = settings;',
                     'settings = this.settings; this.settings = settings;'):
            with self.subTest(body=body):
                path.write_text(original.replace('this.settings = settings;',body),encoding='utf-8')
                self.rejected('capability-injection-control-unsupported')

    def test_rework_injected_field_compound_write(self):
        path=self.project/(self.root+'Library.ets')
        path.write_text(path.read_text(encoding='utf-8').replace('private describe(error:',
            'replace(): void { this.settings ||= this.settings; } private describe(error:'),encoding='utf-8')
        self.rejected('capability-injection-field-reassigned')

    def test_rework_state_clear_cannot_be_unbraced_or_overwritten(self):
        path=self.project/(self.root+'Library.ets'); original=path.read_text(encoding='utf-8')
        for replacement,expected in (
            ('if (false) this.error = null;','capability-init-success-control-unsupported'),
            ('this.error = null; this.error = this.describe(null);','capability-init-state-overwritten'),
            ('this.error = null; this.error ||= this.describe(null);','capability-init-state-overwritten')):
            with self.subTest(replacement=replacement):
                path.write_text(original.replace('this.error = null;',replacement),encoding='utf-8')
                self.rejected(expected)

    def test_rework_state_helper_overwrite_is_not_hidden(self):
        path=self.project/(self.root+'Library.ets')
        path.write_text(path.read_text(encoding='utf-8').replace('private describe(error:',
            'resetError(): void { this.error = this.describe(null); } private describe(error:'),encoding='utf-8')
        self.rejected('capability-init-state-overwritten')

    def test_rework_any_finally_is_explicitly_unsupported(self):
        path=self.project/(self.root+'Library.ets')
        path.write_text(path.read_text(encoding='utf-8').replace(
            'this.error = this.describe(error); return false; }',
            'this.error = this.describe(error); return false; } finally { this.opened = true; }'),encoding='utf-8')
        self.rejected('capability-init-exit-control-unsupported')

    def test_rework_table_compound_and_update_family(self):
        path=self.project/(self.root+'Host.ets'); original=path.read_text(encoding='utf-8')
        variants=['capabilityTable.library '+op+' capabilityTable.library;' for op in ('&&=','||=','??=','+=','-=','**=','>>=')]
        variants += ['capabilityTable.library++;','--capabilityTable.library;',
            '(capabilityTable.library) ||= capabilityTable.library;',
            'delete (capabilityTable.library);']
        for expression in variants:
            with self.subTest(expression=expression):
                path.write_text(original+'\nexport function mutate(): void { '+expression+' }',encoding='utf-8')
                self.rejected('capability-table-mutated')


class PortableLexicalBoundaryTests(unittest.TestCase):
    task=PortableCapabilityTests.task
    write_plans=PortableCapabilityTests.write_plans
    responsibility=PortableCapabilityTests.responsibility
    tearDown=PortableCapabilityTests.tearDown
    attach=PortableCapabilityTests.attach
    setUp=PortableCapabilityTests.setUp
    rejected=PortableDirectedReworkTests.rejected

    def test_additional_non_null_gap_comment_newline_are_writes(self):
        path=self.project/(self.root+'Host.ets');original=path.read_text(encoding='utf-8')
        for gap in (' ', '/* gap */', '\n', ' /* gap\n */ '):
            with self.subTest(gap=gap):
                path.write_text(original+'\nexport function syntaxContrast(): void { capabilityTable.library!'+gap+'= capabilityTable.library; }',encoding='utf-8')
                self.assertFalse((self.project/'spec/execution/capability-manifest.json').exists())
                self.rejected('capability-table-mutated')

    def test_additional_actual_comparisons_survive_spacing_around_operator(self):
        path=self.project/(self.root+'Host.ets');original=path.read_text(encoding='utf-8')
        for expression in ('capabilityTable.library != capabilityTable.library',
                           'capabilityTable.library /* comment */ !== capabilityTable.library',
                           'capabilityTable.library\n!= capabilityTable.library'):
            with self.subTest(expression=expression):
                path.write_text(original+'\nexport function syntaxContrast(): void { '+expression+'; }',encoding='utf-8')
                for kind in ('gen','gate'):
                    with redirect_stdout(StringIO()) as output:
                        code=main(kind,argv=['--project-root',str(self.project)])
                    self.assertEqual(code,0,output.getvalue())

    def test_additional_lexer_values_lines_literals_and_equality_unchanged(self):
        from hmigbot_ios.behavior import _target_tokens, _TargetToken
        text="const word = 'x=>{}'; /* line\n comment */ word != `t${value}`; // tail\n /a[{}]/g;"
        parsed=_target_tokens(text)
        expected=[('const',1,False),('word',1,False),('=',1,False),('<literal>',1,True),(';',1,False),
                  ('word',2,False),('!',2,False),('=',2,False),('<literal>',2,True),(';',2,False),
                  ('<literal>',3,True),(';',3,False)]
        self.assertEqual([(t.value,t.line,t.literal) for t in parsed],expected)
        for token in parsed:
            self.assertGreaterEqual(token.start,0);self.assertGreater(token.end,token.start)
            if not token.literal:self.assertEqual(text[token.start:token.end],token.value)
            self.assertEqual(token.line,text[:token.start].count('\n')+1)
        self.assertEqual(_TargetToken('word',2),_TargetToken('word',2,start=10,end=14))
        self.assertEqual(hash(_TargetToken('word',2)),hash(_TargetToken('word',2,start=10,end=14)))
        self.assertNotEqual(_TargetToken('word',2),_TargetToken('word',2,True))
        contiguous=_target_tokens('x != y');separate=_target_tokens('x! /* c */ = y')
        self.assertEqual([t.value for t in contiguous],[t.value for t in separate])
        self.assertEqual(contiguous[1].end,contiguous[2].start)
        self.assertLess(separate[1].end,separate[2].start)
