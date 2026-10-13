#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E265①⑤ 回归：质量类闸不再「只记账继续」，轮次到顶未收敛不再当成正常收尾。

用户口径（2026-09-23）：「方案不能留条件跳过、质量不达标放行、待人工审核这类让模型偷懒的缺口——
质量不达标就必须返工补齐。」

实证泄漏（AIPPT_930_ds 2026-09-21 全量跑批）：
  · spec/reports/wires-check-debt.json：契约边 92 条只接 87，5 条 consumer-missing 带着欠账走完收尾；
  · spec/blueprint/closure-backlog.json：converged=false / "152 findings remain"，轮次到顶即停、152 条 unowned 无人修。

本模块覆盖四条改动：
  ① 质量门失败 → 派修复任务（任务书带该门报告的逐条违规）
  ② 修复后复跑该门通过 → 主线照常往下
  ③ 修复耗尽 / 不可修门 → 升级停机，禁止 waive-gate 记欠账
  ⑤ closure 轮次到顶且 converged=false / debt 补账用尽而交棒硬门仍 BLOCKED → action=escalate，不得 done
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from test_scheduler_kernel import KernelFixture, LAND_RESULTS, VALID_ALPHA, VALID_BETA

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import _wavelib as W  # noqa: E402
import generate_waves as GW  # noqa: E402
import next_batch as NB  # noqa: E402

# ds 真实报告形态（spec/reports/depth-gate.json / wires-check-debt.json 的裁剪样本）
DEPTH_REPORT = {
    "detector": "depth", "passed": False,
    "stats": {"pages_checked": 2, "pages_judged": 2, "shallow": 1, "missing": 1, "min_ratio": 0.4},
    "findings": [
        {"severity": "FAIL", "code": "depth-shallow", "domain": "alpha", "page": "Search",
         "file": "entry/src/main/ets/pages/SearchPage.ets", "expected": 23, "actual": 5, "ratio": 0.22,
         "message": "Search：spec 23 个要点，产物仅 5 个 ArkUI 节点（ratio 0.22 < 0.40）——速写级还原，需按页重做"},
        {"severity": "FAIL", "code": "page-missing", "domain": "beta", "page": "Detail",
         "file": "entry/src/main/ets/pages/DetailPage.ets", "expected": 11, "actual": 0, "ratio": 0.0,
         "message": "Detail 无产物文件 DetailPage.ets"},
    ],
    "rows": [],
}
WIRES_REPORT = {
    "wave": "wiring", "total": 92, "wired": 87, "counts": {"wired": 87, "consumer-missing": 5},
    "unwired": [{"from": "CreateOutLinePage", "to": "AppTipsDialog", "status": "consumer-missing",
                 "consumer_domain": "app-ppttemplate", "provider_domain": "app-algorithm"},
                {"from": "PPTFilePage", "to": "PPTCreatingDialog", "status": "consumer-missing",
                 "consumer_domain": "app-ppttemplate", "provider_domain": "app-preview"}],
}


class Unattended(KernelFixture):
    """U1 打开（质量门的三档处置只在无人值守面上自动走；attended 面由 TestAttendedEscalate 覆盖）。"""

    def setUp(self):
        super().setUp()
        self._write(self.blueprint / "workflow-params.json",
                    json.dumps({"gates": {"unattended": True, "dispatch_burst": 0}}))

    def _adj(self):
        return W.load_adjudications(self.proj)

    def gate_plan(self, gid: str, *, skip=None) -> dict:
        """把夹具里的 gate:compile 换成被测门；on_fail.skip 置空，便于观察「门过了下游照常派发」。"""
        plan = self.base_plan()
        plan["tasks"][2]["id"] = gid
        plan["tasks"][2]["on_fail"] = {"skip": list(skip or []), "escalate": True}
        plan["tasks"][3]["parents"] = [gid]
        return plan

    def run_to_gate(self, gid: str, *, skip=None) -> None:
        """派发 → 落账 → 该门执行（gate_rc=1 即 REDUCE_FAIL，land 退 2）。"""
        self.write_plan(self.gate_plan(gid, skip=skip))
        self._write(self.gate_rc, "1")
        self.next_batch()
        self.write_result("alpha", VALID_ALPHA)
        self.write_result("beta", VALID_BETA)
        self.land(expect=2)

    def rerun_reduce(self, gid: str, expect: int = 0) -> dict:
        proc = subprocess.run([sys.executable, str(LAND_RESULTS), "--plan", str(self.plan_path),
                               "--state", str(self.state), "--rerun-reduce", gid, "--json"],
                              capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj), timeout=120)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)


