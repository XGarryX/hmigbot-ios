"""C7 source-backed static closure probes; requires an explicit frozen snapshot.

HMIGBOT_C7_SOURCE points to the 20-file read-only snapshot listed in the
engineering receipt. The test plan deliberately scopes 14 C7 providers plus
selected artifacts and one separate generic scoped-consumer edge, not Cuike FV.
"""
import copy
import datetime
import hashlib
import time
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

import test_plan_contract as plan_fixture
from hmigbot_ios.core import MigrationError, write_json
from hmigbot_ios.native_structural_evidence import Source, _one
from hmigbot_ios.capability_runtime import segments, hits
from hmigbot_ios.capability_manifest import derive, main
from hmigbot_ios.plan_contract import validate_plan

ROOT=Path(__file__).resolve().parents[1]


def call(receiver, method, args=(), slot=''):
    return {'receiver':receiver,'method':method,'arguments':list(args),'slot':slot}


def rule(path,owner,method,calls=(),guards=(),result='none'):
    return {'path':path,'owner':owner,'method':method,'calls':list(calls),'guards':list(guards),'result':result}


class CapabilityClosureTests(unittest.TestCase):
    task=plan_fixture.PlanContractTests.task
    write_plans=plan_fixture.PlanContractTests.write_plans
    responsibility=plan_fixture.PlanContractTests.responsibility
    tearDown=plan_fixture.PlanContractTests.tearDown

    def setUp(self):
        snapshot=os.environ.get('HMIGBOT_C7_SOURCE')
        if not snapshot: self.skipTest('Explicit frozen HMIGBOT_C7_SOURCE required; no synthetic C7 success')
        plan_fixture.PlanContractTests.setUp(self)
        self.ets='entry/src/main/ets/'
        shutil.copytree(Path(snapshot)/'entry',self.project/'entry',dirs_exist_ok=True)
        write_json(self.project/'build-profile.json5',{'modules':[{'name':'entry','srcPath':'./entry'}]})
        write_json(self.project/'entry/src/main/module.json5',{'module':{'name':'entry','type':'entry'}})
        source=Source(self.project/(self.ets+'AppAssembly.ets'),self.project)
        canonical=[]; variables={}
        table=_one(source.bindings['capabilityTable'])
        lives={'preferences':['open'],'store':['open'],'router':['install'],'ocrService':['install'],
               'scanController':['install'],'scannerController':['install'],'journalController':['install'],
               'sharedStorage':['install'],'systemServices':['install'],
               'appController':['installRoot','disposeRoot','onActive','onInactive']}
        for part in segments(source,table.initializer):
            slot,var=part[0],part[2]; binding=_one(source.bindings[var]); symbol=source.values[binding.initializer+1]
            provider,remote=_one(source.imports[symbol]); path=provider.relative_to(self.project).as_posix()
            canonical.append({'key':'c7.'+slot,'kind':'runtime-slot','symbol':remote,'path':path,'slot':slot,
                'lifecycle':lives.get(slot,[]),'provider':'spec/baseline/plans/base-plan.md#BASE:Base-1',
                'provenance':'C7 frozen real source','materialization':'materialized'})
            variables[slot]=(var,binding,Source(provider,self.project),remote)
        self.assertEqual(len(canonical),14)
        injections=[]
        reverse={v[0]:k for k,v in variables.items()}
        for slot,(var,binding,provider,symbol) in variables.items():
            args=segments(source,binding.initializer+2)
            if not args: continue
            definition=_one([d for d in provider.definitions if d.name==symbol]); ctor=_one(definition.members['constructor'])
            params=segments(provider,ctor.index+1); body=provider.values[ctor.body[0]+1:ctor.body[1]]
            for position,arg in enumerate(args):
                param=params[position][0]
                assignments=[i for i in hits(body,['=',param,';']) if i>=3 and body[i-3]=='this' and body[i-2]=='.']
                self.assertEqual(len(assignments),1)
                field=body[assignments[0]-1]
                injections.append({'slot':slot,'dependency':reverse[arg[0]],'parameter':position,'field':field})
        app=self.ets+'AppAssembly.ets'; index=self.ets+'pages/Index.ets'; entry=self.ets+'entryability/EntryAbility.ets'
        early=lambda condition:{'mode':'early-return','condition':condition}
        guarded=lambda condition:{'mode':'if','condition':condition}
        hosts=[rule(index,'Index','startupSucceeded',result={'mode':'expression','expression':'this.store.startupError === null'}),
            rule(index,'Index','aboutToAppear',[call('this.appController','installRoot',slot='appController')],[early('!this.startupSucceeded || this.rootInstalled')]),
            rule(index,'Index','aboutToDisappear',[call('this.appController','disposeRoot',slot='appController')],[early('!this.rootInstalled')]),
            rule(entry,'EntryAbility','onCreate',[call('this','consumeWant',['want'])],[guarded('installCapabilities(this.context)')]),
            rule(entry,'EntryAbility','consumeWant',[call('capabilityTable.router','request',['route'],'router'),call('capabilityTable.router','consume',['capabilityTable.store'],'router')],[early('capabilityTable.store.startupError !== null'),guarded('route !== null')]),
            rule(entry,'EntryAbility','onNewWant',[call('this','consumeWant',['want'])]),
            rule(entry,'EntryAbility','onForeground',[call('capabilityTable.appController','onActive',slot='appController')],[guarded('capabilityTable.store.startupError === null')]),
            rule(entry,'EntryAbility','onBackground',[call('capabilityTable.appController','onInactive',slot='appController')],[guarded('capabilityTable.store.startupError === null')]),
            rule(entry,'EntryAbility','onWindowStageDestroy',[call('capabilityTable.appController','disposeRoot',slot='appController')]),
            rule(entry,'EntryAbility','onDestroy',[call('capabilityTable.appController','disposeRoot',slot='appController')])]
        install_slots=['sharedStorage','router','ocrService','scanController','scannerController','journalController','systemServices']
        chains=[rule(app,'','installCapabilities',[call(variables[slot][0],'install',['context'],slot) for slot in install_slots],
                 result={'mode':'return-call','call':call('store','open',['context'],'store')}),
            rule(self.ets+'services/CuikeStore.ets','CuikeStore','open',[call('this.settings','open',['context'],'preferences')],
                 result={'mode':'boolean-state','field':'startupError','error_method':'errorMessage',
                         'early_returns':[{'condition':'this.opened','expression':'this.startupError === null'}]})]
        artifacts=[]
        for name,path in [('SessionStatus','models/CuikeModels.ets'),('ModelText','models/CuikeModels.ets'),('BrewDomain','domain/BrewDomain.ets'),('Theme','design/Theme.ets')]:
            artifacts.append({'key':'artifact.'+name,'kind':'artifact-only','symbol':name,'path':self.ets+path,'slot':'','lifecycle':[],
                'provider':'spec/baseline/plans/base-plan.md#BASE:Base-1','provenance':'real source export','materialization':'materialized'})
        scoped=self.ets+'ScopedModel.ets'
        (self.project/scoped).write_text('export class ScopedModel { value: number = 1; }',encoding='utf-8')
        (self.project/(self.ets+'ScopedConsumer.ets')).write_text("import { ScopedModel } from './ScopedModel';\nexport class ScopedConsumer { create(): ScopedModel { return new ScopedModel(); } }",encoding='utf-8')
        scoped_entry={'key':'generic.scoped','kind':'scoped','symbol':'ScopedModel','path':scoped,'slot':'','lifecycle':[],
            'provider':'spec/baseline/plans/slices/slice-01-F001.md#SLICE:F001:3c','provenance':'separate generic scoped consumer probe','materialization':'materialized'}
        self.contract={'capability_schema':2,'declarations':canonical+artifacts+[scoped_entry],
            'initialization':{'hosts':hosts,'chains':chains,'injections':injections},'seams':'none','absence':'none'}
        base=copy.deepcopy(self.items[0]); base.update(item_id='BASE:Base-1',ownership=sorted({e['path'] for e in canonical+artifacts}),parents=['BASE:Base-0'])
        assembly=copy.deepcopy(base); assembly.update(item_id='BASE:Base-6.5',ownership=[app,entry,self.ets+'ScopedConsumer.ets'],parents=['BASE:Base-1'])
        self.items[0]['ownership']=['build-profile.json5','entry/src/main/module.json5']
        self.items[1]['ownership']=[index]
        self.items[2].update(item_id='SLICE:F001:3c',ownership=[scoped],parents=['BASE:Base-6.5'])
        self.items[3]['parents']=['UI:PAGE-0001','SLICE:F001:3c','BASE:Base-6.5']
        self.items += [base,assembly]
        self.write_plans()
        ui=self.base/'ui-manifest.md'; ui.write_text(ui.read_text(encoding='utf-8').replace('entry/Counter.ets',index),encoding='utf-8')
        self.request['tasks']=[self.task('base',[i for i in self.items if i['item_id'].startswith('BASE:')],mapping_reason='one owner for canonical assembly'),
            self.task('counter',[i for i in self.items if i['item_id'].startswith(('UI:','SLICE:'))],parents=['base'],mapping_reason='one UI and scoped owner'),
            self.task('final',[i for i in self.items if i['item_id'].startswith('FV:')],parents=['counter'],mapping_reason='final readonly checks')]
        self.attach()

    def attach(self):
        self.write_plans()
        path=self.base/'plans/base-plan.md'
        path.write_text(path.read_text(encoding='utf-8')+'\n```capability-declarations\n'+json.dumps(self.contract)+'\n```\n',encoding='utf-8')

    def mutate(self,path,before,after):
        target=self.project/(self.ets+path); text=target.read_text(encoding='utf-8')
        self.assertIn(before,text); target.write_text(text.replace(before,after,1),encoding='utf-8')

    def invoke(self,kind='gate',stage=False):
        helper=ROOT/'skills/arkts-structural-closure/scripts'/('gen_capability_manifest.py' if kind=='gen' else 'capability_ledger_gate.py')
        if stage:
            from hmigbot_ios.native_pipeline_semantics import stage_runtime
            skills=self.project/'isolated-layout/skills'; scripts=skills/'arkts-structural-closure/scripts'; scripts.mkdir(parents=True,exist_ok=True)
            stage_runtime(skills,ROOT); helper=scripts/helper.name
        arguments=[sys.executable,'-B',str(helper),'--project-root',str(self.project)]
        if stage and kind=='gate': arguments += ['--output-json',str(self.project/'staged-gate.json')]
        started=datetime.datetime.now(datetime.timezone.utc).isoformat(); clock=time.perf_counter()
        process=subprocess.run(arguments,cwd=ROOT,capture_output=True,encoding='utf-8')
        elapsed=time.perf_counter()-clock
        try: result=json.loads(process.stdout)
        except ValueError: self.fail(process.stdout+'\n'+process.stderr)
        print(json.dumps({'probe':self._testMethodName,'kind':kind,'stage':stage,'argv':arguments,'cwd':str(ROOT),
            'started_utc':started,'elapsed_seconds':elapsed,'returncode':process.returncode,
            'stdout':process.stdout,'stderr':process.stderr,'result':result},ensure_ascii=True))
        return process.returncode,result

    def test_real_c7_positive(self):
        self.assertEqual(validate_plan(self.project,self.request)['status'],'PASS')
        code,manifest=self.invoke('gen'); self.assertEqual(code,0,manifest)
        self.assertEqual(manifest['counts']['runtime_slots'],14)
        self.assertFalse(manifest['runtime_verified'])
        code,gate=self.invoke(); self.assertEqual(code,0,gate)
        self.assertEqual(manifest['input_digest'],gate['input_digest'])
        example=os.environ.get('HMIGBOT_C7_EXAMPLE')
        if example:
            Path(example).write_text(json.dumps(self.contract,indent=2),encoding='utf-8')


    def failure(self, expected, stage=False, code=None):
        actual,result=self.invoke(stage=stage)
        self.assertNotEqual(actual,0,result)
        if code is not None: self.assertEqual(actual,code,result)
        self.assertIn(expected,json.dumps(result))
        self.assertFalse(result['passed']); self.assertGreater(result['summary']['FAIL'],0)
        return result

    def test_missing_declarations(self):
        self.write_plans(); self.failure('capability-declarations-missing',code=1)

    def test_missing_path_coverage(self):
        self.contract['declarations']=[e for e in self.contract['declarations'] if e['slot']!='store']
        self.attach(); self.failure('capability-coverage-missing',code=1)

    def test_wrong_provider(self):
        self.contract['declarations'][0]['provider']='base-plan.md#BASE:Base-999'; self.attach()
        self.failure('capability-provider-unknown',code=1)

    def test_comment_table_not_evidence(self):
        path=self.project/(self.ets+'AppAssembly.ets'); text=path.read_text(encoding='utf-8')
        first=text.index('export const capabilityTable:'); last=text.index('};',first)+2
        path.write_text(text[:first]+'/*'+text[first:last]+'*/'+text[last:],encoding='utf-8')
        self.failure('capability-table-not-exported',code=1)

    def test_local_table_not_export_root(self):
        self.mutate('AppAssembly.ets','export const capabilityTable:','function decoy() { const capabilityTable:')
        self.mutate('AppAssembly.ets','};\n\nexport function installSystemCapabilities','}; }\n\nexport function installSystemCapabilities')
        self.failure('capability-table-not-exported',code=1)

    def test_null_slot(self):
        self.mutate('AppAssembly.ets','store: store,','store: null,')
        self.failure('capability-slot-not-canonical',code=1)

    def test_wrong_module_same_class(self):
        fake=self.project/(self.ets+'fake'); fake.mkdir()
        (fake/'CuikeStore.ets').write_text('export class CuikeStore { constructor(value: Object) {} }',encoding='utf-8')
        self.mutate('AppAssembly.ets',"from './services/CuikeStore'","from './fake/CuikeStore'")
        self.failure('capability-slot-provider-mismatch',code=1)

    def test_duplicate_inside_assembly(self):
        path=self.project/(self.ets+'AppAssembly.ets')
        path.write_text(path.read_text(encoding='utf-8')+'\nconst duplicate: CuikeStore = new CuikeStore(preferences);',encoding='utf-8')
        self.failure('capability-instance-duplicate',code=1)

    def test_duplicate_outside_assembly(self):
        (self.project/(self.ets+'Extra.ets')).write_text("import { CuikeStore } from './services/CuikeStore';\nexport function duplicate(): CuikeStore { return new CuikeStore(); }",encoding='utf-8')
        self.failure('capability-instance-duplicate',code=1)

    def test_wrong_injection(self):
        self.mutate('AppAssembly.ets','new CuikeStore(preferences)','new CuikeStore(router)')
        self.failure('capability-injection-mismatch',code=1)

    def test_import_alias_supported(self):
        self.mutate('AppAssembly.ets','import { CuikeStore }', 'import { CuikeStore as StoreAlias }')
        self.mutate('AppAssembly.ets','store: CuikeStore;', 'store: StoreAlias;')
        self.mutate('AppAssembly.ets','const store: CuikeStore = new CuikeStore(preferences)', 'const store: StoreAlias = new StoreAlias(preferences)')
        code,result=self.invoke(); self.assertEqual(code,0,result)

    def test_host_wrong_phase(self):
        self.mutate('pages/Index.ets','aboutToAppear(): void', 'differentPhase(): void')
        self.failure('capability-method-missing',code=1)

    def test_missing_store_preferences_open(self):
        self.mutate('services/CuikeStore.ets','this.settings.open(context);','this.settings.readAppearance();')
        self.failure('capability-init-call-mismatch',code=1)

    def test_store_failure_return_true(self):
        self.mutate('services/CuikeStore.ets','return false;','return true;')
        self.failure('capability-init-failure-propagation',code=1)

    def test_entry_unconditional_consumption(self):
        self.mutate('entryability/EntryAbility.ets','if (installCapabilities(this.context)) { this.consumeWant(want); }','installCapabilities(this.context); this.consumeWant(want);')
        self.failure('capability-init-guard-missing',code=1)

    def test_entry_startup_error_guard_removed(self):
        self.mutate('entryability/EntryAbility.ets','if (capabilityTable.store.startupError !== null) { return; }','')
        self.failure('capability-init-guard-missing',code=1)

    def test_store_return_source_always_true(self):
        self.mutate('AppAssembly.ets','return store.open(context);','store.open(context); return true;')
        self.failure('capability-init-return-source',code=1)

    def test_guard_nested_in_dead_branch_rejected(self):
        self.mutate('pages/Index.ets','if (!this.startupSucceeded || this.rootInstalled) { return; }','if (false) { if (!this.startupSucceeded || this.rootInstalled) { return; } }')
        self.failure('capability-init-guard-nondominating',code=2)

    def test_scoped_zero_consumer(self):
        self.mutate('ScopedConsumer.ets','return new ScopedModel();','throw new Error();')
        self.failure('capability-scoped-no-consumer',code=1)

    def test_scoped_global_instance(self):
        path=self.project/(self.ets+'ScopedConsumer.ets')
        path.write_text(path.read_text(encoding='utf-8')+'\nconst global = new ScopedModel();',encoding='utf-8')
        self.failure('capability-scoped-global-instance',code=1)

    def test_artifact_static_factory(self):
        self.mutate('models/CuikeModels.ets','export class ModelText {','export class ModelText { static shared(): ModelText { return new ModelText(); }')
        self.failure('capability-artifact-instance',code=1)

    def test_unknown_phase_field(self):
        self.contract['declarations'][0]['phase']='onCreate'; self.attach()
        self.failure('capability-declaration-invalid',code=2)

    def test_approved_absence_unsupported(self):
        self.contract['absence']={'reason':'anything'}; self.attach()
        self.failure('capability-absence-unsupported',code=2)

    def test_no_excluded_reason_escape(self):
        self.contract['excluded']=[{'path':self.ets+'services/CuikeStore.ets','reason':'value-only'}]; self.attach()
        self.failure('capability-declaration-invalid',code=2)

    def test_duplicate_json_key(self):
        path=self.base/'plans/base-plan.md'; text=path.read_text(encoding='utf-8')
        path.write_text(text.replace('"seams": "none"','"seams": "none", "seams": "none"'),encoding='utf-8')
        self.failure('Duplicate JSON key',code=2)

    def test_pending_future_not_gate_success(self):
        path=self.ets+'FutureModel.ets'
        base=next(i for i in self.items if i['item_id']=='BASE:Base-1'); base['ownership'].append(path)
        entry=copy.deepcopy(self.contract['declarations'][-1]); entry.update(key='future',path=path,symbol='FutureModel',provider='base-plan.md#BASE:Base-1',materialization='pending')
        self.contract['declarations'].append(entry); self.attach()
        code,manifest=self.invoke('gen'); self.assertEqual(code,0,manifest); self.assertIn('future',manifest['pending'])
        self.failure('capability-not-materialized',code=1)

    def test_gate_rederives_not_old_manifest(self):
        code,result=self.invoke('gen'); self.assertEqual(code,0,result)
        path=self.project/'spec/execution/capability-manifest.json'; value=json.loads(path.read_text(encoding='utf-8')); value['input_digest']='forged'; write_json(path,value)
        self.failure('capability-digest-mismatch',code=1)

    def test_plan_raw_byte_digest_changes(self):
        code,result=self.invoke('gen'); self.assertEqual(code,0,result)
        path=self.base/'plans/base-plan.md'; path.write_bytes(path.read_bytes()+b'\n<!-- reviewed plan changed -->\n')
        self.failure('capability-digest-mismatch',code=1)

    def test_staged_helper_failure_propagates(self):
        code,result=self.invoke('gen',stage=True); self.assertEqual(code,0,result)
        code,result=self.invoke(stage=True); self.assertEqual(code,0,result)
        self.mutate('services/CuikeStore.ets','return false;','return true;')
        result=self.failure('capability-init-failure-propagation',stage=True,code=1)
        actual=json.loads((self.project/'staged-gate.json').read_text(encoding='utf-8'))
        self.assertEqual(actual,result)
        # Existing pipeline consumes passed, summary.FAIL/WARN, findings.kind.
        self.assertFalse(actual['passed']); self.assertGreater(actual['summary']['FAIL'],0)
        self.assertTrue(all('kind' in finding for finding in actual['findings']))

    def test_v1_reference_only_compatible(self):
        declarations=[]
        for entry in self.contract['declarations']:
            row={k:v for k,v in entry.items() if k!='materialization'}; row['lifecycle']='none'; declarations.append(row)
        self.contract={'declarations':declarations,'seams':'none'}; self.attach()
        self.assertEqual(validate_plan(self.project,self.request)['status'],'PASS')
        self.failure('capability-v2-required',code=2)

    def test_legacy_exact_process_protocol(self):
        fake=self.project/'legacy.py'; fake.write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\nprint("legacy-stderr",file=sys.stderr)\nraise SystemExit(7)\n',encoding='utf-8')
        write_json(self.project/'.migbot/config.json',{'ios_harness':{'spec_contract_version':1}})
        argv=['--project-root',str(self.project),'--unknown','literal-value']
        snippet='from hmigbot_ios.capability_manifest import main; raise SystemExit(main("gate",'+repr(str(fake))+','+repr(argv)+'))'
        env={**os.environ,'PYTHONPATH':str(ROOT/'src')}
        process=subprocess.run([sys.executable,'-B','-c',snippet],capture_output=True,encoding='utf-8',env=env)
        self.assertEqual(process.returncode,7); self.assertEqual(json.loads(process.stdout),argv); self.assertEqual(process.stderr,'legacy-stderr\n')
        print(json.dumps({'probe':'legacy_exact','returncode':process.returncode,'argv_exact':True,'stdout_stderr_exact':True}))


