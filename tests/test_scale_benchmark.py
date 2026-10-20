"""Small synthetic fixtures only: never run scale probes against the old runtime."""
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fact_capture_benchmark", ROOT / "scripts/benchmark_fact_capture.py")
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_exact_lines_files_unique_views_and_reproducible_bytes(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first_stats = benchmark.generate_source(first, 101, 3)
    second_stats = benchmark.generate_source(second, 101, 3)
    assert first_stats == second_stats
    files = sorted(first.glob("*.swift"))
    assert len(files) == 3
    assert sum(len(p.read_bytes().splitlines()) for p in files) == 101
    assert sum(p.stat().st_size for p in files) == first_stats["source_bytes"]
    views = []
    for path in files:
        assert path.read_bytes() == (second / path.name).read_bytes()
        lines = path.read_text().splitlines()
        views.extend(line for line in lines if line.startswith("struct "))
        assert any("@State" in line for line in lines)
        assert any("Button(\"Increment" in line for line in lines)
    assert len(views) == len(set(views))


def test_small_capture_has_exact_counts_and_final_hash(tmp_path):
    output = tmp_path / "capture"
    report = benchmark.run_benchmark(ROOT / "src", output, 48, 2, 30)
    assert report["status"] == "completed", report
    assert report["source"]["loc"] == 48
    assert report["source"]["files"] == 2
    assert report["facts"] == report["obligations"] == 40
    assert report["facts_by_kind"] == {"state": 8, "write": 16, "event": 8, "composition": 8}
    assert report["final_source_sha256"] == report["source_sha256"] == report["source"]["generated_source_sha256"]
    assert report["capture_wall_seconds"] > 0
    assert report["subprocess_wall_seconds"] >= report["capture_wall_seconds"]
    reads = report["read_bytes"]
    assert reads["phases"]["extraction_snapshot"]["calls"] == 2
    assert reads["phases"]["final_snapshot"]["calls"] == 2
    assert reads["phases"]["final_snapshot"]["logical_bytes"] == report["source"]["source_bytes"]
    assert reads["logical_bytes"] >= 2 * report["source"]["source_bytes"]
    assert reads["disk_io_bytes"] is None
    assert report["tokens"] == "not_applicable"
    assert report["provider_calls"] == report["model_calls"] == 0
    assert report["migration_acceptance"] == "not_evaluated"
    assert report["peak_memory"]["method"]
    assert json.loads((output / "report.json").read_text()) == report


def test_read_bytes_scope_excludes_logs_and_counts_phases(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "Small.swift"
    path.write_bytes(b"abc\n")
    outside = tmp_path / "outside.log"
    outside.write_bytes(b"not source")
    reads = benchmark.SourceReads(source)
    reads.read(outside)
    reads.read(path)
    reads.phase = "final_snapshot"
    reads.read(path)
    stats = reads.report()
    assert stats["calls"] == 2
    assert stats["logical_bytes"] == 8
    assert stats["distinct_files"] == 1
    assert stats["max_calls_per_file"] == 2
    assert stats["phases"] == {"capture_other": {"calls": 1, "logical_bytes": 4},
                               "final_snapshot": {"calls": 1, "logical_bytes": 4}}


def test_existing_output_is_refused_without_overwriting(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "real-project.swift"
    sentinel.write_bytes(b"user source")
    with pytest.raises(FileExistsError):
        benchmark.run_benchmark(ROOT / "src", output, 24, 2, 30)
    assert list(output.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"user source"


@pytest.mark.parametrize("lines,files", [(0, 1), (24, 0), (23, 2), (10001, 1)])
def test_invalid_sizes_do_not_create_source(tmp_path, lines, files):
    source = tmp_path / "source"
    with pytest.raises(ValueError):
        benchmark.generate_source(source, lines, files)
    assert not source.exists()


def make_failing_runtime(tmp_path, body):
    runtime = tmp_path / "fake-runtime"
    package = runtime / "hmigbot_ios"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "core.py").write_text("def snapshot(root):\n    return {}\n")
    (package / "ios_facts.py").write_text(
        "from .core import snapshot\nimport time\ndef extract(source):\n    " + body + "\n")
    return runtime


def test_worker_failure_retains_source_logs_and_failed_report(tmp_path):
    runtime = make_failing_runtime(tmp_path, "raise RuntimeError('intentional fixture failure')")
    output = tmp_path / "failed"
    report = benchmark.run_benchmark(runtime, output, 24, 2, 30)
    assert report["status"] == "failed"
    assert report["worker_exit_code"] == 1
    assert "intentional fixture failure" in (output / "worker.stderr.log").read_text()
    assert len(list((output / "source").glob("*.swift"))) == 2
    assert report["facts"] is None
    assert report["final_source_sha256"] is None
    assert json.loads((output / "report.json").read_text())["status"] == "failed"


def test_timeout_retains_source_logs_and_marks_failed(tmp_path):
    runtime = make_failing_runtime(tmp_path, "time.sleep(10)")
    output = tmp_path / "timeout"
    report = benchmark.run_benchmark(runtime, output, 24, 2, 0.2)
    assert report["status"] == "failed"
    assert report["timed_out"] is True
    assert report["capture_wall_seconds"] is None
    assert (output / "worker.stderr.log").is_file()
    assert (output / "worker.stdout.log").is_file()
    assert len(list((output / "source").glob("*.swift"))) == 2


def test_requires_absolute_directory():
    with pytest.raises(ValueError, match="absolute"):
        benchmark.absolute_directory("relative-output")
