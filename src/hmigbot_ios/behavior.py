"""Behavior-chain gate and explicit process observations; no generated done markers."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .core import MigrationError, digest, json_bytes, read_json, safe_child, snapshot, write_json


def verify(project, source, graph, acs, *, run=False):
    failures, observations = [], []
    spec = read_json(project / 'spec/verification/ios-behavior.json')
    if spec.get('schema_version') != 2 or spec.get('source_sha256') != graph['source_sha256']:
        raise MigrationError('Behavior cases must pin the current independent source snapshot')
    facts = {f['id']: f for f in graph['facts']}
    required = {f['id'] for f in graph['facts'] if f['kind'] in {'event', 'persistence'}}
    linked, covered = set(), set()
    for chain in spec.get('chains', []):
        ident = chain.get('source_fact')
        if ident not in required or ident in linked:
            failures.append({'rule': 'IOS.BEHAVIOR_CHAIN_ID', 'subject': ident}); continue
        linked.add(ident)
        keys = ['input', 'processing', 'feedback'] if facts[ident]['kind'] == 'event' else ['save', 'reload', 'business_effect']
        for key in keys:
            node = chain.get(key)
            try:
                if not isinstance(node, dict) or not isinstance(node.get('symbol'), str) or not node['symbol']:
                    raise MigrationError('Chain node requires a concrete target symbol')
                path = safe_child(project, node['path'])
                data = path.read_bytes()
                if node.get('sha256') != digest(data):
                    raise MigrationError('Target chain node hash is stale')
                text = data.decode('utf-8-sig')
                line = node.get('line')
                if type(line) is not int or not 1 <= line <= len(text.splitlines()) or node['symbol'] not in text.splitlines()[line - 1]:
                    raise MigrationError('Target symbol/line is not present')
                # Minimal detectable empty callbacks/methods, never treated as exhaustive analysis.
                if re.search(r'(?:=>|\b' + re.escape(node['symbol']) + r'\s*\([^)]*\)\s*(?::[^\{\n]+)?)\s*\{\s*(?://[^\n]*\n\s*|/\*.*?\*/\s*)*\}', text, re.S):
                    raise MigrationError('Empty target handler cannot implement a behavior chain')
            except (MigrationError, OSError, UnicodeError, KeyError, TypeError) as exc:
                failures.append({'rule': 'IOS.BEHAVIOR_NODE', 'subject': str(ident) + ':' + key, 'detail': str(exc)})
        if chain.get('review', {}).get('status') != 'reviewed' or not chain.get('review', {}).get('reviewer'):
            failures.append({'rule': 'IOS.BEHAVIOR_REVIEW', 'subject': ident})
    for ident in sorted(required - linked):
        failures.append({'rule': 'IOS.BEHAVIOR_CHAIN_MISSING', 'subject': ident})
    seen = set()
    target_before = snapshot(project)['sha256']
    for case in spec.get('cases', []):
        ident = case.get('id')
        if not isinstance(ident, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', ident) or ident in seen:
            failures.append({'rule': 'IOS.BEHAVIOR_CASE_ID', 'subject': str(ident)}); continue
        seen.add(ident)
        ids = case.get('ac_ids')
        if not isinstance(ids, list) or not ids or any(a not in acs for a in ids):
            failures.append({'rule': 'IOS.BEHAVIOR_CASE_AC', 'subject': ident}); continue
        if not all(acs[a]['judgment'] == case.get('runner') for a in ids):
            failures.append({'rule': 'IOS.BEHAVIOR_RUNNER', 'subject': ident}); continue
        if case.get('oracle', {}).get('source_fact') not in facts or 'expected' not in case.get('oracle', {}) or not case.get('oracle', {}).get('reviewer'):
            failures.append({'rule': 'IOS.INDEPENDENT_ORACLE_MISSING', 'subject': ident}); continue
        targets = case.get('target_hashes')
        if not isinstance(targets, dict) or not targets:
            failures.append({'rule': 'IOS.BEHAVIOR_TARGET_UNBOUND', 'subject': ident}); continue
        try:
            if any(digest(safe_child(project, path).read_bytes()) != expected for path, expected in targets.items()):
                raise MigrationError('Observed target inputs changed')
        except (MigrationError, OSError, TypeError) as exc:
            failures.append({'rule': 'IOS.BEHAVIOR_TARGET_STALE', 'subject': ident, 'detail': str(exc)}); continue
        command = case.get('command')
        timeout = case.get('timeout_seconds', 60)
        if not isinstance(command, list) or not command or any(not isinstance(v, str) or not v for v in command) or type(timeout) is not int or not 1 <= timeout <= 600:
            failures.append({'rule': 'IOS.BEHAVIOR_COMMAND', 'subject': ident}); continue
        observed = {'id': ident, 'ac_ids': ids, 'runner': case['runner'], 'status': 'not_run', 'command': command}
        if run:
            output = project / 'spec/reports/behavior' / ident
            output.mkdir(parents=True, exist_ok=True)
            try:
                proc = subprocess.run(command, cwd=project, input=json_bytes(case.get('input')), capture_output=True, timeout=timeout, shell=False)
                stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
            except subprocess.TimeoutExpired as exc:
                stdout, stderr, code = exc.stdout or b'', exc.stderr or b'', None
            except OSError as exc:
                stdout, stderr, code = b'', str(exc).encode(), None
            (output / 'stdout.log').write_bytes(stdout)
            (output / 'stderr.log').write_bytes(stderr)
            observed['exit_code'] = code
            try:
                import json
                actual = json.loads(stdout)
            except (ValueError, UnicodeError):
                actual = None
            passed = code == 0 and actual == case['oracle']['expected']
            observed.update(status='observed_pass' if passed else 'observed_fail', actual=actual,
                            stdout_sha256=digest(stdout), stderr_sha256=digest(stderr))
            if passed:
                covered.update(ids)
            else:
                failures.append({'rule': 'IOS.BEHAVIOR_OBSERVATION', 'subject': ident})
        observations.append(observed)
        if run:
            try:
                if any(digest(safe_child(project, path).read_bytes()) != expected for path, expected in targets.items()):
                    raise MigrationError('Observed target inputs changed during execution')
            except (MigrationError, OSError, TypeError) as exc:
                failures.append({'rule': 'IOS.BEHAVIOR_TARGET_CHANGED', 'subject': ident, 'detail': str(exc)})
    # Report whether invoked processes changed source/target rather than silently accepting side effects.
    if snapshot(source)['sha256'] != graph['source_sha256']:
        failures.append({'rule': 'IOS.BEHAVIOR_SOURCE_CHANGED', 'subject': 'source'})
    pending = sorted(set(acs) - covered)
    report = {'schema_version': 2, 'status': 'FAIL' if failures else 'UNVERIFIED' if pending else 'PASS',
              'source_sha256': graph['source_sha256'], 'target_before_sha256': target_before,
              'failures': failures, 'observations': observations, 'unverified_ac_ids': pending,
              'behavior_verified': not failures and not pending,
              'scope': 'declared cases and process observations; source oracle and device authenticity need independent review'}
    write_json(project / 'spec/reports/ios-behavior-check.json', report)
    return report, 2 if failures else 3 if pending else 0
