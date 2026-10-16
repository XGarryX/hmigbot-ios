"""Read-only product and evidence projections; raw ledgers remain authoritative.

These views describe reviewed source spans and bound execution records. Neither
literal classification nor historical progress proves runtime equivalence.
"""
from __future__ import annotations

import re
from pathlib import Path

from .core import MigrationError, digest, json_bytes, read_json, safe_child, snapshot

LITERAL_GROUPS = ('texts', 'colors', 'dims', 'durations_ms', 'dynamic_texts',
                  'numeric_constants', 'symbolic_colors')


def spec_inputs(project):
    from .ios_scheduler import baseline_inputs
    from .plan_contract import contract_revision
    return {**baseline_inputs(Path(project), 'domains'), '@tool-contract': contract_revision(Path(project))}


def target_inputs(project):
    """Bind the complete non-generated product tree, separate from tool reports."""
    return {f['path']: f['sha256'] for f in snapshot(Path(project))['files']
            if not f['path'].startswith(('spec/', '.migbot/', 'migration/'))}


def product_literals(project):
    from .native_pipeline import context
    from .ios_facts import validate_graph
    from .ios_harness import ac_inventory
    from .ios_literals import extract
    from .source_scope import preview_lines
    source, project = context(Path(project))
    base = project / 'spec/baseline'
    raw = read_json(base / 'literal-ledger.json')
    if raw != extract(source):
        raise MigrationError('Raw literal ledger is stale or edited; extract it again')
    graph, _ = validate_graph(source, project)
    coverage = read_json(base / 'ios-coverage.json')
    if coverage.get('graph_sha256') != digest(json_bytes(graph)):
        raise MigrationError('Product literal view requires current reviewed coverage')
    acs = ac_inventory(project)
    facts = {f['id']: f for f in graph['facts']}
    reviewed = []
    for mapping in coverage.get('mappings', []):
        review = mapping.get('source_review', {})
        fact = facts.get('IF-' + str(mapping.get('obligation_id', ''))[3:])
        if (fact and mapping.get('ac_ids') and set(mapping['ac_ids']) <= set(acs)
                and review.get('status') == 'reviewed'
                and all(isinstance(review.get(k), str) and review[k].strip()
                        for k in ('input', 'processing', 'observable', 'reviewer'))):
            reviewed.append(fact['anchor'])
    dispositions = []
    scope_path = base / 'ios-source-disposition.json'
    if scope_path.exists():
        scope = read_json(scope_path)
        if scope.get('source_sha256') != graph['source_sha256']:
            raise MigrationError('Source disposition is stale; re-review the scope')
        for item in scope.get('files', []):
            path = safe_child(source, item.get('path', ''))
            start, end = item.get('line'), item.get('end_line')
            if (item.get('disposition') not in {'test', 'dependency', 'not_applicable'}
                    or not isinstance(item.get('reason'), str) or not item['reason'].strip()
                    or type(start) is not int or type(end) is not int
                    or not 1 <= start <= end <= len(path.read_text(encoding='utf-8-sig').splitlines())
                    or item.get('source_sha256') != digest(path.read_bytes())):
                raise MigrationError('Literal exclusions need exact current file hashes, spans and reasons')
            dispositions.append(item)
    preview_cache, entries = {}, []
    for group in LITERAL_GROUPS:
        for index, item in enumerate(raw.get(group, [])):
            for anchor in item.get('sources', []):
                path, sep, raw_line = anchor.rpartition(':')
                if not sep or not raw_line.isdigit():
                    raise MigrationError('Literal source must identify an exact source line')
                line = int(raw_line)
                if path not in preview_cache:
                    preview_cache[path] = preview_lines(safe_child(source, path).read_text(encoding='utf-8-sig'))
                classification, reason = 'unknown', 'No reviewed active source fact at this line'
                if any(a['path'] == path and a['line'] <= line <= a['end_line'] for a in reviewed):
                    classification, reason = 'product', 'Intersects reviewed active source fact; usage still needs source analysis'
                if line in preview_cache[path]:
                    classification, reason = 'preview', 'Exact Preview span; exclusion approval is checked separately by the source gate'
                for scope in dispositions:
                    if scope['path'] == path and scope['line'] <= line <= scope['end_line']:
                        classification = {'not_applicable': 'excluded'}.get(scope['disposition'], scope['disposition'])
                        reason = scope['reason']
                entries.append({**item, 'sources': [anchor], 'raw_ref': {'collection': group, 'index': index},
                                'classification': classification, 'reason': reason, 'usage': 'unresolved'})
    inputs = {'literal-ledger.json': digest(json_bytes(raw)), 'ios-facts.json': digest(json_bytes(graph)),
              'ios-coverage.json': digest(json_bytes(coverage))}
    if scope_path.exists():
        inputs[scope_path.name] = digest(scope_path.read_bytes())
    inputs['acceptance'] = digest(json_bytes(acs))
    return {'schema_version': 1, 'source_sha256': graph['source_sha256'], 'inputs': inputs,
            'entries': entries, 'behavior_verified': False,
            'scope': 'Derived source-consumption candidates; not localization completeness or pixel conversion'}


