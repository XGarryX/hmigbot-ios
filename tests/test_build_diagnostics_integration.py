import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from hmigbot_ios.build import build_target
from hmigbot_ios.core import digest
from hmigbot_ios.harmony_diagnostics import analyze, verify

ROOT = Path(__file__).resolve().parents[1]


def test_zero_exit_and_hap_with_compiler_error_is_rejected(tmp_path):
    source, target = tmp_path / 'ios', tmp_path / 'target'
    source.mkdir()
    target.mkdir()
    (source / 'Model.swift').write_text('struct Model {}', encoding='utf-8')
    (target / 'build-profile.json5').write_text('{}', encoding='utf-8')
    wrapper = tmp_path / 'hvigorw.js'
    wrapper.write_text('// synthetic process boundary', encoding='utf-8')
    hap = target / 'entry/build/default/test.hap'
    hap.parent.mkdir(parents=True)
    hap.write_bytes(b'synthetic artifact for contradictory-log regression')
    config = {'source': {'platform': 'ios', 'root': str(source)},
              'target': {'root': str(target)},
              'tools': {'hvigorw': str(wrapper), 'node': sys.executable}}
    logs = b'ERROR: compiler rejected input\nBUILD SUCCESSFUL\n'
    with patch('hmigbot_ios.build.subprocess.run', return_value=subprocess.CompletedProcess([], 0, logs, b'')):
        report = build_target(config, tmp_path / 'evidence')
    assert report['exit_code'] == 0
    assert report['artifacts']
    assert report['hvigor_success_marker']
    assert report['status'] == 'build_failed'
    path = tmp_path / 'evidence/diagnostics.json'
    diagnostic = json.loads(path.read_text(encoding='utf-8'))
    assert diagnostic['status'] == 'conflicting_build_evidence'
    assert report['diagnostics']['sha256'] == digest(path.read_bytes())
    assert verify(diagnostic)
    assert (tmp_path / 'evidence/stdout.log').read_bytes() == logs
    assert json.loads((tmp_path / 'evidence/build.json').read_text(encoding='utf-8')) == report


def _cli(*arguments):
    return subprocess.run([sys.executable, str(ROOT / 'scripts/ios2harmony.py'),
                           'diagnose-build', *map(str, arguments)], capture_output=True, timeout=30)


def test_diagnostic_cli_keeps_unknown_failure_and_returns_small_receipt(tmp_path):
    log = tmp_path / 'stdout.log'
    log.write_bytes(b'opaque compiler failure\n')
    path = tmp_path / 'diagnostics.json'
    result = _cli('--stdout', log, '--returncode', 7, '--module', 'entry', '--output', path)
    assert result.returncode == 3, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['status'] == 'fail_unparsed'
    assert receipt['build_command_passed'] is False
    assert receipt['functional_verified'] is receipt['ui_verified'] is False
    assert 'findings' not in receipt
    assert len(result.stdout) < 2048
    assert receipt['sha256'] == digest(path.read_bytes())
    assert verify(json.loads(path.read_text(encoding='utf-8')))


def test_diagnostic_cli_refuses_to_replace_its_source_log(tmp_path):
    log = tmp_path / 'stdout.log'
    original = b'BUILD SUCCESSFUL\n'
    log.write_bytes(original)
    result = _cli('--stdout', log, '--returncode', 0, '--output', log)
    assert result.returncode == 2
    assert log.read_bytes() == original


def test_diagnostic_cli_success_is_only_command_evidence(tmp_path):
    log = tmp_path / 'stdout.log'
    log.write_bytes(b'BUILD SUCCESSFUL\n')
    path = tmp_path / 'diagnostics.json'
    result = _cli('--stdout', log, '--returncode', 0, '--output', path)
    assert result.returncode == 0, result.stderr
    report = json.loads(path.read_text(encoding='utf-8'))
    assert report['process_exit_zero'] is True
    assert report['overall_status'] == 'unknown'
    assert report['functional_verified'] is report['ui_verified'] is False


def test_unmapped_numeric_error_does_not_invent_arkts_rule(tmp_path):
    log = tmp_path / 'stdout.log'
    log.write_text('ERROR: Error code: 654321 unfamiliar failure\n', encoding='utf-8')
    finding = analyze(log, returncode=1)['findings'][0]
    assert finding['error_code'] == '654321'
    assert finding['category'] == 'unknown'
    assert finding['confidence'] == 'low'
    assert finding['suggestion'] is None


def test_findings_cap_applies_to_both_streams_together(tmp_path):
    stdout, stderr = tmp_path / 'stdout.log', tmp_path / 'stderr.log'
    stdout.write_text(''.join('ERROR: stdout failure %d\n' % i for i in range(180)), encoding='utf-8')
    stderr.write_text(''.join('ERROR: stderr failure %d\n' % i for i in range(180)), encoding='utf-8')
    report = analyze(stdout, stderr, 1)
    assert len(report['findings']) == 200
    assert report['summary']['truncated'] is True
    assert {item['log_ref']['stream'] for item in report['findings']} == {'stdout', 'stderr'}


def test_success_summary_or_benign_error_word_is_not_a_compiler_error(tmp_path):
    log = tmp_path / 'stdout.log'
    log.write_text('INFO: error diagnostics enabled\nCOMPILE RESULT:SUCCESS {ERROR:0 WARN:0}\n'
                   'WARNING: use a concrete error type\nBUILD SUCCESSFUL\n', encoding='utf-8')
    report = analyze(log, returncode=0)
    assert report['build_command_passed'] is True
    assert report['status'] == 'build_command_passed'
    assert report['summary']['errors'] == 0
    assert report['overall_status'] == 'unknown'
