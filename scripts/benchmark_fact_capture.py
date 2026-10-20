"""Deterministic, isolated fact-capture benchmark; no migration or model calls."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback


SCHEMA = "hmigbot-fact-capture-benchmark/1"
SCOPE = "Synthetic Swift token fact capture, obligations and final source snapshot only"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def absolute_directory(value, *, existing=False):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("Use an explicit absolute directory: " + str(value))
    path = path.resolve()
    if os.name == "nt" and path.drive.lower() != "d:":
        raise ValueError("Benchmark directories must be on D: " + str(value))
    if existing and not path.is_dir():
        raise ValueError("Directory does not exist: " + str(value))
    return path


def swift_block(file_index, view_index):
    suffix = f"f{file_index:05d}_v{view_index:05d}"
    return [
        f"struct BenchmarkView_{suffix}: View {{",
        f"    @State private var count_{suffix}: Int = 0",
        f'    @State private var label_{suffix}: String = "Label {suffix}"',
        "    var body: some View {",
        "        VStack {",
        f"            Text(label_{suffix})",
        f'            Button("Increment {suffix}") {{ count_{suffix} += 1 }}',
        f'            Button("Reset {suffix}") {{ count_{suffix} = 0 }}',
        "        }",
        "    }",
        "}",
    ]


def generate_source(source, lines, files):
    """Exact newline-terminated LOC; at most ten padding comments per file."""
    block_size = len(swift_block(0, 0))
    if files <= 0 or lines < files * (block_size + 1):
        raise ValueError(f"Require positive files and at least {block_size + 1} lines per file")
    if (lines + files - 1) // files > 10000:
        raise ValueError("Use more files: maximum 10,000 lines per synthetic file")
    source.mkdir()
    entries = []
    base, extra = divmod(lines, files)
    for index in range(files):
        count = base + (index < extra)
        body = ["import SwiftUI"]
        blocks, padding = divmod(count - 1, block_size)
        for view_index in range(blocks):
            body.extend(swift_block(index, view_index))
        body.extend(f"// deterministic padding {index}:{n}" for n in range(padding))
        raw = ("\n".join(body) + "\n").encode("utf-8")
        name = f"Benchmark{index:05d}.swift"
        (source / name).write_bytes(raw)
        entries.append({"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    # Matches core.snapshot's documented file-entry fingerprint, independent of paths.
    manifest = (json.dumps(entries, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    return {"loc": lines, "source_bytes": sum(e["bytes"] for e in entries),
            "files": files, "generated_source_sha256": hashlib.sha256(manifest).hexdigest(),
            "generator": "swift-state-string-event-v1", "max_lines_per_file": base + bool(extra)}


def peak_memory():
    """Process lifetime peak (including imports); never claim a capture-only peak."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in (
                        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                        "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                        "PagefileUsage", "PeakPagefileUsage")]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                raise OSError(ctypes.get_last_error())
            return {"bytes": counters.PeakWorkingSetSize, "method": "Windows GetProcessMemoryInfo.PeakWorkingSetSize",
                    "scope": "worker_process_lifetime"}
        except (ImportError, OSError, AttributeError) as exc:
            return {"bytes": None, "method": "unavailable", "reason": str(exc)}
    try:
        import resource
        raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {"bytes": int(raw if sys.platform == "darwin" else raw * 1024),
                "method": f"{sys.platform} resource.ru_maxrss", "scope": "worker_process_lifetime"}
    except (ImportError, OSError) as exc:
        return {"bytes": None, "method": "unavailable", "reason": str(exc)}


class SourceReads:
    """Count successful Path.read_bytes only, restricted to the generated source tree."""
    def __init__(self, source):
        self.source = source.resolve()
        self.phase = "capture_other"
        self.phases = {}
        self.per_file = Counter()
        self.original = Path.read_bytes

    def read(self, path, *args, **kwargs):
        raw = self.original(path, *args, **kwargs)
        # Resolving each read would distort hot-loop timing; source has no links.
        normal = Path(os.path.abspath(str(path)))
        if normal.is_relative_to(self.source):
            stats = self.phases.setdefault(self.phase, {"calls": 0, "logical_bytes": 0})
            stats["calls"] += 1
            stats["logical_bytes"] += len(raw)
            self.per_file[normal.relative_to(self.source).as_posix()] += 1
        return raw

    def report(self):
        return {"api": "pathlib.Path.read_bytes", "scope": "generated source tree only",
                "calls": sum(p["calls"] for p in self.phases.values()),
                "logical_bytes": sum(p["logical_bytes"] for p in self.phases.values()),
                "phases": self.phases, "distinct_files": len(self.per_file),
                "max_calls_per_file": max(self.per_file.values(), default=0),
                "disk_io_bytes": None,
                "limitations": "Logical bytes returned by read_bytes, not physical disk I/O. read_text/open/mmap reads are not counted. Instrumentation adds overhead."}


