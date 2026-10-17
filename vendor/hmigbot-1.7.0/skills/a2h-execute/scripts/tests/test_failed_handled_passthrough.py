"""E44 回归：on_fail.escalate=False 的 reduce 失败（failed_handled）不阻断未被 skip 点名的下游节点。
立此闸的事实：AIPPT_0903 test4 depthfix 波（2026-09-04 23:01）gate:depth-2 FAIL 后 reduce:product-write-audit 被判「不可达」，
拍①吐出一个无事可裁的 escalate。判据：软门失败后其子 reduce 在同一 land 循环内跑完；拍①判 done；on_fail.skip 点名的子任务仍被裁掉。
"""
from __future__ import annotations

import sys

from test_scheduler_kernel import KernelFixture, VALID_ALPHA, VALID_BETA

PY = sys.executable


class TestFailedHandledPassthrough(KernelFixture):
    def _plan(self, skip: list[str]) -> dict:
        plan = self.base_plan()
        plan["tasks"] = [t for t in plan["tasks"] if t["id"] in ("impl:alpha", "impl:beta")] + [
            {"id": "gate:soft", "kind": "reduce", "run": "%s -c \"import sys; sys.exit(1)\"" % PY,
             "parents": ["@domains-impl"], "on_fail": {"skip": skip, "escalate": False}},
            {"id": "reduce:audit", "kind": "reduce", "run": "%s -c \"print(1)\"" % PY,
             "parents": ["gate:soft"], "on_fail": {"escalate": False}},
            {"id": "reduce:victim", "kind": "reduce", "run": "%s -c \"print(1)\"" % PY,
             "parents": ["gate:soft"], "on_fail": {"escalate": False}},
        ]
        return plan

    def test_soft_gate_fail_lets_children_run_and_wave_finish(self):
        self.write_plan(self._plan(skip=["reduce:victim"]))
        self.assertEqual(self.next_batch()["action"], "dispatch")
        self.write_result("alpha", VALID_ALPHA); self.write_result("beta", VALID_BETA, fenced=False)
        out = self.land()
        status = {r["id"]: r["status"] for r in out["reduces"]}
        self.assertEqual(status.get("gate:soft"), "REDUCE_FAIL")
        self.assertEqual(status.get("reduce:audit"), "REDUCE_PASS")            # 未点名 → 照常跑
        self.assertNotEqual(status.get("reduce:victim"), "REDUCE_PASS")        # on_fail.skip 点名 → 被裁
        act = self.next_batch()
        self.assertEqual(act["action"], "done", act)


if __name__ == "__main__":
    import unittest
    unittest.main()
