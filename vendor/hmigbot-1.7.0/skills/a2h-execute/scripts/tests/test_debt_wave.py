#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E207 debt 条件波（AIPPT_930 2026-09-17 15:38 实证：closeout 交棒硬门五类 BLOCKED，主会话宣告 done 停机，用户说
「继续跑完欠账」才临场拼出 wiring r2 / infra r2 / grill_autodecide / 重跑冒烟——本波把那次即兴还债固化为机械有界条件波）。

覆盖：
  · generate_waves --wave debt：handoff-check.json BLOCKED → 按 owner 出任务（wiring 形态 id / 回执名 / domainImpl）、
    白名单 = owner 白名单 + 欠账条目指名文件（不收别的 owner 的文件）、reduce 链（grill-autodecide / merge-gaps / build /
    compile-4 / backlog-settle / handoffs / smoke-1page / report / handoff-check）、lint_plan 通过；
  · 任务书含「欠账清单」段（forward-ref / HANDOFF marker / BK / 决策缺口），assemble_prompt --wave debt --task <owner>；
  · 轮次封顶（gates.debt_max_rounds 缺省 2）：到顶 → 不出任务 + spec/reports/debt-exhausted.json + auto-adjudications debt-cap；
  · 第二轮 reduce id 带 :r2（纯 reduce 轮的 E55 隔离）；纯 reduce 计划（只剩 decision-gaps / smoke）；
  · next_batch：closeout done + BLOCKED → next=wave debt；PASS → skill 交棒；debt done 到顶 → skill 交棒附 debt 摘要。

用法示例:
    python3 -m unittest discover -s codex/skills/a2h-execute/scripts/tests -p test_debt_wave.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from test_generate_plan import PlanFixture, SCRIPTS
from test_scheduler_kernel import KernelFixture, VALID_ALPHA, VALID_BETA

sys.path.insert(0, str(SCRIPTS))
import _wavelib as W  # noqa: E402
import next_batch as NB  # noqa: E402

ASSEMBLE = SCRIPTS / "assemble_prompt.py"


def _blocked_check(blocked: list, ok: bool = False) -> dict:
    checks = [{"id": c, "status": "blocked" if c in blocked else "ok", "detail": "fixture %s" % c}
              for c in ("sign-config", "build-graph", "handoffs", "fix-backlog", "escalated-ratio",
                        "decision-gaps", "smoke-1page", "report", "state-accounts")]
    return {"ok": ok, "generated_at": "2026-09-17T15:38:00+00:00", "checks": checks,
            "blocked": [] if ok else list(blocked), "facts": {}}