class FrameworkRegistrationTests(unittest.TestCase):
    task=CapabilityClosureTests.task
    write_plans=CapabilityClosureTests.write_plans
    responsibility=CapabilityClosureTests.responsibility
    tearDown=CapabilityClosureTests.tearDown
    attach=CapabilityClosureTests.attach
    mutate=CapabilityClosureTests.mutate
    invoke=CapabilityClosureTests.invoke
    failure=CapabilityClosureTests.failure

    def setUp(self):
        CapabilityClosureTests.setUp(self)
        path=os.environ.get('HMIGBOT_C7_FRAMEWORK_SOURCE')
        if not path:self.skipTest('Explicit frozen framework source/registration snapshot required')
        shutil.copytree(Path(path)/'entry',self.project/'entry',dirs_exist_ok=True)
        for symbol,relative in [('CuikeFormAbility','formability/CuikeFormAbility.ets'),('OpenLastRecipeIntentExecutor','insightintents/OpenLastRecipeIntentExecutor.ets')]:
            full=self.ets+relative
            self.items[2]['ownership'].append(full)
            self.contract['declarations'].append({'key':'framework.'+symbol,'kind':'framework-created','symbol':symbol,'path':full,
                'slot':'','lifecycle':[],'provider':'slice-01-F001.md#SLICE:F001:3c','provenance':'real SDK base and exact frozen registration','materialization':'materialized'})
        self.request['tasks'][1]=self.task('counter',[i for i in self.items if i['item_id'].startswith(('UI:','SLICE:'))],parents=['base'],mapping_reason='UI/scoped/framework ownership in isolated feature')
        self.attach()

    def test_framework_real_sources_and_registration(self):
        self.assertEqual(validate_plan(self.project,self.request)['status'],'PASS')
        code,result=self.invoke('gen');self.assertEqual(code,0,result)
        self.assertIn('entry/src/main/module.json5',result['source_evidence'])
        self.assertIn('entry/src/main/resources/base/profile/insight_intent.json',result['source_evidence'])
        code,gate=self.invoke();self.assertEqual(code,0,gate)

    def test_framework_wrong_form_type(self):
        path=self.project/'entry/src/main/module.json5';value=json.loads(path.read_text(encoding='utf-8'));value['module']['extensionAbilities'][0]['type']='service';write_json(path,value)
        self.failure('capability-framework-registration-mismatch',code=1)

    def test_framework_wrong_form_srcEntry(self):
        path=self.project/'entry/src/main/module.json5';value=json.loads(path.read_text(encoding='utf-8'));value['module']['extensionAbilities'][0]['srcEntry']='./ets/formability/Other.ets';write_json(path,value)
        self.failure('capability-framework-registration-mismatch',code=1)

    def test_framework_fake_sdk_base(self):
        self.mutate('formability/CuikeFormAbility.ets',"from '@kit.FormKit'","from '@kit.AbilityKit'")
        self.failure('capability-framework-base-unsupported',code=2)

    def test_framework_sdk_aliases(self):
        self.mutate('formability/CuikeFormAbility.ets','{ FormExtensionAbility,','{ FormExtensionAbility as FormBase,')
        self.mutate('formability/CuikeFormAbility.ets','extends FormExtensionAbility','extends FormBase')
        self.mutate('insightintents/OpenLastRecipeIntentExecutor.ets','{ InsightIntentEntry, InsightIntentEntryExecutor,','{ InsightIntentEntry as EntryTag, InsightIntentEntryExecutor as EntryBase,')
        self.mutate('insightintents/OpenLastRecipeIntentExecutor.ets','@InsightIntentEntry(','@EntryTag(')
        self.mutate('insightintents/OpenLastRecipeIntentExecutor.ets','extends InsightIntentEntryExecutor<void>','extends EntryBase<void>')
        code,result=self.invoke();self.assertEqual(code,0,result)

    def test_framework_missing_decorator(self):
        path=self.project/(self.ets+'insightintents/OpenLastRecipeIntentExecutor.ets');text=path.read_text(encoding='utf-8');first=text.index('@InsightIntentEntry(');last=text.index('export default class',first)
        path.write_text(text[:first]+text[last:],encoding='utf-8')
        self.failure('capability-framework-decorator-missing',code=1)

    def test_framework_wrong_profile_srcEntry(self):
        path=self.project/'entry/src/main/resources/base/profile/insight_intent.json';write_json(path,{'insightIntentsSrcEntry':[{'srcEntry':'./ets/insightintents/Other.ets'}]})
        self.failure('capability-framework-registration-mismatch',code=1)

    def test_framework_manual_new(self):
        path=self.project/(self.ets+'formability/CuikeFormAbility.ets');path.write_text(path.read_text(encoding='utf-8')+'\nexport function manual(): CuikeFormAbility { return new CuikeFormAbility(); }',encoding='utf-8')
        self.failure('capability-framework-manual-instance',code=1)

    def test_framework_registration_raw_digest(self):
        code,result=self.invoke('gen');self.assertEqual(code,0,result)
        path=self.project/'entry/src/main/resources/base/profile/insight_intent.json';path.write_bytes(path.read_bytes()+b'\n')
        self.failure('capability-digest-mismatch',code=1)


    def test_framework_staged_registration_failure(self):
        code,result=self.invoke('gen');self.assertEqual(code,0,result)
        path=self.project/'entry/src/main/module.json5';value=json.loads(path.read_text(encoding='utf-8'));value['module']['extensionAbilities'][0]['type']='service';write_json(path,value)
        result=self.failure('capability-framework-registration-mismatch',stage=True,code=1)
        self.assertEqual(json.loads((self.project/'staged-gate.json').read_text(encoding='utf-8')),result)