def validate_product_view(project, view):
    if view != product_literals(project):
        raise MigrationError('Product literal view changed or its inputs are stale; recompute it')
    return True


def _legacy_counts(path):
    from .artifact_contract import markdown_tables
    counts = {}
    if path.exists():
        for table in markdown_tables(path.read_text(encoding='utf-8-sig')):
            headers = table['headers']
            if '状态' in headers or 'status' in headers:
                pos = headers.index('状态' if '状态' in headers else 'status')
                for row in table['rows']:
                    if len(row) > pos:
                        counts[row[pos]] = counts.get(row[pos], 0) + 1
    return counts


def _placeholders(project):
    from .artifact_contract import markdown_sections, markdown_tables
    path = project / 'spec/placeholder-registry.md'
    statuses = {'registered', 'pending', 'due', 'fired', 'resolved', 'deferred'}
    result = {'status': 'not_present', **dict.fromkeys(sorted(statuses), 0)}
    if not path.exists():
        return result
    text, seen = path.read_text(encoding='utf-8-sig'), set()
    sections = [s for s in markdown_sections(text) if s['title'] == '注册表']
    if len(sections) > 1:
        result['status'] = 'parse_error'; return result
    if sections:
        text = sections[0]['body']
    result['status'] = 'parsed'
    for table in markdown_tables(text):
        for row in table['rows']:
            row = [cell.strip('` ') for cell in row]
            ids = [cell for cell in row if re.fullmatch(r'P-[A-Za-z0-9-]+', cell)]
            if not ids:
                continue
            header = [cell.strip('` ') for cell in table['headers']]
            status_columns = [i for i, name in enumerate(header) if name.lower() in {'status', '状态'}]
            if len(ids) != 1 or ids[0] in seen or len(status_columns) != 1 or status_columns[0] >= len(row):
                result['status'] = 'parse_error'; continue
            seen.add(ids[0])
            status = row[status_columns[0]].lower()
            if status not in statuses:
                result['status'] = 'parse_error'; continue
            result[status] += 1
    if (set(re.findall(r'\bP-[A-Za-z0-9-]+\b', text)) - {'P-ID'}) - seen:
        result['status'] = 'parse_error'
    return result