class DebtFixture(PlanFixture):
    """PlanFixture（alpha / beta 两域 + infra:core）+ 五类欠账产物。"""

    LEDGER = {"total": 1, "met": 0,
              "unmet": [{"file": "features/beta/Bridge.ets", "line": 7, "owner": "beta",
                         "what": "接支付桥", "verify": "grep:PayBridge\\.deliver", "reason": "全工程 .ets 无匹配"}],
              "dangling_fwd_ref": [
                  {"id": "P-DOM-AL-001", "kind": "forward-ref", "status": "registered", "resolve_by": "wiring",
                   "location": "features/alpha/Home.ets#HomeBridge"},
                  {"id": "P-DOM-XX-009", "kind": "forward-ref-uncertain", "status": "registered", "resolve_by": "wiring",
                   "location": "nowhere/Orphan.ets#x"}],
              "resolved_updated": 0, "trigger_met": 0,
              "trigger_unmet": [{"id": "P-DOM-AL-001", "why": "全工程无非 marker 命中",
                                 "trigger": {"type": "symbol-implemented", "arg": "common/Seed.ets#seedHome"}}],
              "trigger_nocheck": [], "strict": True}
    DEFERRED = [
        {"id": "P-DOM-AL-001", "kind": "forward-ref", "status": "registered", "owner_domain": "alpha", "resolve_by": "wiring",
         "location": {"file": "features/alpha/Home.ets", "anchor": "HomeBridge"},
         "trigger": {"type": "symbol-implemented", "arg": "common/Seed.ets#seedHome"}, "note": "等 seed 暴露 seedHome"},
        {"id": "P-DOM-XX-009", "kind": "forward-ref-uncertain", "status": "registered", "resolve_by": "wiring",
         "location": {"file": "nowhere/Orphan.ets", "anchor": "x"}, "trigger": {"type": "grep", "arg": "never"}}]
    BACKLOG = {"version": 1, "open": 1, "by_owner": {"alpha": ["BK-3"]}, "items": [
        {"id": "BK-3", "from": "beta", "required_owner": "alpha", "severity": "P1",
         "file": "features/alpha/A.ets", "summary": "事件桥空桩", "fix": "接 EventHub", "finding_ref": 2, "source": "fix-skipped"}]}
    GAPS = {"version": 1, "total": 1, "blocking": 1, "waived": False,
            "gaps": [{"g_id": "G-ALPHA-1", "category": "C8", "blocking": True, "domain": "alpha", "task": "wiring:alpha"}]}
    SMOKE = {"ok": False, "error": "EVIDENCE_LOST", "detail": "hilog 采集失败"}

    def seed_debt(self, blocked=("handoffs", "fix-backlog", "escalated-ratio", "decision-gaps", "smoke-1page"),
                  ok: bool = False) -> None:
        self._write(self.proj / "spec/reports/handoff-check.json", json.dumps(_blocked_check(list(blocked), ok)))
        self._write(self.proj / "spec/reports/handoff-ledger.json", json.dumps(self.LEDGER))
        self._write(self.proj / "spec/reports/fix-backlog.json", json.dumps(self.BACKLOG))
        self._write(self.blueprint / "wiring-backlog.json", json.dumps(self.BACKLOG))
        self._write(self.proj / "spec/reports/decision-gaps.json", json.dumps(self.GAPS))
        self._write(self.proj / "spec/reports/smoke/one-page.json", json.dumps(self.SMOKE))
        contracts = json.loads((self.blueprint / "contracts.json").read_text(encoding="utf-8"))
        contracts["deferred"] = self.DEFERRED
        self._write(self.blueprint / "contracts.json", json.dumps(contracts))

    def set_gates(self, **gates) -> None:
        wp = json.loads((self.blueprint / "workflow-params.json").read_text(encoding="utf-8"))
        wp.setdefault("gates", {}).update(gates)
        self._write(self.blueprint / "workflow-params.json", json.dumps(wp))

    def journal_rows(self, rows: list) -> None:
        self._write(self.proj / "spec/state/journal.json",
                    json.dumps({"version": 1, "workflow_status": [], "operation_outputs": rows}))


