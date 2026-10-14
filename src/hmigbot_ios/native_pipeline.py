"""iOS source checks for the original a2h spec tree; no model or pipeline scheduler."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys
import shutil
import uuid

from .analyze import analyze
from .core import MigrationError, read_json, safe_child, snapshot, write_json, digest, json_bytes, SOURCE_SUFFIXES, SOURCE_NAMES
from .native_semantics import validate_native_facts

ROOT = Path(__file__).resolve().parents[2]
CODE = {'.swift', '.m', '.mm', '.h', '.c', '.cpp', '.storyboard', '.xib'}


def configure(source: Path, project: Path):
    source, project = source.resolve(), project.resolve()
    if not source.is_dir() or not project.is_dir():
        raise MigrationError('Source and Harmony project directories must exist')
    if source == project or project.is_relative_to(source) or source.is_relative_to(project):
        raise MigrationError('Harmony project must be separate from the iOS source')
    path = project / '.migbot/config.json'
    data = read_json(path) if path.exists() else {}
    if not isinstance(data, dict):
        raise MigrationError('Configuration must be a JSON object')
    if data.get('source_platform') not in (None, 'ios') or (data.get('android') and not data.get('ios')):
        raise MigrationError('Existing Android configuration is not an iOS project; choose another target')
    if data.get('ios') and Path(data['ios']).resolve() != source:
        raise MigrationError('Source changed: review the existing baseline before updating config')
    data.update(source_platform='ios', ios=str(source), harmonyos=str(project))
    data.setdefault('language', 'zh')
    data.setdefault('confirmed', False)
    data.setdefault('telemetry_consent', 'denied')
    write_json(path, data)
    return {'status': 'configured', 'config': str(path), 'confirmed': data['confirmed']}


def context(project: Path):
    project = project.resolve()
    cfg = read_json(project / '.migbot/config.json')
    if not isinstance(cfg, dict):
        raise MigrationError('Configuration must be a JSON object')
    if cfg.get('source_platform') != 'ios' or not cfg.get('ios'):
        raise MigrationError('Expected source_platform=ios and ios source path in .migbot/config.json')
    source = Path(cfg['ios'])
    if not source.is_absolute():
        source = project / source
    if not source.is_dir():
        raise MigrationError('Configured iOS source is unavailable')
    return source.resolve(), project


def index_source(project: Path):
    source, project = context(project)
    path = project / 'spec/baseline/ios-source-index.json'
    if path.exists():
        raise MigrationError('Source index exists: review changes and preserve it before refreshing')
    facts = analyze(source)
    current = snapshot(source)
    data = {'version': 1, 'source_platform': 'ios', 'source_sha256': current['sha256'],
            'files': current['files'], 'excluded_directories': current['excluded_directories'],
            'facts': facts['facts'], 'scope': 'Repository inventory and lexical/structured hints; not complete semantics'}
    write_json(path, data)
    return {'status': 'indexed', 'path': str(path), 'files': len(current['files']), 'spec_complete': False}


def refresh_source_index(project: Path, review_path: Path):
    source, project = context(project)
    review = read_json(review_path)
    path = project / 'spec/baseline/ios-source-index.json'
    prior = read_json(path)
    current = snapshot(source)
    if not isinstance(review, dict) or review.get('previous_source_sha256') != prior['source_sha256'] or review.get('source_sha256') != current['sha256'] or not all(isinstance(review.get(k), str) and review[k].strip() for k in ('reviewer', 'reason')):
        raise MigrationError('Source refresh needs reviewed old/new snapshot digests and a concrete reason')
    from .ios_facts import validate_graph
    validate_graph(source, project)
    archive = project / 'spec/.a2h/history' / digest(json_bytes(prior))
    write_json(archive / 'ios-source-index.json', prior)
    data = {**prior, 'files': current['files'], 'source_sha256': current['sha256'], 'facts': analyze(source)['facts'], 'refresh_review': review}
    write_json(path, data)
    return {'status': 'refreshed_requires_harness_recheck', 'archive': str(archive), 'spec_complete': False}


def source_paths(text: str):
    """Read file anchors from the original YAML list/map conventions, without YAML execution."""
    paths = []
    in_block = False
    for line in text.splitlines():
        if re.match(r'^\s*source_anchors:\s*(?:#.*)?$', line):
            in_block = True
            continue
        if in_block and (line.startswith('```') or (line and not line[0].isspace())):
            in_block = False
        if in_block:
            match = re.match(r'\s+(?:-\s+)?[\w.-]+:\s*(?:"([^"]+)"|\'([^\']+)\'|([^#]+))', line)
            if match:
                value = next(v for v in match.groups() if v is not None).strip()
                if Path(value).suffix.lower() in SOURCE_SUFFIXES or Path(value).name in SOURCE_NAMES:
                    paths.append(value)
    return list(dict.fromkeys(paths))


def findings_module():
    path = ROOT / 'skills/a2h-spec/scripts/_a2h_findings.py'
    spec = importlib.util.spec_from_file_location('ios_a2h_findings', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_source(project: Path, *, after_repair=False, report_only=False):
    """Check source provenance/ownership and AC evidence, updating the original shared queue."""
    source, project = context(project)
    queue = findings_module()
    issues = []
    def fail(rule, subject, detail):
        issues.append(queue.make(rule, 'spec', subject, detail))
    index_path = project / 'spec/baseline/ios-source-index.json'
    if not index_path.is_file():
        fail('IOS.SOURCE_INDEX_MISSING', str(index_path), 'Run source-index before writing the baseline')
        baseline = {'files': []}
    else:
        baseline = read_json(index_path)
        if not isinstance(baseline, dict) or not isinstance(baseline.get('files'), list) or any(
            not isinstance(f, dict) or not isinstance(f.get('path'), str) for f in baseline['files']
        ):
            raise MigrationError('Malformed iOS source index; preserve it and re-review the source baseline')
        current = snapshot(source)
        if baseline.get('source_sha256') != current['sha256']:
            fail('IOS.STALE_SOURCE', str(source), 'Source changed; re-review affected spec and evidence before refreshing the baseline')
    known = {f['path'] for f in baseline['files']}
    ownership = set()
    features = list((project / 'spec/baseline/features').glob('F*.md'))
    pages = list((project / 'spec/baseline/ui').glob('page_*.md'))
    seen_ids = set()
    documents = {}
    for doc in [*features, *pages]:
        text = doc.read_text(encoding='utf-8-sig')
        # Addenda share their parent's anchors; their closure is checked by the original linter.
        if doc in features and re.match(r'F\d+[-_].+\..+\.md$', doc.name):
            continue
        anchors = source_paths(text)
        stable = re.match(r'^(page_\d+|F\d+)', doc.stem)
        if stable:
            if stable[1] in documents:
                fail('IOS.DOCUMENT_DUPLICATE', stable[1], 'Multiple main specs use the same stable ID')
            documents[stable[1]] = ('feature' if doc in features else 'page', anchors)
        if not anchors:
            fail('IOS.SOURCE_ANCHOR_MISSING', doc.name, 'source_anchors must reference real iOS files')
        if re.search(r'android_source_anchors', text):
            fail('IOS.LEGACY_SOURCE_FIELD', doc.name, 'Review the old baseline and migrate to native source_anchors')
        for relative in anchors:
            try:
                file = safe_child(source, relative)
                if relative not in known or not file.is_file():
                    raise MigrationError('Not a file in the indexed iOS source')
                ownership.add(relative)
            except MigrationError as exc:
                fail('IOS.INVALID_SOURCE_ANCHOR', doc.name + ':' + relative, str(exc))
        if 'source_platform: ios' not in text:
            fail('IOS.PLATFORM_UNDECLARED', doc.name, 'Declare source_platform: ios alongside source_anchors')
        if doc in features:
            acs = re.findall(r'^- \[[ xX]\]\s+(F\d+-AC\d+)\s+(.+)$', text, re.M)
            if not acs:
                fail('IOS.AC_MISSING', doc.name, 'Use the original stable AC IDs and source/judgment/truth syntax')
            for ac_id, body in acs:
                if ac_id in seen_ids:
                    fail('IOS.AC_DUPLICATE', ac_id, 'Stable acceptance IDs must be unique')
                seen_ids.add(ac_id)
                if not re.search(r'判:(static|unit|contract|route|ui|visual|device)\s*\|', body):
                    fail('IOS.AC_JUDGMENT_MISSING', ac_id, 'Missing original judgment anchor')
                truth = re.search(r'真:src:(.+?):(\d+)(?:`|\s|$)', body)
                if truth:
                    try:
                        file = safe_child(source, truth[1])
                        if truth[1] not in anchors or not 1 <= int(truth[2]) <= len(file.read_text(encoding='utf-8-sig').splitlines()):
                            raise MigrationError('Truth location is outside the feature anchors or line range')
                    except (MigrationError, OSError, UnicodeError) as exc:
                        fail('IOS.AC_TRUTH_INVALID', ac_id, str(exc))
                elif not re.search(r'真:(test|trace|device|decision):[^`\s]+', body):
                    fail('IOS.AC_TRUTH_MISSING', ac_id, 'Expected independent source/test/trace/device/decision evidence')
    disposition_path = project / 'spec/baseline/ios-source-disposition.json'
    disposition = read_json(disposition_path) if disposition_path.exists() else {'files': []}
    if not isinstance(disposition, dict) or not isinstance(disposition.get('files'), list):
        raise MigrationError('Source dispositions must be an object containing a files list')
    dispositions = disposition['files']
    for item in dispositions:
        if not isinstance(item, dict):
            fail('IOS.INVALID_DISPOSITION', str(item), 'Disposition entry must be an object')
            continue
        if not isinstance(item.get('path'), str) or item['path'] not in known or item.get('disposition') not in {'dependency', 'test', 'not_applicable'} or not isinstance(item.get('reason'), str) or not item['reason'].strip():
            fail('IOS.INVALID_DISPOSITION', str(item.get('path')), 'Unmapped source requires a concrete disposition and reason')
        else:
            ownership.add(item['path'])
    for path in sorted(known):
        if Path(path).suffix.lower() in CODE and path not in ownership:
            fail('IOS.SOURCE_UNACCOUNTED', path, 'Map to a page/feature source anchor or record a reviewed disposition')
    if not features:
        fail('IOS.FEATURES_MISSING', 'features', 'No original-format feature specs exist')
    validate_native_facts(source, project, documents, known, fail)
    result = {'status': 'FAIL' if issues else 'PASS', 'checks': 'source provenance, AC format, file ownership and native semantic contract; not semantic equivalence',
              'findings': issues, 'source_platform': 'ios', 'behavior_verified': False}
    if not report_only:
        queue.replace_section(str(project), 'spec.ios-source', issues, after_repair=after_repair)
        write_json(project / 'spec/baseline/ios-source-check.json', result)
    return result, queue.section_exit_code(str(project), 'spec.ios-source', issues)


def resolve(source: Path, anchor: str):
    source = source.resolve()
    safe_child(source, anchor)  # refuse path traversal even when falling back to suffix matching
    candidates = [source / f['path'] for f in snapshot(source)['files'] if f['path'] == anchor or f['path'].endswith('/' + anchor)]
    if len(candidates) == 1:
        return {'status': 'OK', 'path': str(candidates[0])}, 0
    return {'status': 'AMBIGUOUS' if candidates else 'MISS', 'candidates': [str(p) for p in candidates]}, 3 if candidates else 2


def tool_config(project: Path):
    source, project = context(project)
    cfg = read_json(project / '.migbot/config.json')
    tool = dict(cfg.get('tools') or {})
    for name in ('hvigorw', 'node', 'deveco_sdk', 'hdc'):
        value = cfg.get(name) or tool.get(name)
        if value:
            path = Path(value)
            tool[name] = str((project / path).resolve() if not path.is_absolute() else path)
    if not tool.get('hvigorw'):
        tool['hvigorw'] = next((str(project / p) for p in ('hvigorw', 'hvigorw.bat') if (project / p).is_file()), None)
    tool.setdefault('node', shutil.which('node'))
    return {'source': {'platform': 'ios', 'root': str(source)}, 'target': {'root': str(project)},
            'tools': tool, 'build': cfg.get('build', {})}


def validate_tools(project: Path):
    cfg = tool_config(project)
    failures = []
    hvigor = cfg['tools'].get('hvigorw')
    if not hvigor or not Path(hvigor).is_file():
        failures.append('Configure a real hvigorw path')
    elif Path(hvigor).suffix.lower() in {'.js', '.bat', '.cmd'}:
        if not Path(hvigor).with_suffix('.js').is_file():
            failures.append('JavaScript hvigor entry missing beside wrapper')
        node = cfg['tools'].get('node')
        if not node or not Path(node).is_file():
            failures.append('Configure a real Node executable')
    if not (Path(cfg['target']['root']) / 'build-profile.json5').is_file():
        failures.append('HarmonyOS build-profile.json5 missing; run the original scaffolder first')
    return {'ok': not failures, 'failures': failures, 'source_platform': 'ios',
            'scope': 'source/config/build tool paths only', 'devices_checked': False, 'compiled': False}, 1 if failures else 0


def build_project(project: Path):
    from .build import build_target
    config = tool_config(project)
    # Evidence remains separate from both roots, as required by the build recorder.
    output = project.resolve().parent / '.a2h-build-evidence' / uuid.uuid4().hex
    result = build_target(config, output)
    result['evidence'] = str(output)
    return result, 0 if result['status'] == 'build_passed' else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--source', required=True, type=Path)
    init.add_argument('--project', required=True, type=Path)
    commands.add_parser('expertise-audit')
    for name in ('source-index', 'source-refresh', 'source-check', 'spec-check', 'validate', 'build', 'literals', 'harness-init', 'import-legacy', 'facts', 'facts-view', 'harness-check', 'behavior-check', 'plan-ir', 'replan', 'next-batch', 'land-results', 'expertise-plan', 'expertise-review', 'mcp-query'):
        p = commands.add_parser(name)
        p.add_argument('--project', required=True, type=Path)
        if name == 'source-check':
            p.add_argument('--after-repair', action='store_true')
            p.add_argument('--report-only', action='store_true')
            p.add_argument('--harness', action='store_true')
        if name == 'facts':
            p.add_argument('--variant', type=Path)
            p.add_argument('--providers', type=Path)
        if name == 'facts-view':
            p.add_argument('--scope', choices=['project', 'ui', 'feature', 'api'], required=True)
        if name == 'behavior-check':
            p.add_argument('--run', action='store_true')
        if name in {'plan-ir', 'replan'}:
            p.add_argument('--input', type=Path, required=True)
        if name == 'expertise-review':
            p.add_argument('--input', type=Path, required=True)
        if name == 'mcp-query':
            p.add_argument('--server', type=Path, required=True)
            p.add_argument('--request', type=Path, required=True)
        if name == 'source-refresh':
            p.add_argument('--review', type=Path, required=True)
        if name == 'literals':
            p.add_argument('--output', type=Path)
        if name in {'next-batch', 'land-results'}:
            p.add_argument('--wave', default='domains')
    resolver = commands.add_parser('resolve')
    resolver.add_argument('--source', required=True, type=Path)
    resolver.add_argument('--anchor', required=True)
    args = parser.parse_args(argv)
    try:
        code = 0
        if args.command == 'expertise-audit':
            from .expertise import audit
            manifest, files = audit()
            result = {'status': 'passed', 'packs': len(manifest['packs']), 'files': len(files)}
        elif args.command == 'expertise-plan':
            from .expertise import prepare
            result = prepare(args.project)
        elif args.command == 'expertise-review':
            from .expertise import record
            result = record(args.project, args.input)
        elif args.command == 'mcp-query':
            from .source_mcp import capture
            result = capture(args.project, args.server, args.request)
        elif args.command == 'init': result = configure(args.source, args.project)
        elif args.command == 'source-index': result = index_source(args.project)
        elif args.command == 'source-refresh': result = refresh_source_index(args.project, args.review)
        elif args.command == 'literals':
            from .ios_literals import run
            result = run(args.project, args.output)
        elif args.command == 'spec-check':
            from .spec_contract import check as check_contract
            result, code = check_contract(args.project)
        elif args.command == 'source-check':
            if args.harness:
                from .ios_harness import check
                result, code = check(args.project)
            else:
                result, code = check_source(args.project, after_repair=args.after_repair, report_only=args.report_only)
                result['harness_ready'] = False
                result['compatibility_only'] = True
        elif args.command in {'harness-init', 'import-legacy'}:
            from .ios_harness import initialize
            result = initialize(args.project, import_legacy=args.command == 'import-legacy')
        elif args.command == 'facts':
            from .ios_facts import refresh
            source, project = context(args.project)
            result = refresh(project, source, read_json(args.variant) if args.variant else None, args.providers)
        elif args.command == 'facts-view':
            from .ios_facts import view
            source, project = context(args.project)
            result = view(project, source, args.scope)
        elif args.command == 'harness-check':
            from .ios_harness import check
            result, code = check(args.project)
        elif args.command == 'behavior-check':
            from .ios_facts import validate_graph
            from .ios_harness import ac_inventory
            from .behavior import verify
            source, project = context(args.project)
            graph, _ = validate_graph(source, project)
            result, code = verify(project, source, graph, ac_inventory(project), run=args.run)
        elif args.command == 'plan-ir':
            from .ios_scheduler import generate
            result = generate(args.project, args.input)
        elif args.command == 'replan':
            from .ios_scheduler import replan
            result = replan(args.project, args.input)
        elif args.command in {'next-batch', 'land-results'}:
            from .ios_scheduler import step
            result, code = step(args.project, args.wave, landing=args.command == 'land-results')
        elif args.command == 'validate': result, code = validate_tools(args.project)
        elif args.command == 'build': result, code = build_project(args.project)
        else: result, code = resolve(args.source, args.anchor)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (MigrationError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(json.dumps({'status': 'FAIL', 'error': str(exc)}, ensure_ascii=False))
        return 2
