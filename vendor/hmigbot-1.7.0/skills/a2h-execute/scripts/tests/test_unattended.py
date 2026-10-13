"""U1 无人值守回归。用户裁决（2026-09-05）：全自动执行、多做派——审批门默认 approve；阻断型门自动派一次 repair；
closure STALLED 首次自动 allow_stalled 重跑、二次自动 defer；前波 ERROR 不拦；超时在途按缺失重派。
所有决定留痕 spec/state/auto-adjudications.json，handoff_check 逐条呈报。

E265①（2026-09-23 上午用户裁决）：「质量不达标就必须返工补齐」——可修门 repair 一次仍红即升级停机。

E266（2026-09-23 当日用户再裁决，**覆盖 E265① 的终点**）：「任何情况都不要停机呈报」——
  · 能修的必须真派修复，轮次上限从 1 提到 REPAIR_ROUNDS_MAX=2；
  · 2 轮仍红 / 确定修不了（档 S） → **记欠账放行 + 留全痕**（门名、每一轮修复的失败详情、判定依据、报告路径）；
  · closure STALLED 二次仍由模型自己拍板 defer（C 类：要拍板的模型自己决定），留痕带 open 清单与轮次。
  用户口径：「待人工审核」本身就是要消灭的偷懒缺口，停机呈报不是解法；真正要消灭的是
  「没尝试修就放行」和「放行了不留痕」。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from test_scheduler_kernel import KernelFixture, VALID_ALPHA, VALID_BETA

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import _wavelib as W  # noqa: E402
import next_batch as NB  # noqa: E402


class Unattended(KernelFixture):
    def setUp(self):
        super().setUp()
        self._write(self.blueprint / "workflow-params.json", json.dumps({"gates": {"unattended": True, "dispatch_burst": 0}}))

    def _adj(self):
        return W.load_adjudications(self.proj)


class TestApprovalAuto(Unattended):
    def test_approval_gate_is_auto_approved(self):
        plan = self.base_plan()
        plan["tasks"][2] = {"id": "gate:compile", "kind": "reduce", "run": self.approval_run, "parents": ["@domains-impl"],
                            "approval": {"suspend_payload": "spec/state/approvals/gate.json"}}
        self.write_plan(plan); self.next_batch()
        self.write_result("alpha", VALID_ALPHA); self.write_result("beta", VALID_BETA); self.land(expect=2)
        act = self.next_batch()
        self.assertEqual(act["action"], "dispatch"); self.assertEqual([b["id"] for b in act["batch"]], ["impl:final"])
        d = json.loads((self.proj / "spec/state/approvals/gate.json").read_text(encoding="utf-8"))
        self.assertTrue(d["approved"]); self.assertTrue(d["auto"]); self.assertEqual(d["by"], "auto-policy")
        self.assertEqual([e["kind"] for e in self._adj()], ["approve"])


class TestGatePolicies(Unattended):
    def _still_red(self, gid: str, err: str) -> None:
        """模拟 repair 落地后 --rerun-reduce 仍红：补一条晚于 repair.at 的 REDUCE_FAIL 行。"""
        import time as _t
        from datetime import datetime, timezone
        _t.sleep(1.1)                                                                # auto-adjudications 的 at 精度到秒
        jp = self.state.parent / "journal.json"; j = json.loads(jp.read_text(encoding="utf-8"))
        j["operation_outputs"].append({"workflow_id": "domains", "task_id": gid, "kind": "reduce", "attempt": 1, "status": "REDUCE_FAIL",
                                       "ended_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "error": err})
        self._write(jp, json.dumps(j))

    def test_blocking_gate_repairs_twice_then_waives_with_trace(self):
        """E266：可修门**修两轮**（REPAIR_ROUNDS_MAX），第 3 次仍红 → 记欠账放行，且留痕带两轮修复各自的失败详情。
        用户裁决原话：「不要升级给我，让模型自行解决，一轮不够就修两轮，最多修两轮，还不过就记账放行」。"""
        self.write_plan(self.base_plan()); self._write(self.gate_rc, "1")           # gate:compile 失败（escalate=True，阻断型前缀）
        self.next_batch(); self.write_result("alpha", VALID_ALPHA); self.write_result("beta", VALID_BETA); self.land(expect=2)
        act = self.next_batch()
        self.assertEqual(act["action"], "repair"); self.assertEqual(act["gate"], "gate:compile"); self.assertIn("rerun-reduce gate:compile", act["then"])
        self.assertEqual(act["repair"]["agent"], "a2h-migration-worker")
        self.assertEqual((act["repair_round"], act["repair_rounds_max"]), (1, NB.REPAIR_ROUNDS_MAX))
        self.assertIn("仍红则再派一轮", act["reason"])
        instruction = act["repair"]                                                  # E171：repair 任务书落盘，wait 时原样回投
        saved_prompt = self.proj / instruction["prompt_path"]
        self.assertEqual(saved_prompt.read_text(encoding="utf-8"), instruction["prompt"])
        act = self.next_batch()                                                      # 第二次（repair 在途、门未重跑）：wait，不得急着裁
        self.assertEqual(act["action"], "wait", act); self.assertIn("gate:compile", act["missing"])
        self.assertEqual(act["pending_repair_instructions"][0], instruction)
        self.assertEqual([e["kind"] for e in self._adj()], ["repair"])

        self._still_red("gate:compile", "errors=9 still red")                        # 第 1 轮修完仍红 → 第 2 轮
        act = self.next_batch()
        self.assertEqual(act["action"], "repair", act)
        self.assertEqual(act["repair_round"], 2); self.assertIn("记欠账放行", act["reason"])
        self.assertEqual([e["kind"] for e in self._adj()], ["repair", "repair"])

        self._still_red("gate:compile", "errors=4 still red")                        # 第 2 轮修完仍红 → 记欠账放行
        act = self.next_batch()
        # 欠账后下游照常（不停机）：本波若还有就绪任务就 dispatch，若已全部终态就 done + next 指向下一波；
        # 唯一不许出现的是 escalate。
        self.assertIn(act["action"], ("dispatch", "done"), act)
        self.assertEqual(act.get("next", {}).get("kind", "wave"), "wave", act)
        # `impl:final` 是 gate:compile 的 on_fail.skip 闭包成员，门第一次 REDUCE_FAIL 时就被裁成 folded
        # （land_results.expand_skip_closure）——所以欠账后本波收口，不是再派它。原用例注释即此口径。
        self.assertEqual(act["batch"], [])
        _t = json.loads((self.proj / "spec/state/state.json").read_text(encoding="utf-8"))["waves"]["domains"]["tasks"]
        self.assertEqual([(x["id"], x["status"]) for x in _t if x["id"] == "impl:final"], [("impl:final", "folded")])
        kinds = [e["kind"] for e in self._adj()]; self.assertEqual(kinds, ["repair", "repair", "waive-gate"])
        w = self._adj()[-1]
        self.assertEqual((w["id"], w["terminal"], w["grade"]), ("gate:compile", "waive", "gate-repair-exhausted"))
        self.assertIn("2 轮", w["unfixable_reason"])
        # 留痕能看出两轮分别在修什么（第 1/2 轮 repair 当时的错误 + 最后一次复跑的错误）
        self.assertEqual([r["round"] for r in w["repair_rounds"]], [1, 2, 3])
        self.assertEqual([r.get("final") for r in w["repair_rounds"]], [None, None, True])
        self.assertIn("errors=4", w["repair_rounds"][-1]["error"])

    def test_waivable_gate_still_waived(self):
        """档 W（目前只剩 gate:fence-audit，E73）：越界写盘既成事实、repair 改不了归属 → 仍记欠账继续。"""
        plan = self.base_plan()
        plan["tasks"][2]["id"] = "gate:fence-audit"; plan["tasks"][3]["parents"] = ["gate:fence-audit"]
        plan["tasks"][2]["on_fail"] = {"skip": [], "escalate": True}
        self.write_plan(plan); self._write(self.gate_rc, "1")
        self.next_batch(); self.write_result("alpha", VALID_ALPHA); self.write_result("beta", VALID_BETA); self.land(expect=2)
        act = self.next_batch()
        self.assertEqual(act["action"], "dispatch", act); self.assertEqual([b["id"] for b in act["batch"]], ["impl:final"])   # 欠账后下游照常
        self.assertEqual([e["kind"] for e in self._adj()], ["waive-gate"])

    def test_prev_wave_error_not_blocking(self):
        self.write_plan(self.base_plan())
        jp = self.state.parent / "journal.json"
        j = json.loads(jp.read_text(encoding="utf-8")) if jp.exists() else {"version": 1, "workflow_status": [], "operation_outputs": []}
        j["workflow_status"] = [{"workflow_id": "infra", "status": "ERROR"}]; self._write(jp, json.dumps(j))
        self.assertEqual(self.next_batch()["action"], "dispatch")

    def test_stale_dispatch_becomes_missing_without_flag(self):
        self.write_plan(self.base_plan()); self.next_batch(); self.write_result("beta", VALID_BETA)
        out = self._land_raw("--stale-minutes", "0") if hasattr(self, "_land_raw") else None
        if out is None:
            import subprocess
            r = subprocess.run([sys.executable, str(SCRIPTS / "land_results.py"), "--plan", str(self.plan_path), "--state", str(self.state), "--json", "--stale-minutes", "0"],
                               capture_output=True, text=True, cwd=self.proj); out = json.loads(r.stdout)
        self.assertEqual({r["id"]: r["status"] for r in out["landed"]}, {"impl:alpha": "RETRY_NEEDED", "impl:beta": "OK"})


class TestClosureStalled(Unattended):
    def _backlog(self, **over):
        d = {"version": 1, "round": 3, "max_iter": 8, "verdict": "STALLED", "reason": "fingerprint unchanged", "open": 5,
             "converged": False, "exhausted": False, "items": [], "resolution": {}}
        d.update(over); self._write(self.blueprint / "closure-backlog.json", json.dumps(d))

    def test_first_stalled_retries_second_defers(self):
        self._backlog()
        hint = NB._next_hint({"wave": "closure"}, self.proj / "spec/waves/plan-closure.json", self.proj)
        self.assertEqual(hint["kind"], "wave"); self.assertEqual(hint["wave"], "closure")
        res = json.loads((self.blueprint / "closure-backlog.json").read_text(encoding="utf-8"))["resolution"]
        self.assertTrue(res["allow_stalled"]); self.assertEqual(res["auto_retry"], 1)
        self._backlog(round=4, resolution=res)                                        # 再跑一轮仍 STALLED
        hint = NB._next_hint({"wave": "closure"}, self.proj / "spec/waves/plan-closure.json", self.proj)
        res2 = json.loads((self.blueprint / "closure-backlog.json").read_text(encoding="utf-8"))["resolution"]
        self.assertTrue(res2["defer"]); self.assertNotEqual((hint or {}).get("kind"), "escalate"); self.assertNotEqual((hint or {}).get("wave"), "closure")
        self.assertEqual([e["kind"] for e in self._adj()], ["closure-retry", "closure-defer"])

    def test_preexisting_allow_stalled_counts_as_first_retry(self):
        """既有（人工或伪造）allow_stalled 但未记轮次 → 只再跑一轮，仍 STALLED 即 defer，不会跑满 max_iter。"""
        self._backlog(resolution={"allow_stalled": True, "by": "user", "quote": "x"})
        hint = NB._next_hint({"wave": "closure"}, self.proj / "spec/waves/plan-closure.json", self.proj)
        self.assertEqual(hint["kind"], "wave")
        res = json.loads((self.blueprint / "closure-backlog.json").read_text(encoding="utf-8"))["resolution"]
        self.assertEqual(res["auto_retry"], 1); self.assertEqual(res["by"], "user")
        self._backlog(round=4, resolution=res)
        hint = NB._next_hint({"wave": "closure"}, self.proj / "spec/waves/plan-closure.json", self.proj)
        self.assertTrue(json.loads((self.blueprint / "closure-backlog.json").read_text(encoding="utf-8"))["resolution"]["defer"])
        self.assertNotEqual((hint or {}).get("wave"), "closure")


if __name__ == "__main__":
    import unittest
    unittest.main()
