"""THEF-16 neutral-sample independent behavioral baselines.

Runs the three host oracles (Node + DevEco TypeScript, same pattern as
host-behavior.cjs) against the actual authored target .ets logic for the three
required neutral categories. Aggregates a verification artifact and a summary
with EXPLICIT, SEPARATE denominators:

  * business (normal / normal-cancel / exception) ACs are executed against the
    REAL candidate target. They are the acceptance criteria and a wrong candidate
    must make them FAIL.
  * guard (mutation / missing-evidence) ACs prove the oracle can discriminate a
    real defect. Each guard first proves its mutation actually changed the
    source; a guard whose mutation did not apply is itself a FAIL, never a silent
    GUARD-OK. Guard results are listed separately and never enter the business
    denominator.

This is NOT an autonomous migration success benchmark. Build/device/visual stay
UNVERIFIED (no DevEco HAP build, no iOS/ArkUI device). The oracles verify
business semantics and discriminate mutants; they do not claim UI/device pass.

Use ``--candidate <sample> <path>`` to run a real candidate file (e.g. a broken
disable) as the formal input for a sample; the business AC must then FAIL.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import digest

TS = Path(r'D:/Program Files/DevEco Studio/tools/hvigor/hvigor/node_modules/typescript/lib/typescript.js')
NODE = r'D:/Program Files/nodejs/node.exe'

SAMPLES = [
    ('binding-navigation', 'host-binding.cjs', HERE / 'targets/binding-navigation/EnabledStore.ets',
     ['sources/binding-navigation/BindingNavigation.swift']),
    ('uikit-ib', 'host-uikit.cjs', HERE / 'targets/uikit-ib/CounterController.ets',
     ['sources/uikit-ib/CounterController.h', 'sources/uikit-ib/CounterController.m', 'sources/uikit-ib/CounterController.xib']),
    ('cross-page-async', 'host-async.cjs', HERE / 'targets/cross-page-async/SharedSave.ets',
     ['sources/cross-page-async/SharedSave.swift']),
]

BUSINESS_KINDS = {'normal', 'normal-cancel', 'exception'}
GUARD_KINDS = {'mutation', 'missing-evidence'}


def run_oracle(script, target):
    cmd = [NODE, str(HERE / script), str(TS), str(target)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(HERE))
    if proc.returncode != 0:
        raise RuntimeError(f'{script} failed rc={proc.returncode}: {proc.stderr[:500]}')
    return json.loads(proc.stdout)


def status_for(case):
    # Business -> PASS/FAIL ; guard -> GUARD-OK (discriminated) / FAIL.
    if case['kind'] in BUSINESS_KINDS:
        return 'PASS' if case['pass'] else 'FAIL'
    return 'GUARD-OK' if case['pass'] else 'FAIL'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--candidate', nargs=2, action='append', default=[],
                    metavar=('SAMPLE', 'PATH'),
                    help='Run a real candidate file as formal input for SAMPLE (repeatable).')
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)

    overrides = {name: Path(p).resolve() for name, p in args.candidate}

    chains, cases_all = [], []
    business = {'PASS': 0, 'FAIL': 0}
    guard = {'GUARD-OK': 0, 'FAIL': 0}
    for sample, script, target, sources in SAMPLES:
        effective_target = overrides.get(sample, target)
        result = run_oracle(script, effective_target)
        src_sha = {s: digest((HERE.parent / s).read_bytes()) for s in sources}
        tgt_sha = digest(effective_target.read_bytes())
        for c in result['cases']:
            st = status_for(c)
            if c['kind'] in BUSINESS_KINDS:
                business[st] += 1
            else:
                guard[st] += 1
            cases_all.append({**c, 'sample': sample, 'status': st,
                'source_sha256': src_sha, 'target_sha256': tgt_sha,
                'target_path': str(effective_target)})
        chains.append({'sample': sample, 'source': result['source'],
            'target': str(effective_target), 'source_sha256': src_sha, 'target_sha256': tgt_sha,
            'case_ids': [c['id'] for c in result['cases']],
            'candidate_override': str(effective_target) != str(target)})

    verification = {
        'schema_version': 2,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'tool': 'neutral_baselines.py (host oracles, DevEco TS transpile + Node vm)',
        'denominators': {'business': business, 'guard': guard},
        'chains': chains,
        'cases': cases_all,
        'honest_limits': {
            'build': 'UNVERIFIED: no HarmonyOS HAP build run; contract forbids building user app.',
            'device': 'UNVERIFIED: hdc list targets = [Empty]; no iOS/ArkUI device execution or visual alignment.',
            'source_execution': 'UNVERIFIED: Windows host has no Xcode; Swift/ObjC not compiled or run.'}}

    # ACs requiring real device/build evidence are explicitly UNVERIFIED here.
    unverified_build_device = []
    for cat, body in json.loads((HERE / 'neutral-acs.json').read_text(encoding='utf-8'))['categories'].items():
        for ac in body['acs']:
            if ac['judgment'] == 'ui':
                unverified_build_device.append(ac['id'])

    any_fail = (business['FAIL'] > 0) or (guard['FAIL'] > 0)
    summary = {
        'schema_version': 2,
        'business_acs': sum(business.values()),
        'guard_acs': sum(guard.values()),
        'total_acs': sum(business.values()) + sum(guard.values()),
        'business': business,
        'guard': guard,
        'denominator_note': 'Business (normal/normal-cancel/exception) ACs run on the REAL candidate and are the acceptance criteria; guard (mutation/missing-evidence) ACs prove the oracle discriminates and are listed separately, not in the business denominator.',
        'unverified_build_device_ac_ids': unverified_build_device,
        'build_status': 'UNVERIFIED',
        'device_status': 'UNVERIFIED',
        'source_execution_status': 'UNVERIFIED',
        'verdict': 'FAIL: a business or guard AC did not pass.' if any_fail
                   else f'host-logic PASS for {sum(business.values())} business + {sum(guard.values())} guard ACs; build/device/source-exec UNVERIFIED.'}

    write = lambda p, o: (p.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding='utf-8'))
    write(out / 'neutral-verification.json', verification)
    write(out / 'neutral-summary.json', summary)
    print(json.dumps({'business': business, 'guard': guard, 'build': 'UNVERIFIED',
        'device': 'UNVERIFIED', 'source_exec': 'UNVERIFIED', 'verdict': summary['verdict']},
        ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
