"""Auditable, local usage ledger; no provider calls or token estimation.

All attempts (including failed calls and child agents) must be recorded separately.
The caller is responsible for complete coverage and disjoint call scopes: do not
record both a provider call and an aggregate which already includes that call.
PASS certifies only the supplied ledger, not migration quality or source size.

Normalization contracts (all output totals already include reasoning/image tokens):
* openai_responses: input_tokens includes input_tokens_details.cached_tokens.
* anthropic_messages: input_tokens excludes cache_read_input_tokens and
  cache_creation_input_tokens (optional cache counters mean zero).
* canonical_cache_subset / canonical_cache_separate: input_tokens includes /
  excludes cache_read_tokens + cache_write_tokens (both counters required).
* multica_input_includes_cache / multica_input_excludes_cache: explicit caller
  contract for total_input_tokens relative to total_cache_read_tokens and
  total_cache_write_tokens. unreported_task_count is required; nonzero is unknown.
  These are terminal aggregates, usable only for a disjoint aggregate scope.

Missing input/output is unknown; known components still count. Optional subset
detail counters never increase totals. Unknown formats must use unreported.
Wall time starts at start(), includes waits/builds/verification, and stops only
at finish(). Clock reversals/disagreement permanently prevent PASS.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import platform
import tempfile
import time
from typing import Any


TARGET_TOKENS = 20_000_000
DEFAULT_TOKEN_LIMIT = 19_900_000
MAX_WALLTIME_SECONDS = 120 * 60
MODES = frozenset({"openai_responses", "anthropic_messages", "canonical_cache_subset",
                   "canonical_cache_separate", "multica_input_includes_cache",
                   "multica_input_excludes_cache", "unreported"})


class BudgetError(ValueError):
    """Invalid evidence or conflicting ledger operation."""


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BudgetError(f"{field} must be a nonempty string")
    return value


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BudgetError(f"{field} must be a nonnegative integer")
    return value


def _raw(value: Any) -> Any:
    """Validate and copy JSON without discarding the original provider evidence."""
    def validate(item: Any) -> None:
        if isinstance(item, bool):
            raise BudgetError("boolean usage is invalid")
        if isinstance(item, (int, float)):
            if item < 0 or (isinstance(item, float) and not math.isfinite(item)):
                raise BudgetError("usage numbers must be finite and nonnegative")
        elif isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise BudgetError("usage keys must be strings")
                validate(child)
        elif isinstance(item, list):
            for child in item:
                validate(child)
        elif item is not None and not isinstance(item, str):
            raise BudgetError("usage must contain JSON values")
    if value is not None and not isinstance(value, dict):
        raise BudgetError("raw_usage must be an object or None")
    validate(value)
    return json.loads(json.dumps(value, allow_nan=False))


def _normalize(raw: Any, mode: str) -> dict:
    if not isinstance(mode, str) or mode not in MODES:
        raise BudgetError(f"unsupported normalization_mode: {mode}")
    reasons: list[str] = []
    raw = _raw(raw)
    if raw is None or mode == "unreported":
        return {"non_cached_input_tokens": None, "cached_input_tokens": None,
                "output_tokens": None, "total_tokens": 0, "verified": False,
                "reasons": ["usage_unreported"]}

    def counter(mapping: dict, key: str, *, optional: bool = False) -> int | None:
        if key not in mapping:
            if optional:
                return 0
            reasons.append(f"missing:{key}")
            return None
        if mapping[key] is None:
            reasons.append(f"null:{key}")
            return None
        return _integer(mapping[key], key)

    def details(key: str) -> dict:
        item = raw.get(key, {})
        if not isinstance(item, dict):
            raise BudgetError(f"{key} must be an object")
        return item

    separate = mode in {"anthropic_messages", "canonical_cache_separate",
                        "multica_input_excludes_cache"}
    if mode.startswith("multica_"):
        inp = counter(raw, "total_input_tokens")
        out = counter(raw, "total_output_tokens")
        read = counter(raw, "total_cache_read_tokens")
        write = counter(raw, "total_cache_write_tokens")
        unreported = counter(raw, "unreported_task_count")
        if unreported:
            reasons.append("unreported_tasks")
    else:
        inp, out = counter(raw, "input_tokens"), counter(raw, "output_tokens")
        if mode == "openai_responses":
            read = counter(details("input_tokens_details"), "cached_tokens", optional=True)
            write = 0
            reasoning = counter(details("output_tokens_details"), "reasoning_tokens", optional=True)
            if out is not None and reasoning is not None and reasoning > out:
                raise BudgetError("reasoning_tokens exceeds inclusive output_tokens")
        elif mode == "anthropic_messages":
            read = counter(raw, "cache_read_input_tokens", optional=True)
            write = counter(raw, "cache_creation_input_tokens", optional=True)
        else:
            read = counter(raw, "cache_read_tokens")
            write = counter(raw, "cache_write_tokens")
    cache = None if read is None or write is None else read + write
    if not separate and inp is not None and cache is not None and cache > inp:
        raise BudgetError("cache subset exceeds inclusive input_tokens")
    noncache = inp if separate else (inp - cache if inp is not None and cache is not None else None)
    # Inclusive input remains fully countable even if cache breakdown is missing.
    known_cache = (read or 0) + (write or 0)
    total_input = (inp or 0) + known_cache if separate else (inp if inp is not None else known_cache)
    total = total_input + (out or 0)
    if mode == "openai_responses" and "total_tokens" in raw:
        reported_total = _integer(raw["total_tokens"], "total_tokens")
        if inp is not None and out is not None and reported_total != total:
            raise BudgetError("total_tokens disagrees with input/output counters")
    return {"non_cached_input_tokens": noncache, "cached_input_tokens": cache,
            "output_tokens": out, "total_tokens": total,
            "verified": not reasons, "reasons": reasons}


def _path(ledger: str | Path) -> Path:
    path = Path(ledger)
    if not path.is_absolute():
        raise BudgetError("ledger must be an explicit absolute path")
    path = path.resolve()
    if os.name == "nt" and path.drive.upper() != "D:":
        raise BudgetError("ledger and temporary files must be on D:")
    return path


@contextmanager
def _lock(path: Path):
    """OS-held lock: released on crash; never remove the shared lock inode."""
    lockpath = path.with_name(path.name + ".lock")
    descriptor = os.open(lockpath, os.O_RDWR | os.O_CREAT, 0o600)
    locked = False
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
        deadline = time.monotonic() + 10
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise BudgetError("ledger is busy; retry without dropping the call")
                time.sleep(0.02)
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _save(path: Path, data: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            json.dump(data, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _clock() -> tuple[float, float]:
    return time.time(), time.monotonic()


def _clock_source() -> str:
    # Python 3.11 monotonic clocks share their reference across local processes.
    # A copied live ledger from another host cannot establish elapsed time here.
    return platform.system() + ":" + platform.node()


def _observe(data: dict) -> None:
    if data["finished"]:
        return
    wall, mono = _clock()
    if not all(math.isfinite(value) for value in (wall, mono)):
        raise BudgetError("nonfinite clock observation")
    previous = data["clock"]
    wall_step, mono_step = wall - previous["last_wall"], mono - previous["last_mono"]
    anomalies = data["clock_anomalies"]
    for condition, reason in ((data["clock_source"] != _clock_source(), "clock_source_changed"),
                              (wall_step < 0, "wall_clock_reversed"),
                              (mono_step < 0, "monotonic_clock_reversed"),
                              (abs(wall_step - mono_step) > 5, "clock_disagreement")):
        if condition and reason not in anomalies:
            anomalies.append(reason)
    data["elapsed_seconds"] = max(data["elapsed_seconds"], wall - previous["start_wall"],
                                   mono - previous["start_mono"], 0)
    previous.update(last_wall=wall, last_mono=mono)


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["schema_version"] != 1:
            raise BudgetError("unsupported ledger schema")
        root = _path(data["project_root"])
        if not path.is_relative_to(root):
            raise BudgetError("ledger is outside its declared project_root")
        _name(data["run_id"], "run_id")
        _name(data["clock_source"], "clock_source")
        _limits(data["token_limit"], data["walltime_limit_seconds"])
        if type(data["finished"]) is not bool or not isinstance(data["calls"], list):
            raise BudgetError("invalid ledger state")
        for key in ("start_wall", "start_mono", "last_wall", "last_mono"):
            value = data["clock"][key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise BudgetError("invalid persisted clock")
        elapsed = data["elapsed_seconds"]
        if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
            raise BudgetError("invalid elapsed_seconds")
        if not isinstance(data["clock_anomalies"], list):
            raise BudgetError("invalid clock evidence")
        seen = set()
        for call in data["calls"]:
            for field in ("call_id", "stage", "agent", "provider", "run_id"):
                _name(call[field], field)
            if call["run_id"] != data["run_id"] or call["call_id"] in seen:
                raise BudgetError("duplicate call or mismatched run identity")
            seen.add(call["call_id"])
            if _integer(call["attempt"], "attempt") < 1:
                raise BudgetError("attempt starts at 1")
            if call["normalized"] != _normalize(call["raw_usage"], call["normalization_mode"]):
                raise BudgetError("stored normalization disagrees with raw usage")
        return data
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise BudgetError("invalid ledger evidence") from error


def _limits(token_limit: int, walltime_limit_seconds: int) -> None:
    if not 0 < _integer(token_limit, "token_limit") < TARGET_TOKENS:
        raise BudgetError("token_limit must be positive and strictly below 20M")
    if not 0 < _integer(walltime_limit_seconds, "walltime_limit_seconds") <= MAX_WALLTIME_SECONDS:
        raise BudgetError("walltime limit must be positive and at most 7200 seconds")


def _summary(data: dict) -> dict:
    calls = data["calls"]
    total = sum(call["normalized"]["total_tokens"] for call in calls)
    unknown = sum(not call["normalized"]["verified"] for call in calls)
    failed = []
    if total >= TARGET_TOKENS:
        failed.append("strict_20M_target_exceeded")
    if total > data["token_limit"]:
        failed.append("run_token_limit_exceeded")
    if data["elapsed_seconds"] > data["walltime_limit_seconds"]:
        failed.append("walltime_limit_exceeded")
    uncertain = []
    if unknown:
        uncertain.append("unverified_usage")
    if data["clock_anomalies"]:
        uncertain.append("unverified_clock")
    if not data["finished"]:
        uncertain.append("run_not_finished")
    status = "FAIL" if failed else ("UNKNOWN" if uncertain else "PASS")
    return {"run_id": data["run_id"], "status": status, "finished": data["finished"],
            "call_count": len(calls), "unverified_call_count": unknown,
            "known_non_cached_input_tokens": sum(call["normalized"]["non_cached_input_tokens"] or 0 for call in calls),
            "known_cached_input_tokens": sum(call["normalized"]["cached_input_tokens"] or 0 for call in calls),
            "known_output_tokens": sum(call["normalized"]["output_tokens"] or 0 for call in calls),
            "total_tokens": total, "token_limit": data["token_limit"],
            "target_tokens_exclusive": TARGET_TOKENS,
            "elapsed_seconds": data["elapsed_seconds"],
            "walltime_limit_seconds": data["walltime_limit_seconds"],
            "clock_anomalies": list(data["clock_anomalies"]),
            "reasons": failed + uncertain,
            "can_continue": not data["finished"] and not unknown and not data["clock_anomalies"]
                and total < data["token_limit"] and data["elapsed_seconds"] < data["walltime_limit_seconds"]}


def start(ledger: str | Path, run_id: str, *, project_root: str | Path,
          token_limit: int = DEFAULT_TOKEN_LIMIT,
          walltime_limit_seconds: int = MAX_WALLTIME_SECONDS) -> dict:
    """Start immediately before end-to-end work. Refuses to overwrite a run.

    On Windows both paths must be on D:. Ledger must be within project_root.
    Bounds only govern checks: record always preserves real over-limit evidence.
    """
    path, root = _path(ledger), _path(project_root)
    _name(run_id, "run_id")
    _limits(token_limit, walltime_limit_seconds)
    if not root.is_dir() or path == root or not path.is_relative_to(root):
        raise BudgetError("ledger must be within an existing project_root")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock(path):
        if path.exists():
            raise BudgetError("ledger already exists; use a new ledger for a new run")
        wall, mono = _clock()
        if not all(math.isfinite(value) for value in (wall, mono)):
            raise BudgetError("nonfinite clock observation")
        data = {"schema_version": 1, "run_id": run_id, "project_root": str(root),
                "token_limit": token_limit, "walltime_limit_seconds": walltime_limit_seconds,
                "finished": False, "elapsed_seconds": 0, "clock_anomalies": [],
                "clock_source": _clock_source(),
                "clock": {"start_wall": wall, "start_mono": mono, "last_wall": wall, "last_mono": mono},
                "calls": []}
        _save(path, data)
        return _summary(data)


def record(ledger: str | Path, call_id: str, raw_usage: dict | None, *, run_id: str,
           normalization_mode: str, stage: str, agent: str, provider: str,
           attempt: int = 1) -> dict:
    """Record every provider attempt under a unique call_id, even failed attempts.

    Reusing an ID is idempotent only when raw evidence AND all identity fields
    are unchanged. Child-agent input/output belongs here too. Finished runs are
    immutable. This does not reserve future tokens or dispatch provider work.
    """
    path = _path(ledger)
    call = {"call_id": _name(call_id, "call_id"), "run_id": _name(run_id, "run_id"),
            "stage": _name(stage, "stage"), "agent": _name(agent, "agent"),
            "provider": _name(provider, "provider"), "attempt": _integer(attempt, "attempt"),
            "normalization_mode": normalization_mode, "raw_usage": _raw(raw_usage)}
    if attempt < 1:
        raise BudgetError("attempt starts at 1")
    call["normalized"] = _normalize(call["raw_usage"], normalization_mode)
    with _lock(path):
        data = _load(path)
        if data["finished"] or data["run_id"] != run_id:
            raise BudgetError("run is finished or run_id does not match")
        previous = next((item for item in data["calls"] if item["call_id"] == call_id), None)
        if previous is not None and previous != call:
            raise BudgetError("call_id conflicts with existing evidence")
        if previous is None:
            data["calls"].append(call)
        _observe(data)
        _save(path, data)
        return _summary(data)


def summary(ledger: str | Path) -> dict:
    """Replay raw evidence and observe elapsed wall time under the writer lock.

    total_tokens and known_* are lower bounds whenever usage is unverified.
    """
    path = _path(ledger)
    with _lock(path):
        data = _load(path)
        _observe(data)
        if not data["finished"]:
            _save(path, data)
        return _summary(data)


def check(ledger: str | Path) -> dict:
    """Return PASS/FAIL/UNKNOWN plus can_continue; never calls a model."""
    return summary(ledger)


def finish(ledger: str | Path, *, run_id: str) -> dict:
    """Freeze end-to-end elapsed time after all waits/builds/validation complete."""
    path = _path(ledger)
    with _lock(path):
        data = _load(path)
        if data["run_id"] != run_id:
            raise BudgetError("run_id does not match")
        _observe(data)
        data["finished"] = True
        _save(path, data)
        return _summary(data)