class TestDebtPlanShape(DebtFixture):

    def test_blocked_five_categories_generate_tasks_and_reduces(self) -> None:
        self.seed_debt()
        proc = self.gen("debt")
        self.assertIn("无法归属任何 owner", proc.stderr)          # P-DOM-XX-009 无主：只警告不派
        plan = self.plan("debt")
        by_id = {t["id"]: t for t in plan["tasks"]}
        agents = sorted(t["id"] for t in plan["tasks"] if t["kind"] == "agent")
        self.assertEqual(agents, ["wiring:alpha", "wiring:beta"])   # wiring 形态 id（回执 schema / backlog_settle 零改动）
        a, b = by_id["wiring:alpha"], by_id["wiring:beta"]
        self.assertEqual(a["schema"], "domainImpl")
        self.assertEqual(a["map_group"], "debt-impl")
        self.assertEqual(a["fork_turns"], "all")
        self.assertEqual(a["resume_key"], "debt:wiring:alpha")
        self.assertEqual(a["result_path"], "spec/waves/results/debt/wiring-alpha.json")
        self.assertEqual(a["prompt_file"], "spec/waves/prompts/debt/wiring-alpha.txt")
        # 白名单 = owner 白名单 + 欠账指名文件（common/Seed.ets 归 infra:core 持有 → 不收；features/alpha/Home.ets 已在 glob 内）
        self.assertEqual(a["ownership"], ["features/alpha/**"])
        self.assertEqual(b["ownership"], ["features/beta/**"])
        # reduce 链：wiring 波尾 + closeout 收尾 + 两个按类别挂的节点
        self.assertEqual(by_id["reduce:pagemap"]["parents"], ["@debt-impl"])
        self.assertIn("--merge-deferred-dir spec/waves/results/debt", by_id["reduce:merge-deferred"]["run"])
        self.assertEqual(by_id["reduce:grill-autodecide"]["parents"], ["@start"])
        self.assertIn("grill_autodecide.py --project . --apply --default-first --normalize-ids --json",
                      by_id["reduce:grill-autodecide"]["run"])
        self.assertFalse(by_id["reduce:grill-autodecide"]["on_fail"]["escalate"])
        self.assertEqual(sorted(by_id["reduce:merge-gaps"]["parents"]), ["@debt-impl", "reduce:grill-autodecide"])
        self.assertIn("--results-dir spec/waves/results/debt", by_id["reduce:merge-gaps"]["run"])
        self.assertEqual(by_id["reduce:build-debt"]["parents"], ["reduce:probe"])          # E37 探针（写产物的波）
        self.assertIn("--detach-probe", by_id["reduce:build-debt"]["run"])
        self.assertEqual(sorted(by_id["reduce:probe"]["parents"]),
                         ["gate:fence-audit", "reduce:merge-deferred", "reduce:pagemap", "reduce:resource-sweep"])
        self.assertEqual(by_id["gate:compile-4"]["parents"], ["reduce:build-debt"])
        self.assertIn("--gate compile#4 --build-log spec/reports/build-debt.log", by_id["gate:compile-4"]["run"])
        self.assertEqual(by_id["reduce:backlog-settle"]["parents"], ["gate:compile-4"])
        self.assertIn("--results-dir spec/waves/results/debt", by_id["reduce:backlog-settle"]["run"])
        self.assertEqual(by_id["gate:handoffs"]["parents"], ["gate:compile-4"])
        self.assertIn("verify_handoffs.py", by_id["gate:handoffs"]["run"])
        self.assertEqual(by_id["gate:smoke-1page"]["parents"], ["gate:compile-4"])
        self.assertIn("smoke_one_page.py", by_id["gate:smoke-1page"]["run"])
        self.assertEqual(by_id["reduce:report"]["parents"],
                         ["gate:handoffs", "gate:smoke-1page", "reduce:backlog-settle", "reduce:merge-gaps"])
        self.assertEqual(by_id["gate:handoff-check"]["parents"], ["reduce:report"])
        self.assertIn("handoff_check.py", by_id["gate:handoff-check"]["run"])
        self.assertIn("reduce:product-write-audit", by_id)                                  # E24
        self.assertIn("reduce:wires-check", by_id)                                          # I5
        self.assertNotIn("gate:escalated-ratio", by_id)                                     # 只报不派
        self.assertTrue(self.lint("debt")["ok"])
        self.assertFalse((self.proj / "spec/reports/debt-exhausted.json").exists())

    def test_brief_contains_debt_ledger_section(self) -> None:
        self.seed_debt()
        self.gen("debt")
        by_id = {t["id"]: t for t in self.plan("debt")["tasks"]}
        prompt = (self.proj / by_id["wiring:alpha"]["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("## 你的任务（wave=debt，owner=alpha）", prompt)
        self.assertIn("### 欠账清单（本任务必须逐条兑现或按占位分类法改判）", prompt)
        self.assertIn("**P-DOM-AL-001**（forward-ref，status=registered，resolve_by=wiring）", prompt)
        self.assertIn("触发器：symbol-implemented: common/Seed.ets#seedHome", prompt)
        self.assertIn("未兑现原因（verify_handoffs）：全工程无非 marker 命中", prompt)
        self.assertIn("等 seed 暴露 seedHome", prompt)
        self.assertIn("BK-3", prompt)                                    # fix-backlog 条目沿 wiring 格式
        self.assertIn("接 EventHub", prompt)
        self.assertIn("决策缺口 G-ALPHA-1", prompt)
        self.assertIn("resolved_refs[]", prompt)                          # wiring 回执纪律原样
        self.assertIn("白名单（越界需求 → skipped 附 required_owner，禁越界写）", prompt)
        self.assertNotIn("HANDOFF features/beta/Bridge.ets:7", prompt)   # beta 的 marker 不进 alpha 任务书
        beta = (self.proj / by_id["wiring:beta"]["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("**HANDOFF features/beta/Bridge.ets:7**（owner=beta）what=接支付桥", beta)
        self.assertNotIn("P-DOM-AL-001", beta)
        # CLI 直组：--wave debt --task <owner>
        env = dict(os.environ); env["ARKTS_SKILL_DIR"] = str(SCRIPTS.parent)
        proc = subprocess.run([sys.executable, str(ASSEMBLE), "--blueprint", "spec/blueprint", "--wave", "debt",
                               "--task", "alpha", "--json"], capture_output=True, text=True, encoding="utf-8",
                              cwd=str(self.proj), env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out["ok"]); self.assertIn("### 欠账清单", out["prompt"])
        proc = subprocess.run([sys.executable, str(ASSEMBLE), "--blueprint", "spec/blueprint", "--wave", "debt",
                               "--task", "gamma"], capture_output=True, text=True, encoding="utf-8",
                              cwd=str(self.proj), env=env, timeout=120)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("无 owner=gamma", proc.stderr)

    def test_deferred_location_extends_ownership_when_unowned(self) -> None:
        """欠账指名的文件无人持有 → 并入该 owner 白名单；别的 owner 持有 → 不收（lint R3）。"""
        self.seed_debt()
        ledger = json.loads(json.dumps(self.LEDGER))
        ledger["dangling_fwd_ref"][0]["location"] = "shared/Glue.ets#HomeBridge"
        self._write(self.proj / "spec/reports/handoff-check.json", json.dumps(_blocked_check(["handoffs"])))
        self._write(self.proj / "spec/reports/handoff-ledger.json", json.dumps(ledger))
        contracts = json.loads((self.blueprint / "contracts.json").read_text(encoding="utf-8"))
        contracts["deferred"][0]["location"] = {"file": "shared/Glue.ets", "anchor": "HomeBridge"}
        self._write(self.blueprint / "contracts.json", json.dumps(contracts))
        self.gen("debt")
        by_id = {t["id"]: t for t in self.plan("debt")["tasks"]}
        self.assertEqual(by_id["wiring:alpha"]["ownership"], ["features/alpha/**", "shared/Glue.ets"])
        self.assertTrue(self.lint("debt")["ok"])

    def test_pass_or_missing_handoff_check_is_expected_empty(self) -> None:
        proc = self.gen("debt")
        self.assertIn("handoff-check.json 缺失", proc.stderr)
        self.assertIn("条件波，属预期", proc.stderr)
        self.assertFalse((self.proj / "spec/waves/plan-debt.json").exists())
        self.seed_debt(ok=True)
        proc = self.gen("debt")
        self.assertIn("判 PASS", proc.stderr)
        self.assertFalse((self.proj / "spec/waves/plan-debt.json").exists())

    def test_report_only_category_generates_nothing(self) -> None:
        self.seed_debt(blocked=("escalated-ratio",))
        proc = self.gen("debt")
        self.assertIn("只报不派", proc.stderr)
        self.assertFalse((self.proj / "spec/waves/plan-debt.json").exists())
        ex = json.loads((self.proj / "spec/reports/debt-exhausted.json").read_text(encoding="utf-8"))
        self.assertEqual(ex["blocked"], ["escalated-ratio"])
        self.assertEqual(ex["handoff_check_generated_at"], "2026-09-17T15:38:00+00:00")

    def test_reduce_only_plan_when_only_gaps_and_smoke_blocked(self) -> None:
        self.seed_debt(blocked=("decision-gaps", "smoke-1page"))
        self.gen("debt")
        plan = self.plan("debt")
        self.assertEqual([t for t in plan["tasks"] if t["kind"] == "agent"], [])
        by_id = {t["id"]: t for t in plan["tasks"]}
        self.assertEqual(by_id["reduce:build-debt"]["parents"], ["reduce:probe"])
        self.assertEqual(by_id["reduce:probe"]["parents"], ["@start"])
        self.assertEqual(by_id["reduce:merge-gaps"]["parents"], ["reduce:grill-autodecide"])
        self.assertIn("gate:smoke-1page", by_id)
        self.assertNotIn("reduce:backlog-settle", by_id)
        self.assertNotIn("reduce:pagemap", by_id)
        self.assertEqual(by_id["reduce:report"]["parents"], ["gate:handoffs", "gate:smoke-1page", "reduce:merge-gaps"])
        self.assertTrue(self.lint("debt")["ok"])

    def test_second_round_tags_agents_and_reduces(self) -> None:
        """第二轮：agent id wiring:r2:<owner>、回执名 wiring-r2-<owner>、reduce id 尾部 :r2（E55 轮次隔离）。"""
        self.seed_debt()
        self.journal_rows([{"workflow_id": "debt", "task_id": "wiring:alpha", "kind": "agent", "attempt": 1, "status": "OK"},
                           {"workflow_id": "debt", "task_id": "gate:handoff-check", "kind": "reduce", "attempt": 1, "status": "REDUCE_FAIL"}])
        self.gen("debt")
        plan = self.plan("debt")
        by_id = {t["id"]: t for t in plan["tasks"]}
        self.assertIn("wiring:r2:alpha", by_id)
        self.assertEqual(by_id["wiring:r2:alpha"]["result_path"], "spec/waves/results/debt/wiring-r2-alpha.json")
        self.assertIn("reduce:build-debt:r2", by_id)
        self.assertEqual(by_id["gate:compile-4:r2"]["parents"], ["reduce:build-debt:r2"])
        self.assertEqual(by_id["gate:handoff-check:r2"]["parents"], ["reduce:report:r2"])
        self.assertTrue(all(t["id"].endswith(":r2") for t in plan["tasks"] if t["kind"] == "reduce"))
        self.assertEqual(W.plan_run_tag(plan), "r2")
        self.assertTrue(self.lint("debt")["ok"])
        # 纯 reduce 第一轮落账后（无 agent 行）也计一轮
        self.journal_rows([{"workflow_id": "debt", "task_id": "gate:handoff-check", "kind": "reduce", "attempt": 1, "status": "REDUCE_FAIL"}])
        self.assertEqual(W.debt_round(self.proj / "spec/state/journal.json"), 2)
        self.journal_rows([{"workflow_id": "debt", "task_id": "gate:handoff-check:r2", "kind": "reduce", "attempt": 1, "status": "REDUCE_FAIL"}])
        self.assertEqual(W.debt_round(self.proj / "spec/state/journal.json"), 3)

    def test_round_cap_reached_writes_exhausted_ledger(self) -> None:
        self.seed_debt()
        self.journal_rows([{"workflow_id": "debt", "task_id": "wiring:r2:alpha", "kind": "agent", "attempt": 1, "status": "OK"}])
        proc = self.gen("debt")
        self.assertIn("已到轮次上限", proc.stderr)
        self.assertFalse((self.proj / "spec/waves/plan-debt.json").exists())
        ex = json.loads((self.proj / "spec/reports/debt-exhausted.json").read_text(encoding="utf-8"))
        self.assertEqual((ex["rounds_run"], ex["cap"]), (2, 2))
        self.assertEqual(sorted(ex["remaining"]["handoffs"]), ["alpha", "beta"])
        self.assertEqual([it["id"] for it in ex["remaining"]["handoffs"]["alpha"]], ["P-DOM-AL-001"])
        self.assertEqual(ex["remaining"]["fix_backlog"], {"alpha": ["BK-3"]})
        self.assertEqual(ex["remaining"]["decision_gaps"], ["G-ALPHA-1"])
        self.assertEqual(ex["remaining"]["smoke"]["error"], "EVIDENCE_LOST")
        self.assertEqual([u["id"] for u in ex["remaining"]["unowned"]], ["P-DOM-XX-009"])
        adj = W.load_adjudications(self.proj)
        self.assertEqual([e["kind"] for e in adj], ["debt-cap"])
        self.gen("debt")                                                 # 幂等：同一份判决不重复留痕
        self.assertEqual(len(W.load_adjudications(self.proj)), 1)
        # 上限可调：gates.debt_max_rounds=3 → 第三轮照派
        self.set_gates(debt_max_rounds=3)
        self.gen("debt")
        self.assertIn("wiring:r3:alpha", {t["id"] for t in self.plan("debt")["tasks"]})
        # 0 = 关闭：首轮也不派
        self.set_gates(debt_max_rounds=0)
        self.journal_rows([])
        (self.proj / "spec/waves/plan-debt.json").unlink()
        proc = self.gen("debt")
        self.assertIn("已到轮次上限", proc.stderr)
        self.assertFalse((self.proj / "spec/waves/plan-debt.json").exists())
        self.assertTrue(W.debt_state(self.proj)["exhausted"])


class TestDebtNextHint(KernelFixture):
    """closeout done → BLOCKED 出 debt；PASS → skill；debt 到顶/无可派仍 BLOCKED → escalate（E265⑤，原为 skill 附摘要）。"""

    def _run_wave_to_done(self, wave: str, expect: str = "done") -> dict:
        plan = self.base_plan(); plan["wave"] = wave
        path = self.proj / "spec" / "waves" / ("plan-%s.json" % wave)
        self.write_plan(plan, path=path)
        self.next_batch(path=path)
        self.write_result("alpha", VALID_ALPHA); self.write_result("beta", VALID_BETA)
        self.land(path=path)
        act = self.next_batch(path=path)
        self.assertEqual(act["action"], "dispatch")
        self.write_result("final", {"task": "domain:final", "final_state": "PASS", "files": ["reports/final.md"]})
        self.land(path=path)
        act = self.next_batch(path=path)
        self.assertEqual(act["action"], expect, act)
        return act

    def _handoff(self, blocked, ok=False) -> None:
        self._write(self.proj / "spec/reports/handoff-check.json", json.dumps(_blocked_check(list(blocked), ok)))

    def test_closeout_done_blocked_points_to_debt(self) -> None:
        self._handoff(["handoffs", "fix-backlog", "escalated-ratio", "decision-gaps", "smoke-1page"])
        act = self._run_wave_to_done("closeout")
        nxt = act["next"]
        self.assertEqual((nxt["kind"], nxt["wave"]), ("wave", "debt"))
        self.assertFalse(nxt["exists"])
        self.assertEqual(nxt["plan"], "spec/waves/plan-debt.json")
        self.assertIn("--wave debt --json", nxt["generate"])
        self.assertIn("第 1/2 轮", nxt["reason"])
        self.assertNotIn("restart", nxt)


    def test_closeout_done_pass_hands_off(self) -> None:
        self._handoff([], ok=True)
        act = self._run_wave_to_done("closeout")
        self.assertEqual((act["next"]["kind"], act["next"]["skill"]), ("skill", "a2h-verify"))
        self.assertNotIn("debt", act["next"])

    def test_closeout_done_report_only_settles(self) -> None:
        """E265⑤：BLOCKED 只剩「只报不派」的类别时，原实现直接交棒 a2h-verify（附一段 debt 摘要）——
        没有可机械补账的路 ≠ 欠账已清，那正是「带欠账收尾」。现在必须停机呈报等用户裁决。"""
        self._handoff(["escalated-ratio"])
        act = self._run_wave_to_done("closeout", expect="done")   # E266：不再停机，改记欠账放行
        self.assertTrue(act["wave_complete"])
        self.assertEqual(act["next"]["kind"], "settled")  # E266：不再停机，改记欠账放行
        self.assertEqual(act["next"]["debt"]["blocked"], ["escalated-ratio"])
        self.assertIn("只报不派", act["next"]["reason"])   # E266：原因随材料留在 next 里，动作是 done
        self.assertEqual(act["next"]["handoff"]["skill"], "a2h-verify")   # 裁决通过后才走的那条交棒路径仍在材料里

    def test_debt_done_blocked_reenters_until_cap(self) -> None:
        self._handoff(["fix-backlog"])
        act = self._run_wave_to_done("debt")                             # journal 现有 debt 第 1 轮（impl:* 行按无后缀计 1）
        self.assertEqual((act["next"]["kind"], act["next"]["wave"]), ("wave", "debt"))
        self.assertIn("第 2/2 轮", act["next"]["reason"])
        # E265⑤：轮次到顶而 handoff-check 仍 BLOCKED → 升级呈报（原为交棒 a2h-verify 并附 debt 摘要）
        jp = self.proj / "spec/state/journal.json"
        j = json.loads(jp.read_text(encoding="utf-8"))
        j["operation_outputs"].append({"workflow_id": "debt", "task_id": "wiring:r2:alpha", "kind": "agent", "attempt": 1, "status": "OK"})
        jp.write_text(json.dumps(j), encoding="utf-8")
        hint = NB._next_hint({"wave": "debt"}, self.proj / "spec/waves/plan-debt.json", self.proj)
        self.assertEqual(hint["kind"], "escalate")
        self.assertIs(hint["converged"], False)
        self.assertEqual(hint["debt"]["exhausted"], True)
        self.assertEqual((hint["debt"]["rounds_run"], hint["debt"]["cap"]), (2, 2))
        self.assertIn("已用尽", hint["reason"])

    def test_attended_handoff_check_red_escalate_carries_debt_next(self) -> None:
        """有人值守：closeout 的 gate:handoff-check 红 → escalate 材料附 next=wave debt（不靠人临场拼还债步骤）。"""
        self._handoff(["handoffs", "smoke-1page"])
        plan = self.base_plan(); plan["wave"] = "closeout"
        gate = next(t for t in plan["tasks"] if t["id"] == "gate:compile")
        gate["id"] = "gate:handoff-check"; gate["on_fail"] = {"escalate": True}
        plan["tasks"] = [t for t in plan["tasks"] if t["id"] != "impl:final"]
        path = self.proj / "spec/waves/plan-closeout.json"
        self.write_plan(plan, path=path)
        self._write(self.gate_rc, "1")
        self.next_batch(path=path)
        self.write_result("alpha", VALID_ALPHA); self.write_result("beta", VALID_BETA)
        self.land(expect=2, path=path)
        act = self.next_batch(path=path)
        self.assertEqual((act["action"], act.get("settled")), ("done", True))  # E266：不再停机，改记欠账放行
        self.assertEqual(act["failed_gates"], ["gate:handoff-check"])
        self.assertEqual((act["next"]["kind"], act["next"]["wave"]), ("wave", "debt"))
        self.assertIn("debt 条件波", act["hint"])

    def test_exhausted_ledger_for_same_verdict_stops_reentry(self) -> None:
        self._handoff(["handoffs"])
        self._write(self.proj / "spec/reports/debt-exhausted.json", json.dumps(
            {"wave": "debt", "handoff_check_generated_at": "2026-09-17T15:38:00+00:00"}))
        self.assertIsNone(NB._debt_hint(self.proj / "spec/waves/plan-closeout.json", self.proj))
        self._write(self.proj / "spec/reports/handoff-check.json", json.dumps(
            dict(_blocked_check(["handoffs"]), generated_at="2026-09-18T00:00:00+00:00")))
        self.assertEqual(NB._debt_hint(self.proj / "spec/waves/plan-closeout.json", self.proj)["wave"], "debt")


if __name__ == "__main__":
    unittest.main()
