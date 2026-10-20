"""Attempt-scoped provider captures.

A capture is identified by what was asked for (operation + source snapshot + config/input
fingerprint) and each try gets its own attempt directory and run id. A failure therefore never
occupies the place a retry would need, and a published success is never rewritten in place.
Nothing here invents evidence: only an artifact.json written by the atom is treated as success.
"""
from __future__ import annotations

import re
from pathlib import Path

from .core import MigrationError, digest, json_bytes, read_json, write_json

RUNS_FOLDER = 'runs'
ARTIFACT_NAME = 'artifact.json'
RUN_RECORD_NAME = 'run.json'
FAILURE_NAME = 'failure.json'
ATTEMPT_PATTERN = re.compile(r'^attempt-(\d{6})-([0-9a-f]{12})$')
SUCCESS_STATUSES = {'operation_completed', 'partial'}


def _fingerprint(path) -> str | None:
    """Content digest of the exact input the provider consumes; None when there is nothing to read.

    Absent or unreadable inputs stay None instead of guessing a value: the atom will fail on its
    own, and the failure record then shows a fingerprint that cannot be mistaken for real input.
    """
    if not path:
        return None
    target = path if isinstance(path, Path) else Path(str(path))
    if target.is_dir():
        target = target / 'manifest.json'
    try:
        return digest(target.read_bytes())
    except OSError:
        return None


def capture_root(project) -> Path:
    return Path(project) / 'spec/ref/provider-runs'


def identity_of(operation, source_sha256, config_sha256, input_sha256) -> str:
    return digest(json_bytes([operation, source_sha256, config_sha256, input_sha256]))[:16]


def _attempt_dirs(directory: Path):
    if not directory.is_dir():
        return []
    return sorted((p for p in directory.iterdir() if p.is_dir() and ATTEMPT_PATTERN.match(p.name)),
                  key=lambda p: p.name)


def _attempt_number(directory: Path) -> int:
    match = ATTEMPT_PATTERN.match(directory.name)
    return int(match.group(1)) if match else 0


def _run_id(directory: Path) -> str:
    match = ATTEMPT_PATTERN.match(directory.name)
    return match.group(2) if match else 'unrecorded'


class ProviderRun:
    """One provider try: fresh directory, traceable run id, no overwrite of earlier evidence."""

    def __init__(self, project, operation, source_sha256, *, config=None, input_path=None):
        self.project = Path(project)
        self.operation = operation
        self.source_sha256 = source_sha256
        self.config_sha256 = _fingerprint(config)
        self.input_sha256 = _fingerprint(input_path)
        self.identity = identity_of(operation, source_sha256, self.config_sha256, self.input_sha256)
        self.identity_directory = capture_root(project) / operation / source_sha256 / RUNS_FOLDER / self.identity
        existing = _attempt_dirs(self.identity_directory)
        self.attempt = _attempt_number(existing[-1]) + 1 if existing else 1
        self.run_id = digest(json_bytes([self.identity, self.attempt]))[:12]
        self.directory = self.identity_directory / ('attempt-%06d-%s' % (self.attempt, self.run_id))
        self.artifact_path = self.directory / ARTIFACT_NAME
        self.failure_path = self.directory / FAILURE_NAME

    def relative(self, path: Path) -> str:
        return path.relative_to(self.project).as_posix()

    def _base_record(self, status):
        return {'schema_version': 1, 'status': status, 'operation': self.operation,
                'source_sha256': self.source_sha256, 'identity': self.identity,
                'attempt': self.attempt, 'run_id': self.run_id,
                'config_sha256': self.config_sha256, 'input_sha256': self.input_sha256}

    def publish(self, report):
        """Record success next to the artifact the atom just wrote; the artifact stays untouched."""
        if not self.artifact_path.is_file():
            raise MigrationError('Provider atom reported success without publishing ' + self.relative(self.artifact_path))
        data = self.artifact_path.read_bytes()
        record = {**self._base_record('succeeded'), 'artifact': ARTIFACT_NAME,
                  'artifact_sha256': digest(data), 'artifact_status': report.get('status'),
                  'atom_issue_count': len(report.get('issues') or [])}
        write_json(self.directory / RUN_RECORD_NAME, record)
        return {'path': self.relative(self.artifact_path), 'sha256': digest(data), 'operation': self.operation,
                'run': {'identity': self.identity, 'attempt': self.attempt, 'run_id': self.run_id}}

    def fail(self, error):
        """Keep the failed try on disk so a later run can see what was already attempted."""
        record = {**self._base_record('failed'), 'error': str(error),
                  'retry': 'a new attempt is allowed; this record is retained for review'}
        write_json(self.failure_path, record)
        write_json(self.directory / RUN_RECORD_NAME, record)
        return self.relative(self.failure_path)

    def reusable(self):
        """Return the newest earlier success for this identity, or None when a fresh try is needed."""
        for attempt_dir in reversed(_attempt_dirs(self.identity_directory)):
            artifact, record = attempt_dir / ARTIFACT_NAME, attempt_dir / RUN_RECORD_NAME
            if not artifact.is_file() or not record.is_file():
                continue
            try:
                saved = read_json(record)
                data = artifact.read_bytes()
                report = read_json(artifact)
            except (MigrationError, OSError):
                continue
            if (saved.get('status') == 'succeeded' and saved.get('run_id')
                    and saved.get('artifact_sha256') == digest(data)
                    and saved.get('operation') == self.operation
                    and report.get('operation') == self.operation
                    and report.get('source_sha256') == self.source_sha256
                    and report.get('status') in SUCCESS_STATUSES):
                return {'path': self.relative(artifact), 'sha256': digest(data), 'operation': self.operation,
                        'run': {'identity': self.identity,
                                'attempt': _attempt_number(attempt_dir),
                                'run_id': saved.get('run_id')},
                        'report': report}
        return None


def retained_failures(artifact_path):
    """Failures kept for the identity that produced this artifact, oldest attempt first.

    Only the attempt-scoped layout is scanned. A legacy flat capture has no attempt siblings, so
    previously saved graphs keep validating exactly as before instead of gaining new issues.
    """
    artifact = Path(artifact_path)
    attempt, identity_dir = artifact.parent, artifact.parent.parent
    if identity_dir.parent.name != RUNS_FOLDER or not ATTEMPT_PATTERN.match(attempt.name):
        return []
    failures = []
    for attempt_dir in _attempt_dirs(identity_dir):
        record = attempt_dir / FAILURE_NAME
        if not record.is_file():
            continue
        try:
            saved = read_json(record)
        except (MigrationError, OSError) as exc:
            failures.append({'attempt': _attempt_number(attempt_dir), 'run_id': _run_id(attempt_dir),
                             'error': 'unreadable failure record: ' + str(exc)})
            continue
        failures.append({'attempt': saved.get('attempt', _attempt_number(attempt_dir)),
                         'run_id': saved.get('run_id', _run_id(attempt_dir)), 'error': saved.get('error')})
    return failures
