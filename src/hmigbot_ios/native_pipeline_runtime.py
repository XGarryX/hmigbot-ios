"""Run the unchanged compiled structural pipeline in its expected skill layout.

Nuitka resolves ``__file__`` beside its executable.  The shipping launcher puts
that executable three directories below scripts, so sibling helper discovery
cannot find the complete bundle.  A disposable layout places the entry binary
beside the original scripts and retains each helper's own unchanged payload.
Native input bridges retain the original detectors and their failure decisions.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

from .core import io_path
from .scheduler_windows_runtime import run as run_owned_process
from .windows_python_runtime import stage_base_python
from .runtime_timeouts import timeout_for

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / 'vendor/hmigbot/skills'
HELPERS = {
    'arkts-structural-closure': ('assembly_gate.py', 'binding_gate.py'),
    'a2h-execute': ('dead_shell_gate.py', 'carrier_gate.py',
                    'hit_test_gate.py', 'resource_name_gate.py'),
}


def _platform():
    system = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'macos'}.get(platform.system())
    if system is None:
        raise ValueError('Unsupported structural pipeline platform')
    architecture = 'arm64' if platform.machine().lower() in {'arm64', 'aarch64'} else 'x64'
    return system, architecture


def _copy_scripts(source, destination, system, architecture):
    destination.mkdir(parents=True)
    for path in source.iterdir():
        if path.name in {'bin', 'tests', '__pycache__'}:
            continue
        if path.is_dir():
            shutil.copytree(path, destination / path.name, ignore=shutil.ignore_patterns('__pycache__'))
        else:
            shutil.copy2(path, destination / path.name)
    payload = source / 'bin' / (system + '-' + architecture) / '_entry.dist'
    if not payload.is_dir():
        raise ValueError('Complete original structural payload is missing: ' + str(payload))
    shutil.copytree(payload, destination / 'bin' / (system + '-' + architecture) / '_entry.dist')
    return payload


@contextmanager
def runtime_layout():
    """Yield an isolated original engine; never mutate the installed bundle."""
    system, architecture = _platform()
    with tempfile.TemporaryDirectory(prefix='native-pipeline-') as temporary:
        skills = Path(temporary) / 'skills'
        closure = skills / 'arkts-structural-closure/scripts'
        payload = _copy_scripts(VENDOR / 'arkts-structural-closure/scripts', closure, system, architecture)
        _copy_scripts(VENDOR / 'a2h-execute/scripts', skills / 'a2h-execute/scripts', system, architecture)
        for skill, names in HELPERS.items():
            for name in names:
                if not (skills / skill / 'scripts' / name).is_file():
                    raise ValueError('Complete original structural helper is missing: ' + name)
        # The entrypoint is flat only to restore __file__-based sibling paths.
        # Nested helper launchers keep their original payload and command line.
        for path in payload.iterdir():
            if path.is_dir():
                shutil.copytree(path, closure / path.name)
            else:
                shutil.copy2(path, closure / path.name)
        icon = skills / 'arkts-icon-sizing/scripts/icon_autofix.py'
        icon.parent.mkdir(parents=True)
        icon.write_text('import sys\n'
            f'sys.path.insert(0, {str(ROOT / "src")!r})\n'
            'from hmigbot_ios.native_icon_scope import autofix_main\n'
            'raise SystemExit(autofix_main())\n', encoding='utf-8')
        literal = skills / 'a2h-execute/scripts/literal_gate.py'
        literal.write_text('import sys\n'
            f'sys.path.insert(0, {str(ROOT / "src")!r})\n'
            'from hmigbot_ios.native_literal_scope import main\n'
            'raise SystemExit(main())\n', encoding='utf-8')
        from .native_pipeline_semantics import stage_runtime
        stage_runtime(skills, root=ROOT)
        env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8',
               'ARKTS_SKILL_DIR': str(closure)}
        if system == 'windows':
            stage_base_python(closure, env)
        suffix = '.exe' if system == 'windows' else '.bin'
        yield closure / ('_entry' + suffix), env


def _invoke_raw(arguments, original=None):
    """Return the original pipeline's exact stdout/stderr/exit disposition."""
    arguments = list(map(str, arguments))
    # The suspended-process / host-interpreter repair is Windows-specific.
    # Preserve the established launcher on platforms that do not need it.
    if os.name != 'nt' and original is not None:
        timeout_for('structural')  # Validate inherited policy before the legacy callback.
        return original('arkts-structural-closure', 'structural_loop.py', arguments)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--project-root', type=Path)
    probe, _ = parser.parse_known_args(arguments)
    project = io_path(probe.project_root or Path.cwd()).resolve()
    command = ['structural_loop', *arguments]
    tree = None
    try:
        timeout_for('structural')
        with runtime_layout() as (executable, env):
            command = [str(executable), 'structural_loop', *arguments]
            limit = timeout_for('structural', env=env)
            if os.name == 'nt':
                result = run_owned_process(command, cwd=project, env=env, timeout=limit)
            else:
                result = subprocess.run(command, cwd=project, env=env, capture_output=True,
                                        timeout=limit, shell=False)
    except subprocess.TimeoutExpired as exc:
        # The Windows owned runner already terminates and reaps its Job tree.
        tree = getattr(exc, 'ios_process_tree', None)
        result = subprocess.CompletedProcess(command, 124, exc.output or b'',
            (exc.stderr or b'') + f'\nOriginal structural pipeline timed out after {exc.timeout:g} seconds.\n'.encode())
    decoded = subprocess.CompletedProcess(result.args, result.returncode,
        result.stdout.decode('utf-8', errors='replace'),
        result.stderr.decode('utf-8', errors='replace'))
    if tree is not None:
        decoded.ios_process_tree = tree
    return decoded


def invoke(arguments, original=None):
    """Preserve raw engine evidence, then use the original native loop protocol."""
    arguments = list(map(str, arguments))
    if arguments and arguments[0] == 'iterate':
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument('--mode')
        args, _ = parser.parse_known_args(arguments)
        if args.mode == 'pipeline':
            from .native_pipeline_semantics import pipeline_iterate
            return pipeline_iterate(arguments, lambda raw: _invoke_raw(raw, original=original))
    return _invoke_raw(arguments, original=original)
