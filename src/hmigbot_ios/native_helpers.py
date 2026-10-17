"""Narrow native frontends for bundled HMigBot consumers, not a migration engine."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def original(skill, helper, arguments, *, cwd=None):
    path = ROOT / 'vendor/hmigbot/skills' / skill / 'scripts' / helper
    if not path.is_file():
        raise ValueError('Complete bundled helper is missing: ' + helper)
    return subprocess.run([sys.executable, str(path), *map(str, arguments)], cwd=cwd,
                          capture_output=True, encoding='utf-8', errors='replace', shell=False)


def feature_inputs(arguments):
    # Keep upstream ID/addendum parsing; only the emitted oracle destination changes.
    parser = argparse.ArgumentParser(description='Resolve native feature, AC and source-oracle output paths')
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--scope')
    args = parser.parse_args(arguments)
    call = ['--project-root', args.project_root]
    if args.scope:
        call += ['--scope', args.scope]
    result = original('arkts-ut-verifier', 'feature_inputs.py', call)
    if result.returncode:
        sys.stderr.write(result.stderr or result.stdout)
        return result.returncode
    data = json.loads(result.stdout)
    for feature in data['features']:
        filename = Path(feature['oracle_file']).name
        feature['oracle_file'] = str(args.project_root.resolve() / 'spec/verify/ut/source-oracle' / filename)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def icon_audit(project, output):
    """Read-only original detector; never infer iOS scale from a default density."""
    project, output = Path(project).resolve(), Path(output).resolve()
    if not project.is_dir():
        raise ValueError('Target project is missing')
    # A previous report must never be mistaken for this invocation's output.
    output.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.TemporaryDirectory(prefix='native-icon-audit-') as temp:
        current = Path(temp) / 'report.json'
        result = original('arkts-icon-sizing', 'icon_audit.py', ['--json', current], cwd=project)
        if result.returncode or not current.is_file():
            raise ValueError('Image constraint detector failed: ' + result.stderr[-1000:])
        data = json.loads(current.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or not isinstance(data.get('flagged'), list):
        raise ValueError('Unexpected image constraint report')
    # No hidden mutation is allowed for flagged dynamic images either.
    native = {'source_platform': 'ios', 'status': 'needs_source_dimensions' if data['flagged'] else 'passed',
              'mutated': False, 'report': data,
              'scope': 'Image constraints only; not visual equivalence or inferred point-to-vp scale'}
    output.write_text(json.dumps(native, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return native


def structural_loop(arguments):
    parser = argparse.ArgumentParser(description='Original structural loop with native image constraints preflight')
    sub = parser.add_subparsers(dest='operation', required=True)
    iterate = sub.add_parser('iterate')
    iterate.add_argument('--project-root', type=Path, required=True)
    iterate.add_argument('--mode', choices=['stage', 'slice', 'group', 'pipeline'], required=True)
    iterate.add_argument('--target', required=True)
    iterate.add_argument('--state-file', type=Path, required=True)
    iterate.add_argument('--slices')
    iterate.add_argument('--max-iter', type=int)
    iterate.add_argument('--diff-base')
    iterate.add_argument('--handoffs', nargs='*')
    iterate.add_argument('--output-json', type=Path)
    finalize = sub.add_parser('finalize')
    finalize.add_argument('--state-file', type=Path, required=True)
    finalize.add_argument('--output-json', type=Path)
    args = parser.parse_args(arguments)
    if args.operation == 'iterate' and args.mode in {'slice', 'group'}:
        from .native_structural import enabled, iterate as native_iterate
        if enabled(args.project_root):
            try:
                return native_iterate(args, original)
            except (ValueError, KeyError, OSError) as exc:
                if args.output_json:
                    from .core import write_json
                    write_json(args.output_json, {'status': 'failed', 'passed': False, 'error': str(exc)})
                raise
    if args.operation == 'iterate' and args.mode == 'pipeline':
        report = args.state_file.resolve().with_name(args.state_file.stem + '-native-images.json')
        audit = icon_audit(args.project_root, report)
        if audit['status'] != 'passed':
            data = {'verdict': 'NATIVE_INPUT_REQUIRED', 'passed': False, 'mutated': False,
                    'report': str(report), 'findings': audit['report']['flagged'],
                    'action': 'Use actual source layout and asset scale; fix owned ArkUI dimensions, then retry'}
            if args.output_json:
                args.output_json.parent.mkdir(parents=True, exist_ok=True)
                args.output_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 3
    result = original('arkts-structural-closure', 'structural_loop.py', arguments)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def verify_slice_wiring(arguments):
    from .native_structural import enabled, wiring
    # Let the bundled parser own the complete legacy CLI, including help and
    # validation errors. Only a positively identified native project adapts.
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument('--project-root', type=Path)
    identity, _ = probe.parse_known_args(arguments)
    if identity.project_root is None or not enabled(identity.project_root):
        result = original('arkts-structural-closure', 'verify_slice_wiring.py', arguments)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.returncode
    parser = argparse.ArgumentParser(description='Native indexed wiring with original C1/C3/C4 detectors')
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--slice', dest='slice_number', type=int, required=True)
    parser.add_argument('--feature-plan', type=Path)
    parser.add_argument('--output-json', type=Path)
    args = parser.parse_args(arguments)
    import tempfile
    try:
        with tempfile.TemporaryDirectory(prefix='native-wiring-') as directory:
            report = wiring(args.project_root.resolve(), args.slice_number,
                            args.output_json or Path(directory) / 'wiring.json', original,
                            feature_plan=args.feature_plan)
    except (ValueError, KeyError, OSError) as exc:
        if args.output_json:
            from .core import write_json
            write_json(args.output_json, {'status': 'failed', 'overall': 'BLOCKED', 'error': str(exc)})
        raise
    if not args.output_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['overall'] == 'PASS' else 1


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    try:
        if not arguments:
            raise ValueError('Expected feature-inputs, structural-loop or icon-audit')
        operation = arguments.pop(0)
        if operation == 'feature-inputs':
            return feature_inputs(arguments)
        if operation == 'structural-loop':
            return structural_loop(arguments)
        if operation == 'verify-slice-wiring':
            return verify_slice_wiring(arguments)
        if operation == 'icon-audit':
            parser = argparse.ArgumentParser(description='Read-only native image constraints check')
            parser.add_argument('--project-root', type=Path, required=True)
            parser.add_argument('--output-json', type=Path, required=True)
            args = parser.parse_args(arguments)
            report = icon_audit(args.project_root, args.output_json)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report['status'] == 'passed' else 2
        raise ValueError('Unknown helper operation')
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