# ── ① 质量门失败 → 派修复任务（任务书带逐条违规）─────────────────────────────

class TestQualityGateRepairDispatch(Unattended):
    def test_depth2_failure_dispatches_repair_with_findings(self):
        """gate:depth-2 判浅 → repair 任务书必须带 depth-gate.json 的逐页 expected/actual（否则代理不知道要修什么）。"""
        self._write(self.proj / "spec/reports/depth-gate.json", json.dumps(DEPTH_REPORT, ensure_ascii=False))
        self.run_to_gate("gate:depth-2")
        act = self.next_batch()
        self.assertEqual(act["action"], "repair", act)
        self.assertEqual(act["gate"], "gate:depth-2")
        self.assertEqual(act["report"], "spec/reports/depth-gate.json")
        prompt = act["repair"]["prompt"]
        self.assertIn("depth-shallow", prompt)
        self.assertIn("entry/src/main/ets/pages/SearchPage.ets", prompt)
        self.assertIn("Detail 无产物文件", prompt)          # page-missing 也要进清单
        self.assertIn("升级停机", prompt)                    # 不给「记欠账放行」的暗示
        self.assertEqual((self.proj / act["repair"]["prompt_path"]).read_text(encoding="utf-8"), prompt)
        self.assertEqual([e["kind"] for e in self._adj()], ["repair"])

    def test_wires_check_repair_lists_each_unwired_edge(self):
        """reduce:wires-check 的修法是逐条接边，任务书必须点名 from→to（ds 那 5 条 consumer-missing 就是这么漏的）。"""
        self._write(self.proj / "spec/reports/wires-check-domains.json", json.dumps(WIRES_REPORT, ensure_ascii=False))
        self.run_to_gate("reduce:wires-check")
        act = self.next_batch()
        self.assertEqual(act["action"], "repair", act)
        prompt = act["repair"]["prompt"]
        self.assertIn("CreateOutLinePage → AppTipsDialog", prompt)
        self.assertIn("PPTFilePage → PPTCreatingDialog", prompt)
        self.assertIn("consumer-missing", prompt)

    def test_spec_layer_gate_repair_scopes_write_to_spec(self):
        """spec 层的门（gate:spec-depth-2 / gate:interface-2）判的是 spec/domains/*.md，写权提示不能写成「只修产物」。"""
        self.run_to_gate("gate:spec-depth-2")
        act = self.next_batch()
        self.assertEqual(act["action"], "repair", act)
        self.assertIn("spec/domains/**", act["repair"]["prompt"])
        self.assertNotIn("请只修产物", act["repair"]["prompt"])


# ── ② 修复后复跑该门通过 → 主线照常 ───────────────────────────────────────

class TestRepairThenGatePasses(Unattended):
    def test_gate_green_after_repair_lets_downstream_run(self):
        self._write(self.proj / "spec/reports/depth-gate.json", json.dumps(DEPTH_REPORT, ensure_ascii=False))
        self.run_to_gate("gate:depth-2")
        self.assertEqual(self.next_batch()["action"], "repair")
        self._write(self.gate_rc, "0")                      # repair 代理改完，门复跑转绿
        self.rerun_reduce("gate:depth-2")
        act = self.next_batch()
        self.assertEqual(act["action"], "dispatch", act)
        self.assertEqual([b["id"] for b in act["batch"]], ["impl:final"])
        # 只留 repair 一条裁决——既没有 waive-gate（放行），也没有 escalate-gate（停机）
        self.assertEqual([e["kind"] for e in self._adj()], ["repair"])


# ── ③ 修复轮次用尽 / 不可修门 → 记欠账放行 + 留全痕（E266 覆盖 E265① 的「升级停机」）────
# 用户裁决（2026-09-23 当日，覆盖同日上午的 E265①）：「任何情况都不要停机呈报」——
# 能修的最多修两轮，修不动的记账放行；要消灭的是「没尝试修就放行」和「放行了不留痕」，不是放行本身。

