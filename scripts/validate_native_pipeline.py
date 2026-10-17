"""Exercise real bundled a2h consumers on an iOS spec, including expected failures.

This is a protocol regression fixture, not proof of arbitrary app migration.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def validate(plugin, fixtures, output):
    output.mkdir(parents=True, exist_ok=False)
    source, project = output / 'ios', output / 'harmony'
    shutil.copytree(fixtures / 'uikit_interaction', source)
    shutil.copytree(fixtures / 'a2h-native-spec', project)
    checks = []
    env = {**os.environ, 'PYTHONUTF8': '1', 'A2H_TELEMETRY_OFF': '1'}

    def run(name, relative, args, expected=0):
        result = subprocess.run([sys.executable, '-X', 'utf8', str(plugin / relative), *map(str, args)],
                                cwd=project, env=env, capture_output=True, timeout=90)
        (output / (name + '.stdout.log')).write_bytes(result.stdout)
        (output / (name + '.stderr.log')).write_bytes(result.stderr)
        check = {'name': name, 'exit_code': result.returncode, 'expected_exit': expected,
                 'passed': result.returncode == expected}
        checks.append(check)
        if not check['passed']:
            raise RuntimeError(name + ': ' + result.stderr.decode('utf-8', errors='replace') +
                               result.stdout.decode('utf-8', errors='replace'))
        return result

    def read(path):
        return json.loads(path.read_text(encoding='utf-8'))

    def write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

    report = {'status': 'failed', 'scope': 'Original spec/plan/UT/wiring consumers; not runtime behavior acceptance',
              'known_limitations': ['The original structural checker may accept an empty event handler; independent behavior AC tests remain required.'],
              'checks': checks, 'source_platform': 'ios'}
    try:
        helper = 'scripts/a2h_ios.py'
        run('source-init', helper, ['init', '--source', source, '--project', project])
        run('source-index', helper, ['source-index', '--project', project])
        run('source-check', helper, ['source-check', '--project', project])
        run('original-addenda-closure', 'skills/a2h-spec/scripts/lint_addenda_closure.py', ['--spec', project / 'spec/baseline'])
        run('original-platform-divergence', 'skills/a2h-spec/scripts/lint_divergence.py', ['--spec-dir', project / 'spec/baseline/features', '--gate'])
        run('native-literal-index', 'skills/a2h-spec/scripts/extract_literals.py', ['--spec-dir', project / 'spec/baseline', '--out', project / 'spec/baseline/literal-index.json'])
        run('original-traceability', 'skills/a2h-spec/scripts/build_traceability_index.py', ['--project-root', project])
        state = project / 'spec/.a2h'
        requirements = read(state / 'requirements-index.json')['requirements']
        if len(requirements) != 3 or any(not r['truth_source'].startswith('src:CounterViewController.swift:') for r in requirements):
            raise RuntimeError('Original traceability consumer lost the iOS truth anchors')
        coverage = {'packets': [{'packet_id': 'slice-01-F001',
                                'requirement_ids': [r['requirement_id'] for r in requirements],
                                'requirement_digests': {r['requirement_id']: r['assertion_digest'] for r in requirements}}]}
        write(state / 'plan-coverage.json', coverage)
        plan = 'skills/a2h-plan/scripts/lint_plan_coverage.py'
        run('original-plan-covered', plan, ['--project-root', project])
        missing = coverage['packets'][0]['requirement_ids'].pop()
        write(state / 'plan-coverage.json', coverage)
        result = run('original-plan-unowned-ac', plan, ['--project-root', project], expected=2)
        if b'PLAN.REQUIREMENT_UNOWNED' not in result.stdout + result.stderr:
            raise RuntimeError('Plan failed for a different reason than the deliberately unowned AC')
        coverage['packets'][0]['requirement_ids'].append(missing)
        write(state / 'plan-coverage.json', coverage)
        run('original-plan-repaired', plan, ['--project-root', project, '--after-repair'])
        run('original-ut-feature-inputs', 'skills/arkts-ut-verifier/scripts/feature_inputs.py', ['--project-root', project])
        run('original-ut-ac-inputs', 'skills/arkts-ut-verifier/scripts/ac_inputs.py',
            ['--feature-file', project / 'spec/baseline/features/F001-counter.md', '--feature-id', 'F001'])
        wiring = 'skills/arkts-structural-closure/scripts/verify_slice_wiring.py'
        wiring_args = ['--slice', 1, '--project-root', project]
        run('original-wiring-missing', wiring, wiring_args + ['--output-json', output / 'wiring-missing.json'], expected=1)
        missing_wire = read(output / 'wiring-missing.json')
        if missing_wire['categories']['C1_orphan_check']['fail'] != 1:
            raise RuntimeError('Missing target did not produce a genuine orphan finding')
        shutil.copytree(fixtures / 'a2h-native-target/entry', project / 'entry')
        run('original-wiring-connected', wiring, wiring_args + ['--output-json', output / 'wiring-connected.json'])
        page = project / 'entry/src/main/ets/pages/CounterPage.ets'
        original = page.read_bytes()
        page.write_text(page.read_text(encoding='utf-8').replace('this.viewModel.increment();', ''), encoding='utf-8')
        run('original-wiring-empty-handler-limitation', wiring, wiring_args + ['--output-json', output / 'wiring-empty-handler.json'])
        page.write_text('@Entry\n@ComponentV2\nstruct CounterPage { build() { Text("Count: 0") } }\n', encoding='utf-8')
        run('original-wiring-disconnected', wiring, wiring_args + ['--output-json', output / 'wiring-disconnected.json'], expected=1)
        if read(output / 'wiring-disconnected.json')['categories']['C1_orphan_check']['fail'] < 1:
            raise RuntimeError('Disconnected ViewModel did not produce an orphan failure')
        page.write_bytes(original)
        run('original-wiring-repaired', wiring, wiring_args + ['--output-json', output / 'wiring-repaired.json'])
        swift = source / 'CounterViewController.swift'
        original = swift.read_bytes()
        swift.write_bytes(original + b'\n// Source changed after spec\n')
        run('stale-ios-source', helper, ['source-check', '--project', project], expected=2)
        if not any(f['rule'] == 'IOS.STALE_SOURCE' for f in read(project / 'spec/baseline/ios-source-check.json')['findings']):
            raise RuntimeError('Stale source was not detected')
        swift.write_bytes(original)
        run('ios-source-repaired', helper, ['source-check', '--project', project, '--after-repair'])
        report['status'] = 'passed'
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
        report['error'] = str(exc)
    write(output / 'native-pipeline-checks.json', report)
    return report


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin', type=Path, default=root)
    parser.add_argument('--fixtures', type=Path, default=root / 'tests/fixtures')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = validate(args.plugin.resolve(), args.fixtures.resolve(), args.output.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