def worker(runtime, source, result):
    reads = SourceReads(source)
    report = {"status": "failed", "capture_wall_seconds": None}
    started = None
    try:
        sys.path.insert(0, str(runtime))
        from hmigbot_ios import core, ios_facts

        loaded = Path(ios_facts.__file__).resolve()
        if not loaded.is_relative_to(runtime):
            raise RuntimeError("Imported runtime does not match --runtime")
        snapshot = core.snapshot

        def measured_snapshot(root):
            previous = reads.phase
            reads.phase = "extraction_snapshot"
            try:
                return snapshot(root)
            finally:
                reads.phase = previous

        core.snapshot = ios_facts.snapshot = measured_snapshot
        Path.read_bytes = lambda path, *args, **kwargs: reads.read(path, *args, **kwargs)
        started = time.perf_counter()
        graph = ios_facts.extract(source)
        obligations = ios_facts.obligations(graph)
        reads.phase = "final_snapshot"
        final = snapshot(source)
        elapsed = time.perf_counter() - started
        if final["sha256"] != graph["source_sha256"]:
            raise RuntimeError("Source changed during fact capture")
        report.update(status="completed", capture_wall_seconds=elapsed,
                      facts=len(graph["facts"]), obligations=len(obligations["obligations"]),
                      issues=len(graph.get("issues", [])), source_sha256=graph["source_sha256"],
                      final_source_sha256=final["sha256"],
                      facts_by_kind=dict(Counter(f["kind"] for f in graph["facts"])),
                      runtime_module=str(loaded))
    except Exception as exc:
        if started is not None:
            report["capture_wall_seconds"] = time.perf_counter() - started
        report["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        Path.read_bytes = reads.original
        report["read_bytes"] = reads.report()
        report["peak_memory"] = peak_memory()
        write_json(result, report)
    return 0 if report["status"] == "completed" else 1


def run_benchmark(runtime, output, lines, files, timeout):
    runtime = absolute_directory(runtime, existing=True)
    output = absolute_directory(output)
    if not (runtime / "hmigbot_ios/ios_facts.py").is_file():
        raise ValueError("--runtime must contain hmigbot_ios/ios_facts.py (the src directory)")
    if not output.parent.is_dir():
        raise ValueError("Output parent must already exist")
    if timeout <= 0:
        raise ValueError("Timeout must be positive")
    # Validate sizes before reserving output, and refuse any existing output, even empty.
    if files <= 0 or lines < files * 12 or (lines + files - 1) // files > 10000:
        raise ValueError("Require 12..10,000 lines per file and positive file count")
    output.mkdir(exist_ok=False)
    report = {"schema": SCHEMA, "status": "failed", "scope": SCOPE,
              "acceptance": "not_evaluated", "migration_acceptance": "not_evaluated",
              "tokens": "not_applicable", "provider_calls": 0, "model_calls": 0,
              "runtime": str(runtime), "output": str(output), "timeout_seconds": timeout,
              "platform": platform.platform(), "python": sys.version,
              "capture_wall_seconds": None, "facts": None, "obligations": None,
              "final_source_sha256": None,
              "timing_scope": "extract + obligations + final snapshot; excludes generation, import and report serialization",
              "limitations": ["Synthetic token signals are not compiler or runtime proof.",
                              "No functional, visual, end-to-end migration, 20M-token or two-hour acceptance.",
                              "Do not extrapolate these timings to end-to-end migration throughput."]}
    try:
        report["source"] = generate_source(output / "source", lines, files)
        command = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()),
                   "--worker", "--runtime", str(runtime), "--output", str(output)]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
        if os.name == "nt":
            env.update(TEMP="D:/Temp", TMP="D:/Temp")
        started = time.perf_counter()
        with (output / "worker.stdout.log").open("wb") as stdout, (output / "worker.stderr.log").open("wb") as stderr:
            try:
                completed = subprocess.run(command, cwd=output, env=env, stdout=stdout,
                                           stderr=stderr, timeout=timeout, check=False)
                report["worker_exit_code"] = completed.returncode
            except subprocess.TimeoutExpired:
                report["error"] = "Fact capture worker timed out; source and logs retained"
                report["timed_out"] = True
        report["subprocess_wall_seconds"] = time.perf_counter() - started
        result = output / "worker-result.json"
        if result.is_file():
            report.update(json.loads(result.read_text(encoding="utf-8")))
        if report.get("timed_out") or report.get("worker_exit_code") != 0:
            report["status"] = "failed"
            report.setdefault("error", "Worker failed; see worker.stderr.log")
        if report["status"] == "completed" and report["final_source_sha256"] != report["source"]["generated_source_sha256"]:
            report.update(status="failed", error="Final runtime fingerprint differs from generated source")
        if report.get("read_bytes"):
            report["read_bytes"]["logical_bytes_per_source_byte"] = report["read_bytes"]["logical_bytes"] / report["source"]["source_bytes"]
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        (output / "benchmark-error.log").write_text(traceback.format_exc(), encoding="utf-8")
    write_json(output / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, help="Absolute D: path to the runtime's src directory")
    parser.add_argument("--output", required=True, help="New absolute D: directory; existing paths are refused")
    parser.add_argument("--lines", type=int, help="Exact LOC; typical probes: 100000, 200000, optional 500000")
    parser.add_argument("--files", type=int, help="Exact Swift file count (required)")
    parser.add_argument("--timeout", type=float, default=300, help="Worker timeout seconds, default 300")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.worker:
            runtime = absolute_directory(args.runtime, existing=True)
            output = absolute_directory(args.output, existing=True)
            return worker(runtime, output / "source", output / "worker-result.json")
        if args.lines is None or args.files is None:
            parser.error("--lines and --files are required")
        report = run_benchmark(args.runtime, args.output, args.lines, args.files, args.timeout)
    except (ValueError, OSError) as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps({"status": report["status"], "report": str(Path(args.output) / "report.json")}, sort_keys=True))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
