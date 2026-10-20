"""THEF-16 neutral evidence -> real tool consumption (behavior.verify).

Builds a minimal, valid migration project that reuses the exact host oracles and
feeds their results into the shipped behavior gate ``behavior.verify`` (the same
evidence-consumption entry used by run_evaluation.py). It does NOT invent a new
summarizer: behavior.verify executes each neutral case command and decides
PASS/FAIL from the real output, rejecting stale / missing / wrong-object evidence
and the broken disable candidate.

Usage:
  neutral_consume.py --output <dir> [--candidate binding-navigation <broken.ets>]
"""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import digest, snapshot, read_json, write_json, safe_child
from hmigbot_ios.behavior import verify as behavior_verify
from neutral_runtime import add_runtime_options, resolve_runtime

TS = Path(r'D:/Program Files/DevEco Studio/tools/hvigor/hvigor/node_modules/typescript/lib/typescript.js')
NODE = r'D:/Program Files/nodejs/node.exe'
SOURCES = HERE.parent / 'sources'

# (sample, script, source_rel, target_rel_under_neutral, chain_symbols)
SAMPLES = [
    ('binding-navigation', 'host-binding.cjs', 'sources/binding-navigation/BindingNavigation.swift',
     'targets/binding-navigation/EnabledStore.ets',
     {'input': 'disable', 'processing': 'toggle', 'feedback': 'toggle'}),
    ('uikit-ib', 'host-uikit.cjs', 'sources/uikit-ib/CounterController.m',
     'targets/uikit-ib/CounterController.ets',
     {'input': 'add', 'processing': 'viewDidLoad', 'feedback': 'add'}),
    ('cross-page-async', 'host-async.cjs', 'sources/cross-page-async/SharedSave.swift',
     'targets/cross-page-async/SharedSave.ets',
     {'input': 'save', 'processing': 'cancel', 'feedback': 'cancel'}),
]

BUSINESS_KINDS = {'normal', 'normal-cancel', 'exception'}
REVIEWER = 'THEF-16-rework'


def line_of(text, symbol):
    for i, line in enumerate(text.splitlines(), 1):
        if symbol in line.split():
            return i
    # fallback: substring (handles method signatures)
    for i, line in enumerate(text.splitlines(), 1):
        if symbol in line:
            return i
    raise RuntimeError(f'symbol {symbol!r} not found in target')


def build_project(out, overrides):
    project = out / 'project'
    if project.exists():
        if (project.is_symlink() or (hasattr(project, 'is_junction') and project.is_junction())
                or project.resolve().parent != out.resolve()):
            raise RuntimeError('Evaluation project cleanup must stay inside the selected output directory')
        shutil.rmtree(project)
    project.mkdir(parents=True)
    (project / '.migbot').mkdir(parents=True)
    write_json(project / '.migbot/config.json', {'ios_harness': {'spec_contract_version': 1}})
    (project / 'spec/neutral-targets').mkdir(parents=True)
    (project / 'spec/baseline/features').mkdir(parents=True)
    (project / 'spec/verification').mkdir(parents=True)
    target_paths, cases_all, chains, facts, ac_lines = {}, [], [], {}, {s[0]: [] for s in SAMPLES}

    for sample, script, source_rel, target_rel, syms in SAMPLES:
        src_file = (HERE.parent / source_rel)
        tgt_src = overrides.get(sample, HERE / target_rel)
        tgt_dst = project / 'spec/neutral-targets' / (sample + '.ets')
        shutil.copyfile(tgt_src, tgt_dst)
        tgt_rel = tgt_dst.relative_to(project).as_posix()
        tgt_sha = digest(tgt_dst.read_bytes())
        target_paths[sample] = (tgt_dst, tgt_rel, tgt_sha)

        proc = subprocess.run([NODE, str(HERE / script), str(TS), str(tgt_dst)],
                              capture_output=True, text=True, encoding='utf-8', cwd=str(HERE))
        if proc.returncode != 0:
            raise RuntimeError(f'{script} failed: {proc.stderr[:400]}')
        result = json.loads(proc.stdout)
        text = tgt_dst.read_text(encoding='utf-8-sig')
        # one event fact per sample, linked by a real behavior chain
        fact_id = 'NEUTRAL-EV-' + sample.upper()
        facts[sample] = {'id': fact_id, 'kind': 'event',
                         'anchor': {'path': source_rel, 'line': 1}}
        chain_nodes = {}
        for key, sym in syms.items():
            chain_nodes[key] = {'path': tgt_rel, 'line': line_of(text, sym),
                                'symbol': sym, 'sha256': tgt_sha}
        chains.append({'source_fact': fact_id, **chain_nodes,
                       'review': {'status': 'reviewed', 'reviewer': REVIEWER}})
        for c in result['cases']:
            ac_lines[sample].append(c['id'])
            if c['kind'] in BUSINESS_KINDS:
                expected = c['expected']
            else:
                expected = {'mutant_applied': True, 'discriminated': True}
            cases_all.append({
                'id': c['id'], 'ac_ids': [c['id']], 'runner': 'unit',
                'command': [sys.executable, str(HERE / 'neutral_case_runner.py'),
                            '--node', NODE, str(HERE / script), str(TS), str(tgt_dst), c['id']],
                'timeout_seconds': 60, 'input': None,
                'target_hashes': {tgt_rel: tgt_sha},
                'oracle': {'source_fact': fact_id, 'expected': expected, 'reviewer': REVIEWER}})

    # Stable AC inventory (real acceptance criteria consumed by ac_inventory).
    feature_doc = {
        'binding-navigation': 'SwiftUI @State identity + two-way @Binding across NavigationStack',
        'uikit-ib': 'UIKit/ObjC viewDidLoad init + IBAction add wired to touchUpInside + countLabel outlet',
        'cross-page-async': 'ObservableObject save Task with cancellation, UserDefaults persistence, typed errors',
    }
    anchors = {
        'binding-navigation': 'BindingNavigation.swift', 'uikit-ib': 'CounterController.m',
        'cross-page-async': 'SharedSave.swift'}
    for sample, script, source_rel, target_rel, syms in SAMPLES:
        body = [f'# {sample}', '',
                f'- 源语义：{feature_doc[sample]}（源独立；不来自正在迁移的 App）。', '']
        for ac_id in ac_lines[sample]:
            body.append(f'- [ ] {ac_id} 中性样本稳定 AC，源 {anchors[sample]} `判:unit | 源独立预期 | 真:src:{anchors[sample]}`')
        (project / 'spec/baseline/features' / f'F-{sample}.md').write_text('\n'.join(body) + '\n', encoding='utf-8')

    source_sha = snapshot(SOURCES)['sha256']
    verification = {
        'schema_version': 2, 'source_sha256': source_sha,
        'chains': chains, 'cases': cases_all,
        'scope': 'neutral host-oracle evidence consumed by behavior.verify; build/device/source-exec UNVERIFIED'}
    write_json(project / 'spec/verification/ios-behavior.json', verification)
    return project, source_sha, cases_all


