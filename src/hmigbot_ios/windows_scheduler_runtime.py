"""Windows-only runtime bootstrap, separate from immutable plan contracts.

This replaces process staging, not scheduler algorithms: the shipped original
binary still validates and writes all three state ledgers. A disposable helper
shim loads the original lint rules with a linear equivalent declaration match.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from .core import MigrationError, atomic_write, io_path, write_json
from . import ios_scheduler as original
from .scheduler_windows_runtime import run as run_owned_process
from .windows_python_runtime import stage_base_python
from .runtime_timeouts import timeout_for


def install():
    if os.name == 'nt':
        original.invoke = invoke


def invoke(project, program, args):
    if os.name != 'nt':
        raise MigrationError('Windows scheduler runtime used on another platform')
    project = io_path(project)
    args = list(args)
    for index, flag in enumerate(args[:-1]):
        if flag in {'--plan', '--state'}:
            path = Path(args[index + 1])
            args[index + 1] = os.fspath(io_path(path if path.is_absolute() else project / path))
    env = {**os.environ, 'PYTHONUTF8': '1'}
    cleanup_reports = []
    try:
        timeout_for('scheduler', env=env)
        with original._runtime_directory(project, program, windows=True, cleanup_reports=cleanup_reports) as temp:
            if platform.machine().lower() not in {'amd64', 'x86_64', 'x64'}:
                raise MigrationError('Bundled Windows kernel requires x64')
            scripts = Path(temp) / 'a2h-execute/scripts'
            scripts.mkdir(parents=True)
            for source in original.UPSTREAM.glob('*.py'):
                shutil.copy2(source, scripts / source.name)
            shim = ('import sys\n'
                    f'sys.path.insert(0, {str(original.ROOT / "src")!r})\n'
                    'from hmigbot_ios.native_static_runtime import main\n'
                    f'raise SystemExit(main({str(original.UPSTREAM)!r}))\n')
            (scripts / 'static_runtime_lint.py').write_text(shim, encoding='utf-8')
            directory = scripts / 'bin/windows-x64/_entry.dist'
            shutil.copytree(original.UPSTREAM / 'bin/windows-x64/_entry.dist', directory)
            stage_base_python(directory, env)
            env['ARKTS_SKILL_DIR'] = str(scripts.parent)
            command = [str(directory / '_entry.exe'), program, *args]
            process = run_owned_process(command, cwd=project, env=env,
                                        timeout=timeout_for('scheduler', env=env))
    except (subprocess.TimeoutExpired, OSError) as exc:
        directory = project / 'spec/reports/scheduler'
        atomic_write(directory / (program + '.stdout.log'), getattr(exc, 'output', None) or b'')
        atomic_write(directory / (program + '.stderr.log'), getattr(exc, 'stderr', None) or b'')
        log = directory / (program + '.failure.json')
        report = {'program': program, 'error': str(exc), 'status': 'FAIL',
                  'process_tree': getattr(exc, 'ios_process_tree', None),
                  'timeout_policy': getattr(exc, 'ios_timeout_policy', None)}
        if cleanup_reports:
            report['runtime_cleanup'] = cleanup_reports
        write_json(log, report)
        raise MigrationError('Original scheduler failed; evidence: ' + str(log)) from exc
    directory = project / 'spec/reports/scheduler'
    atomic_write(directory / (program + '.stdout.log'), process.stdout)
    atomic_write(directory / (program + '.stderr.log'), process.stderr)
    if process.returncode:
        raise MigrationError('Original scheduler rejected input: '
                             + process.stderr.decode('utf-8', errors='replace')[-1800:])
    try:
        result = json.loads(process.stdout)
        if isinstance(result, dict) and any('stderr_error' in item for item in cleanup_reports):
            result['ios_runtime_cleanup'] = cleanup_reports
        return result
    except (ValueError, UnicodeError) as exc:
        raise MigrationError('Original scheduler did not return a JSON action') from exc