class DirectedReworkTests(unittest.TestCase):
    """Fresh gen then gate for the four independent-review counterexamples."""
    task=CapabilityClosureTests.task
    write_plans=CapabilityClosureTests.write_plans
    responsibility=CapabilityClosureTests.responsibility
    tearDown=CapabilityClosureTests.tearDown
    setUp=CapabilityClosureTests.setUp
    attach=CapabilityClosureTests.attach
    mutate=CapabilityClosureTests.mutate
    invoke=CapabilityClosureTests.invoke

    def mutate(self,path,before,after):
        target=self.project/(self.ets+path); original=target.read_bytes()
        newline='\r\n' if b'\r\n' in original else '\n'
        old=before.replace('\n',newline).encode('utf-8')
        new=after.replace('\n',newline).encode('utf-8')
        self.assertEqual(original.count(old),1)
        changed=original.replace(old,new,1);target.write_bytes(changed)
        print(json.dumps({'probe':self._testMethodName,'mutation_path':path,
            'before_sha256':hashlib.sha256(original).hexdigest(),
            'after_sha256':hashlib.sha256(changed).hexdigest(),'single_byte_substitution':True}))

    def rejected_fresh(self, expected):
        manifest=self.project/'spec/execution/capability-manifest.json'
        self.assertFalse(manifest.exists())
        for kind in ('gen','gate'):
            code,result=self.invoke(kind)
            self.assertNotEqual(code,0,result)
            self.assertFalse(result['passed'])
            self.assertIn(expected,json.dumps(result))
            self.assertNotIn('capability-digest-mismatch',json.dumps(result))
        self.assertFalse(manifest.exists())

    def test_rework_c31_01_original_dead_constructor_assignment(self):
        self.mutate('services/CuikeStore.ets',
            'constructor(settings: CuikePreferences) { this.settings = settings; }',
            'constructor(settings: CuikePreferences) { if (false) { this.settings = settings; } }')
        self.rejected_fresh('capability-injection-control-unsupported')

    def test_rework_c31_02_original_dead_success_clear(self):
        self.mutate('services/CuikeStore.ets','this.startupError = null;',
            'if (false) { this.startupError = null; }')
        self.rejected_fresh('capability-init-success-control-unsupported')

    def test_rework_c31_03_original_finally_overrides_failure(self):
        self.mutate('services/CuikeStore.ets',
            'this.startupError = this.errorMessage(error);\n      return false;\n    }',
            'this.startupError = this.errorMessage(error);\n      return false;\n    } finally { return true; }')
        self.rejected_fresh('capability-init-exit-control-unsupported')

    def test_rework_c31_04_original_compound_table_write(self):
        path=self.project/(self.ets+'pages/Index.ets')
        original=path.read_bytes()
        changed=original+b'\nexport function mutate(): void { capabilityTable.store &&= capabilityTable.store; }\n'
        path.write_bytes(changed)
        print(json.dumps({'probe':self._testMethodName,'mutation_path':self.ets+'pages/Index.ets',
            'before_sha256':hashlib.sha256(original).hexdigest(),
            'after_sha256':hashlib.sha256(changed).hexdigest(),'single_byte_append':True}))
        self.rejected_fresh('capability-table-mutated')