def main():
    global NODE, TS
    ap = argparse.ArgumentParser()
    add_runtime_options(ap)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--candidate', nargs=2, action='append', default=[], metavar=('SAMPLE', 'PATH'))
    args = ap.parse_args()
    NODE, TS, runtime = resolve_runtime(args, ap)
    names = [name for name, _ in args.candidate]
    if len(set(names)) != len(names) or set(names) - {sample[0] for sample in SAMPLES}:
        ap.error('--candidate requires a unique known sample name')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    overrides = {name: Path(p).resolve() for name, p in args.candidate}

    project, source_sha, cases_all = build_project(out, overrides)
    graph = {'source_sha256': source_sha, 'facts': [
        {'id': c['oracle']['source_fact'], 'kind': 'event',
         'anchor': {'path': 'sources', 'line': 1}} for c in cases_all]}
    acs = {c['id']: {'judgment': 'unit', 'body': ''} for c in cases_all}
    report, code = behavior_verify(project, SOURCES, graph, acs, run=True)
    # This metadata describes only the host cases supplied above. It does not
    # promote the hand-authored minimal graph to a refreshed source analysis.
    matrix = read_json(HERE / 'neutral-acs.json')
    kinds = {ac['id']: ac['kind'] for category in matrix['categories'].values()
             for ac in category['acs']}
    denominators = {'business': {'observed_pass': 0, 'observed_fail': 0},
                    'guard': {'observed_pass': 0, 'observed_fail': 0}}
    for observation in report['observations']:
        group = 'business' if kinds[observation['id']] in BUSINESS_KINDS else 'guard'
        denominators[group][observation['status']] += 1
    report['neutral_evaluation'] = {'denominators': denominators, 'runtime': runtime,
        'build': 'UNVERIFIED', 'device_ui': 'UNVERIFIED',
        'source_execution': 'UNVERIFIED', 'source_analysis_chain': 'UNVERIFIED',
        'scope': 'Explicit host-case consumption only; guard results are not business acceptance or App migration acceptance.'}
    write_json(out / 'neutral-behavior-consumed.json', report)
    print(json.dumps({'status': report['status'], 'code': code,
                      'failures': len(report['failures']),
                      'behavior_verified': report.get('behavior_verified'),
                      'denominators': denominators,
                      'scope': report['neutral_evaluation']['scope'],
                      'unverified_ac_ids': report.get('unverified_ac_ids')},
                     ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
