"""Real child-process races and fixed-input tests; no compiler or migration claims."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from hmigbot_ios.atoms import run_atom
from hmigbot_ios.core import MigrationError, digest, read_json, snapshot, write_json
from hmigbot_ios.evidence import pack
from hmigbot_ios.ios_facts import refresh, validate_graph
from hmigbot_ios.provider_runs import ProviderRun


RUNTIME = Path(__file__).resolve().parents[1] / 'src'
WORKER = '''
import json, pathlib, sys, time
sys.path.insert(0, sys.argv[1])
from hmigbot_ios.atoms import run_atom
from hmigbot_ios.core import snapshot
from hmigbot_ios.provider_runs import ProviderRun
source, project, barrier = map(pathlib.Path, sys.argv[2:5])
label, case = sys.argv[5:7]
run = ProviderRun(project, 'interface-builder', snapshot(source)['sha256'])
(barrier / ('ready-' + label)).write_text('ready')
deadline = time.monotonic() + 15
while len(list(barrier.glob('ready-*'))) < 2:
    if time.monotonic() > deadline:
        raise RuntimeError('concurrency barrier timed out')
    time.sleep(0.01)
run.reserve()
try:
    if case == 'fail_fail' or (case == 'success_fail' and label == 'B'):
        raise ValueError('fixture failure ' + label)
    with run.fixed_inputs() as (config, bundle):
        report = run_atom('interface-builder', source, run.directory, provider_config=config, input_path=bundle)
        run.publish(report)
    status = 'succeeded'
except Exception as exc:
    run.fail(exc)
    status = 'failed'
print(json.dumps({'directory': str(run.directory), 'attempt': run.attempt, 'run_id': run.run_id, 'status': status}))
'''


def setup_source(tmp_path):
    source, project = tmp_path / 'source', tmp_path / 'project'
    source.mkdir()
    project.mkdir()
    (source / 'App.swift').write_text('struct App { var canCreate: Bool { true } }\n')
    return source, project


def make_plan(tmp_path, operation, config=None, bundle=None):
    entry = {'operation': operation}
    if config:
        entry['config'] = str(config)
    if bundle:
        entry['input'] = str(bundle)
    plan = tmp_path / 'plan.json'
    write_json(plan, {'schema_version': 2, 'providers': [entry]})
    return plan


def make_provider(path, marker):
    script = """import json, sys
if '--version' in sys.argv:
    print(MARKER)
else:
    inputs = json.load(sys.stdin)
    print(json.dumps({'protocol_version': 1, 'provider': 'SwiftSyntax', 'semantic_resolution': False,
        'implementation_marker': MARKER,
        'files': [{'path': f['path'], 'sha256': f['sha256'], 'nodes': [], 'parse_has_error': False} for f in inputs['files']]}))