def _compilation(project, source_sha, evidence):
    if evidence is None:
        return {'status': 'not_run'}
    path = Path(evidence)
    report = read_json(path)
    result = {'status': 'legacy_unclassified', 'evidence': str(path.resolve())}
    required = {'target_project', 'source_sha256', 'target_input_hashes', 'spec_input_hashes', 'artifacts'}
    if not required <= set(report):
        return result
    try:
        current = (Path(report['target_project']).resolve() == project.resolve()
                   and report['source_sha256'] == source_sha
                   and report['target_input_hashes'] == target_inputs(project)
                   and report['spec_input_hashes'] == spec_inputs(project))
        artifacts = report['artifacts']
        current = current and isinstance(artifacts, list) and bool(artifacts) and all(
            digest(safe_child(project, a['path']).read_bytes()) == a['sha256'] for a in artifacts)
    except (OSError, KeyError, TypeError, MigrationError):
        current = False
    result['status'] = ('stale' if not current else 'passed' if report.get('status') == 'build_passed'
                        and report.get('exit_code') == 0 and report.get('hvigor_success_marker') is True
                        and report.get('source_changed') is False else 'failed')
    return result


def _behavior(project, source_sha, acs):
    path = project / 'spec/reports/ios-behavior-check.json'
    if not path.exists():
        return {'status': 'not_run'}
    result = {'status': 'legacy_unclassified', 'evidence': path.relative_to(project).as_posix()}
    report = read_json(path)
    required = {'spec_input_hashes', 'verification_sha256', 'target_input_hashes'}
    if not required <= set(report):
        return result
    verification = project / 'spec/verification/ios-behavior.json'
    current = (report.get('source_sha256') == source_sha and verification.exists()
               and report['verification_sha256'] == digest(verification.read_bytes())
               and report['spec_input_hashes'] == spec_inputs(project)
               and report['target_input_hashes'] == target_inputs(project))
    if not current:
        result['status'] = 'stale'; return result
    covered = set()
    logs_current = True
    for item in report.get('observations', []):
        if item.get('status') == 'observed_pass':
            covered.update(item.get('ac_ids', []))
            for stream in ('stdout', 'stderr'):
                log = safe_child(project, 'spec/reports/behavior/' + item['id'] + '/' + stream + '.log')
                logs_current = logs_current and log.exists() and digest(log.read_bytes()) == item.get(stream + '_sha256')
    result['status'] = ('passed' if report.get('behavior_verified') is True and report.get('status') == 'PASS'
                        and not report.get('failures') and covered == set(acs) and logs_current
                        else 'failed' if report.get('failures') else 'unverified')
    result['scope'] = report.get('scope')
    return result


def summary(project, *, build_evidence=None):
    from .artifact_contract import _primary_feature
    from .native_pipeline import context
    from .ios_harness import ac_inventory
    source, project = context(Path(project))
    acs = ac_inventory(project)
    source_sha = snapshot(source)['sha256']
    base = project / 'spec/baseline'
    axes = {'generation': {'status': 'not_run'},
            'compilation': _compilation(project, source_sha, build_evidence),
            'behavior': _behavior(project, source_sha, acs), 'visual': {'status': 'not_run'}}
    # Receipts report generated files, never runtime correctness or original landing.
    receipts = list((project / 'spec/waves/results').glob('*/*.json'))
    if receipts:
        axes['generation'] = {'status': 'receipts_present', 'count': len(receipts),
                              'scope': 'Receipt presence only; next-batch/land-results remain the acceptance authority'}
    visual = project / 'spec/reports/visual-verify-report.md'
    if visual.exists():
        axes['visual'] = {'status': 'legacy_unclassified', 'evidence': visual.relative_to(project).as_posix()}
    return {'schema_version': 1, 'source_sha256': source_sha, 'axes': axes,
            'behavior_verified': axes['behavior']['status'] == 'passed',
            'counts': {'acceptance': len(acs), 'features': sum(_primary_feature(p) for p in (base / 'features').glob('F*.md')),
                       'pages': len(list((base / 'ui').glob('page_*.md')))},
            'legacy_progress': {'features': _legacy_counts(base / 'feature-index.md'),
                                'pages': _legacy_counts(base / 'ui-manifest.md')},
            'placeholders': _placeholders(project),
            'scope': 'Read-only evidence axes; historical verified cells are compatibility progress only'}
