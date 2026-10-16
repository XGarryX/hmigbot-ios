"""Typed iOS plan adapter; original 1.7.0 programs remain the only state writers."""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import shutil
import platform
import uuid
from pathlib import Path

from .core import MigrationError, atomic_write, digest, json_bytes, read_json, safe_child, snapshot, write_json
from .ios_facts import validate_graph
from .ios_harness import ac_inventory, check
from .harness_schema import validate

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / 'vendor/hmigbot-1.7.0/skills/a2h-execute/scripts'


def baseline_inputs(project, wave):
    mutable = {'spec/baseline/' + name for name in ('ui-manifest.md', 'feature-index.md', 'verification.json', 'impl-claims.json', 'ios-source-check.json')}
    from .plan_contract import profile, structural_digest
    projected = {'spec/baseline/ui-manifest.md', 'spec/baseline/feature-index.md'} if profile(project) >= 2 else set()
    mutable -= projected
    inputs = {f['path']: f['sha256'] for f in snapshot(project)['files']
            if (f['path'].startswith('spec/baseline/') and f['path'] not in mutable
                or f['path'].startswith(('spec/ref/ios-expertise-', 'spec/ref/ios-mcp-', 'spec/ref/mcp-runs/', 'spec/ref/ios-analysis-provenance.json', 'spec/ref/ios-manifest-evidence/')))
            and (wave != 'understand' or Path(f['path']).name in {'ios-facts.json', 'ios-obligations.json', 'ios-source-index.json'})}
    if wave == 'domains':
        from .spec_contract import dependency_inputs
        inputs.update({path: value for path, value in dependency_inputs(project).items()
                       if path not in mutable})
        inputs.pop('spec/baseline/plans/resource-mapping.md', None)
        if profile(project) >= 2:
            from .plan_contract import indexed_contract_inputs
            inputs.update(indexed_contract_inputs(project))
    for path in projected:
        target = safe_child(project, path)
        if path in inputs and target.is_file():
            inputs[path] = structural_digest(target.read_text(encoding='utf-8-sig'), artifact=path)
    return inputs


def execution_files(project):
    excluded = ('spec/state/', 'spec/reports/', 'spec/waves/')
    return {f['path']: f['sha256'] for f in snapshot(project)['files'] if not f['path'].startswith(excluded)}