class TestRepairExhaustedWaivesWithTrace(Unattended):
    def _still_red_after_repair(self, gid: str, err: str = "shallow=1 missing=1") -> dict:
        """模拟 repair 落地后 --rerun-reduce 仍红：补一条晚于 repair.at 的 REDUCE_FAIL 行。"""
        import time
        from datetime import datetime, timezone
        time.sleep(1.1)                                     # auto-adjudications 的 at 精度到秒
        jp = self.state.parent / "journal.json"
        j = json.loads(jp.read_text(encoding="utf-8"))
        j["operation_outputs"].append(
            {"workflow_id": "domains", "task_id": gid, "kind": "reduce", "attempt": 1, "status": "REDUCE_FAIL",
             "ended_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "error": err})
        self._write(jp, json.dumps(j))
        return self.next_batch()

    def test_quality_gate_gets_two_repair_rounds_then_waives(self):
        """档 R：第 1 轮 repair → 仍红第 2 轮 repair → 仍红才记欠账放行（不是修一次就裁）。"""
        self._write(self.proj / "spec/reports/depth-gate.json", json.dumps(DEPTH_REPORT, ensure_ascii=False))
        self.run_to_gate("gate:depth-2")
        act = self.next_batch()
        self.assertEqual((act["action"], act["repair_round"]), ("repair", 1))
        self.assertEqual(self.next_batch()["action"], "wait")        # repair 在途不得急着裁
        act = self._still_red_after_repair("gate:depth-2", "shallow=1 missing=1（第一轮后）")
        self.assertEqual((act["action"], act["repair_round"]), ("repair", 2), act)
        self.assertEqual(act["repair_rounds_max"], NB.REPAIR_ROUNDS_MAX)
        self.assertEqual([e["kind"] for e in self._adj()], ["repair", "repair"])

    def test_waive_trace_carries_every_repair_round(self):
        """记欠账放行的那条裁决必须自带：门名 / 每轮修复的失败详情 / 判定修不了的依据 / 报告路径 + 摘要。
        AIPPT_930_ds 的真正泄漏是「放行了不留痕」——收尾报告只剩一句「带欠账」。"""
        self._write(self.proj / "spec/reports/depth-gate.json", json.dumps(DEPTH_REPORT, ensure_ascii=False))
        self.run_to_gate("gate:depth-2")
        self.next_batch()                                            # 第 1 轮 repair
        self._still_red_after_repair("gate:depth-2", "第一轮后仍红")   # → 第 2 轮 repair
        act = self._still_red_after_repair("gate:depth-2", "第二轮后仍红")
        self.assertEqual(act["action"], "dispatch", act)             # 记账放行，下游照常（绝不停机）
        self.assertEqual([b["id"] for b in act["batch"]], ["impl:final"])
        kinds = [e["kind"] for e in self._adj()]
        self.assertEqual(kinds, ["repair", "repair", "waive-gate"])
        self.assertNotIn("escalate-gate", kinds)
        w = self._adj()[-1]
        self.assertEqual((w["id"], w["terminal"], w["grade"]), ("gate:depth-2", "waive", "gate-repair-exhausted"))
        self.assertEqual(w["report"], "spec/reports/depth-gate.json")
        self.assertIn("depth-shallow", w["excerpt"])                 # 逐条违规也在账里，不用再去翻报告
        self.assertEqual([r["round"] for r in w["repair_rounds"]], [1, 2, 3])
        self.assertIn("第二轮后仍红", w["repair_rounds"][-1]["error"])
        self.assertIn("%d 轮 repair" % NB.REPAIR_ROUNDS_MAX, w["unfixable_reason"])

    def test_unrepairable_gate_waives_without_spending_an_agent(self):
        """档 S（脚本单写者崩了 / 越权写盘）：派代理改产物修不好 → 不烧 repair 轮次，直接记账放行并写明依据。"""
        for gid in ("reduce:product-write-audit", "reduce:harvest-literals", "reduce:seed-resources",
                    "reduce:contract-fill", "reduce:backlog-settle", "gate:round0"):
            with self.subTest(gate=gid):
                self.setUp()
                self.run_to_gate(gid)
                act = self.next_batch()
                self.assertEqual(act["action"], "dispatch", act)
                self.assertEqual([e["kind"] for e in self._adj()], ["waive-gate"])
                w = self._adj()[-1]
                self.assertEqual((w["id"], w["grade"], w["terminal"]), (gid, "gate-unrepairable", "waive"))
                self.assertEqual(w["repair_rounds"][0]["round"], 1)   # 只有「最后一次复跑」这一条，没派过 repair
                self.assertTrue(w["repair_rounds"][0].get("final"))
                self.assertIn("派代理改 .ets 改不动它", w["unfixable_reason"])

    def test_round0_clear_is_repairable_but_round0_is_not(self):
        """findings 销账门判的是产物质量（可修）；round0 预检非 0 只代表脚本没产出（不可修）。"""
        self.assertTrue(NB._is_blocking_gate("gate:round0-clear"))
        self.assertFalse(NB._is_blocking_gate("gate:round0"))
        self.assertTrue(NB._is_unrepairable_gate("gate:round0"))


# ── 门禁三档分类（改动的机械口径，防回归）────────────────────────────────

class TestGateTaxonomy(unittest.TestCase):
    REPAIRABLE = ("gate:compile-2", "gate:compile-4:r2", "reduce:build-domains", "reduce:pagemap",
                  "gate:round0-clear", "gate:depth-2", "gate:spec-depth-2", "gate:interface-2",
                  "reduce:wires-check")
    NO_REPAIR = ("gate:round0", "reduce:harvest-literals", "reduce:seed-resources",
                 "reduce:resource-sweep", "reduce:contract-fill", "reduce:backlog-settle",
                 "reduce:product-write-audit")
    # 一轮闸的失败是条件波的派发信号（返工机制本身），不是放行 → 不进阻断表
    ROUND_ONE = ("gate:depth", "gate:spec-depth", "gate:interface")

    def test_repairable(self):
        for g in self.REPAIRABLE:
            self.assertTrue(NB._is_blocking_gate(g), g)
            self.assertFalse(NB._is_unrepairable_gate(g), g)
            self.assertEqual(NB._gate_terminal_key(g), "gate-repair-exhausted", g)

    def test_no_repair_rounds_but_still_waived(self):
        for g in self.NO_REPAIR:
            self.assertFalse(NB._is_blocking_gate(g), g)
            self.assertTrue(NB._is_unrepairable_gate(g), g)
            self.assertEqual(NB._gate_terminal_key(g), "gate-unrepairable", g)

    def test_round_one_gates_and_fence_audit_stay_out(self):
        for g in self.ROUND_ONE:
            self.assertFalse(NB._is_blocking_gate(g), g)
            self.assertFalse(NB._is_unrepairable_gate(g), g)
            self.assertEqual(NB._gate_terminal_key(g), "gate-waivable", g)
        self.assertFalse(NB._is_unrepairable_gate("gate:fence-audit"))    # E73：档 W，仍可欠账

    def test_every_terminal_is_waive(self):
        """E266：终点表里不允许再出现停机——任何一档都走记欠账放行。"""
        self.assertEqual(set(NB.TERMINALS.values()), {NB.TERMINAL_WAIVE})
        self.assertEqual(NB.terminal_of("no-such-key"), NB.TERMINAL_WAIVE)   # 表外键同样不停机
        self.assertEqual(NB.REPAIR_ROUNDS_MAX, 2)
        for k in NB.TERMINALS:
            if k != "approval-open-debt":                                     # 该档的依据在 _wavelib.approval_debt_note
                self.assertIn(k, NB.UNFIXABLE_REASONS, k)                     # 每个终点都要有「凭什么判定修不了」

    def test_report_excerpt_shapes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "spec/reports").mkdir(parents=True)
            (root / "spec/reports/depth-gate.json").write_text(json.dumps(DEPTH_REPORT, ensure_ascii=False), encoding="utf-8")
            (root / "spec/reports/wires-check-debt.json").write_text(json.dumps(WIRES_REPORT, ensure_ascii=False), encoding="utf-8")
            depth = NB._gate_report_excerpt(root, "gate:depth-2", "depthfix")
            self.assertIn("共 2 条", depth)
            self.assertIn("[FAIL] depth-shallow", depth)
            wires = NB._gate_report_excerpt(root, "reduce:wires-check", "debt")
            self.assertIn("CreateOutLinePage → AppTipsDialog", wires)
            self.assertEqual(NB._gate_report_excerpt(root, "gate:interface-2", "specfix"), "")   # 报告缺席 → 不编造


# ── 有人值守面：失败门的逐条违规也要进升级材料 ───────────────────────────

class TestAttendedEscalate(KernelFixture):
    def test_escalate_carries_gate_report_and_excerpt(self):
        self._write(self.proj / "spec/reports/depth-gate.json", json.dumps(DEPTH_REPORT, ensure_ascii=False))
        plan = self.base_plan()
        plan["tasks"][2]["id"] = "gate:depth-2"
        plan["tasks"][2]["on_fail"] = {"skip": ["impl:final"], "escalate": True}
        plan["tasks"][3]["parents"] = ["gate:depth-2"]
        self.write_plan(plan)
        self._write(self.gate_rc, "1")
        self.next_batch()
        self.write_result("alpha", VALID_ALPHA)
        self.write_result("beta", VALID_BETA)
        self.land(expect=2)
        act = self.next_batch()
        self.assertEqual((act["action"], act.get("settled")), ("done", True), act)  # E266：不再停机，改记欠账放行
        self.assertEqual(act["gate_reports"]["gate:depth-2"], "spec/reports/depth-gate.json")
        self.assertIn("SearchPage.ets", act["excerpts"]["gate:depth-2"])


# ── ⑤ 轮次到顶但未收敛 → 不许收尾 ────────────────────────────────────────

CLOSURE_BASE = {"version": 1, "round": 9, "max_iter": 8, "verdict": "CONTINUE",
                "reason": "152 findings remain; dispatch repair worker for iter 9", "open": 1,
                "converged": False, "exhausted": True, "items": [],
                "unowned": [{"code": "class-not-migrated", "file": "entry/src/main/ets/x/A.ets",
                             "line": 12, "message": "Android 类 A 未迁移"}],
                "resolution": {}}


class TestClosureExhausted(KernelFixture):
    def _backlog(self, **over) -> None:
        d = dict(CLOSURE_BASE)
        d.update(over)
        self._write(self.blueprint / "closure-backlog.json", json.dumps(d, ensure_ascii=False))

    def _hint(self, wave="closure"):
        return NB._next_hint({"wave": wave}, self.proj / "spec" / "waves" / ("plan-%s.json" % wave), self.proj)

    def test_exhausted_unconverged_escalates_with_list(self):
        """ds 实证形态：round 到顶、converged=false、152 条无主 finding——原路径是跳过 closure 直接进 closeout。"""
        self._backlog()
        h = self._hint()
        self.assertEqual(h["kind"], "escalate")
        self.assertIs(h["converged"], False)
        self.assertEqual(h["counts"], {"items": 0, "unowned": 1})
        self.assertIn("class-not-migrated", h["unconverged"][0])
        self.assertIn("entry/src/main/ets/x/A.ets:12", h["unconverged"][0])
        self.assertIn("轮次到顶仍未收敛", h["reason"])

    def test_converged_goes_on_as_before(self):
        self._backlog(converged=True, exhausted=False, open=0, verdict="CONVERGED", round=3, unowned=[])
        h = self._hint()
        self.assertEqual((h["kind"], h["wave"]), ("wave", "closeout"))

    def test_user_defer_is_respected(self):
        """用户明示 defer 是人的裁决，不是模型给自己开口子——仍放行进 closeout。"""
        self._backlog(resolution={"defer": True, "by": "user", "quote": "接受这批欠账"})
        h = self._hint()
        self.assertEqual((h["kind"], h["wave"]), ("wave", "closeout"))

    def test_upstream_wave_also_stops_before_entering_closeout(self):
        """从上游波（wiring）看过去：closure 到顶未收敛时不得跳过它直奔 closeout。"""
        self._backlog()
        h = self._hint(wave="wiring")
        self.assertEqual(h["kind"], "escalate")
        self.assertEqual(h["wave"], "closure")

    def test_decide_returns_escalate_not_done(self):
        """收口动作本身必须是 escalate：把 escalate 塞进 done.next 等于让主会话自己决定要不要停。"""
        self._backlog()
        plan = self.base_plan()
        plan["wave"] = "closure"
        path = self.proj / "spec" / "waves" / "plan-closure.json"
        self.write_plan(plan, path=path)
        self.next_batch(path=path)
        self.write_result("alpha", VALID_ALPHA)
        self.write_result("beta", VALID_BETA)
        self.land(path=path)
        self.assertEqual(self.next_batch(path=path)["action"], "dispatch")
        self.write_result("final", {"task": "domain:final", "final_state": "PASS", "files": ["reports/final.md"]})
        self.land(path=path)
        act = self.next_batch(path=path)
        self.assertEqual((act["action"], act.get("settled")), ("done", True), act)  # E266：不再停机，改记欠账放行
        self.assertTrue(act["wave_complete"])
        self.assertEqual(act["next"]["kind"], "settled")  # E266：不再停机，改记欠账放行


class TestDebtExhaustedLedger(unittest.TestCase):
    """generate_waves._record_debt_exhausted：账面要机械写明「未收敛 / 要升级」，不靠 rule 散文。"""

    def test_ledger_marks_unconverged_and_settles(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "spec" / "blueprint").mkdir(parents=True)
            bp = {"_dir": root / "spec" / "blueprint", "workflow_params": {}}
            led = {"generated_at": "2026-09-21T20:00:00+00:00", "blocked": ["handoffs"],
                   "handoffs": {"alpha": [{"id": "P-1", "trigger": "x"}]}, "backlog": {}, "gaps": {},
                   "unowned": [], "smoke": None, "escalated_ratio": None}
            out = GW._record_debt_exhausted(bp, led, 3, 2, "debt 轮次到顶（已跑 2 轮 / 上限 2）")
            doc = json.loads(Path(out).read_text(encoding="utf-8"))
            self.assertIs(doc["converged"], False)
            # E266（2026-09-23 用户裁决「任何分支都不停机」）：到顶未收敛不再 escalate，改为记账放行；
            # 账要记全——remaining 逐条留住，事后查得到「放了什么」。
            self.assertIs(doc["escalate"], False)
            self.assertEqual(doc["remaining"]["handoffs"]["alpha"], [{"id": "P-1"}])
            self.assertIn("2 轮", doc["rule"])
            adj = W.load_adjudications(root)
            self.assertEqual([e["kind"] for e in adj], ["debt-cap"])
            self.assertIn("记账放行", adj[0]["decision"])


# ── generate_waves 侧：on_fail 口径矩阵 ──────────────────────────────────

class TestWaveNodePolicy(unittest.TestCase):
    """节点 on_fail 是本改动的另一半：next_batch 只处置 failed_esc，on_fail 不升级则连判都判不到。"""

    @staticmethod
    def _by_id(wave, bp):
        return {n["id"]: n for n in GW.wave_reduce_nodes(bp, wave)}

    def setUp(self):
        self.bp = {"_dir": Path("/tmp/does-not-matter/spec/blueprint"), "workflow_params": {}}

    def test_round_two_gates_block(self):
        spec = self._by_id("specfix", self.bp)
        self.assertIs(spec["gate:spec-depth-2"]["on_fail"]["escalate"], True)
        self.assertIs(spec["gate:interface-2"]["on_fail"]["escalate"], True)
        depthfix = self._by_id("depthfix", self.bp)
        self.assertIs(depthfix["gate:depth-2"]["on_fail"]["escalate"], True)

    def test_round_one_gates_stay_report_only(self):
        und = self._by_id("understand", self.bp)
        self.assertIs(und["gate:spec-depth"]["on_fail"]["escalate"], False)
        self.assertIs(und["gate:interface"]["on_fail"]["escalate"], False)
        self.assertIs(und["reduce:harvest-literals"]["on_fail"]["escalate"], True)
        self.assertIs(und["reduce:seed-resources"]["on_fail"]["escalate"], True)

    def test_single_writer_reduces_block(self):
        self.assertIs(GW._resource_sweep_node("domains", ["@x"])["on_fail"]["escalate"], True)
        self.assertIs(GW._contract_fill_node(["@x"])["on_fail"]["escalate"], True)

    def test_product_write_audit_blocks(self):
        nodes = GW._append_product_write_audit(
            [{"id": "reduce:build-domains", "kind": "reduce", "run": "x", "parents": ["@domains-impl"]}], "domains")
        self.assertIs(nodes[-1]["on_fail"]["escalate"], True)

    def test_wires_check_strict_only_in_closing_waves(self):
        """--strict 与 on_fail 必须同进同退：不带 --strict 的 verify_wires 恒 exit 0，escalate 会是死字段。"""
        for wave, strict in (("domains", False), ("infra", False), ("auditfix", False),
                             ("wiring", True), ("closure", True), (GW.DEBT_WAVE, True)):
            with self.subTest(wave=wave):
                nodes = GW._insert_wires_check(
                    [{"id": "reduce:build-%s" % wave, "kind": "reduce", "run": "x", "parents": []}], wave)
                node = nodes[-1]
                self.assertEqual(node["id"], "reduce:wires-check")
                self.assertEqual("--strict" in node["run"], strict)
                self.assertIs(node["on_fail"]["escalate"], strict)


# ── ③ 质量返工在收敛时的额外配额（跨文件接口：land_results 写账、next_batch 算配额）────

class TestQualityReworkQuota(KernelFixture):
    """land_results 侧（并行任务）判退时写 journal 行的 quality_rework{progressed}/selfcheck_left；
    重试配额在 next_batch 算——不接上的话第二次判退必然 escalate，多轮补漏根本开不了。"""

    def _journal(self) -> dict:
        p = self.state.parent / "journal.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"version": 1, "operation_outputs": []}

    def _land_row(self, tid: str, attempt: int, *, status="FAIL", rework=None, left=None) -> None:
        """补一条 land_results 形态的 agent 落账行（含 E265③ 的两个新字段）。"""
        p = self.state.parent / "journal.json"
        j = self._journal()
        j.setdefault("operation_outputs", [])
        row = {"workflow_id": "domains", "resume_key": "domains:" + tid, "task_id": tid,
               "kind": "agent", "attempt": attempt, "status": status, "error": "ui_form P1 未清零"}
        if left is not None:
            row["selfcheck_left"] = {"ui_form": left}
        if rework is not None:
            row["quality_rework"] = {"task": tid, "check": "ui_form", "left": rework.get("left"),
                                     "prev_left": rework.get("prev_left"), "progressed": rework["progressed"],
                                     "attempts": attempt, "infra_waived": 0}
        j["operation_outputs"].append(row)
        self._write(p, json.dumps(j, ensure_ascii=False))

    def _fail_state(self, *tids: str) -> None:
        state = json.loads(self.state.read_text(encoding="utf-8"))
        for t in state["waves"]["domains"]["tasks"]:
            if t["id"] in tids:
                t["status"] = "failed"
        self._write(self.state, json.dumps(state, ensure_ascii=False))

    def _dispatched_once(self) -> None:
        """派发 alpha/beta（beta 正常完成，alpha 走返工线）。"""
        plan = self.base_plan()
        plan["tasks"] = [t for t in plan["tasks"] if t["id"] in ("impl:alpha", "impl:beta")]
        self.write_plan(plan)
        self.next_batch()
        self.write_result("beta", VALID_BETA)
        self.write_result("alpha", VALID_ALPHA)
        self.land()

    def _rebuild(self, attempt: int, **rework_kw) -> dict:
        """把 alpha 置为第 attempt 次判退（journal 行 + state failed + dispatch 计数），返回拍①动作。"""
        self._land_row("impl:alpha", attempt, **rework_kw)
        self._fail_state("impl:alpha")
        d = json.loads((self.state.parent / "dispatch.json").read_text(encoding="utf-8"))
        d["waves"]["domains"]["dispatched"]["impl:alpha"]["attempts"] = attempt
        self._write(self.state.parent / "dispatch.json", json.dumps(d, ensure_ascii=False))
        return self.next_batch()

    def test_progress_buys_one_more_rework_round(self):
        """配额用尽（attempts=2）但违规条数在降 → 再放一轮补漏，而不是 escalate。"""
        self._dispatched_once()
        act = self._rebuild(2, left=3, rework={"progressed": True, "left": 3, "prev_left": 9})
        self.assertEqual(act["action"], "dispatch", act)
        self.assertEqual([b["id"] for b in act["batch"]], ["impl:alpha"])
        self.assertTrue(act["retry"])
        self.assertIn("质量返工补漏轮", act["reason"])
        self.assertEqual(act["quality_rework"]["impl:alpha"][-1]["left"], 3)

    def test_zero_progress_twice_escalates_with_curve(self):
        """连续两轮零进展 → 不再放，升级材料带 selfcheck_left 下降曲线。"""
        self._dispatched_once()
        self.assertEqual(self._rebuild(2, left=9, rework={"progressed": False, "left": 9, "prev_left": 9})["action"],
                         "dispatch")                      # 第一轮零进展仍给一次（补漏任务书还在）
        act = self._rebuild(3, left=9, rework={"progressed": False, "left": 9, "prev_left": 9})
        self.assertEqual((act["action"], act.get("settled")), ("done", True), act)
        self.assertEqual(act["exhausted"], ["impl:alpha"])
        self.assertEqual([x["left"] for x in act["quality_rework"]["impl:alpha"]], [9, 9])
        self.assertIn("连续 2 轮零进展", act["hint"])

    def test_extra_rounds_are_capped(self):
        """一直有进展也不能无限放：额外配额封顶 MAX_REWORK_EXTRA（总派发 = 2 + 3）。"""
        self._dispatched_once()
        for n, (prev, left) in enumerate([(9, 7), (7, 5), (5, 4), (4, 3)], start=2):
            act = self._rebuild(n, left=left, rework={"progressed": True, "left": left, "prev_left": prev})
            if n < NB.MAX_ATTEMPTS + NB.MAX_REWORK_EXTRA:
                self.assertEqual(act["action"], "dispatch", (n, act))
            else:
                self.assertEqual((act["action"], act.get("settled")), ("done", True), (n, act))
                self.assertEqual(act["exhausted"], ["impl:alpha"])
                self.assertIn("尚在收敛但轮次用尽", act["hint"])

    def test_infra_fail_waiver_untouched(self):
        """INFRA_FAIL 是平台事故不是质量问题：豁免口径不受本改动影响，也不靠 quality_rework。"""
        self._dispatched_once()
        self._land_row("impl:alpha", 2, status="INFRA_FAIL")
        state = json.loads(self.state.read_text(encoding="utf-8"))
        for t in state["waves"]["domains"]["tasks"]:
            if t["id"] == "impl:alpha":
                t["status"] = "pending"
        self._write(self.state, json.dumps(state, ensure_ascii=False))
        d = json.loads((self.state.parent / "dispatch.json").read_text(encoding="utf-8"))
        d["waves"]["domains"]["dispatched"]["impl:alpha"]["attempts"] = 2
        self._write(self.state.parent / "dispatch.json", json.dumps(d, ensure_ascii=False))
        j = self._journal()
        self.assertEqual(NB._rework_credit(j, "domains", "impl:alpha"), 0)   # INFRA_FAIL 行不带 quality_rework
        act = self.next_batch()
        self.assertEqual(act["action"], "dispatch", act)                     # K7 豁免照旧续派
        self.assertNotIn("quality_rework", act)

    def test_credit_helpers(self):
        j = {"operation_outputs": [
            {"workflow_id": "domains", "task_id": "impl:alpha", "kind": "agent", "attempt": 2,
             "quality_rework": {"progressed": True, "left": 3, "prev_left": 9, "check": "ui_form"}},
            {"workflow_id": "domains", "task_id": "impl:alpha", "kind": "agent", "attempt": 3,
             "quality_rework": {"progressed": False, "left": 3, "prev_left": 3, "check": "ui_form"}},
        ]}
        self.assertEqual(NB._rework_credit(j, "domains", "impl:alpha"), 2)    # 末轮零进展但前一轮有进展 → 还给
        j["operation_outputs"].append(dict(j["operation_outputs"][1], attempt=4))
        self.assertEqual(NB._rework_credit(j, "domains", "impl:alpha"), 0)    # 连续两轮零进展 → 不给
        self.assertEqual(NB._rework_credit(j, "domains", "impl:beta"), 0)     # 无返工行 → 0
        self.assertEqual([x["attempt"] for x in NB._rework_curve(j, "domains", "impl:alpha")], [2, 3, 4])


if __name__ == "__main__":
    unittest.main()
