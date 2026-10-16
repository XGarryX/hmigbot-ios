"""iOS contract gates shared by skills, dispatch and receipt landing."""
from __future__ import annotations

import re
from pathlib import Path

from .core import MigrationError, digest, json_bytes, read_json, safe_child, write_json
from .ios_facts import RULES, validate_graph


def initialize(project: Path, *, import_legacy=False):
    from .native_pipeline import context
    source, project = context(project)
    cfg_path = project / '.migbot/config.json'
    cfg = read_json(cfg_path)
    marker = cfg.get('ios_harness')
    contract_version = marker.get('spec_contract_version', 1) if isinstance(marker, dict) else 2
    if type(contract_version) is not int or contract_version not in (1, 2):
        raise MigrationError('Unsupported spec contract version; preserve the current baseline')
    if marker and marker.get('version') != 2:
        raise MigrationError('Unsupported harness version; do not overwrite state')
    if (project / 'spec/state/state.json').exists() and not marker:
        raise MigrationError('Existing state writer must be retired before adopting the iOS harness')
    legacy = project / 'spec/baseline/ios-semantics.json'
    if legacy.exists() and read_json(legacy).get('schema_version') != 2:
        if not import_legacy:
            raise MigrationError('Existing v1 baseline needs explicit import-legacy; preserve stable IDs')
        original = read_json(legacy)
        archive = project / 'spec/.a2h/legacy-0.5.0'
        for name in ('ios-semantics.json', 'ios-source-check.json', 'verification.json', 'impl-claims.json'):
            path = project / 'spec/baseline' / name
            if path.exists() and not (archive / name).exists():
                write_json(archive / name, read_json(path))
        migrated = {**original, 'schema_version': 2, 'imported_from': '0.5.0'}
        for doc in migrated.get('documents', []):
            for field, value in doc.get('facts', {}).items():
                doc['facts'][field] = {'status': 'unknown', 'reason': 'Imported v1 claim requires typed facts and independent review', 'legacy_claim': value}
        write_json(legacy, migrated)
    cfg['ios_harness'] = {'version': 2, 'spec_contract_version': contract_version,
                          'scheduler': 'hmigbot-codex-1.7.0',
                          'state_writer': 'state_update.py', 'journal_writer': 'land_results.py',
                          'dispatch_writer': 'next_batch.py', 'legacy_pass_inherited': False}
    cfg['ios_expertise'] = {'version': 1, 'required': True}
    write_json(cfg_path, cfg)
    return {'status': 'initialized', 'harness_version': 2, 'legacy_pass_inherited': False, 'source': str(source)}


def ac_inventory(project):
    acs = {}
    for doc in sorted((project / 'spec/baseline/features').glob('F*.md')):
        for ident, body in re.findall(r'^- \[[ xX]\]\s+(F\d+-AC\d+)\s+(.+)$', doc.read_text(encoding='utf-8-sig'), re.M):
            if ident in acs:
                raise MigrationError('Duplicate acceptance ID: ' + ident)
            judgment = re.search(r'判:(static|unit|contract|route|ui|visual|device)\s*\|', body)
            if not judgment:
                raise MigrationError('Missing judgment: ' + ident)
            acs[ident] = {'judgment': judgment[1], 'body': body}
    if not acs:
        raise MigrationError('No stable acceptance criteria exist')
    return acs


