"""Export compact, hash-backed observations; never change migration state."""
import argparse
from pathlib import Path
import shutil
import subprocess

from run_evaluation import HERE, MODEL, PAGE, digest, read_json, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', type=Path, required=True)
    parser.add_argument('--matrix', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--failure', default=None)
    parser.add_argument('--include-artifacts', action='store_true')
    args = parser.parse_args()
    attempt, output = args.attempt.resolve(), args.output.resolve()
    if output.exists(): raise SystemExit('Choose a fresh export directory.')
    target = attempt / 'target'
    graph = read_json(target / 'spec/baseline/ios-facts.json')
    build = read_json(attempt / 'build/build.json')
    tools = read_json(target / '.migbot/config.json')['tools']
    node_version = subprocess.run([tools['node'], '--version'], capture_output=True, check=False).stdout.decode().strip()
    hvigor_package = Path(tools['hvigorw']).parent.parent / 'hvigor/package.json'
    sdk_package = Path(tools['deveco_sdk']) / 'default/openharmony/ets/oh-uni-package.json'
    hdc = Path(tools['deveco_sdk']) / 'default/openharmony/toolchains/hdc.exe'
    targets = subprocess.run([str(hdc), 'list', 'targets'], capture_output=True, check=False).stdout.decode().strip() if hdc.exists() else 'unavailable'
    journal = read_json(target / 'spec/state/journal.json')
    behavior_path = attempt / ('behavior-reviewed.json' if (attempt / 'behavior-reviewed.json').exists() else 'behavior.json')
    mutation_path = attempt / ('mutation-reviewed.json' if (attempt / 'mutation-reviewed.json').exists() else 'mutation.json')
    behavior, mutation = read_json(behavior_path), read_json(mutation_path)
    actions = read_json(attempt / 'actions.json')
    ledger_files = ['spec/waves/plan-domains.json', 'spec/blueprint/contracts.json',
                    'spec/state/state.json', 'spec/state/dispatch.json', 'spec/state/journal.json']
    result = {'source_sha256': graph['source_sha256'],
        'source_gate': read_json(attempt / 'source-gate.json')['status'],
        'plan_check': read_json(attempt / 'plan-check.json')['status'],
        'plan_ir': read_json(attempt / 'plan-ir.json')['status'],
        'landed_tasks': [{'task_id': entry['task_id'], 'status': entry['status'], 'attempt': entry['attempt']}
            for entry in journal.get('operation_outputs', [])],
        'scheduler_last_action': actions[-1].get('action'),
        'final_landing_failure': read_json(attempt / 'failure.json') if (attempt / 'failure.json').exists() else None,
        'final_landing_failure_note': args.failure,
        'build': {key: build[key] for key in ('status', 'started_at', 'command', 'exit_code', 'hvigor_success_marker',
            'source_changed', 'source_sha256', 'target_input_sha256', 'target_after_sha256', 'artifacts')},
        'behavior': {'status': behavior['status'], 'behavior_verified': behavior['behavior_verified'],
            'unverified_ac_ids': behavior['unverified_ac_ids'], 'failures': behavior['failures'],
            'observations': [{k: observation.get(k) for k in ('id', 'runner', 'status', 'exit_code', 'actual', 'ac_ids', 'stdout_sha256', 'stderr_sha256')}
                for observation in behavior['observations']]},
        'mutation': mutation, 'independent_review': read_json(HERE / 'review.json'),
        'matrix': read_json(args.matrix / 'matrix-capture.json'),
        'evidence_hashes': {p: digest((target / p).read_bytes()) for p in ledger_files if (target / p).exists()},
        'capture_hashes': {p.relative_to(attempt).as_posix(): digest(p.read_bytes()) for p in [
            attempt / 'source-gate.json', attempt / 'plan-check.json', attempt / 'plan-ir.json',
            attempt / 'actions.json', attempt / 'build/build.json', attempt / 'build/stdout.log',
            attempt / 'build/stderr.log', behavior_path, mutation_path]},
        'environment': {'node': node_version, 'hvigor': read_json(hvigor_package)['version'],
            'ets_sdk': read_json(sdk_package)['version'],
            'hdc_targets': targets, 'ios_source_build': 'not_run', 'device_ui': 'not_run', 'visual': 'not_run'},
        'scope': 'One author-read Counter candidate replay; actual generation/state writers/build and host business logic. Not device behavior, iOS execution, full Swift Int domain or independent model-success-rate evidence.'}
    if (attempt / 'run.json').exists(): result['run'] = read_json(attempt / 'run.json')
    write_json(output / 'result.json', result)
    if args.include_artifacts:
        for relative in [PAGE, MODEL, 'spec/baseline/feature-base.md', 'spec/baseline/feature-index.md',
                'spec/baseline/ui-manifest.md', 'spec/baseline/features/F001-counter.md',
                'spec/baseline/ui/page_0001_Counter.md', 'spec/baseline/plans/base-plan.md',
                'spec/baseline/plans/ui-plan.md', 'spec/baseline/plans/feature-plan.md',
                'spec/baseline/plans/slices/slice-01-F001.md']:
            destination = output / 'authored-output' / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target / relative, destination)
    print(output / 'result.json')


if __name__ == '__main__': main()
