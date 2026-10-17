#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""land_results --infra-fail 幂等回归 + unattended_runner 在途判定按最大派发序号。

AIPPT_token3（2026-09-21）实证：Codex 主会话因 429 / 模型满载崩溃，unattended_runner 对派出未落账的任务跑
`land_results --infra-fail <ids>` 改判；续跑的主会话按 CODEX_PROMPT 续跑条款对同一批 id 再跑一次——journal 里 7 个任务
18 行 INFRA_FAIL（两个任务各 4 行），失败统计虚高；_wavelib.infra_waived 按行计数，重复行还虚增了配额豁免。重复行又让
runner 的在途判定（原按行数）把之后再派出的在途任务误判为已落账，漏改判。

用法示例:
    cd a2h-execute/scripts/tests && PYTHONPATH=.. python3 -m unittest test_infra_fail_idempotent
    python3 -m pytest a2h-execute/scripts/tests/test_infra_fail_idempotent.py -q

覆盖:
    同一次派发两次 --infra-fail → 只一行 INFRA_FAIL，第二次输出 already_infra_failed；仍可重派；
    改判 → 重派 → 再改判 → 两行（新派发的失败照常记账）；
    RETRY_NEEDED 事后改判 INFRA_FAIL（reclassified）通道不受影响，改判后再重复 --infra-fail 才跳过；
    already_infra_failed 判据（attempt 比较 / 缺 attempt 时 last_dispatch_at 兜底）；
    unattended_runner._in_flight 按最大 attempt 而非行数判在途。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from test_scheduler_kernel import KernelFixture, LAND_RESULTS, SCRIPTS, VALID_BETA

sys.path.insert(0, str(SCRIPTS))
import _wavelib as W  # noqa: E402
import land_results as LR  # noqa: E402
import unattended_runner as UR  # noqa: E402


class InfraFailFixture(KernelFixture):
    def setUp(self) -> None:
        super().setUp()
        # 关错峰（E34），让「重派」在同一测试里立即发生
        self._write(self.blueprint / "workflow-params.json", json.dumps({"gates": {"dispatch_burst": 0}}))
        self.write_plan(self.base_plan())

    def land_flags(self, *extra: str) -> dict:
        proc = self._run(LAND_RESULTS, "--plan", str(self.plan_path), "--state", str(self.state), "--json", *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        out = json.loads(proc.stdout)
        out["_stderr"] = proc.stderr
        return out

    def journal(self) -> dict:
        return json.loads((self.state.parent / "journal.json").read_text(encoding="utf-8"))

    def infra_rows(self, tid: str) -> list:
        return [r for r in self.journal()["operation_outputs"]
                if r.get("task_id") == tid and r.get("status") == "INFRA_FAIL"]

    def dispatched_ids(self, act: dict) -> list:
        return [t["id"] for t in act.get("batch") or []]


class TestInfraFailIdempotent(InfraFailFixture):
    def test_double_call_writes_one_row(self) -> None:
        self.assertEqual(sorted(self.dispatched_ids(self.next_batch())), ["impl:alpha", "impl:beta"])
        first = self.land_flags("--infra-fail", "impl:alpha,impl:beta")      # unattended_runner 崩溃恢复改判
        self.assertEqual(sorted(r["id"] for r in first["landed"] if r["status"] == "INFRA_FAIL"), ["impl:alpha", "impl:beta"])
        self.assertEqual(first["already_infra_failed"], [])
        second = self.land_flags("--infra-fail", "impl:alpha,impl:beta")     # 续跑主会话按续跑条款再跑一次
        self.assertEqual(second["landed"], [])
        self.assertEqual(second["already_infra_failed"], ["impl:alpha", "impl:beta"])
        self.assertIn("幂等", second["_stderr"])
        for tid in ("impl:alpha", "impl:beta"):
            self.assertEqual(len(self.infra_rows(tid)), 1, tid)
            self.assertEqual(self.state_task(tid)["status"], "pending")
        self.assertEqual(W.infra_waived(self.journal(), "domains"), {"impl:alpha": 1, "impl:beta": 1})
        # 语义不变：不计 attempts、仍可重派
        self.assertEqual(sorted(self.dispatched_ids(self.next_batch())), ["impl:alpha", "impl:beta"])

    def test_call_redispatch_call_writes_two_rows(self) -> None:
        self.next_batch()
        self.write_result("beta", VALID_BETA)
        self.land_flags("--infra-fail", "impl:alpha")                       # alpha 改判、beta 正常落账（无在途，拍①可补派）
        act = self.next_batch()                                             # alpha 重派（attempts 2）
        self.assertEqual(self.dispatched_ids(act), ["impl:alpha"])
        again = self.land_flags("--infra-fail", "impl:alpha")               # 新一次派发又被杀：新的失败，照常记账
        self.assertEqual(again["already_infra_failed"], [])
        self.assertEqual([r["status"] for r in again["landed"]], ["INFRA_FAIL"])
        rows = self.infra_rows("impl:alpha")
        self.assertEqual([r["attempt"] for r in rows], [1, 2])
        self.assertEqual(W.infra_waived(self.journal(), "domains")["impl:alpha"], 2)
        self.assertEqual(self.dispatched_ids(self.next_batch()), ["impl:alpha"])   # 有效计数 3−2=1，仍可派

    def test_posthoc_reclassify_still_works_then_dedups(self) -> None:
        self.next_batch()
        # 代理已终止、主会话当时只知缺 result → RETRY_NEEDED；事后才知是 429 → --infra-fail 改判（reclassified 行）
        miss = self.land_flags("--missing-as-failed", "impl:alpha")
        self.assertEqual([r["status"] for r in miss["landed"]], ["RETRY_NEEDED"])
        re1 = self.land_flags("--infra-fail", "impl:alpha")
        self.assertEqual([r["status"] for r in re1["landed"]], ["INFRA_FAIL"])
        self.assertEqual(re1["already_infra_failed"], [])
        rows = self.infra_rows("impl:alpha")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].get("reclassified"))
        re2 = self.land_flags("--infra-fail", "impl:alpha")
        self.assertEqual((re2["landed"], re2["already_infra_failed"]), ([], ["impl:alpha"]))
        self.assertEqual(len(self.infra_rows("impl:alpha")), 1)

    def test_flag_absent_output_has_no_key(self) -> None:
        self.next_batch()
        self.assertNotIn("already_infra_failed", self.land_flags())