"""
    path.write_text(script.replace('MARKER', repr(marker)), encoding='utf-8')


def provider_config(script):
    return {'command': [sys.executable, '-B', str(script)],
            'version_command': [sys.executable, '-B', str(script), '--version']}


@pytest.mark.parametrize('case,successes', [('fail_fail', 0), ('success_fail', 1), ('success_success', 2)])
def test_real_processes_get_exclusive_attempts_and_keep_all_evidence(tmp_path, case, successes):
    source, project = setup_source(tmp_path)
    barrier = tmp_path / 'barrier'
    barrier.mkdir()
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    workers = [subprocess.Popen([sys.executable, '-B', '-c', WORKER, str(RUNTIME), str(source),
                                str(project), str(barrier), label, case],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
               for label in ('A', 'B')]
    results = []
    try:
        for worker in workers:
            stdout, stderr = worker.communicate(timeout=20)
            assert worker.returncode == 0, stderr.decode(errors='replace')
            results.append(json.loads(stdout))
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.wait()
    assert len({item['directory'] for item in results}) == 2
    assert {item['attempt'] for item in results} == {1, 2}
    assert len({item['run_id'] for item in results}) == 2
    records = [read_json(Path(item['directory']) / 'run.json') for item in results]
    assert sum(record['status'] == 'succeeded' for record in records) == successes
    assert len(list(project.rglob('artifact.json'))) == successes
    failures = [read_json(path) for path in project.rglob('failure.json')]
    assert len(failures) == 2 - successes
    assert len({item['error'] for item in failures}) == len(failures)


def test_tool_replaced_at_same_path_is_executed_again(tmp_path):
    source, project = setup_source(tmp_path)
    tool = tmp_path / 'provider.py'
    make_provider(tool, 'fixture-version-1')
    config = tmp_path / 'config.json'
    write_json(config, provider_config(tool))
    plan = make_plan(tmp_path, 'swift-syntax', config)
    first = refresh(project, source, provider_plan=plan)['provider_artifacts'][0]
    original_artifact = (project / first['path']).read_bytes()
    config_hash = digest(config.read_bytes())
    make_provider(tool, 'fixture-version-2')
    second = refresh(project, source, provider_plan=plan)['provider_artifacts'][0]
    assert digest(config.read_bytes()) == config_hash
    assert first['path'] != second['path']
    assert read_json(project / second['path'])['data']['tool_version_output'] == 'fixture-version-2'
    assert (project / first['path']).read_bytes() == original_artifact
    assert ProviderRun(project, 'swift-syntax', snapshot(source)['sha256'], config=config).reusable() is None
    assert ProviderRun(project, 'clang-ast', snapshot(source)['sha256'], config=config).reusable() is None


def test_reservation_survives_atoms_empty_directory_publication_window(tmp_path):
    source, project = setup_source(tmp_path)
    first = ProviderRun(project, 'interface-builder', snapshot(source)['sha256'])
    first.reserve()
    assert not any(first.directory.iterdir())
    first.directory.rmdir()  # Emulate write_new_tree between empty-output removal and rename.
    second = ProviderRun(project, 'interface-builder', snapshot(source)['sha256'])
    second.reserve()
    assert second.attempt == first.attempt + 1
    assert second.directory != first.directory


def test_finished_attempt_cannot_overwrite_its_success_with_failure(tmp_path):
    source, project = setup_source(tmp_path)
    run = ProviderRun(project, 'interface-builder', snapshot(source)['sha256'])
    run.reserve()
    with run.fixed_inputs() as (config, bundle):
        report = run_atom('interface-builder', source, run.directory, provider_config=config, input_path=bundle)
        run.publish(report)
    original = (run.directory / 'run.json').read_bytes()
    with pytest.raises(MigrationError, match='terminal record'):
        run.fail(ValueError('late failure'))
    assert (run.directory / 'run.json').read_bytes() == original
    assert not run.failure_path.exists()


def test_config_aba_consumes_initial_bytes_and_erases_private_copy(tmp_path, monkeypatch):
    source, project = setup_source(tmp_path)
    first_tool, other_tool = tmp_path / 'first.py', tmp_path / 'other.py'
    make_provider(first_tool, 'config-A')
    make_provider(other_tool, 'config-B')
    config = tmp_path / 'config.json'
    value = provider_config(first_tool)
    value['sensitive_fixture'] = 'private-fixture-value'
    write_json(config, value)
    original = config.read_bytes()
    fixed_paths = []

    def aba(operation, root, output, **kwargs):
        fixed = kwargs['provider_config']
        fixed_paths.append(fixed)
        assert fixed != config
        assert fixed.read_bytes() == original
        write_json(config, provider_config(other_tool))
        try:
            return run_atom(operation, root, output, **kwargs)
        finally:
            config.write_bytes(original)

    monkeypatch.setattr('hmigbot_ios.atoms.run_atom', aba)
    graph = refresh(project, source, provider_plan=make_plan(tmp_path, 'swift-syntax', config))
    artifact = project / graph['provider_artifacts'][0]['path']
    assert read_json(artifact)['data']['implementation_marker'] == 'config-A'
    assert read_json(artifact.parent / 'run.json')['config_sha256'] == digest(original)
    assert all(not path.exists() for path in fixed_paths)
    assert all(b'private-fixture-value' not in path.read_bytes() for path in project.rglob('*') if path.is_file())


def test_relative_provider_arguments_keep_original_cwd(tmp_path, monkeypatch):
    source, project = setup_source(tmp_path)
    make_provider(tmp_path / 'provider.py', 'relative-command')
    settings = tmp_path / 'settings'
    settings.mkdir()
    config = settings / 'config.json'
    write_json(config, provider_config(Path('provider.py')))
    monkeypatch.chdir(tmp_path)
    graph = refresh(project, source, provider_plan=make_plan(tmp_path, 'swift-syntax', config))
    assert read_json(project / graph['provider_artifacts'][0]['path'])['data']['implementation_marker'] == 'relative-command'


def test_tampered_private_config_is_not_published(tmp_path, monkeypatch):
    source, project = setup_source(tmp_path)
    tool = tmp_path / 'provider.py'
    make_provider(tool, 'stable')
    config = tmp_path / 'config.json'
    write_json(config, provider_config(tool))

    def tamper(operation, root, output, **kwargs):
        result = run_atom(operation, root, output, **kwargs)
        kwargs['provider_config'].write_bytes(b'{}')
        return result

    monkeypatch.setattr('hmigbot_ios.atoms.run_atom', tamper)
    with pytest.raises(MigrationError, match='Provider failed'):
        refresh(project, source, provider_plan=make_plan(tmp_path, 'swift-syntax', config))
    assert not (project / 'spec/baseline/ios-facts.json').exists()
    record, = [read_json(path) for path in project.rglob('run.json')]
    assert record['status'] == 'failed'


def test_persistent_config_drift_fails_and_keeps_published_baseline_valid(tmp_path, monkeypatch):
    source, project = setup_source(tmp_path)
    tool = tmp_path / 'provider.py'
    make_provider(tool, 'stable')
    config = tmp_path / 'config.json'
    write_json(config, provider_config(tool))
    plan = make_plan(tmp_path, 'swift-syntax', config)
    refresh(project, source, provider_plan=plan)
    baseline = (project / 'spec/baseline/ios-facts.json').read_bytes()

    def drift(operation, root, output, **kwargs):
        changed = read_json(config)
        changed['timeout_seconds'] = 119
        write_json(config, changed)
        return run_atom(operation, root, output, **kwargs)

    monkeypatch.setattr('hmigbot_ios.atoms.run_atom', drift)
    with pytest.raises(MigrationError, match='Provider failed'):
        refresh(project, source, provider_plan=plan)
    assert (project / 'spec/baseline/ios-facts.json').read_bytes() == baseline
    validate_graph(source, project)
    assert len(list(project.rglob('failure.json'))) == 1
    assert [read_json(path)['status'] for path in sorted(project.rglob('run.json'))] == ['succeeded', 'failed']


def test_input_manifest_aba_consumes_fixed_hashed_payloads(tmp_path, monkeypatch):
    source, project = setup_source(tmp_path)
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    write_json(artifacts / 'build-settings.json', [{'target': 'App', 'buildSettings': {'PRODUCT_NAME': 'A'}}])
    bundle = tmp_path / 'bundle'
    pack(source, artifacts, bundle, 'source_build', 'fixture-provider')
    original_manifest = (bundle / 'manifest.json').read_bytes()
    payload = bundle / 'artifacts/build-settings.json'
    original_payload = payload.read_bytes()
    fixed_paths = []

    def aba(operation, root, output, **kwargs):
        fixed_paths.append(kwargs['input_path'])
        write_json(payload, [{'target': 'App', 'buildSettings': {'PRODUCT_NAME': 'B'}}])
        other_manifest = read_json(bundle / 'manifest.json')
        other_manifest['artifacts']['artifacts/build-settings.json'] = digest(payload.read_bytes())
        write_json(bundle / 'manifest.json', other_manifest)
        try:
            return run_atom(operation, root, output, **kwargs)
        finally:
            payload.write_bytes(original_payload)
            (bundle / 'manifest.json').write_bytes(original_manifest)

    monkeypatch.setattr('hmigbot_ios.atoms.run_atom', aba)
    graph = refresh(project, source, provider_plan=make_plan(tmp_path, 'build-settings', bundle=bundle))
    report = read_json(project / graph['provider_artifacts'][0]['path'])
    assert report['data']['targets'][0]['settings']['PRODUCT_NAME'] == 'A'
    assert report['input_manifest_sha256'] == digest(original_manifest)
    assert all(not path.exists() for path in fixed_paths)