def check(project: Path, *, report_only=False):
    from .native_pipeline import context, check_source, source_paths, findings_module
    source, project = context(project)
    queue = findings_module()
    issues = []
    excluded_obligations = set()
    preview_cache = {}

    def fail(rule, subject, detail):
        issues.append(queue.make(rule, 'spec', subject, detail))

    try:
        if read_json(project / '.migbot/config.json').get('ios_harness', {}).get('version') != 2:
            raise MigrationError('Initialize v2 harness; legacy check results are not harness acceptance')
        # Original ownership/AC contracts still run. v2 semantics are checked below.
        result, _ = check_source(project, report_only=True)
        issues.extend(result['findings'])
        graph, obs = validate_graph(source, project)
        from .expertise import check as check_expertise
        expertise = check_expertise(project, source, graph)
        from .ios_literals import extract as extract_literals
        if read_json(project / 'spec/baseline/literal-ledger.json') != extract_literals(source):
            raise MigrationError('Literal ledger must be extracted from current iOS source; spec-only empty scans are insufficient')
        for issue in graph['issues']:
            fail('IOS.EXTRACTION_UNRESOLVED', str(issue.get('path', 'project')), str(issue))
        facts = {f['id']: f for f in graph['facts']}
        semantics = read_json(project / 'spec/baseline/ios-semantics.json')
        if semantics.get('schema_version') != 2:
            raise MigrationError('v1 free-text semantics cannot satisfy v2 gates; import and review')
        for doc in semantics.get('documents', []):
            anchors = set()
            folder = 'ui' if doc.get('kind') == 'page' else 'features'
            for path in (project / 'spec/baseline' / folder).glob(doc.get('id', '') + '*.md'):
                anchors.update(source_paths(path.read_text(encoding='utf-8-sig')))
            for dimension, claim in doc.get('facts', {}).items():
                relevant = [f for f in facts.values() if f['anchor']['path'] in anchors and dimension in RULES[f['kind']]['dimensions']]
                subject = str(doc.get('id')) + ':' + dimension
                tool_ids = claim.get('tool_evidence_ids', [])
                if not isinstance(tool_ids, list):
                    raise MigrationError('tool_evidence_ids must be a list')
                if tool_ids:
                    from .source_mcp import validate_captures
                    validate_captures(project, graph, tool_ids, claim.get('fact_ids', []))
                if claim.get('status') == 'not_applicable' and relevant:
                    fail('IOS.NA_CONTRADICTION', subject, 'Source signals require treatment: ' + ','.join(f['id'] for f in relevant))
                if claim.get('status') == 'known':
                    if not isinstance(claim.get('value'), dict) or not claim['value']:
                        fail('IOS.CLAIM_TYPED_VALUE', subject, 'v2 known values must be structured objects')
                    refs = claim.get('fact_ids')
                    if not isinstance(refs, list) or not refs or any(r not in facts or facts[r]['anchor']['path'] not in anchors for r in refs):
                        fail('IOS.CLAIM_FACT_LINK', subject, 'Known claims need machine fact IDs within document source anchors')
                    elif relevant and not {f['id'] for f in relevant} <= set(refs):
                        fail('IOS.CLAIM_SIGNAL_MISSING', subject, 'Known dimension omitted a detected source signal')
                    else:
                        evidence = claim.get('evidence', [])
                        if any(not any(e.get('path') == facts[r]['anchor']['path'] and facts[r]['anchor']['line'] <= e.get('line', 0) <= facts[r]['anchor']['end_line'] for r in refs) for e in evidence):
                            fail('IOS.CLAIM_UNRELATED_LINE', subject, 'Evidence must intersect the linked fact spans')
                    if dimension == 'state_ownership' and relevant:
                        expected = [{'fact_id': f['id'], 'owner': f['owner'], **f['value']} for f in relevant if f['kind'] == 'state']
                        if claim.get('value') != {'states': expected}:
                            fail('IOS.STATE_VALUE_CONTRADICTION', subject, 'State owner/storage/type/initializer must match extracted declarations')
        coverage = read_json(project / 'spec/baseline/ios-coverage.json')
        if coverage.get('schema_version') != 2 or coverage.get('graph_sha256') != digest(json_bytes(graph)) or not isinstance(coverage.get('mappings'), list):
            raise MigrationError('Coverage requires v2 mappings and current graph_sha256')
        acs, seen = ac_inventory(project), set()
        expected = {o['id']: o for o in obs['obligations']}
        for mapping in coverage['mappings']:
            if not isinstance(mapping, dict):
                raise MigrationError('Coverage mapping must be an object')
            ident = mapping.get('obligation_id')
            if ident not in expected or ident in seen:
                fail('IOS.OBLIGATION_ID', str(ident), 'Unknown or duplicate obligation mapping'); continue
            seen.add(ident)
            ids = mapping.get('ac_ids', [])
            from .source_scope import preview_lines
            source_fact = facts[expected[ident]['fact_id']]
            anchor = source_fact['anchor']
            if anchor['path'] not in preview_cache:
                preview_cache[anchor['path']] = preview_lines(safe_child(source, anchor['path']).read_text(encoding='utf-8-sig'))
            preview = preview_cache[anchor['path']]
            is_preview = set(range(anchor['line'], anchor['end_line'] + 1)) <= preview
            if is_preview or mapping.get('disposition') == 'preview-only':
                from .spec_contract import sections
                review = mapping.get('source_review', {})
                skip_ref = mapping.get('skip_ref', '')
                skip_path, _, heading = skip_ref.partition('#')
                skip_text = (project / 'spec/baseline/skip-list.md').read_text(encoding='utf-8-sig')
                reviewed = (is_preview and not ids and mapping.get('disposition') == 'preview-only'
                    and mapping.get('source_sha256') == anchor['file_sha256']
                    and skip_path == 'spec/baseline/skip-list.md' and heading in sections(skip_text)
                    and anchor['path'] in sections(skip_text).get(heading, '')
                    and isinstance(review, dict) and review.get('status') == 'reviewed'
                    and all(isinstance(review.get(k), str) and review[k].strip() for k in ('input', 'processing', 'observable', 'reviewer')))
                if reviewed:
                    excluded_obligations.add(ident)
                else:
                    fail('IOS.PREVIEW_REVIEW_REQUIRED', ident, 'Keep the original obligation; exclude only exact Preview spans with current file hash, source review and skip-list heading, without product ACs')
                continue
            if not ids or any(a not in acs for a in ids):
                fail('IOS.OBLIGATION_AC_MISSING', ident, 'Bind obligation to real stable acceptance criteria'); continue
            if not any(acs[a]['judgment'] in expected[ident]['judgments'] for a in ids):
                fail('IOS.ORACLE_TOO_WEAK', ident, 'Required judgment: ' + '/'.join(expected[ident]['judgments']))
            # A signal is a review obligation, not a claim that token analysis bound its calls.
            review = mapping.get('source_review')
            if not isinstance(review, dict) or review.get('status') != 'reviewed' or not all(isinstance(review.get(k), str) and review[k].strip() for k in ('input', 'processing', 'observable', 'reviewer')):
                fail('IOS.SOURCE_REVIEW_MISSING', ident, 'Review input -> processing -> observable outcome against source')
        for ident in sorted(expected.keys() - seen):
            fail('IOS.OBLIGATION_UNCOVERED', ident, expected[ident]['obligation'])
        from .spec_contract import check as check_contract
        content, _ = check_contract(project)
        issues.extend(content['findings'])
    except (MigrationError, OSError, ValueError, TypeError, AttributeError) as exc:
        fail('IOS.HARNESS_CONTRACT', 'harness', str(exc))
    if not report_only:
        queue.replace_section(str(project), 'spec.ios-harness', issues)
    report = {'schema_version': 2, 'status': 'FAIL' if issues else 'PASS', 'findings': issues,
              'scope': 'source contract and obligation coverage', 'behavior_verified': False,
              'excluded_obligation_ids': sorted(excluded_obligations)}
    if not report_only:
        write_json(project / 'spec/reports/ios-harness-check.json', report)
    return report, 2 if issues else 0


def behavior_check(project: Path):
    """Validate source/target chains and run explicit independent executable oracles.

    Static checks deliberately cannot establish runtime equivalence.
    """
    from .native_pipeline import context
    from .ios_facts import validate_graph
    from .behavior import verify
    source, project = context(project)
    graph, _ = validate_graph(source, project)
    return verify(project, source, graph, ac_inventory(project))
