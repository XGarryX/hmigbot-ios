"""Run the actual handoff consumers after a completed evaluation; save every exit code."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from run_evaluation import ROOT, digest, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', type=Path, required=True)
    args = parser.parse_args()
    out = args.attempt.resolve()
    target = out / 'target'
    evidence = out / 'delivery'
    if evidence.exists(): raise SystemExit('Preserve previous delivery capture; do not overwrite it.')
    evidence.mkdir()
    prefix = [sys.executable, '-X', 'utf8', str(ROOT / 'scripts/a2h_ios.py')]
    project_args = ['--project', str(target)]
    build_args = ['--build-evidence', str(out / 'build/build.json')]
    operations = [
        ('source-check', ['source-check', *project_args, '--harness', '--report-only']),
        ('spec-check', ['spec-check', *project_args]),
        ('plan-check', ['plan-check', *project_args, '--input', str(out / 'typed-plan.json')]),
        ('spec-summary', ['spec-summary', *project_args, *build_args, '--output', str(target / 'spec/reports/spec-summary.json')]),
        ('migration-report', ['migration-report', *project_args, *build_args, '--output', str(target / 'spec/migration-report.md')]),
        ('migration-report-check', ['migration-report', *project_args, *build_args, '--check', str(target / 'spec/migration-report.md')]),
    ]
    captures = []
    for name, arguments in operations:
        proc = subprocess.run([*prefix, *arguments], cwd=ROOT, capture_output=True, check=False)
        (evidence / (name + '.stdout.txt')).write_bytes(proc.stdout)
        (evidence / (name + '.stderr.txt')).write_bytes(proc.stderr)
        payload = json.loads(proc.stdout) if proc.returncode == 0 else None
        captures.append({'operation': name, 'command': [*prefix, *arguments], 'exit_code': proc.returncode,
            'status': payload.get('status', 'validated_summary') if payload else 'failed',
            'stdout_sha256': digest(proc.stdout), 'stderr_sha256': digest(proc.stderr)})
        write_json(evidence / 'capture.json', {'operations': captures})
        if proc.returncode: raise SystemExit('Delivery consumer failed: ' + name)
    write_json(evidence / 'capture.json', {'operations': captures,
        'summary_sha256': digest((target / 'spec/reports/spec-summary.json').read_bytes()),
        'report_sha256': digest((target / 'spec/migration-report.md').read_bytes())})
    print(json.dumps({'status': 'passed', 'operations': len(captures), 'migration_report_check': captures[-1]['status']}))


if __name__ == '__main__': main()
