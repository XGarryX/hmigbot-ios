#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E266②⑧（2026-09-23）：把「查出来的不达标」真正接进返工通道，堵掉「模型替自己签字放过」的缺口。

背景（AIPPT_930_ds 2026-09-21 实证）：
  · closure-backlog.json 停在 round:5 / converged:false / "152 findings remain"——152 条全在 unowned[]，
    老路径记一笔 auto-adjudications closure-unowned-defer 就跳过整个 closure 波，一条没修；
  · findings-gate.json 里 119 条 P1、wires-check 的 shared_holders 未接通——交棒面判 blocked 只等于停机呈报，
    debt 波压根不认这两类，扇不出任何修复任务。

覆盖：
  ②  closure unowned 逐条按 ownership 写权白名单机械归属 → 写回 backlog（任务书才摘得到材料）→ 按 owner 扇出；
      归不了属 / 同一条目已真派满 2 轮 → 记欠账放行（closure-unowned.json#settled + auto-adjudications），不停机；
  ⑧  debt 波为 findings / shared-holders 扇出修复任务，材料逐条摘进任务书（含 multi-definition 派给多出那份所在域、
      无主条目在任务书里点名要求申报）；两类都没有时 debt 波行为不变。

用法示例:
    python3 -m unittest discover -s codex/skills/a2h-execute/scripts/tests -p test_e266_rework_channel.py -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from test_generate_plan import PlanFixture, SCRIPTS
from test_debt_wave import DebtFixture, _blocked_check

sys.path.insert(0, str(SCRIPTS))
import _wavelib as W  # noqa: E402


# ── ② closure 无主条目：机械归属后派修 / 归不了才记账放行 ──────────────────────────────

class ClosureUnownedFixture(PlanFixture):

    def backlog(self, items=(), unowned=(), round_n=1, verdict="CONTINUE"):
        doc = {"version": 1, "round": round_n, "max_iter": 8, "verdict": verdict, "reason": "fixture",
               "open": max(len(items) or len(unowned), 1), "converged": False, "exhausted": False,
               "scan_kind": "repair-rescan", "items": list(items), "unowned": list(unowned),
               "class_coverage_items": 0, "brief_ref": "spec/execution/autofix-log/round-latest/x.json",
               "resolution": {}}
        self._write(self.blueprint / "closure-backlog.json", json.dumps(doc))
        return doc

    def read_backlog(self):
        return json.loads((self.blueprint / "closure-backlog.json").read_text(encoding="utf-8"))

    def ledger(self):
        return json.loads((self.proj / "spec/reports/closure-unowned.json").read_text(encoding="utf-8"))

    @staticmethod
    def row(i, file, code="class-unmigrated"):
        return {"id": "CL-%03d" % i, "detector": "class-coverage", "file": file, "anchor": "%s#C%d" % (file, i),
                "severity": "FAIL", "code": code, "layer": "feat", "owner": None,
                "summary": "安卓类 C%d 在鸿蒙产物里没有任何同名声明" % i,
                "suggested_action": "按本域 spec 把 C%d 迁成 ArkTS" % i}


