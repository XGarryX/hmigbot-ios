"""One deterministic entry to source capture and unreviewed authoring candidates.

This is a preparation command. It does not synthesize business ACs, run agents,
approve a specification, dispatch implementation or certify an application.
"""
from pathlib import Path
import time

from .core import MigrationError, digest, read_json, snapshot, write_json


def run(project, *, variant=None, providers=None, manifest_evidence=None, apply_scaffold=False):
    from .native_pipeline import context, index_source
    from .ios_harness import initialize
    from .ios_facts import refresh, obligations
    from .ios_literals import run as literal_index
    from .native_scaffold import scaffold, apply_scaffold as apply_candidate

    source, project = context(Path(project))
    # This convenience entry prepares the baseline before planning. A reviewed
    # replan/source refresh remains the path for an existing execution contract.
    if ((project / 'spec/state/state.json').exists()
            or any((project / 'spec/waves').glob('plan-*.json'))):
        raise MigrationError('Source analysis cannot mutate a planned project; use reviewed source-refresh/replan')
    current = snapshot(source)
    index_path = project / 'spec/baseline/ios-source-index.json'
    if index_path.exists():
        index = read_json(index_path)
        if index.get('source_sha256') != current['sha256'] or index.get('files') != current['files']:
            raise MigrationError('Source index is stale; preserve it and use reviewed source-refresh before analysis')
    report_path = project / 'spec/reports/derived/source-analysis.json'
    report = {'schema_version': 1, 'status': 'running', 'source_sha256': current['sha256'],
              'spec_complete': False, 'behavior_verified': False, 'build': 'not_run',
              'stages': [], 'artifacts': {}, 'counts': {}}
    started = time.monotonic()

    def save():
        report['elapsed_seconds'] = time.monotonic() - started
        write_json(report_path, report)

    def artifact(path):
        body = path.read_bytes()
        report['artifacts'][path.relative_to(project).as_posix()] = {
            'sha256': digest(body), 'bytes': len(body)}

    def stage(name, action):
        stamp = time.monotonic()
        entry = {'name': name, 'status': 'running'}
        report['stages'].append(entry)
        save()
        result = action()
        entry.update(status='completed', elapsed_seconds=time.monotonic() - stamp)
        save()
        return result

    save()
    try:
        stage('harness', lambda: initialize(project))
        stage('source-index', lambda: {'status': 'reused'} if index_path.exists() else index_source(project))
        artifact(index_path)
        graph = stage('facts', lambda: refresh(project, source, variant, providers, manifest_evidence))
        for name in ('ios-facts.json', 'ios-obligations.json'):
            artifact(project / 'spec/baseline' / name)
        literals = stage('literals', lambda: literal_index(project))
        artifact(project / 'spec/baseline/literal-ledger.json')
        candidate = stage('spec-scaffold', lambda: scaffold(project, source_sha256=current['sha256']))
        candidate_path = project / 'spec/reports/derived/spec-scaffold.json'
        write_json(candidate_path, candidate)
        artifact(candidate_path)
        if apply_scaffold:
            applied = stage('apply-scaffold', lambda: apply_candidate(project, candidate))
            if applied.get('refused'):
                raise MigrationError('Scaffold apply refused candidate files; inspect the retained candidate')
            from .native_authoring import prepare
            authoring = stage('spec-authoring', lambda: prepare(project))
            authoring_path = project / 'spec/reports/derived/spec-authoring.json'
            write_json(authoring_path, authoring)
            artifact(authoring_path)
            report['applied'] = applied
        final = snapshot(source)
        if (final['sha256'] != current['sha256'] or graph['source_sha256'] != current['sha256']
                or literals['source_sha256'] != current['sha256']):
            raise MigrationError('Source changed during analysis; retained artifacts require fresh capture and review')
        report['counts'] = {'source_files': len(current['files']), 'facts': len(graph['facts']),
                            'obligations': len(obligations(graph)['obligations']),
                            'extraction_issues': len(graph['issues']),
                            'candidates': candidate['summary']}
        report['status'] = 'needs_review'
        report['next'] = ['Review every candidate and unknown source item',
                          'Author source-backed semantics, ACs and independent validation oracles',
                          'Run spec-check and source-check --harness before plan-ir']
        save()
        return {**report, 'report': str(report_path)}
    except (MigrationError, OSError, ValueError, KeyError, TypeError) as exc:
        report.update(status='failed', error=str(exc))
        if report['stages'] and report['stages'][-1]['status'] == 'running':
            report['stages'][-1]['status'] = 'failed'
        save()
        raise MigrationError(str(exc) + '; retained analysis receipt: ' + str(report_path)) from exc
