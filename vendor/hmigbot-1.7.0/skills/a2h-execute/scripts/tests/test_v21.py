#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V21（aippt_new_v5 全程复盘）kernel 回归：
--infra-fail 直判 / 重派后旧 result 视为在途 / 解说包裹 JSON 抢救 / 落账后 next 提示 / next_batch --brief /
resolved_refs 通道（parse + contract_sync 归一与置 resolved）/ verify_handoffs trigger 对账 /
merge_gaps 逐条 waived / escalated-ratio 按域计 / smoke 多候选靶点 / $SKILLS 展开自校验。

用法示例:
    python3 -m unittest discover -s arkts-skills/skills/a2h-execute/scripts/tests -v
输入:  复用 KernelFixture 合成工程（subprocess 黑盒）+ 纯函数单测。
输出:  unittest 标准输出。无副作用（tmp 目录）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from test_scheduler_kernel import KernelFixture, VALID_BETA, SCRIPTS, LAND_RESULTS, NEXT_BATCH

sys.path.insert(0, str(SCRIPTS))
import contract_sync  # noqa: E402
import land_results  # noqa: E402
import merge_gaps  # noqa: E402
import verify_handoffs  # noqa: E402

VV = SCRIPTS.parent.parent / "arkts-visual-verify" / "scripts"
sys.path.insert(0, str(VV))
import smoke_one_page  # noqa: E402