class TestClosureUnownedAttribution(ClosureUnownedFixture):

    def test_unowned_items_are_attributed_and_dispatched(self) -> None:
        """全部 open 都在 unowned[] 时，不再跳过整个 closure 波：按写权白名单归属后照常派修。"""
        self.backlog(unowned=[self.row(1, "features/alpha/A.ets"), self.row(2, "features/beta/B.ets")])
        proc = self.gen("closure")
        plan = self.plan("closure")
        agents = sorted(t["id"] for t in plan["tasks"] if t["kind"] == "agent")
        self.assertEqual(agents, ["closure:r1:alpha", "closure:r1:beta"], proc.stderr)
        self.assertIn("机械归属 2 条", proc.stderr)
        # 归属写回 backlog——任务书按 items[].owner 摘材料，不写回等于派出去的代理拿空清单
        back = self.read_backlog()
        self.assertEqual(back["unowned"], [])
        self.assertEqual(sorted(it["owner"] for it in back["items"]), ["alpha", "beta"])
        self.assertTrue(all(it["owner_source"].startswith("generate_waves") for it in back["items"]))
        self.assertEqual(back["open"], 2)
        # 任务书拿到逐条材料（文件 / 处方），不是「你这个域有问题」
        by_id = {t["id"]: t for t in plan["tasks"]}
        prompt = (self.proj / by_id["closure:r1:alpha"]["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("CL-001", prompt)
        self.assertIn("features/alpha/A.ets", prompt)
        self.assertIn("按本域 spec 把 C1 迁成 ArkTS", prompt)
        self.assertNotIn("features/beta/B.ets", prompt)
        self.assertTrue(self.lint("closure")["ok"])
        led = self.ledger()
        self.assertEqual([x["owner"] for x in led["attributed"]], ["alpha", "beta"])
        self.assertEqual(led["settled"], [])
        self.assertFalse(led["escalate"])            # 任何分支都不停机

    def test_truly_unattributable_items_are_settled_not_stopped(self) -> None:
        """文件不在任何域写权白名单内 → 记欠账放行（exit 0、无计划），账要记全。"""
        self.backlog(unowned=[self.row(1, "third_party/X.ets")])
        proc = self.gen("closure")                      # exit 0：放行，不是停机
        self.assertFalse((self.proj / "spec/waves/plan-closure.json").exists())
        self.assertIn("归属后仍无可派 owner", proc.stderr)
        led = self.ledger()
        self.assertEqual(led["attributed"], [])
        self.assertEqual([x["file"] for x in led["settled"]], ["third_party/X.ets"])
        self.assertIn("不在任何域的写权白名单内", led["settled"][0]["reason"])
        self.assertEqual(led["settled"][0]["suggested_action"], "按本域 spec 把 C1 迁成 ArkTS")
        self.assertTrue(led["deferred"])
        self.assertFalse(led["escalate"])
        adj = [e for e in W.load_adjudications(self.proj) if e.get("kind") == "closure-unowned-defer"]
        self.assertEqual(len(adj), 1)
        self.assertIn("third_party/X.ets", adj[0]["detail"])

    def test_attribution_stops_after_two_real_repair_rounds(self) -> None:
        """同一条目最多真派 2 轮；第 3 轮仍在 unowned[] → 判「模型修不了」记欠账放行，不再空转。"""
        row = self.row(1, "features/alpha/A.ets")
        for rnd in (1, 2):
            self.backlog(unowned=[dict(row)], round_n=rnd)
            self.gen("closure")
            self.assertIn("closure:r%d:alpha" % rnd, [t["id"] for t in self.plan("closure")["tasks"]])
        self.assertEqual(sorted(self.ledger()["repair_rounds"].values())[0], [1, 2])
        self.backlog(unowned=[dict(row)], round_n=3)
        (self.proj / "spec/waves/plan-closure.json").unlink()   # 轮 1/2 的旧计划，别把它当本轮产物
        proc = self.gen("closure")
        self.assertFalse((self.proj / "spec/waves/plan-closure.json").exists())
        led = self.ledger()
        self.assertEqual([x["file"] for x in led["settled"]], ["features/alpha/A.ets"])
        self.assertIn("真派修 2 轮", led["settled"][0]["reason"])
        self.assertIn("归属后仍无可派 owner", proc.stderr)

    def test_same_round_regenerate_does_not_burn_a_round(self) -> None:
        """同一轮重跑 generate（--resume / 重生成）不重复计轮——轮次按 backlog.round 去重。"""
        self.backlog(unowned=[self.row(1, "features/alpha/A.ets")], round_n=1)
        self.gen("closure")
        self.backlog(unowned=[self.row(1, "features/alpha/A.ets")], round_n=1)
        self.gen("closure")
        self.assertEqual(list(self.ledger()["repair_rounds"].values())[0], [1])

    def test_owned_items_untouched_when_nothing_unowned(self) -> None:
        """没有 unowned[] 时行为完全不变（不写 backlog、不产留痕文件）。"""
        self.backlog(items=[dict(self.row(1, "features/alpha/A.ets"), owner="alpha")])
        before = (self.blueprint / "closure-backlog.json").read_text(encoding="utf-8")
        self.gen("closure")
        self.assertEqual((self.blueprint / "closure-backlog.json").read_text(encoding="utf-8"), before)
        self.assertFalse((self.proj / "spec/reports/closure-unowned.json").exists())
        self.assertEqual([t["id"] for t in self.plan("closure")["tasks"] if t["kind"] == "agent"],
                         ["closure:r1:alpha"])


# ── ⑧ debt 波：findings / shared-holders 的修复任务与逐条材料 ──────────────────────────

FINDING_ALPHA = {"file": "features/alpha/A.ets", "line": 12, "severity": "P1", "kind": "arkts",
                 "check": "arkts-any", "summary": "显式 any 违反 ArkTS strict",
                 "fix": "把 any 换成具体类型或 Object", "domain": "alpha"}
FINDING_BY_DOMAIN = {"file": "", "line": 0, "severity": "P0", "kind": "runtime", "check": "router-missing",
                     "message": "页面未注册路由", "fix": "在 route_map.json5 补条目", "domain": "beta"}
FINDING_ORPHAN = {"file": "third_party/Z.ets", "line": 3, "severity": "P1", "kind": "arkts",
                  "check": "arkts-any", "message": "三方目录里的 any", "fix": "改类型", "domain": "ghost"}

HOLDER_CONSUMER = {"kind": "store", "symbol": "AppState", "holder": "class", "consumer_domain": "beta",
                   "owner_domain": "alpha", "status": "consumer-missing",
                   "definitions": ["features/alpha/AppState.ets"]}
HOLDER_MULTI = {"kind": "store", "symbol": "SharedCfg", "holder": "class", "consumer_domain": "alpha",
                "owner_domain": "alpha", "status": "multi-definition",
                "definitions": ["features/alpha/SharedCfg.ets", "features/beta/SharedCfg.ets"]}
HOLDER_ORPHAN = {"kind": "event", "symbol": "event:ghost", "holder": "event", "consumer_domain": "ghost",
                 "owner_domain": "ghost", "status": "provider-missing", "definitions": []}


class TestDebtQualityRework(DebtFixture):

    def seed_findings(self, rows) -> None:
        self._write(self.proj / "spec/reports/findings-gate.json",
                    json.dumps({"detector": "findings-gate", "mode": "blocking", "passed": False,
                                "counts": {"P0": 0, "P1": len(rows), "P2": 0},
                                "open": list(rows), "open_items": list(rows), "waived": [], "backlog": []}))

    def seed_holders(self, rows) -> None:
        self._write(self.proj / "spec/reports/wires-check-final.json",
                    json.dumps({"wave": "closeout", "rows": [],
                                "symbol_wires": {"by_kind": {}, "unwired": [], "shared_holders": list(rows)}}))

    def prompt_of(self, task_id) -> str:
        by_id = {t["id"]: t for t in self.plan("debt")["tasks"]}
        return (self.proj / by_id[task_id]["prompt_file"]).read_text(encoding="utf-8")

    def test_findings_generate_owner_tasks_with_per_item_material(self) -> None:
        """findings 阻断 → 按 owner 扇出修复任务，任务书逐条带 file:line / 问题 / 修法（E265① 的教训）。"""
        self.seed_debt(blocked=("findings",))
        self.seed_findings([FINDING_ALPHA, FINDING_BY_DOMAIN, FINDING_ORPHAN])
        proc = self.gen("debt")
        agents = sorted(t["id"] for t in self.plan("debt")["tasks"] if t["kind"] == "agent")
        self.assertEqual(agents, ["wiring:alpha", "wiring:beta"], proc.stderr)   # 文件归属 + domain 兜底各一个
        alpha = self.prompt_of("wiring:alpha")
        self.assertIn("### 质量门未销账清单（findings-gate，本 owner 名下 1 条）", alpha)
        self.assertIn("features/alpha/A.ets:12", alpha)
        self.assertIn("显式 any 违反 ArkTS strict", alpha)
        self.assertIn("把 any 换成具体类型或 Object", alpha)
        self.assertIn("白名单（越界需求 → skipped 附 required_owner，禁越界写）", alpha)   # wiring 同款尾段
        self.assertNotIn("页面未注册路由", alpha)                                        # 别人的条目不进来
        beta = self.prompt_of("wiring:beta")
        self.assertIn("页面未注册路由", beta)                                            # 无 file 时按 domain 归属
        # 无主条目在每份任务书里点名 + 要求申报，不静默丢掉
        for p in (alpha, beta):
            self.assertIn("### 无主条目（推不出 owner，本波没人被派修——逐条申报，不许当没看见）", p)
            self.assertIn("third_party/Z.ets", p)
            self.assertIn("required_owner", p)
        self.assertIn("推不出 owner", proc.stderr)
        self.assertTrue(self.lint("debt")["ok"])
        self.assertFalse((self.proj / "spec/reports/debt-exhausted.json").exists())

    def test_shared_holders_route_by_consumer_and_extra_definition(self) -> None:
        """shared-holders 阻断 → 按 consumer_domain 派接线；multi-definition 派给**多出那份所在的域**。"""
        self.seed_debt(blocked=("shared-holders",))
        self.seed_holders([HOLDER_CONSUMER, HOLDER_MULTI, HOLDER_ORPHAN])
        proc = self.gen("debt")
        agents = sorted(t["id"] for t in self.plan("debt")["tasks"] if t["kind"] == "agent")
        self.assertEqual(agents, ["wiring:beta"], proc.stderr)   # consumer=beta 与「多出那份」都落在 beta
        beta = self.prompt_of("wiring:beta")
        self.assertIn("### 跨域共享状态 / 事件边未接通（shared-holders，本 owner 名下 2 条）", beta)
        self.assertIn("wires-check-final.json", beta)
        self.assertIn("`AppState`", beta)
        self.assertIn("提供方已就位、本域没接", beta)
        self.assertIn("`SharedCfg`", beta)
        self.assertIn("去重到唯一定义方", beta)
        self.assertIn("features/beta/SharedCfg.ets", beta)
        self.assertIn("event:ghost", beta)                       # 无主条目点名（ghost 域没有白名单）
        self.assertTrue(self.lint("debt")["ok"])

    def test_quality_material_merges_into_existing_owner_task(self) -> None:
        """同一 owner 既有 fix-backlog 欠账又有 findings → 仍只出一个任务，一份任务书两段材料都在。"""
        self.seed_debt(blocked=("fix-backlog", "findings"))
        self.seed_findings([FINDING_ALPHA])
        self.gen("debt")
        agents = sorted(t["id"] for t in self.plan("debt")["tasks"] if t["kind"] == "agent")
        self.assertEqual(agents, ["wiring:alpha"])
        alpha = self.prompt_of("wiring:alpha")
        self.assertIn("### 欠账清单（本任务必须逐条兑现或按占位分类法改判）", alpha)   # brief_debt 原段
        self.assertIn("BK-3", alpha)
        self.assertIn("### 质量门未销账清单", alpha)                                  # E266⑧ 追加段
        self.assertIn("features/alpha/A.ets:12", alpha)
        self.assertTrue(self.lint("debt")["ok"])

    def test_no_quality_blockers_keeps_debt_wave_unchanged(self) -> None:
        """两类都没有（且报告存在也不读）→ 任务集与任务书与 E266 之前完全一致。"""
        self.seed_debt(blocked=("handoffs", "fix-backlog"))
        self.seed_findings([FINDING_ALPHA])      # 存在但 handoff-check 没判 blocked → 不入任务书
        self.seed_holders([HOLDER_CONSUMER])
        self.gen("debt")
        agents = sorted(t["id"] for t in self.plan("debt")["tasks"] if t["kind"] == "agent")
        self.assertEqual(agents, ["wiring:alpha", "wiring:beta"])
        alpha = self.prompt_of("wiring:alpha")
        self.assertNotIn("### 质量门未销账清单", alpha)
        self.assertNotIn("### 跨域共享状态 / 事件边未接通", alpha)
        self.assertNotIn("### 无主条目", alpha)
        self.assertTrue(self.lint("debt")["ok"])

    def test_all_unowned_quality_items_land_in_debt_ledger(self) -> None:
        """全部推不出 owner → 无任务可派，但两类条目逐条进 debt-exhausted.json（不静默消失），且不停机。"""
        self.seed_debt(blocked=("findings", "shared-holders"))
        self.seed_findings([FINDING_ORPHAN])
        self.seed_holders([HOLDER_ORPHAN])
        proc = self.gen("debt")
        self.assertFalse((self.proj / "spec/waves/plan-debt.json").exists())
        ex = json.loads((self.proj / "spec/reports/debt-exhausted.json").read_text(encoding="utf-8"))
        self.assertEqual([f["file"] for f in ex["remaining"]["findings"]], ["third_party/Z.ets"])
        self.assertEqual([h["symbol"] for h in ex["remaining"]["shared_holders"]], ["event:ghost"])
        self.assertFalse(ex["escalate"])          # 记账放行，不停机
        self.assertTrue(ex["deferred"])
        self.assertFalse(ex["converged"])         # 但欠账未清这件事如实留在账上
        self.assertIn("推不出 owner", proc.stderr)

    def test_round_cap_matches_two_repair_rounds(self) -> None:
        """debt 波返工额度 = gates.debt_max_rounds 缺省 2（与处置阶梯「最多 2 轮」同值），到顶记账放行。"""
        self.seed_debt(blocked=("findings",))
        self.seed_findings([FINDING_ALPHA])
        self.assertEqual(W.debt_cap(self.proj), 2)
        self.journal_rows([{"workflow_id": "debt", "task_id": "wiring:r2:alpha", "kind": "agent",
                            "attempt": 1, "status": "OK"}])
        self.gen("debt")
        self.assertFalse((self.proj / "spec/waves/plan-debt.json").exists())
        ex = json.loads((self.proj / "spec/reports/debt-exhausted.json").read_text(encoding="utf-8"))
        self.assertEqual((ex["rounds_run"], ex["cap"]), (2, 2))
        self.assertFalse(ex["escalate"])


if __name__ == "__main__":
    unittest.main()
