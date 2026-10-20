"""Per-case runner for THEF-16 neutral oracles, consumed by behavior.verify.

Runs the host oracle for one sample and emits ONLY the requested case's result
in a form behavior.verify can compare against the independent oracle expectation:

  * business (normal/normal-cancel/exception) -> emits the real behavior ACTUAL
    value, compared to the source-derived EXPECTED value.
  * guard (mutation/missing-evidence) -> emits {mutant_applied, discriminated};
    the expected value is {mutant_applied: True, discriminated: True}. A guard
    whose mutation could not apply (applied=False) or that failed to discriminate
    is emitted as not-equal and is therefore rejected by the real gate.

This is the genuine evidence-consumption entry: behavior.verify executes this
command and decides PASS/FAIL from the real output, not from a hand summary.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

NODE = r'D:/Program Files/nodejs/node.exe'
BUSINESS_KINDS = {'normal', 'normal-cancel', 'exception'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--node', default=NODE)
    for name in ('script', 'typescript', 'target', 'case_id'):
        parser.add_argument(name)
    args = parser.parse_args()
    script, ts, target, case_id = args.script, args.typescript, args.target, args.case_id
    proc = subprocess.run([args.node, script, ts, target], capture_output=True, text=True, encoding='utf-8',
                          cwd=str(Path(script).parent))
    if proc.returncode != 0:
        print(json.dumps(None))
        return
    data = json.loads(proc.stdout)
    case = next((c for c in data['cases'] if c['id'] == case_id), None)
    if case is None:
        print(json.dumps(None))
        return
    if case['kind'] in BUSINESS_KINDS:
        print(json.dumps(case.get('actual')))
    else:
        print(json.dumps({'mutant_applied': bool(case.get('applied')),
                          'discriminated': bool(case.get('pass'))}))


if __name__ == '__main__':
    main()
