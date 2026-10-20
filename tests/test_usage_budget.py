"""Synthetic provider-shaped evidence: no model calls or migration benchmark."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hmigbot_ios import usage_budget as budget


class UsageBudgetTests(unittest.TestCase):
    def setUp(self):
        # The configured machine requires all test files to remain on D:.
        self.temp = tempfile.TemporaryDirectory(dir="D:/Temp" if os.name == "nt" else None,
                                                prefix="hmigbot-budget-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root / "usage.json"
        self.clock = [1_000_000.0, 500.0]
        self.patcher = patch.object(budget, "_clock", side_effect=lambda: tuple(self.clock))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        budget.start(self.ledger, "run", project_root=self.root)

    def record(self, call_id="call", raw=None, **kwargs):
        options = dict(run_id="run", normalization_mode="canonical_cache_subset",
                       stage="convert", agent="agent-1", provider="synthetic", attempt=1)
        options.update(kwargs)
        return budget.record(self.ledger, call_id, raw, **options)

    def raw(self, input_tokens=100, output_tokens=20):
        return dict(input_tokens=input_tokens, cache_read_tokens=30, cache_write_tokens=10,
                    output_tokens=output_tokens, reasoning_tokens=5, image_tokens=10)

    def finish(self):
        return budget.finish(self.ledger, run_id="run")

    def test_cache_subset_does_not_double_count_reasoning_or_image(self):
        result = self.record(raw=self.raw())
        self.assertEqual(result["total_tokens"], 120)
        self.assertEqual((result["known_non_cached_input_tokens"], result["known_cached_input_tokens"],
                          result["known_output_tokens"]), (60, 40, 20))
        call = json.loads(self.ledger.read_text())["calls"][0]
        self.assertEqual(call["normalized"]["non_cached_input_tokens"], 60)
        self.assertEqual(call["normalized"]["cached_input_tokens"], 40)
        self.assertEqual(call["raw_usage"], self.raw())
        self.assertEqual(self.finish()["status"], "PASS")

    def test_cache_separate(self):
        result = self.record(raw=self.raw(), normalization_mode="canonical_cache_separate")
        self.assertEqual(result["total_tokens"], 160)

    def test_openai_responses_synthetic(self):
        raw = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
               "input_tokens_details": {"cached_tokens": 40},
               "output_tokens_details": {"reasoning_tokens": 15}}
        self.assertEqual(self.record(raw=raw, normalization_mode="openai_responses")["total_tokens"], 120)

    def test_anthropic_messages_synthetic(self):
        raw = {"input_tokens": 100, "output_tokens": 20,
               "cache_read_input_tokens": 30, "cache_creation_input_tokens": 10}
        self.assertEqual(self.record(raw=raw, normalization_mode="anthropic_messages")["total_tokens"], 160)

    def test_multica_requires_explicit_cache_contract_and_report_count(self):
        raw = {"total_input_tokens": 100, "total_output_tokens": 20,
               "total_cache_read_tokens": 30, "total_cache_write_tokens": 10,
               "unreported_task_count": 0}
        self.assertEqual(self.record("aggregate-1", raw, normalization_mode="multica_input_includes_cache")["total_tokens"], 120)
        self.assertEqual(self.record("aggregate-2", raw, normalization_mode="multica_input_excludes_cache")["total_tokens"], 280)
        raw["unreported_task_count"] = 1
        self.record("aggregate-3", raw, normalization_mode="multica_input_includes_cache")
        self.assertEqual(self.finish()["status"], "UNKNOWN")

    def test_retries_and_all_agents_count(self):
        self.record("failed-attempt", self.raw(), attempt=1)
        self.record("retry", self.raw(), attempt=2)
        result = self.record("child-agent", self.raw(), agent="child-agent")
        self.assertEqual((result["call_count"], result["total_tokens"]), (3, 360))

    def test_same_call_and_identity_are_idempotent(self):
        self.record(raw=self.raw())
        self.assertEqual(self.record(raw=self.raw())["call_count"], 1)
        for changed in ({"raw": self.raw(output_tokens=21)}, {"agent": "other"}, {"attempt": 2},
                        {"provider": "other"}, {"stage": "build"},
                        {"normalization_mode": "canonical_cache_separate"}):
            with self.subTest(changed=changed), self.assertRaises(budget.BudgetError):
                self.record(**({"raw": self.raw()} | changed))

    def test_missing_usage_unknown_and_known_partial_components_count(self):
        self.record("missing", None)
        result = self.record("partial", {"output_tokens": 25})
        self.assertEqual(result["total_tokens"], 25)
        self.assertEqual(result["unverified_call_count"], 2)
        self.assertFalse(result["can_continue"])
        self.assertEqual(self.finish()["status"], "UNKNOWN")

    def test_missing_multica_unreported_count_is_unknown(self):
        raw = {"total_input_tokens": 100, "total_output_tokens": 20,
               "total_cache_read_tokens": 30, "total_cache_write_tokens": 10}
        self.record(raw=raw, normalization_mode="multica_input_includes_cache")
        self.assertEqual(self.finish()["status"], "UNKNOWN")

    def test_null_counters_are_unknown_and_known_cache_is_counted(self):
        raw = {"input_tokens": None, "output_tokens": 20,
               "cache_read_tokens": 30, "cache_write_tokens": 10}
        result = self.record(raw=raw)
        self.assertEqual((result["total_tokens"], result["unverified_call_count"]), (60, 1))
        self.assertEqual(self.finish()["status"], "UNKNOWN")

    def test_null_optional_provider_counter_is_not_assumed_zero(self):
        self.record(raw={"input_tokens": 100, "output_tokens": 20,
                         "input_tokens_details": {"cached_tokens": None}},
                    normalization_mode="openai_responses")
        self.assertEqual(self.finish()["status"], "UNKNOWN")

    def test_invalid_usage_numbers_and_cache_contract(self):
        for value in (-1, float("nan"), float("inf"), True, 1.5):
            with self.subTest(value=value), self.assertRaises(budget.BudgetError):
                self.record(raw=self.raw(output_tokens=value))
        with self.assertRaises(budget.BudgetError):
            self.record(raw=self.raw(input_tokens=20))
        with self.assertRaises(budget.BudgetError):
            self.record(raw={"input_tokens": 10, "output_tokens": 2,
                             "output_tokens_details": {"reasoning_tokens": 3}},
                        normalization_mode="openai_responses")
        self.assertEqual(budget.summary(self.ledger)["call_count"], 0)

    def test_wrong_openai_total_is_rejected(self):
        with self.assertRaises(budget.BudgetError):
            self.record(raw={"input_tokens": 10, "output_tokens": 2, "total_tokens": 20},
                        normalization_mode="openai_responses")

    def test_identity_required_and_run_match(self):
        for field, value in (("run_id", "wrong"), ("stage", ""), ("agent", ""),
                             ("provider", ""), ("attempt", 0), ("attempt", True)):
            with self.subTest(field=field), self.assertRaises(budget.BudgetError):
                self.record(raw=self.raw(), **{field: value})

    def test_live_run_never_passes_and_finish_freezes_time(self):
        self.record(raw=self.raw())
        self.assertEqual(budget.check(self.ledger)["status"], "UNKNOWN")
        self.clock[0] += 150
        self.clock[1] += 150
        self.assertEqual(self.finish()["elapsed_seconds"], 150)
        self.clock[0] += 20_000
        self.clock[1] += 20_000
        self.assertEqual(self.finish()["status"], "PASS")
        self.assertEqual(budget.summary(self.ledger)["elapsed_seconds"], 150)
        with self.assertRaises(budget.BudgetError):
            self.record(raw=self.raw())

    def test_wait_time_counts_and_120_minutes_boundary(self):
        self.clock[0] += 7200
        self.clock[1] += 7200
        result = budget.check(self.ledger)
        self.assertEqual(result["elapsed_seconds"], 7200)
        self.assertFalse(result["can_continue"])
        self.assertEqual(self.finish()["status"], "PASS")

    def test_wait_beyond_120_minutes_fails(self):
        self.clock[0] += 7200.01
        self.clock[1] += 7200.01
        self.assertEqual(self.finish()["status"], "FAIL")

    def test_running_cap_and_strict_20M_evidence(self):
        result = self.record(raw=self.raw(input_tokens=19_900_000, output_tokens=0))
        self.assertFalse(result["can_continue"])
        self.assertEqual(result["total_tokens"], 19_900_000)
        # Over-limit evidence is still accepted and saved, never silently dropped.
        result = self.record("over", self.raw(input_tokens=100_000, output_tokens=0))
        self.assertEqual(result["total_tokens"], 20_000_000)
        self.assertEqual(self.finish()["status"], "FAIL")

    def test_clock_reversal_stays_unknown(self):
        self.clock[0] -= 1
        self.clock[1] += 10
        self.assertFalse(budget.check(self.ledger)["can_continue"])
        self.clock[0] += 100
        self.clock[1] += 100
        self.assertEqual(self.finish()["status"], "UNKNOWN")

    def test_monotonic_reversal_or_clock_jump_never_passes(self):
        for delta in ((10, -1), (100, 0)):
            with self.subTest(delta=delta):
                self.clock[0] += delta[0]
                self.clock[1] += delta[1]
                result = budget.check(self.ledger)
                self.assertIn("unverified_clock", result["reasons"])
        self.assertEqual(self.finish()["status"], "UNKNOWN")

    def test_changed_clock_source_never_passes(self):
        with patch.object(budget, "_clock_source", return_value="another-host"):
            self.assertIn("clock_source_changed", budget.check(self.ledger)["clock_anomalies"])
        self.assertEqual(self.finish()["status"], "UNKNOWN")

    def test_replay_recomputes_from_original_evidence(self):
        self.record(raw=self.raw())
        replay = self.root / "replayed.json"
        replay.write_bytes(self.ledger.read_bytes())
        self.assertEqual(budget.summary(replay)["total_tokens"], 120)
        data = json.loads(replay.read_text())
        data["calls"][0]["raw_usage"]["output_tokens"] = 21
        replay.write_text(json.dumps(data))
        with self.assertRaises(budget.BudgetError):
            budget.summary(replay)

    def test_atomic_save_failure_preserves_previous_evidence(self):
        previous = self.ledger.read_bytes()
        with patch.object(budget.os, "replace", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                self.record(raw=self.raw())
        self.assertEqual(self.ledger.read_bytes(), previous)
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_thread_writers_do_not_lose_records(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda number: self.record(str(number), self.raw()), range(16)))
        result = budget.summary(self.ledger)
        self.assertEqual((result["call_count"], result["total_tokens"]), (16, 1920))

    def test_process_writers_do_not_lose_records(self):
        # Use real clocks for independent interpreter processes.
        real_ledger = self.root / "processes.json"
        with patch.object(budget, "_clock", side_effect=lambda: (time.time(), time.monotonic())):
            budget.start(real_ledger, "process-run", project_root=self.root)
        code = ("from hmigbot_ios.usage_budget import record; import sys; "
                "record(sys.argv[1], sys.argv[2], {'input_tokens': 100, 'output_tokens': 20}, "
                "run_id='process-run', normalization_mode='openai_responses', "
                "stage='convert', agent='child', provider='synthetic')")
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
        processes = [subprocess.Popen([sys.executable, "-c", code, str(real_ledger), str(i)],
                                      env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for i in range(6)]
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, (stdout, stderr))
        with patch.object(budget, "_clock", side_effect=lambda: (time.time(), time.monotonic())):
            result = budget.finish(real_ledger, run_id="process-run")
        self.assertEqual((result["call_count"], result["total_tokens"], result["status"]),
                         (6, 720, "PASS"))

    def test_start_refuses_reset_bad_limits_or_external_path(self):
        with self.assertRaises(budget.BudgetError):
            budget.start(self.ledger, "different-run", project_root=self.root)
        for kwargs in ({"token_limit": 20_000_000}, {"token_limit": True},
                       {"walltime_limit_seconds": 7201}, {"walltime_limit_seconds": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(budget.BudgetError):
                budget.start(self.root / "bad.json", "run", project_root=self.root, **kwargs)
        with self.assertRaises(budget.BudgetError):
            budget.start("relative.json", "run", project_root=self.root)
        with self.assertRaises(budget.BudgetError):
            budget.start(self.root.parent / "external.json", "run", project_root=self.root)


if __name__ == "__main__":
    unittest.main()