class TestInfraFailFlag(KernelFixture):
    def _land(self, *extra):
        proc = self._run(LAND_RESULTS, "--plan", str(self.plan_path),
                         "--state", str(self.state), "--json", *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        return json.loads(proc.stdout)

    def test_infra_fail_flag_lands_without_placeholder(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("beta", VALID_BETA)
        out = self._land("--infra-fail", "impl:alpha")
        st = {r["id"]: r["status"] for r in out["landed"]}
        self.assertEqual(st["impl:alpha"], "INFRA_FAIL")
        self.assertEqual(st["impl:beta"], "OK")
        journal = json.loads((self.state.parent / "journal.json").read_text(encoding="utf-8"))
        rows = [r for r in journal["operation_outputs"] if r.get("task_id") == "impl:alpha"]
        self.assertEqual(rows[-1]["status"], "INFRA_FAIL")
        # 豁免：拍①按新任务重吐 alpha
        nb = self.next_batch()
        self.assertIn("impl:alpha", [t["id"] for t in nb["batch"]])

    def test_stale_result_after_redispatch_is_pending(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("beta", VALID_BETA)
        self._land("--infra-fail", "impl:alpha")
        # 把旧的（非法）占位写进 alpha result，再重派 → 旧文件早于新派发时刻
        alpha = self.proj / "spec/waves/results/domains/alpha.json"
        alpha.parent.mkdir(parents=True, exist_ok=True)
        alpha.write_text("FAIL spec/waves/results/domains/alpha.json API Error 529 overloaded\n", encoding="utf-8")
        old = time.time() - 120
        os.utime(alpha, (old, old))
        self.next_batch()          # attempts → 2，last_dispatch_at = now
        out = self._land()
        self.assertEqual(out["landed"], [])
        self.assertIn("impl:alpha", out["pending"])
        self.assertIn("impl:alpha", out.get("stale_results", []))

    def test_salvage_json_wrapped_in_prose(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        beta = self.proj / "spec/waves/results/domains/beta.json"
        beta.parent.mkdir(parents=True, exist_ok=True)
        self._touch_declared(VALID_BETA)
        beta.write_text("下面是我的结果：\n" + json.dumps(VALID_BETA, ensure_ascii=False) + "\n以上。\n",
                        encoding="utf-8")
        out = self._land()
        st = {r["id"]: r["status"] for r in out["landed"]}
        self.assertEqual(st["impl:beta"], "OK")
        journal = json.loads((self.state.parent / "journal.json").read_text(encoding="utf-8"))
        row = [r for r in journal["operation_outputs"] if r.get("task_id") == "impl:beta"][-1]
        self.assertTrue(any("salvaged-json" in n for n in row.get("normalized", [])))

    def test_next_hint_and_brief(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("beta", VALID_BETA)
        out = self._land()
        self.assertEqual(out["next"]["kind"], "beat1")
        self.assertIn("next_batch.py", out["next"]["cmd"])
        proc = self._run(NEXT_BATCH, "--plan", str(self.plan_path), "--state", str(self.state), "--brief")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.startswith("action="), proc.stdout)


class TestResolvedRefs(unittest.TestCase):
    def test_normalize_resolve_by(self) -> None:
        self.assertEqual(contract_sync._normalize_resolve_by("wiring"), ("wiring", None))
        rb, note = contract_sync._normalize_resolve_by("已兑现（wiring 波本任务）：Routes 生成区已含全部 68 条")
        self.assertEqual(rb, "wiring")
        self.assertIn("resolve_by 原文", note)
        self.assertEqual(contract_sync._normalize_resolve_by("由后端同事负责")[0], None)

    def test_merge_rejects_resolved_kind_with_hint(self) -> None:
        contracts = {"deferred": []}
        report, _ = contract_sync.merge_deferred(contracts, [({"kind": "forward-ref-resolved",
                                                              "location": "a/B.ets#x",
                                                              "trigger": "symbol-implemented:a/B.ets#x"},
                                                             "app-home")])
        self.assertEqual(report["summary"]["rejected"], 1)
        self.assertIn("resolved_refs", report["rejected"][0]["reason"])

    def test_apply_resolved_refs_flips_status(self) -> None:
        contracts = {"deferred": [
            {"id": "P-DOM-AH-001", "kind": "forward-ref", "status": "registered",
             "location": {"file": "entry/a/HomeBridges.ets", "anchor": "openVip"}},
            {"id": "P-DOM-AH-002", "kind": "forward-ref", "status": "registered",
             "location": {"file": "entry/a/Other.ets", "anchor": "x"}},
        ]}
        res = contract_sync.apply_resolved_refs(
            contracts, [("P-DOM-AH-001", "wiring:app-home"), ("entry/a/Other.ets#x", "wiring:app-home"),
                        ("P-DOM-NOPE-9", "wiring:app-home")])
        self.assertEqual({r["id"] for r in res["resolved"]}, {"P-DOM-AH-001", "P-DOM-AH-002"})
        self.assertEqual(len(res["unknown"]), 1)
        self.assertTrue(all(it["status"] == "resolved" for it in contracts["deferred"]))

    def test_symbol_implemented_path_arg(self) -> None:
        trig, err = contract_sync._structure_trigger({"type": "symbol-implemented", "arg": "entry/x/Y.ets"})
        self.assertIsNone(err)
        self.assertTrue(trig["check_cmd"].startswith("test -s"))


class TestVerifyHandoffsReconcile(unittest.TestCase):
    def test_trigger_reconcile_marks_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            corpus = [("entry/src/main/ets/pages/A.ets", "import x\nAppConstant.setVipProvider(p)\n// FWD-REF: Foo.bar\n"),
                      ("entry/src/main/ets/pages/B.ets", "class B { }\n")]
            contracts = {"deferred": [
                {"id": "P1", "kind": "forward-ref", "status": "registered",
                 "trigger": {"type": "grep", "arg": r"AppConstant\.setVipProvider\("}},
                {"id": "P2", "kind": "forward-ref", "status": "registered",
                 "trigger": {"type": "symbol-implemented", "arg": "Foo.bar"}},     # 只在 marker 行出现 → 不算
                {"id": "P3", "kind": "forward-ref", "status": "registered", "trigger": None},
            ]}
            out = verify_handoffs.reconcile_triggers(contracts, corpus, root)
            self.assertEqual([r["id"] for r in out["met"]], ["P1"])
            self.assertEqual([r["id"] for r in out["unmet"]], ["P2"])
            self.assertEqual([r["id"] for r in out["nocheck"]], ["P3"])
            self.assertEqual(contracts["deferred"][0]["status"], "resolved")
            self.assertEqual(contracts["deferred"][1]["status"], "registered")


class TestMiscUnits(unittest.TestCase):
    def test_older_than_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "r.json"
            f.write_text("{}", encoding="utf-8")
            future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
            past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            self.assertTrue(land_results._older_than_dispatch(f, future))
            self.assertFalse(land_results._older_than_dispatch(f, past))
            self.assertFalse(land_results._older_than_dispatch(f, None))

    def test_salvage_json_helper(self) -> None:
        self.assertEqual(land_results._salvage_json('说明 {"a": 1} 尾注')["a"], 1)
        self.assertIsNone(land_results._salvage_json("没有对象"))

    def test_skills_root_tolerates_skills_dir_env(self) -> None:
        skills_root = SCRIPTS.parent.parent
        saved = os.environ.get("ARKTS_SKILL_DIR")
        try:
            os.environ["ARKTS_SKILL_DIR"] = str(skills_root)          # 误设成 skills 根
            self.assertEqual(land_results._skills_root(), skills_root)
            os.environ["ARKTS_SKILL_DIR"] = str(skills_root / "a2h-execute")   # 正确设法
            self.assertEqual(land_results._skills_root(), skills_root)
        finally:
            if saved is None:
                os.environ.pop("ARKTS_SKILL_DIR", None)
            else:
                os.environ["ARKTS_SKILL_DIR"] = saved

    def test_clickable_candidates_prefer_text(self) -> None:
        dump = json.dumps({"attributes": {}, "children": [
            {"attributes": {"clickable": "true", "bounds": "[0,0][100,100]", "type": "Stack"}, "children": []},
            {"attributes": {"clickable": "true", "bounds": "[0,200][100,300]", "type": "Button", "text": "登录"}, "children": []},
            {"attributes": {"clickable": "true", "bounds": "[0,400][100,500]", "type": "Text", "text": "首页"}, "children": []},
        ]})
        c = smoke_one_page.clickable_candidates(dump)
        self.assertEqual([t[2] for t in c], ["登录", "首页", "Stack"])
        c2 = smoke_one_page.clickable_candidates(dump, prefer_text="首页")
        self.assertEqual(c2[0][2], "首页")
        self.assertEqual(smoke_one_page.first_clickable(dump)[2], "登录")

    def test_escalated_ratio_counts_domains(self) -> None:
        import gate_check
        with tempfile.TemporaryDirectory() as td:
            cwd = os.getcwd()
            os.chdir(td)
            try:
                Path("spec/reports").mkdir(parents=True)
                Path("spec/reports/fix-backlog.json").write_text(json.dumps({
                    "open": 5, "items": [
                        {"severity": "P0", "required_owner": "app-home"},
                        {"severity": "P0", "required_owner": "app-home"},
                        {"severity": "P0", "required_owner": "app-mine"},
                        {"severity": "P1", "required_owner": "app-x"},
                    ]}), encoding="utf-8")
                state = {"domains": {k: {"final_state": "PASS"} for k in ("a", "b", "c", "d")}}
                r = gate_check.check_escalated_ratio(state, {"gates": {"escalated_block_ratio": 0.1}}, None)
                self.assertEqual(r["cross_p0"], 2)
                self.assertEqual(r["cross_p0_items"], 3)
                self.assertAlmostEqual(r["ratio"], 0.5)
            finally:
                os.chdir(cwd)


class TestMergeGapsPerItemWaived(unittest.TestCase):
    def test_per_item_waived_unblocks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rd = root / "results"
            rd.mkdir()
            (rd / "x.json").write_text(json.dumps({"task": "impl:x", "decision_gaps": [
                {"g_id": "G-IP-001", "category": "ip", "blocking": True}]}), encoding="utf-8")
            out = root / "decision-gaps.json"
            out.write_text(json.dumps({"waived": False, "gaps": [
                {"g_id": "G-IP-001", "blocking": True, "waived": True}]}), encoding="utf-8")
            import subprocess
            proc = subprocess.run([sys.executable, str(SCRIPTS / "merge_gaps.py"), "--results-dir", str(rd),
                                   "--out", str(out), "--json"], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertTrue(json.loads(proc.stdout)["gaps"][0].get("waived"))


if __name__ == "__main__":
    unittest.main()