class AdditionalLexicalBoundaryTests(unittest.TestCase):
    task=CapabilityClosureTests.task
    write_plans=CapabilityClosureTests.write_plans
    responsibility=CapabilityClosureTests.responsibility
    tearDown=CapabilityClosureTests.tearDown
    setUp=CapabilityClosureTests.setUp
    attach=CapabilityClosureTests.attach
    invoke=CapabilityClosureTests.invoke
    rejected_fresh=DirectedReworkTests.rejected_fresh

    def append_contrast(self, expression):
        path=self.project/(self.ets+'pages/Index.ets');original=path.read_bytes()
        changed=original+('\nexport function syntaxContrast(): void { '+expression+'; }\n').encode()
        path.write_bytes(changed)
        print(json.dumps({'probe':self._testMethodName,'expression':expression,
            'before_sha256':hashlib.sha256(original).hexdigest(),
            'after_sha256':hashlib.sha256(changed).hexdigest()}))

    def test_additional_true_inequality_read_is_preserved(self):
        self.append_contrast('capabilityTable.store != capabilityTable.store')
        for kind in ('gen','gate'):
            code,result=self.invoke(kind);self.assertEqual(code,0,result)

    def test_additional_exact_non_null_assignment_rejected(self):
        self.append_contrast('capabilityTable.store! = capabilityTable.store')
        self.rejected_fresh('capability-table-mutated')
