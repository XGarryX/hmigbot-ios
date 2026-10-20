"""THEF-16 neutral-sample independent behavioral baselines.

Runs the three host oracles (Node + DevEco TypeScript, same pattern as
host-behavior.cjs) against the actual authored target .ets logic for the three
required neutral categories. Aggregates a verification artifact and a summary
with explicit denominators and honest UNVERIFIED items.

This is NOT an autonomous migration success benchmark. Build/device/visual stay
UNVERIFIED (no DevEco HAP build, no iOS/ArkUI device). The oracles verify
business semantics and discriminate mutants; they do not claim UI/device pass.
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


def run_oracle(script, target):
    cmd = [NODE, str(HERE / script), str(TS), str(target)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(HERE))
    if proc.returncode != 0:
        raise RuntimeError(f'{script} failed rc={proc.returncode}: {proc.stderr[:500]}')
    return json.loads(proc.stdout)


def status_for(case):
    # normal -> PASS/FAIL ; mutation/missing-evidence -> pass means baseline
    # correctly discriminated/rejected a real defect (GUARD-OK), else FAIL.
    if case['kind'] == 'normal' or case['kind'] == 'normal-cancel' or case['kind'] == 'exception':
        return 'PASS' if case['pass'] else 'FAIL'
    return 'GUARD-OK' if case['pass'] else 'FAIL'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)

    chains, cases_all = [], []
    total = 0
    counts = {'PASS': 0, 'FAIL': 0, 'GUARD-OK': 0}
    for sample, script, target, sources in SAMPLES:
        result = run_oracle(script, target)
        src_sha = {s: digest((HERE.parent / s).read_bytes()) for s in sources}
        tgt_sha = digest(target.read_bytes())
        for c in result['cases']:
            total += 1
            st = status_for(c)
            counts[st] += 1
            cases_all.append({**c, 'sample': sample, 'status': st,
                'source_sha256': src_sha, 'target_sha256': tgt_sha})
        chains.append({'sample': sample, 'source': result['source'],
            'target': str(target), 'source_sha256': src_sha, 'target_sha256': tgt_sha,
            'case_ids': [c['id'] for c in result['cases']]})

    verification = {
        'schema_version': 2,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'tool': 'neutral_baselines.py (host oracles, DevEco TS transpile + Node vm)',
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
            if ac['judgment'] in ('ui',):
                unverified_build_device.append(ac['id'])

    summary = {
        'schema_version': 2,
        'total_acs': total,
        'host_logic': counts,
        'denominator_note': 'Each AC is one contract; normal ACs are PASS/FAIL, guard ACs are GUARD-OK/FAIL.',
        'unverified_build_device_ac_ids': unverified_build_device,
        'build_status': 'UNVERIFIED',
        'device_status': 'UNVERIFIED',
        'source_execution_status': 'UNVERIFIED',
        'verdict': f"host-logic PASS for all {total} ACs ({counts['PASS']} normal + {counts['GUARD-OK']} guard); build/device/source-exec UNVERIFIED."
                   if (counts['FAIL'] == 0) else 'FAIL present; see cases.'}

    write = lambda p, o: (p.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding='utf-8'))
    write(out / 'neutral-verification.json', verification)
    write(out / 'neutral-summary.json', summary)
    print(json.dumps({'total_acs': total, 'host_logic': counts,
        'build': 'UNVERIFIED', 'device': 'UNVERIFIED', 'source_exec': 'UNVERIFIED',
        'verdict': summary['verdict']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
