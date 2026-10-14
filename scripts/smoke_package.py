"""Install an extracted ZIP and run original consumers using only installed resources."""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
from manage_install import filesystem_path


def sha(path):
    with filesystem_path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Use a new validation report path')
    package = args.package.resolve()
    checksum = sha(package)
    if checksum != package.with_suffix(package.suffix + '.sha256').read_text().split()[0]:
        raise SystemExit('Package checksum mismatch')
    report = {'package': package.name, 'sha256': checksum, 'status': 'failed', 'checks': [],
              'platform': platform.platform(), 'architecture': platform.machine(),
              'scope': 'Standalone installation, original consumers and installed iOS harness adversarial/four-beat contracts on this host; no device behavior acceptance'}
    evidence = args.output.resolve().parent / (args.output.stem + '-evidence')
    if evidence.exists(): raise SystemExit('Evidence directory already exists')
    evidence.mkdir(parents=True)
    try:
        with tempfile.TemporaryDirectory(prefix='hmigbot standalone 发行包 ') as tmp:
            root = Path(tmp).resolve()
            with zipfile.ZipFile(package) as archive:
                for info in archive.infolist():
                    path = (root / info.filename).resolve()
                    if not path.is_relative_to(root) or '\\' in info.filename or ':' in info.filename or (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise RuntimeError('Unsafe ZIP path or link')
                if archive.testzip(): raise RuntimeError('Package CRC failure')
                archive.extractall(root)
            plugin = root / 'hmigbot-ios'
            workspace = root / '安装 workspace'
            workspace.mkdir()
            original = b'# User rules\r\nPreserve these exact bytes.\r\n'
            (workspace / 'AGENTS.md').write_bytes(original)
            env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHON': sys.executable, 'A2H_TELEMETRY_OFF': '1'}

            def execute(name, command, cwd=root):
                result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=300, shell=False)
                (evidence / (name + '.stdout.log')).write_bytes(result.stdout)
                (evidence / (name + '.stderr.log')).write_bytes(result.stderr)
                report['checks'].append({'name': name, 'exit_code': result.returncode, 'passed': result.returncode == 0})
                if result.returncode:
                    raise RuntimeError(name + ': ' + result.stderr.decode('utf-8', errors='replace'))
                return result

            def wrapper(mode, base):
                if os.name == 'nt':
                    return ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(base / (mode + '.ps1')),
                            '-Workspace', str(workspace), '-Python', sys.executable]
                return ['/bin/sh', str(base / (mode + '.sh')), str(workspace)]

            installed = json.loads(execute('platform-install', wrapper('install', plugin)).stdout)
            if installed.get('skills') != 96 or installed.get('agents') != 29 or installed.get('hmigbot') != 'bundled':
                raise RuntimeError('Incomplete installed skill/role resources')
            runtime = workspace / '.hmigbot-ios/plugin'
            manifest = json.loads((workspace / '.hmigbot-ios/install.json').read_text(encoding='utf-8'))
            for relative, expected in manifest['files'].items():
                if sha(workspace / relative) != expected:
                    raise RuntimeError('Installed file differs from manifest: ' + relative)
            if (workspace / '.hmigbot-ios/hmigbot-binding.json').exists():
                raise RuntimeError('External HMigBot binding unexpectedly required')
            report['checks'].append({'name': 'all-installed-resources-hashed', 'passed': True, 'files': len(manifest['files'])})
            # Source assets are fixture data only. Every consumer below comes from the installed runtime.
            fixtures = plugin / 'tests/fixtures'
            execute('installed-native-pipeline', [sys.executable, '-X', 'utf8', str(runtime / 'scripts/validate_native_pipeline.py'),
                    '--fixtures', str(fixtures), '--output', str(evidence / 'native-pipeline')])
            execute('installed-upstream-audit', [sys.executable, '-X', 'utf8', str(runtime / 'scripts/audit_upstream.py')])
            execute('installed-scheduler-audit', [sys.executable, '-X', 'utf8', str(runtime / 'scripts/audit_scheduler.py')])
            execute('installed-expertise-audit', [sys.executable, '-X', 'utf8', str(runtime / 'scripts/a2h_ios.py'), 'expertise-audit'])
            execute('installed-native-surface', [sys.executable, '-X', 'utf8', str(runtime / 'scripts/audit_native_surface.py')])
            env['HMIGBOT_TEST_RUNTIME'] = str(runtime)
            execute('installed-ios-harness', [sys.executable, '-X', 'utf8', '-m', 'unittest', 'discover',
                    '-s', str(plugin / 'tests'), '-p', 'test_ios_harness.py', '-v'])
            execute('installed-spec-contract', [sys.executable, '-X', 'utf8', '-m', 'unittest', 'discover',
                    '-s', str(plugin / 'tests'), '-p', 'test_spec_contract.py', '-v'])
            execute('installed-expertise-mcp', [sys.executable, '-X', 'utf8', '-m', 'unittest', 'discover',
                    '-s', str(plugin / 'tests'), '-p', 'test_expertise_mcp.py', '-v'])
            del env['HMIGBOT_TEST_RUNTIME']
            fixture_project = evidence / 'native-pipeline/harmony'
            native = workspace / '.migbot/bin' / ('a2h.exe' if os.name == 'nt' else 'a2h')
            execute('offline-runtime-init', [str(native), 'init-run', '--consent', 'denied'], cwd=fixture_project)
            execute('offline-stage-marker', [str(native), 'mark-stage', 'a2h-retrospect'], cwd=fixture_project)
            if not list((fixture_project / '.migbot/metrics').glob('*/retrospect.done')):
                raise RuntimeError('Original runtime did not produce the stage sentinel')
            # Hide the extracted original before upgrading from the installed copy.
            plugin.rename(root / 'extracted-source-hidden')
            execute('self-contained-upgrade', wrapper('install', runtime))
            execute('self-contained-uninstall', wrapper('uninstall', runtime))
            if (workspace / 'AGENTS.md').read_bytes() != original or (workspace / '.agents/skills/a2h-run/SKILL.md').exists():
                raise RuntimeError('Uninstall did not preserve ownership boundaries')
            report['checks'].append({'name': 'restored-original-agents', 'passed': True})
            report['status'] = 'passed'
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired, zipfile.BadZipFile) as exc:
        report['error'] = str(exc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
