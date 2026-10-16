"""Reproduce a neutral profile-2 migration through the shipped state writers.

This is an authored evaluation, not an autonomous migration success benchmark.
The source oracle is [0, 1, 2] from Counter.swift:3,7. The host test executes
production CounterModel.ets; ArkUI/device and iOS source execution stay unverified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))

from hmigbot_ios.core import MigrationError, digest, json_bytes, read_json, snapshot, write_json
from hmigbot_ios.native_pipeline import configure, index_source, tool_config
from hmigbot_ios.ios_harness import initialize, check, ac_inventory
from hmigbot_ios.ios_facts import refresh, RULES
from hmigbot_ios.ios_literals import run as literals
from hmigbot_ios.native_semantics import required_facts
from hmigbot_ios.expertise import prepare, record
from hmigbot_ios.ios_scheduler import generate as plan_ir, step
from hmigbot_ios.generate import generate as scaffold
from hmigbot_ios.build import build_target
from hmigbot_ios.behavior import verify
from spec_contract_fixture import strict_contract


PAGE = 'entry/src/main/ets/pages/CounterPage.ets'
MODEL = 'entry/src/main/ets/models/CounterModel.ets'
MODEL_SOURCE = '''export class CounterModel {
  count: number = 0;
  add(): number {
    this.count += 1;
    return this.count;
  }
}
'''
PAGE_SOURCE = '''import { CounterModel } from '../models/CounterModel';

@Entry
@Component
struct CounterPage {
  private model: CounterModel = new CounterModel();
  @State private count: number = 0;
  private add(): void {
    this.count = this.model.add();
  }
  build() {
    Column() {
      Text($r('app.string.count_text', this.count))
      Button($r('app.string.add_text'))
        .onClick(() => { this.add(); })
    }
  }
}
'''


def author_contract(target):
    # This seed preserves canonical headings; all behavior-specific additions,
    # mappings and limitations below were authored after reading Counter.swift.
    strict_contract(target)
    base = target / 'spec/baseline'
    for path in base.rglob('*.md'):
        text = path.read_text(encoding='utf-8').replace('Counter.swift:1-10', 'Counter.swift:1-16')
        text = text.replace('this ten-line counter fixture', 'this sixteen-line native app')
        path.write_text(text, encoding='utf-8')
    feature = base / 'features/F001-counter.md'
    text = feature.read_text(encoding='utf-8')
    text = text.replace('## 数据流\n', '## 数据流\nCounterApplication @main -> WindowGroup -> Counter; source: Counter.swift:11-15.\n')
    text = text.replace('| `CounterPage.add(): void` |', '| `CounterModel.add(): number` |')
    text = text.replace('increment count by 1 |', 'increment count by 1 and return the next count |')
    text = text.replace('CounterPage.onAdd -> CounterPage.add() -> CounterPage.count -> displayed Count text.',
        'CounterPage Button -> CounterPage.add -> CounterModel.add -> CounterPage.count -> Count text.\n'
        'CounterModel is created once per page instance; page state starts at 0. No global/shared instance.\n'
        'Evaluated numeric range: 0..2; full Swift Int overflow/large integer equivalence remains unverified.')
    text = text[:text.index('## 验收标准')] + '''## 验收标准
- [ ] F001-AC01 从初值0依次调用两次Add，业务状态依次为0、1、2 `源:Counter.body → 标:CounterModel.add` `判:unit | counts=[0,1,2]，加2或丢失更新必须失败` `真:src:Counter.swift:3`
- [ ] F001-AC02 App进入显示Count:0，点击Add后同页显示Count:1 `源:Counter.body → 标:CounterPage.add` `判:ui | 实际控件点击后文本从Count:0变为Count:1` `真:src:Counter.swift:7`

## 动作合同
not_applicable: one synchronous page-local increment; no cross-page or asynchronous action; source: Counter.swift:3-9

## API 接口
not_applicable: the complete native app has no network, external service or storage API; source: Counter.swift:1-16
'''
    # Both the model public method and the UI event are declared target contracts.
    text = text.replace('## 状态管理',
        '| Counter Button | `CounterModel.add` | return count + 1; Counter.swift:7 | equivalent | D0 |\n'
        '\n## 状态管理')
    feature.write_text(text, encoding='utf-8')
    page = base / 'ui/page_0001_Counter.md'
    text = page.read_text(encoding='utf-8').replace('F001-AC01;', 'F001-AC02;')
    text = text.replace('CounterPage.onAdd invokes CounterPage.add', 'Button.onClick invokes CounterPage.add')
    text += '\nCounterApplication WindowGroup is the source entry; page lifetime owns model and visible count.\n'
    page.write_text(text, encoding='utf-8')
    base_doc = base / 'feature-base.md'
    text = base_doc.read_text(encoding='utf-8')
    category_bodies = {
        '数据库与文件恢复': 'not_applicable: no database/file save or reload exists; a new root initializes count to 0; source: Counter.swift:1-16',
        '网络与外部合同': 'not_applicable: no request, remote response, external application or SDK call exists; source: Counter.swift:1-16',
        '事件系统': 'Button Add directly invokes its synchronous closure; no application event bus or observer subscription. Source: Counter.swift:7.',
        '偏好设置': 'not_applicable: no UserDefaults/preferences key is read or written; source: Counter.swift:1-16',
        '权限声明': 'not_applicable: this sample performs no protected capability or permission request; source: Counter.swift:1-16',
        '公共组件与资源': 'No reusable child component. Page-local Count format and Add label map to app.string.count_text and app.string.add_text in Base-0; source: Counter.swift:6-7. The evaluation scaffold icon is a demo artifact, not evidence of migrated source app identity.',
    }
    for title, body in category_bodies.items():
        start = text.index('## ' + title + '\n') + len('## ' + title + '\n')
        end = text.find('\n## ', start)
        text = text[:start] + body + '\n' + (text[end:] if end != -1 else '')
    text = text.replace('| CounterPage.add | void/no error |', '| CounterModel.add | next count/no error |')
    base_doc.write_text(text, encoding='utf-8')
    index = base / 'feature-index.md'
    index.write_text(index.read_text(encoding='utf-8').replace('| base | base |', '| base | 无 |'), encoding='utf-8')


def source_semantics(target, graph):
    descriptions = {
        'state_transitions': {'initial': 0, 'transition': 'count += 1 synchronously for each Add', 'scope': 'Swift Int domain; 0..2 evaluated'},
        'data_flow': {'input': 'Add action', 'processing': 'read current count then increment', 'observable': 'Text consumes count; no persistence'},
        'composition': {'tree': 'CounterApplication.WindowGroup > Counter > VStack > Text, Button'},
        'layout': {'axis': 'vertical VStack', 'spacing': 'native default, no source literal', 'safe_area': 'native default', 'visual': 'not_run'},
        'events': {'input': 'Button Add', 'processing': 'page-local count += 1', 'feedback': 'Count interpolation invalidates body'},
    }
    absent = {
        'error_behavior': 'No throwing/error branch in Counter.swift:1-16; integer overflow behavior not evaluated.',
        'navigation': 'The only root is WindowGroup Counter; no links, routes or overlays in lines 1-16.',
        'binding_flow': 'No Binding or projected child state in lines 1-16; count is local @State.',
        'environment': 'No environment injection or reads in lines 1-16.',
        'task_lifetime': 'No task/await/callback in lines 1-16.',
        'modifier_order': 'No chained modifiers in lines 1-16.',
        'concurrency': 'Add is a synchronous closure; no application-created task in lines 1-16.',
        'persistence': 'No storage API/key/read/write in lines 1-16; root recreation starts at zero.',
        'platform_capabilities': 'No permission or platform service invocation in lines 1-16.',
        'optionality': 'No optional value, nil/default branch or force unwrap in lines 1-16.',
    }
    documents = []
    for ident, kind in [('F001', 'feature'), ('page_0001', 'page')]:
        claims = {}
        for dimension in sorted(required_facts(kind, {'swift'}, {'swiftui'})):
            relevant = [f for f in graph['facts'] if dimension in RULES[f['kind']]['dimensions']]
            if relevant:
                value = descriptions.get(dimension, {'source_rule': 'Counter.swift:3,7; synchronous page-owned integer state and Add action'})
                if dimension == 'state_ownership':
                    value = {'states': [{'fact_id': f['id'], 'owner': f['owner'], **f['value']} for f in relevant if f['kind'] == 'state']}
                claims[dimension] = {'status': 'known', 'value': value,
                    'fact_ids': [f['id'] for f in relevant], 'evidence': [{'path': f['anchor']['path'], 'line': f['anchor']['line']} for f in relevant]}
            elif dimension in absent:
                claims[dimension] = {'status': 'not_applicable', 'reason': absent[dimension]}
            else:
                # A structured claim may link an existing composition/state locator
                # when the lexical extractor has no dedicated signal for this fact.
                locator = next(f for f in graph['facts'] if f['kind'] == 'state')
                detail = {
                    'entrypoints': 'CounterApplication @main and WindowGroup mount Counter, lines 11-15.',
                    'identity': 'Single Counter root position; @State survives body recomputation, resets on root recreation.',
                    'accessibility': 'Source uses native Text/Button labels, no custom accessibility override; device behavior not run.',
                    'lifetime': 'Counter @State count lives with view identity; no global or storage restore.',
                    'value_reference_semantics': 'Counter is a View struct; SwiftUI owns @State storage, not an arbitrary copied global.',
                    'concurrency_model': 'No tasks/actors/Sendable transfer in complete source; Add runs in native view action context.',
                }[dimension]
                claims[dimension] = {'status': 'known', 'value': {'source_rule': detail},
                    'fact_ids': [locator['id']], 'evidence': [{'path': locator['anchor']['path'], 'line': locator['anchor']['line']}]}
        documents.append({'id': ident, 'kind': kind, 'languages': ['swift'], 'frameworks': ['swiftui'], 'facts': claims})
    base = target / 'spec/baseline'
    write_json(base / 'ios-semantics.json', {'schema_version': 2, 'source_platform': 'ios', 'documents': documents})
    obs = read_json(base / 'ios-obligations.json')['obligations']
    by_id = {f['id']: f for f in graph['facts']}
    write_json(base / 'ios-coverage.json', {'schema_version': 2, 'graph_sha256': digest(json_bytes(graph)),
        'mappings': [{'obligation_id': o['id'], 'ac_ids': ['F001-AC02'] if by_id[o['fact_id']]['kind'] in {'event', 'composition'} else ['F001-AC01'],
            'source_review': {'status': 'reviewed', 'input': 'Mount Counter and tap Add',
                'processing': 'Initialize @State count=0; each Add increments the current value by one synchronously',
                'observable': 'Count text reads the resulting count; business prefix is 0,1,2',
                'reviewer': '/root/fix_raw_strings'}} for o in obs]})


def responsibility(item):
    return '\n### ' + item['item_id'] + '\n| 字段 | 值 |\n|---|---|\n' + ''.join(
        '| ' + field + ' | ' + json.dumps(value, ensure_ascii=False) + ' |\n' for field, value in item.items())


def write_plans(target, graph, base_outputs):
    acs = ['F001-AC01', 'F001-AC02']
    items = [
        dict(item_id='BASE:Base-0', ac_ids=[], ownership=sorted(base_outputs), parents=[], page_ids=[], scope='product', verification='generated'),
        dict(item_id='UI:PAGE-0001', ac_ids=['F001-AC02'], ownership=[PAGE], parents=['BASE:Base-0'], page_ids=['page_0001'], scope='product', verification='generated'),
        dict(item_id='SLICE:F001:3a', ac_ids=['F001-AC01'], ownership=[MODEL], parents=['BASE:Base-0'], page_ids=['page_0001'], scope='product', verification='generated'),
        dict(item_id='FV:FV-1', ac_ids=acs, ownership=[], parents=['UI:PAGE-0001', 'SLICE:F001:3a'], page_ids=[], scope='product', verification='compile'),
        dict(item_id='FV:FV-2', ac_ids=acs, ownership=[], parents=['FV:FV-1'], page_ids=[], scope='product', verification='compile'),
    ]
    plans = target / 'spec/baseline/plans'
    (plans / 'slices').mkdir(parents=True)
    for prefix, filename, context in [
        ('BASE:', 'base-plan.md', 'Create the explicit SDK 26.0.0 scaffold, actual string resources and CounterPage registration.'),
        ('UI:', 'ui-plan.md', 'Preserve VStack/Text/Button order and page lifetime; Button calls add, model result refreshes @State count.'),
        ('SLICE:', 'slices/slice-01-F001.md', 'Implement synchronous CounterModel.add from Counter.swift:3,7. No persistence, async, global store or invented reset.'),
        ('FV:', 'feature-plan.md', 'Check imports/registration/wiring first, then run actual hvigor assembleHap. Device UI is unavailable.'),
    ]:
        selected = [i for i in items if i['item_id'].startswith(prefix)]
        text = '# Counter migration plan\nplan_format: indexed-v1\n\n## Context\n' + context + '\n'
        if prefix == 'FV:': text += '\n## Base\ndetail: plans/base-plan.md\n\n## F001\ndetail: plans/slices/slice-01-F001.md\n'
        if prefix == 'UI:': text += '\n## Batch 1\n| item_id | 目标文件 | ac_ids | owning_slice |\n|---|---|---|---|\n| PAGE-0001 | ' + PAGE + ' | ["F001-AC02"] | F001 |\n'
        for item in selected: text += responsibility(item)
        text += '\n```json\n' + json.dumps({'plan_items_version': 2, 'items': selected}, ensure_ascii=False, indent=2) + '\n```\n'
        (plans / filename).write_text(text, encoding='utf-8')
    request = {'schema_version': 2, 'wave': 'domains', 'graph_sha256': digest(json_bytes(graph)), 'max_parallel': 1,
        'tasks': []}
    for ident, selected, parents in [('base', items[:1], []), ('counter', items[1:3], ['base']), ('final', items[3:], ['counter'])]:
        task = {'id': ident, 'role': 'a2h-ios-converter' if ident == 'counter' else 'a2h-closer',
            'goal': {'base': 'Create the Counter scaffold and register exact resources', 'counter': 'Implement Counter model and page from frozen source contracts', 'final': 'Inspect wiring and compile the actual Counter HAP'}[ident],
            'fact_ids': [f['id'] for f in graph['facts']], 'ac_ids': sorted({a for item in selected for a in item['ac_ids']}),
            'ownership': sorted({p for item in selected for p in item['ownership']}), 'parents': parents,
            'plan_item_refs': [i['item_id'] for i in selected], 'verification': selected[-1]['verification']}
        if len(selected) > 1: task['mapping_reason'] = 'One owner preserves file ownership while consuming each mapped responsibility in sequence.'
        request['tasks'].append(task)
    return request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--deveco', type=Path, default=Path('D:/Program Files/DevEco Studio'))
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists(): raise SystemExit('Choose a fresh output directory; earlier attempts remain evidence.')
    out.mkdir(parents=True)
    source, target = out / 'source', out / 'target'
    shutil.copytree(HERE / 'sources/counter', source)
    target.mkdir()
    configure(source, target); initialize(target); index_source(target)
    cfg = read_json(target / '.migbot/config.json')
    cfg['tools'] = {'deveco_sdk': str(args.deveco / 'sdk'), 'node': str(args.deveco / 'tools/node/node.exe'),
        'hvigorw': str(args.deveco / 'tools/hvigor/bin/hvigorw.js')}
    write_json(target / '.migbot/config.json', cfg)
    from hmigbot_ios.plan_contract import contract_revision
    evidence_inputs = [
        'skills/ios-source-analysis/references/harness-v2.md',
        'skills/ios-source-analysis/references/native-facts.md',
        'skills/ios-feature-analyzer/references/analysis-v2.md',
        'skills/a2h-plan/references/plan-delivery-contract.md',
        'skills/a2h-spec/templates/page-spec-template.md',
        'skills/ios-ui-to-arkui/SKILL.md',
        'schemas/spec-plan-artifacts.json', 'schemas/ios-harness-v2.schema.json',
        'tests/spec_contract_fixture.py',
    ]
    write_json(out / 'run.json', {'author': '/root/fix_raw_strings',
        'model': 'Inherited parent configuration; exact runtime model id not exposed to this script',
        'generation': 'Single source-read author candidate, replayed through real tools; not an independent model sample',
        'source_sha256': snapshot(source)['sha256'], 'contract_revision': contract_revision(target),
        'tool_inputs': {p: digest((ROOT / p).read_bytes()) for p in evidence_inputs},
        'evaluation_inputs': {p.relative_to(HERE).as_posix(): digest(p.read_bytes()) for p in HERE.rglob('*')
            if p.is_file() and p.suffix in {'.py', '.cjs', '.swift', '.m', '.h', '.xib', '.md', '.json'}
            and '__pycache__' not in p.parts and 'results' not in p.relative_to(HERE).parts},
        'device': 'hdc list targets returned [Empty]; UI and visual not run',
        'source_execution': 'not_run; Windows host has no Xcode/iOS runtime evidence'})
    author_contract(target)
    graph = refresh(target, source); literals(target); source_semantics(target, graph)
    prepare(target)
    expertise = read_json(target / 'spec/ref/ios-expertise-plan.json')
    review_input = out / 'expertise-review.json'
    write_json(review_input, {'plan_sha256': digest(json_bytes(expertise)), 'reviews': [
        {'id': r['id'], 'resources': r['resources'], 'status': 'reviewed', 'reviewer': '/root/fix_raw_strings',
            'observations': [{'source': {'path': p, 'line': 3}, 'interpretation': 'Counter @State is initialized to 0 for the view lifetime; Add synchronously increments current count. @main WindowGroup mounts Counter. No task, storage, custom modifier, navigation or service exists; no device/source execution is claimed.', 'unknowns': ['Device layout and UI behavior not run; Swift Int large-value equivalence not evaluated.']} for p in r['source_paths']]}
        for r in expertise['reviews']]})
    record(target, review_input)
    gate, code = check(target); write_json(out / 'source-gate.json', gate)
    if code: raise SystemExit('Source gate failed; retained source-gate.json')
    scaffold(source, out / 'scaffold', sdk='26.0.0', min_sdk='6.0.2(22)', model_version='6.0.2',
        bundle_name='org.example.wbevaluation', scaffold_only=True)
    base_outputs = {p.relative_to(out / 'scaffold').as_posix(): p.read_bytes() for p in (out / 'scaffold').rglob('*')
        if p.is_file() and not p.relative_to(out / 'scaffold').as_posix().startswith('migration/')
        and p.relative_to(out / 'scaffold').as_posix() != 'entry/src/main/ets/pages/Index.ets'}
    for name in ('AppScope/resources/base/element/string.json', 'entry/src/main/resources/base/element/string.json'):
        base_outputs[name] = base_outputs[name].replace(b'Index', b'Counter')
    ability = 'entry/src/main/ets/entryability/EntryAbility.ets'
    base_outputs[ability] = base_outputs[ability].replace(b'pages/Index', b'pages/CounterPage')
    base_outputs['entry/src/main/resources/base/profile/main_pages.json'] = json_bytes({'src': ['pages/CounterPage']})
    base_outputs['entry/src/main/resources/base/element/string.json'] = json_bytes({'string': [
        {'name': 'entry_label', 'value': 'Counter'}, {'name': 'count_text', 'value': 'Count: %d'}, {'name': 'add_text', 'value': 'Add'}]})
    request = write_plans(target, graph, base_outputs)
    request_path = out / 'typed-plan.json'; write_json(request_path, request)
    write_json(out / 'plan-check.json', plan_ir(target, request_path, validate_only=True))
    write_json(out / 'plan-ir.json', plan_ir(target, request_path))
    actions = []
    for iteration in range(8):
        action, code = step(target, 'domains'); actions.append(action)
        write_json(out / 'actions.json', actions)
        if code: raise SystemExit('Dispatch failed; actions retained.')
        if action['action'] == 'done': break
        if action['action'] != 'dispatch': raise SystemExit('Unexpected scheduler action: ' + action['action'])
        for task in action['batch']:
            ident = task['id']
            definition = next(t for t in request['tasks'] if t['id'] == ident)
            # Read exact pinned headings before applying the evaluated implementation.
            contract = read_json(target / 'spec/blueprint/contracts.json')
            for reference in contract['task_inputs'][ident]:
                if digest((target / reference['path']).read_bytes()) != reference['sha256']:
                    raise RuntimeError('Changed consumption input')
                (target / reference['path']).read_text(encoding='utf-8-sig')
            if ident == 'base': outputs = base_outputs
            elif ident == 'counter': outputs = {PAGE: PAGE_SOURCE.encode(), MODEL: MODEL_SOURCE.encode()}
            else:
                if 'this.count = this.model.add();' not in (target / PAGE).read_text(): raise RuntimeError('Missing page/model wiring')
                build = build_target(tool_config(target), out / 'build', timeout=300)
                if build['status'] != 'build_passed': raise SystemExit('Real hvigor failed; build logs retained.')
                outputs = {}
            for name, data in outputs.items():
                path = target / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            plan_path = target / 'spec/waves/plan-domains.json'
            receipt = {'ios_receipt_version': 2, 'task_id': ident, 'domain': ident,
                'source_sha256': graph['source_sha256'], 'plan_sha256': digest(plan_path.read_bytes()),
                'status': 'generated', 'final_state': 'PASS', 'behavior_verified': False,
                'ac_ids': definition['ac_ids'], 'file_hashes': {p: digest((target / p).read_bytes()) for p in definition['ownership']},
                'files_touched': definition['ownership'], 'fixed': [], 'skipped': [], 'findings': []}
            write_json(target / 'spec/waves/results/domains' / (ident + '.json'), receipt)
        try:
            landed, code = step(target, 'domains', landing=True)
        except MigrationError as error:
            write_json(out / 'failure.json', {'operation': 'land-results', 'error': str(error),
                'exception': type(error).__name__, 'plan_sha256': digest((target / 'spec/waves/plan-domains.json').read_bytes())})
            raise
        actions.append(landed)
        write_json(out / 'actions.json', actions)
        if code: raise SystemExit('Landing failed; retained actions.')
    else: raise SystemExit('Scheduler did not finish.')
    node = str(args.deveco / 'tools/node/node.exe')
    typescript = str(args.deveco / 'tools/hvigor/hvigor/node_modules/typescript/lib/typescript.js')
    command = [node, str(HERE / 'host-behavior.cjs'), typescript, str(target / MODEL)]
    review = read_json(HERE / 'review.json')
    if review['source_sha256'] != graph['source_sha256'] or any(
            digest((target / p).read_bytes()) != expected for p, expected in review['target_hashes'].items()):
        raise RuntimeError('Independent source/target review no longer matches; re-review before claiming an oracle.')
    event = next(f for f in graph['facts'] if f['kind'] == 'event')
    def anchor(path, symbol):
        text = (target / path).read_text(encoding='utf-8')
        line = next(i for i, content in enumerate(text.splitlines(), 1) if symbol in content)
        return {'path': path, 'line': line, 'symbol': symbol, 'sha256': digest((target / path).read_bytes())}
    verification = {'schema_version': 2, 'source_sha256': graph['source_sha256'],
        'chains': [{'source_fact': event['id'], 'input': anchor(PAGE, 'onClick'), 'processing': anchor(MODEL, 'add'),
            'feedback': anchor(PAGE, 'Text'), 'review': {'status': 'reviewed', 'reviewer': review['reviewer']}}],
        'cases': [{'id': 'counter-prefix', 'ac_ids': ['F001-AC01'], 'runner': 'unit', 'command': command,
            'target_hashes': {MODEL: digest((target / MODEL).read_bytes())}, 'input': None,
            'oracle': {'source_fact': next(f['id'] for f in graph['facts'] if f['kind'] == 'state'),
                'expected': review['expected'], 'reviewer': review['reviewer']}}]}
    write_json(target / 'spec/verification/ios-behavior.json', verification)
    behavior, code = verify(target, source, graph, ac_inventory(target), run=True)
    write_json(out / 'behavior.json', behavior)
    mutant = out / 'CounterModel-mutant.ets'
    mutant.write_text(MODEL_SOURCE.replace('+= 1', '+= 2'), encoding='utf-8')
    probe = subprocess.run([*command[:-1], str(mutant)], capture_output=True, check=False)
    write_json(out / 'mutation.json', {'mutation': 'increment +1 becomes +2', 'exit_code': probe.returncode,
        'actual': json.loads(probe.stdout), 'oracle': {'counts': [0, 1, 2]},
        'discriminated': json.loads(probe.stdout) != {'counts': [0, 1, 2]}})
    from hmigbot_ios.quality_views import summary
    result = summary(target, build_evidence=out / 'build/build.json')
    write_json(out / 'summary.json', result)
    print(json.dumps({'output': str(out), 'source_gate': gate['status'], 'scheduler': actions[-1]['action'],
        'build': read_json(out / 'build/build.json')['status'], 'unit_observations': behavior['observations'],
        'behavior': behavior['status'], 'unverified_ac_ids': behavior['unverified_ac_ids']}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