def kernel():
    spec = importlib.util.spec_from_file_location('ios_upstream_wavelib', UPSTREAM / '_wavelib.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(project, program, args):
    env = {**os.environ, 'PYTHONUTF8': '1', 'ARKTS_SKILL_DIR': str(UPSTREAM.parent)}
    try:
        # Frozen upstream sys.executable points at a non-shipped python.exe beside
        # its binary on Windows. Stage unchanged payload plus the host interpreter;
        # never repair vendor bytes in place or replace original state algorithms.
        with tempfile.TemporaryDirectory(prefix='ios-scheduler-python-') as temp:
            command = [sys.executable, str(UPSTREAM / (program + '.py')), *args]
            if os.name == 'nt':
                if platform.machine().lower() not in {'amd64', 'x86_64', 'x64'}:
                    raise MigrationError('Bundled Windows kernel requires x64')
                directory = Path(temp) / '_entry.dist'
                shutil.copytree(UPSTREAM / 'bin/windows-x64/_entry.dist', directory)
                for name in ('python.exe', 'python3.exe'):
                    shutil.copy2(sys.executable, directory / name)
                for dll in Path(sys.base_prefix).glob('*.dll'):
                    shutil.copy2(dll, directory / dll.name)
                env['PATH'] = str(directory) + os.pathsep + env.get('PATH', '')
                env['PYTHONHOME'] = sys.base_prefix
                command = [str(directory / '_entry.exe'), program, *args]
            proc = subprocess.run(command,
                                  cwd=project, env=env, capture_output=True, timeout=60, shell=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        log = project / 'spec/reports/scheduler' / (program + '.failure.json')
        write_json(log, {'program': program, 'error': str(exc), 'status': 'FAIL'})
        raise MigrationError('Original scheduler failed; evidence: ' + str(log)) from exc
    directory = project / 'spec/reports/scheduler'
    atomic_write(directory / (program + '.stdout.log'), proc.stdout)
    atomic_write(directory / (program + '.stderr.log'), proc.stderr)
    if proc.returncode:
        raise MigrationError('Original scheduler rejected input: ' + proc.stderr.decode('utf-8', errors='replace')[-1800:])
    import json
    try:
        return json.loads(proc.stdout)
    except (ValueError, UnicodeError) as exc:
        raise MigrationError('Original scheduler did not return a JSON action') from exc


def generate(project, input_path, *, validate_only=False):
    from .native_pipeline import context
    source, project = context(project)
    request = validate(read_json(input_path), 'planRequest')
    from .plan_contract import profile, contract_revision, validate_plan
    contract_profile = profile(project)
    existing_contract = project / 'spec/blueprint/contracts.json'
    if existing_contract.is_file() and read_json(existing_contract).get('spec_contract_version', 1) > contract_profile:
        raise MigrationError('Cannot downgrade a frozen spec contract profile to bypass planning gates')
    if request.get('schema_version') != 2 or request.get('wave') not in {'understand', 'domains'}:
        raise MigrationError('Expected typed v2 plan for understand or domains wave')
    wave = request['wave']
    plan_contract = validate_plan(project, request)
    graph, _ = validate_graph(source, project)
    if wave == 'domains':
        report, code = check(project, report_only=validate_only)
        if code:
            raise MigrationError('Source harness gate failed; resolve findings before planning implementation')
    graph_hash = digest(json_bytes(graph))
    if request.get('graph_sha256') != graph_hash:
        raise MigrationError('Plan input must pin the current fact graph')
    tasks = request.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        raise MigrationError('Plan must have nonempty typed tasks')
    ids, owned, covered, planned = set(), set(), set(), []
    all_acs = ac_inventory(project) if wave == 'domains' else {}
    all_facts = {f['id'] for f in graph['facts']}
    for task in tasks:
        ident = task.get('id')
        if not isinstance(ident, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', ident) or ident in ids:
            raise MigrationError('Task IDs must be unique portable names')
        ids.add(ident)
        role = task.get('role')
        if not isinstance(role, str) or not (ROOT / 'agents-codex' / (role + '.toml')).is_file():
            raise MigrationError('Role is not bundled: ' + str(role))
        own = task.get('ownership')
        readonly_verification = contract_profile >= 2 and task.get('verification') in {'compile', 'behavior', 'visual'} and not own
        if not isinstance(own, list) or not own and not readonly_verification:
            raise MigrationError('Tasks need explicit file ownership; wildcards are not allowed')
        for path in own:
            safe_child(project, path)
            portable = path.casefold()
            if any(ch in path for ch in '*?[') or portable in owned or portable.startswith(('spec/state/', 'spec/blueprint/', 'spec/waves/', 'spec/.a2h/', '.migbot/', '.hmigbot-ios/', '.agents/', '.codex/', '.git/')):
                raise MigrationError('Overlapping or control-plane ownership: ' + path)
            if wave == 'understand' and not path.startswith('spec/'):
                raise MigrationError('Understanding tasks may only write specs')
            owned.add(portable)
        ac_ids = task.get('ac_ids', [])
        fact_ids = task.get('fact_ids')
        if not isinstance(ac_ids, list) or any(a not in all_acs for a in ac_ids) or wave == 'domains' and not ac_ids and contract_profile < 2:
            raise MigrationError('Implementation task must bind real acceptance criteria')
        if not isinstance(fact_ids, list) or not fact_ids or not set(fact_ids) <= all_facts:
            raise MigrationError('Task must bind current machine facts')
        covered.update(ac_ids)
        if not isinstance(task.get('goal'), str) or not task['goal'].strip():
            raise MigrationError('Task goal is required')
        planned.append(task)
    if set(all_acs) - covered:
        raise MigrationError('Plan omitted acceptance criteria: ' + ','.join(sorted(set(all_acs) - covered)))
    if wave == 'domains':
        mapping = read_json(project / 'spec/baseline/ios-coverage.json')['mappings']
        obs = read_json(project / 'spec/baseline/ios-obligations.json')['obligations']
        by_obligation = {o['id']: o for o in obs}
        for row in mapping:
            if row['obligation_id'] in report.get('excluded_obligation_ids', []):
                continue  # Only source-harness-validated Preview reviews are non-product obligations.
            fact_id = by_obligation[row['obligation_id']]['fact_id']
            if not any(fact_id in t['fact_ids'] and set(t['ac_ids']) & set(row['ac_ids']) for t in tasks):
                raise MigrationError('Obligation has no implementation owner: ' + row['obligation_id'])
    completed = set()
    while len(completed) < len(tasks):
        ready = [t['id'] for t in tasks if t['id'] not in completed and isinstance(t.get('parents', []), list) and set(t.get('parents', [])) <= completed]
        if not ready:
            raise MigrationError('Unknown parent or dependency cycle')
        completed.update(ready)
    parallel = request.get('max_parallel', 1)
    if type(parallel) is not int or not 1 <= parallel <= 8:
        raise MigrationError('max_parallel must be 1..8; serial is the default')
    if validate_only:
        return {'status': 'request_validated', 'source_sha256': graph['source_sha256'], 'plan_contract': plan_contract}
    plan_path = project / f'spec/waves/plan-{wave}.json'
    if plan_path.exists():
        raise MigrationError('Existing plan is immutable; use a new project or explicit reviewed replan')
    blueprint = project / 'spec/blueprint'
    if wave == 'domains' and (blueprint / 'workflow-params.json').exists():
        if read_json(blueprint / 'workflow-params.json').get('ios_adapter_version') != 2:
            raise MigrationError('Original blueprint needs explicit compatibility adaptation')
    # Pin complete model-authored request in the canonical six-item contract.
    input_hashes = baseline_inputs(project, wave)
    for name, value in {
        'domain-map.json': {'version': 1, 'domains': [{'key': t['id'], 'title': t['goal'], 'pages': []} for t in planned]},
        'ownership.json': {'version': 1, 'owners': {t['id']: t['ownership'] for t in planned}, 'mainloop_owned': []},
        'contracts.json': {'version': 1, 'ios_adapter_version': 2, 'source_sha256': graph['source_sha256'],
                           'graph_sha256': graph_hash, 'input_hashes': input_hashes, 'ios_tasks': tasks, 'modules': [], 'wires': [],
                           'spec_contract_version': contract_profile, 'contract_revision': contract_revision(project),
                           'task_inputs': plan_contract['task_inputs']},
        'decisions.json': {'version': 1, 'decisions': request.get('decisions', [])},
        'workflow-params.json': {'ios_adapter_version': 2, 'project': {'root': str(project), 'ios_src': str(source)}, 'gates': {'unattended': False}}
    }.items():
        write_json(blueprint / name, value)
    if not (blueprint / 'decision-ledger.md').exists():
        atomic_write(blueprint / 'decision-ledger.md', b'# iOS decisions\n\nNo implicit platform decisions.\n')
    warnings = []
    nodes = []
    for t in planned:
        prompt = f'spec/waves/prompts/{wave}/{t["id"]}.txt'
        receipt = f'spec/waves/results/{wave}/{t["id"]}.json'
        facts = [f for f in graph['facts'] if f['id'] in t['fact_ids']]
        consumer_inputs = plan_contract['task_inputs'].get(t['id'], [])
        body = ('Use the assigned bundled role and iOS skill protocol. You share the codebase; preserve others\' edits.\n'
                'Read spec/ref/ios-expertise-plan.json and ios-expertise-reviews.json when present.\n'
                'Use frozen source semantics, ACs and linked tool_evidence_ids; do not replace source behavior with upstream best practices.\n'
                'Only write the explicitly owned files. Shared wiring requires its designated owner.\n'
                'Return generated/blocked; generation is not compilation or behavior verification.\n'
                f'Goal: {t["goal"]}\nRole: {t["role"]}\nOwnership: {t["ownership"]}\nACs: {t.get("ac_ids", [])}\n'
                f'Spec contract profile: {contract_profile}; revision: {contract_revision(project)}\n'
                f'Markdown plan items: {t.get("plan_item_refs", [])}\nVerification obligation: {t.get("verification", "generated")} (not an achieved result)\n'
                'Read each mapped item and preserve all its verification duties; the highest enum does not replace independent behavior/visual evidence.\n'
                'Required inputs: read every exact heading below at the pinned file hash. If missing/conflicting, return blocked and identify the conflicting references.\n'
                + json_bytes(consumer_inputs).decode() + '\n'
                +
                f'Receipt path: {receipt}\nUse ios-receipt v2 with source_sha256, plan_sha256, task_id, files hashes, ac_ids and findings.\n'
                'Facts:\n' + json_bytes(facts).decode() + '\nDecisions:\n' + json_bytes(request.get('decisions', [])).decode())
        atomic_write(safe_child(project, prompt), body.encode())
        nodes.append({'id': t['id'], 'kind': 'agent', 'agent': t['role'] + '@0.6.0',
                      'model': t.get('model', 'inherit'), 'schema': 'fixResult',
                      'prompt_file': prompt, 'parents': t.get('parents', []), 'map_group': 'ios-' + wave,
                      'ownership': t['ownership'], 'result_path': receipt, 'resume_key': wave + ':' + t['id']})
    plan = {'plan_version': 'a2h-2.1.0', 'wave': wave,
            'max_parallel': parallel, 'max_attempts': 2, 'tasks': nodes, 'products': {}, 'ios_adapter_version': 2}
    contract = read_json(blueprint / 'contracts.json')
    contract['plan_identity_sha256'] = digest(json_bytes(plan))
    contract['prompt_hashes'] = {n['prompt_file']: digest(safe_child(project, n['prompt_file']).read_bytes()) for n in nodes}
    write_json(blueprint / 'contracts.json', contract)
    contract_hash = kernel().compute_contract_hash(blueprint, warnings)
    plan['contract_hash'] = contract_hash
    write_json(plan_path, plan)
    invoke(project, 'state_update', ['--state', 'spec/state/state.json', '--op', 'init', '--json'])
    return {'status': 'plan_generated', 'plan': str(plan_path), 'contract_hash': contract_hash, 'warnings': warnings,
            'state_writer': 'original state_update.py', 'behavior_verified': False}


def step(project, wave, *, landing=False):
    from .native_pipeline import context
    source, project = context(project)
    if wave not in {'understand', 'domains'}:
        raise MigrationError('Unsupported adapter wave')
    plan_path = project / f'spec/waves/plan-{wave}.json'
    plan = read_json(plan_path)
    if plan.get('ios_adapter_version') != 2:
        raise MigrationError('Do not mix original and iOS state consumers')
    contract = read_json(project / 'spec/blueprint/contracts.json')
    from .plan_contract import assert_pinned
    assert_pinned(project, contract)
    for refs in contract.get('task_inputs', {}).values():
        for ref in refs:
            if digest(safe_child(project, ref['path']).read_bytes()) != ref['sha256']:
                raise MigrationError('Pinned task contract input changed: ' + ref['path'] + '#' + ref['heading'])
    if digest(json_bytes({k: v for k, v in plan.items() if k != 'contract_hash'})) != contract.get('plan_identity_sha256'):
        raise MigrationError('Plan IR changed after generation; do not dispatch edited tasks')
    for path, expected in contract.get('prompt_hashes', {}).items():
        if digest(safe_child(project, path).read_bytes()) != expected:
            raise MigrationError('Task prompt changed after generation: ' + path)
    graph, _ = validate_graph(source, project)
    if graph['source_sha256'] != contract['source_sha256']:
        raise MigrationError('Plan source snapshot changed')
    if baseline_inputs(project, wave) != contract['input_hashes']:
        raise MigrationError('Plan baseline changed; review and explicitly replan')
    if wave == 'domains' and check(project)[1]:
        raise MigrationError('Source harness gate failed')
    if landing:
        evidence_path = project / f'spec/reports/ios-dispatch-{wave}.json'
        dispatch_evidence = read_json(evidence_path)
        if dispatch_evidence.get('plan_sha256') != digest(plan_path.read_bytes()):
            raise MigrationError('Dispatch evidence does not match frozen plan')
        actual = execution_files(project)
        before = dispatch_evidence['before_files']
        changed = {p for p in before.keys() | actual.keys() if before.get(p) != actual.get(p)}
        active_ids = set(dispatch_evidence['task_ids'])
        allowed = {p for task in contract['ios_tasks'] if task['id'] in active_ids for p in task['ownership']}
        if changed - allowed:
            raise MigrationError('Dispatch changed files outside ownership: ' + ','.join(sorted(changed - allowed)))
        owned_tasks = {t['id']: t for t in contract['ios_tasks']}
        for task in plan['tasks']:
            path = safe_child(project, task['result_path'])
            if not path.exists():
                continue  # Original in-flight timeout and retry rules remain authoritative.
            receipt = validate(read_json(path), 'receipt')
            task_def = owned_tasks[task['id']]
            # Adapter receipt and original schema share a single result file, never a second state file.
            if receipt.get('ios_receipt_version') != 2 or receipt.get('source_sha256') != graph['source_sha256'] or receipt.get('plan_sha256') != digest(plan_path.read_bytes()) or receipt.get('task_id') != task['id']:
                raise MigrationError('Stale/invalid receipt: ' + task['id'])
            if receipt.get('status') not in {'generated', 'blocked'} or receipt.get('behavior_verified') is not False:
                raise MigrationError('Receipt cannot claim compilation or behavior acceptance')
            if receipt.get('final_state') != ('PASS' if receipt['status'] == 'generated' else 'BLOCKED'):
                raise MigrationError('Receipt generation status and original final_state disagree')
            files = receipt.get('file_hashes')
            readonly_verification = contract.get('spec_contract_version', 1) >= 2 and not task_def['ownership'] and task_def.get('verification') in {'compile', 'behavior', 'visual'}
            if not isinstance(files, dict) or receipt.get('status') == 'generated' and not files and not readonly_verification:
                raise MigrationError('Receipt must pin actual generated files')
            for name, expected in files.items():
                if name not in task_def['ownership'] or digest(safe_child(project, name).read_bytes()) != expected:
                    raise MigrationError('Receipt ownership/hash mismatch: ' + name)
            if receipt.get('status') == 'generated' and set(files) != set(task_def['ownership']):
                raise MigrationError('Generated receipt omitted planned outputs')
            if set(receipt.get('files_touched', [])) != set(files):
                raise MigrationError('Original touched-files field differs from pinned outputs')
            if set(receipt.get('ac_ids', [])) != set(task_def.get('ac_ids', [])):
                raise MigrationError('Receipt omitted task acceptance criteria')
            if receipt.get('status') == 'generated' and receipt.get('findings'):
                raise MigrationError('Open semantic findings cannot be landed as generated success')
        action = invoke(project, 'land_results', ['--plan', str(plan_path), '--state', 'spec/state/state.json', '--json'])
    else:
        before = execution_files(project)
        action = invoke(project, 'next_batch', ['--plan', str(plan_path), '--state', 'spec/state/state.json', '--json'])
        if action.get('action') == 'dispatch':
            evidence_path = project / f'spec/reports/ios-dispatch-{wave}.json'
            prior = read_json(evidence_path) if evidence_path.exists() else None
            # Preserve earlier batch baseline so in-flight writes stay attributable.
            if prior and prior.get('plan_sha256') == digest(plan_path.read_bytes()):
                before = prior['before_files']
                task_ids = list(dict.fromkeys(prior['task_ids'] + [b['id'] for b in action['batch']]))
            else:
                task_ids = [b['id'] for b in action['batch']]
            write_json(evidence_path, {'plan_sha256': digest(plan_path.read_bytes()), 'before_files': before, 'task_ids': task_ids})
    action['ios_scope'] = 'task generation only; compile and behavior gates remain separate'
    action['behavior_verified'] = False
    failed = action.get('action') == 'escalate' or any(x.get('status') in {'RETRY_NEEDED', 'RETRY_EXHAUSTED'} for x in action.get('landed', []))
    return action, 2 if failed else 0


def replan(project, input_path):
    """Explicit new run: preserve every old control artifact; never import old success."""
    from .native_pipeline import context
    source, project = context(project)
    request = validate(read_json(input_path), 'planRequest')
    review = request.get('replan_review', {})
    if not all(isinstance(review.get(k), str) and review[k].strip() for k in ('reviewer', 'reason')):
        raise MigrationError('Replan requires a concrete reviewer and change reason')
    graph, _ = validate_graph(source, project)
    if request['graph_sha256'] != digest(json_bytes(graph)) or request['wave'] == 'domains' and check(project)[1]:
        raise MigrationError('Resolve changed source contracts before replanning')
    generate(project, input_path, validate_only=True)
    state_dir = project / 'spec/state'
    if (state_dir / 'dispatch.json').exists():
        dispatch = read_json(state_dir / 'dispatch.json')
        journal = read_json(state_dir / 'journal.json') if (state_dir / 'journal.json').exists() else {}
        for wave, record in dispatch.get('waves', {}).items():
            landed, _ = kernel().journal_indexes(journal, wave)
            if any(row.get('attempts', 0) > landed.get(ident, 0) for ident, row in record.get('dispatched', {}).items()):
                raise MigrationError('In-flight tasks must land or be explicitly terminated before replan')
    archive = safe_child(project, 'spec/.a2h/history/replan-' + uuid.uuid4().hex)
    archive.mkdir(parents=True)
    moved = []
    try:
        for relative in ('spec/state', 'spec/blueprint', 'spec/waves'):
            origin = safe_child(project, relative)
            if origin.exists():
                destination = safe_child(archive, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                origin.rename(destination)
                moved.append((origin, destination))
        result = generate(project, input_path)
    except Exception:
        # No recursive deletes. A partial new run is retained for diagnosis; old
        # data stays recoverable and never gets silently overwritten.
        write_json(archive / 'replan-failure.json', {'review': review, 'moved': [str(d) for _, d in moved], 'status': 'failed'})
        raise
    result.update(archive=str(archive), replan_review=review, prior_success_inherited=False)
    write_json(archive / 'replan-review.json', result)
    return result