class TestAlreadyInfraFailedPredicate(unittest.TestCase):
    def test_attempt_comparison_and_fallback(self) -> None:
        row = {"status": "INFRA_FAIL", "attempt": 2, "started_at": "2026-09-21T10:15:02+00:00"}
        self.assertTrue(LR.already_infra_failed({"attempts": 2}, row))
        self.assertFalse(LR.already_infra_failed({"attempts": 3}, row))                       # 之后又派过
        self.assertFalse(LR.already_infra_failed({"attempts": 2}, dict(row, status="RETRY_NEEDED")))
        self.assertFalse(LR.already_infra_failed({"attempts": 2}, None))
        legacy = {"status": "INFRA_FAIL", "started_at": "2026-09-21T10:15:02+00:00"}          # 旧账行缺 attempt
        self.assertTrue(LR.already_infra_failed({"attempts": 2, "last_dispatch_at": "2026-09-21T10:15:02+00:00"}, legacy))
        self.assertFalse(LR.already_infra_failed({"attempts": 3, "last_dispatch_at": "2026-09-21T10:32:21+00:00"}, legacy))

    def test_latest_rows_last_wins_and_skips_reduce(self) -> None:
        j = {"operation_outputs": [
            {"workflow_id": "w", "task_id": "t", "kind": "agent", "status": "INFRA_FAIL", "attempt": 1},
            {"workflow_id": "w", "task_id": "t", "kind": "agent", "status": "OK", "attempt": 2},
            {"workflow_id": "w", "task_id": "g", "kind": "reduce", "status": "REDUCE_PASS"},
            {"workflow_id": "x", "task_id": "t", "kind": "agent", "status": "INFRA_FAIL", "attempt": 9}]}
        latest = LR.latest_agent_rows(j, "w")
        self.assertEqual(sorted(latest), ["t"])
        self.assertEqual(latest["t"]["status"], "OK")


class TestRunnerInFlight(unittest.TestCase):
    """runner 在途判定按已落账的最大 attempt——行数会被同一派发的多行（事后改判 / 旧版重复改判）顶高。"""

    def _proj(self, attempts: int, rows: list) -> Path:
        tmp = tempfile.TemporaryDirectory(prefix="a2h-runner-inflight-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "spec/state").mkdir(parents=True)
        (root / "spec/waves").mkdir(parents=True)
        (root / "spec/waves/plan-specfix.json").write_text(json.dumps({"wave": "specfix"}), encoding="utf-8")
        (root / "spec/state/dispatch.json").write_text(json.dumps({"waves": {"specfix": {"dispatched": {
            "read:r9:dom": {"attempts": attempts, "last_dispatch_at": "2026-09-21T10:32:21+00:00"}}}}}), encoding="utf-8")
        (root / "spec/state/journal.json").write_text(json.dumps({"operation_outputs": [
            dict({"workflow_id": "specfix", "task_id": "read:r9:dom", "kind": "agent"}, **r) for r in rows]}), encoding="utf-8")
        return root

    def test_duplicate_rows_do_not_hide_inflight_dispatch(self) -> None:
        rows = [{"status": "INFRA_FAIL", "attempt": 1}, {"status": "INFRA_FAIL", "attempt": 2},
                {"status": "INFRA_FAIL", "attempt": 2, "reclassified": True}]
        found = UR._in_flight(self._proj(3, rows))                 # 第 3 次派发在途：行数 3 但最大 attempt 2
        self.assertEqual([(p.name, ids) for p, ids in found], [("plan-specfix.json", ["read:r9:dom"])])
        self.assertEqual(UR._in_flight(self._proj(2, rows)), [])   # 第 2 次派发已落账：不在途

    def test_rows_without_attempt_fall_back_to_count(self) -> None:
        self.assertEqual(UR._in_flight(self._proj(1, [{"status": "OK"}])), [])
        found = UR._in_flight(self._proj(2, [{"status": "OK"}]))
        self.assertEqual([ids for _, ids in found], [["read:r9:dom"]])


if __name__ == "__main__":
    unittest.main()
