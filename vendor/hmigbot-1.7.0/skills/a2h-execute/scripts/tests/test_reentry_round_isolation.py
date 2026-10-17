"""E55 回归：同名波重入（closure rN）的 reduce 行按轮次隔离。立此闸的事实：AIPPT_0903 test4 closure r4 六个代理落地后
build/compile/rescan 全部沿用 r3 的 REDUCE_PASS，5 分钟判 SUCCESS、一条 finding 未重扫（2026-09-05 09:12）。
判据：plan_run_tag 从 agent id 取 rN；journal_indexes 带 run_tag 时忽略其它轮与无标签的 reduce 行；不带时行为不变；
land_results 写 reduce 行带 run 字段（重入波）/不带（普通波）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from test_scheduler_kernel import KernelFixture, VALID_ALPHA, VALID_BETA

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import _wavelib as W  # noqa: E402


class TestRunTag(KernelFixture):
    def test_plan_run_tag(self):
        self.assertEqual(W.plan_run_tag({"tasks": [{"id": "closure:r4:domain:x", "kind": "agent"}, {"id": "reduce:build-closure", "kind": "reduce"}]}), "r4")
        self.assertIsNone(W.plan_run_tag({"tasks": [{"id": "impl:alpha", "kind": "agent"}]}))

    def test_journal_indexes_isolates_rounds(self):
        j = {"operation_outputs": [
            {"workflow_id": "closure", "task_id": "gate:closure-rescan", "kind": "reduce", "status": "REDUCE_PASS"},            # 旧行（无标签）
            {"workflow_id": "closure", "task_id": "reduce:build-closure", "kind": "reduce", "status": "REDUCE_PASS", "run": "r3"},
            {"workflow_id": "closure", "task_id": "reduce:probe", "kind": "reduce", "status": "REDUCE_PASS", "run": "r4"},
            {"workflow_id": "closure", "task_id": "closure:r4:domain:x", "kind": "agent", "attempt": 1, "status": "OK"},
        ]}
        landed, red = W.journal_indexes(j, "closure", "r4")
        self.assertEqual(red, {"reduce:probe": "REDUCE_PASS"}); self.assertEqual(landed, {"closure:r4:domain:x": 1})
        _, red_all = W.journal_indexes(j, "closure")
        self.assertEqual(set(red_all), {"gate:closure-rescan", "reduce:build-closure", "reduce:probe"})

    def test_land_results_tags_reduce_rows_only_for_reentrant_waves(self):
        self.write_plan(self.base_plan()); self.next_batch()
        self.write_result("alpha", VALID_ALPHA); self.write_result("beta", VALID_BETA, fenced=False); self.land()
        j = json.loads((self.state.parent / "journal.json").read_text(encoding="utf-8"))
        rows = [r for r in j["operation_outputs"] if r["kind"] == "reduce"]
        self.assertTrue(rows); self.assertTrue(all("run" not in r for r in rows))           # 普通波不带
        self.assertEqual(W.plan_run_tag(json.loads(self.plan_path.read_text(encoding="utf-8"))), None)

    def test_reentry_repins_hash_only_for_new_round(self):
        import next_batch as NB
        rec = {"contract_hash": "sha256:old", "dispatched": {"closure:r4:domain:x": {"attempts": 1}}}
        plan5 = {"contract_hash": "sha256:new", "tasks": [{"id": "closure:r5:domain:x", "kind": "agent"}]}
        self.assertTrue(NB.reentry_repin(rec, plan5, "closure")); self.assertEqual(rec["contract_hash"], "sha256:new")
        self.assertEqual(rec["contract_hash_history"][0]["hash"], "sha256:old")
        plan5b = {"contract_hash": "sha256:newer", "tasks": [{"id": "closure:r5:domain:x", "kind": "agent"}]}
        rec["dispatched"]["closure:r5:domain:x"] = {"attempts": 1}
        self.assertFalse(NB.reentry_repin(rec, plan5b, "closure"))                       # 同轮已派 → 仍拒绝
        # E67：无标签波、任务集不相交 → 允许重 pin；有重叠 → 拒绝；空派发记录 → 拒绝（由首派建分区）
        rec2 = {"contract_hash": "a", "dispatched": {"read:app-tips": {"attempts": 1}}}
        self.assertTrue(NB.reentry_repin(rec2, {"contract_hash": "b", "tasks": [{"id": "read:app-load", "kind": "agent"}]}, "specfix")); self.assertEqual(rec2["contract_hash"], "b")
        self.assertFalse(NB.reentry_repin({"contract_hash": "a", "dispatched": {"read:app-tips": {}}}, {"contract_hash": "b", "tasks": [{"id": "read:app-tips", "kind": "agent"}]}, "specfix"))
        self.assertFalse(NB.reentry_repin({"contract_hash": "a", "dispatched": {}}, {"contract_hash": "b", "tasks": [{"id": "impl:a", "kind": "agent"}]}, "domains"))
        # E122：重叠但重叠任务全部已落账（journal attempt ≥ 派发 attempts）→ 允许重 pin（AIPPT 拆域后 understand 重生成 21 旧 + 17 新）
        rec3 = {"contract_hash": "a", "dispatched": {"read:x": {"attempts": 1}, "read:z": {"attempts": 1}}}
        plan3 = {"contract_hash": "b", "tasks": [{"id": "read:x", "kind": "agent"}, {"id": "read:y", "kind": "agent"}]}
        self.assertFalse(NB.reentry_repin(dict(rec3, dispatched=dict(rec3["dispatched"])), plan3, "understand", {"read:x": 0}))   # x 在途 → 拒绝
        self.assertTrue(NB.reentry_repin(rec3, plan3, "understand", {"read:x": 1}))
        self.assertEqual((rec3["contract_hash"], rec3["contract_hash_history"][0]["new_round"]), ("b", "landed-overlap-reentry"))

    def test_adjudications_are_round_scoped(self):
        W.record_adjudication(self.proj, {"kind": "waive-gate", "wave": "closure", "id": "gate:compile-closure", "run": "r4"})
        W.record_adjudication(self.proj, {"kind": "repair", "wave": "closure", "id": "gate:compile-closure", "run": "r4"})
        self.assertEqual(W.waived_ids(self.proj, "closure", "r5"), set()); self.assertEqual(W.repair_count(self.proj, "closure", "gate:compile-closure", "r5"), 0)
        self.assertEqual(W.waived_ids(self.proj, "closure", "r4"), {"gate:compile-closure"}); self.assertEqual(W.repair_count(self.proj, "closure", "gate:compile-closure", "r4"), 1)
        self.assertEqual(W.waived_ids(self.proj, "closure"), {"gate:compile-closure"})            # 无 tag 的波不过滤


if __name__ == "__main__":
    import unittest
    unittest.main()
