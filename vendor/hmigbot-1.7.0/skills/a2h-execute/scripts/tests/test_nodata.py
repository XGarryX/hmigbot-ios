#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3 空账门（OPT-PLAN-V3 P2/P3/P5 第一批）单测：NO_DATA 判定 / gate·domain 落账 /
sync_pagemap 零 builder / register-state 底账 / G2 逐层活性 / report --strict。

用法示例:
    python3 -m unittest discover -s arkts-skills/skills/a2h-execute/scripts/tests -v
    python3 arkts-skills/skills/a2h-execute/scripts/tests/test_nodata.py

输入:  复用 test_scheduler_kernel.KernelFixture 的合成工程；全部 subprocess 黑盒调用。
输出:  unittest 标准输出。无副作用。

约定（P2 的测试纪律）：每个门禁/检查函数至少一条「空输入 ≠ PASS」用例——
v3 复盘原因 5 的回归面（escalated-ratio 0/18=PASS、pagemap builders=0 判 ok、
G2 存在性放行 BLOCKED、报告「无数据」不致命）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_scheduler_kernel import (KernelFixture, VALID_BETA, SCRIPTS)

GATE_CHECK = SCRIPTS / "gate_check.py"
SYNC_PAGEMAP = SCRIPTS / "sync_pagemap.py"
A3_FINALIZE = SCRIPTS.parent.parent / "a2h-plan" / "scripts" / "a3_finalize.py"
LINT_BLUEPRINT = SCRIPTS.parent.parent / "a2h-plan" / "scripts" / "lint_blueprint.py"
REPORT_AGG = SCRIPTS / "report_aggregate.py"

# 输出 gate_check 同构 verdict JSON 的假门禁（V3 gate 落账路径的驱动器）：
# argv[1]=verdict 文件（内容即 verdict 串，缺省 green）；verdict!=green → exit 1
FAKE_GATE_JSON = """\
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
verdict = p.read_text(encoding="utf-8").strip() if p.exists() else "green"
print(json.dumps({"gate": "compile#2", "verdict": verdict, "ratio": 1.0,
                  "errors_total": 0, "by_domain": {}}))
sys.exit(0 if verdict == "green" else 1)
"""

FINDINGS_ALPHA = {"domain": "alpha", "findings": [
    {"file": "features/alpha/A.ets", "line": 3, "severity": "P0", "kind": "functional",
     "summary": "初始化链断", "fix": "接上 AppInitializer"},
    {"file": "features/alpha/A.ets", "line": 9, "severity": "P1", "kind": "visual",
     "summary": "圆角错", "fix": "改 8vp"},
]}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestEscalatedRatioNoData(unittest.TestCase):
    """空 state.domains → NO_DATA exit 1；有账照旧；fix-backlog P0 计入分子。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-nodata-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.bp = self.proj / "spec" / "blueprint"
        _write(self.bp / "domain-map.json", json.dumps(
            {"version": 1, "domains": [{"key": "alpha"}, {"key": "beta"}]}))

    def _run(self, state: dict) -> subprocess.CompletedProcess:
        _write(self.proj / "spec/state/state.json", json.dumps(state))
        return subprocess.run(
            [sys.executable, str(GATE_CHECK), "--state", "spec/state/state.json",
             "--gate", "escalated-ratio", "--blueprint", "spec/blueprint", "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj), timeout=120)

    def test_empty_domains_is_nodata_not_pass(self) -> None:
        proc = self._run({"version": 1, "domains": {}, "waves": {}, "gates": {}, "pages": {}})
        self.assertEqual(proc.returncode, 1, proc.stdout)
        out = json.loads(proc.stdout)
        self.assertEqual(out["verdict"], "NO_DATA")
        self.assertIn("register-state", out["reason"])

    def test_registered_domains_pass_as_before(self) -> None:
        proc = self._run({"version": 1, "pages": {}, "waves": {}, "gates": {},
                          "domains": {"alpha": {"final_state": "PASS"},
                                      "beta": {"final_state": "PASS"}}})
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(json.loads(proc.stdout)["verdict"], "PASS")

    def test_cross_p0_backlog_counts_into_numerator(self) -> None:
        _write(self.proj / "spec/reports/fix-backlog.json", json.dumps(
            {"open": 2, "items": [
                {"id": "BK-1", "severity": "P0", "required_owner": "beta"},
                {"id": "BK-2", "severity": "P1", "required_owner": "beta"}]}))
        proc = self._run({"version": 1, "pages": {}, "waves": {}, "gates": {},
                          "domains": {"alpha": {"final_state": "PASS"},
                                      "beta": {"final_state": "PASS"}}})
        self.assertEqual(proc.returncode, 1, proc.stdout)   # (0+1)/2 = 0.5 > 0.10
        out = json.loads(proc.stdout)
        self.assertEqual(out["verdict"], "FAIL")
        self.assertEqual(out["cross_p0"], 1)
        self.assertIn("backlog", out["reason"])

    def test_deferred_backlog_not_counted(self) -> None:
        _write(self.proj / "spec/reports/fix-backlog.json", json.dumps(
            {"open": 1, "resolution": {"defer": True},
             "items": [{"id": "BK-1", "severity": "P0"}]}))
        proc = self._run({"version": 1, "pages": {}, "waves": {}, "gates": {},
                          "domains": {"alpha": {"final_state": "PASS"},
                                      "beta": {"final_state": "PASS"}}})
        self.assertEqual(proc.returncode, 0, proc.stdout)


class TestGateAccountLanded(KernelFixture):
    """V3：gate: 前缀 reduce 执行后 verdict JSON 落 state.gates（红绿门都记账）。"""

    def _json_gate_plan(self) -> dict:
        gate_dir = self.proj / "tools"
        self._write(gate_dir / "fake_gate_json.py", FAKE_GATE_JSON)
        self.verdict_file = gate_dir / "verdict.txt"
        plan = self.base_plan()
        plan["tasks"][2] = {"id": "gate:compile", "kind": "reduce",
                            "run": f"python3 {gate_dir / 'fake_gate_json.py'} {self.verdict_file}",
                            "parents": ["@domains-impl"],
                            "on_fail": {"skip": ["impl:final"], "escalate": True}}
        return plan

    def _dispatch_and_result(self) -> None:
        self.next_batch()
        self.write_result("alpha", {"task": "domain:alpha", "final_state": "PASS",
                                    "files": ["features/alpha/A.ets"]})
        self.write_result("beta", VALID_BETA)

    def _gates(self) -> dict:
        return json.loads(self.state.read_text(encoding="utf-8")).get("gates") or {}

    def test_green_gate_landed_into_state(self) -> None:
        self.write_plan(self._json_gate_plan())
        self._dispatch_and_result()
        self.land()
        rec = self._gates().get("compile#2")
        self.assertIsNotNone(rec, self._gates())
        self.assertEqual(rec["status"], "green")
        self.assertTrue(rec["passed"])

    def test_red_gate_also_landed(self) -> None:
        self.write_plan(self._json_gate_plan())
        self._write(self.verdict_file, "quick_fix")
        self._dispatch_and_result()
        out = self.land(expect=2)                        # on_fail.escalate 照旧
        self.assertEqual(out["reduces"][0]["status"], "REDUCE_FAIL")
        rec = self._gates().get("compile#2")
        self.assertIsNotNone(rec, self._gates())
        self.assertEqual(rec["status"], "quick_fix")
        self.assertFalse(rec["passed"])


class TestDomainAccountLanded(KernelFixture):
    """V3：落账合格的 impl/findings/fix 结果同步写 state.domains（P3 有字段必有消费者）。"""

    def test_impl_final_state_lands_into_domains(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("alpha", {"task": "domain:alpha", "final_state": "PASS",
                                    "files": ["features/alpha/A.ets"]})
        self.write_result("beta", {"task": "domain:beta", "final_state": "ESCALATED",
                                   "files": [],
                                   "escalation": {"reason": "SDK 无对等物", "g_id": "G-1"}})
        self.land(expect=0)
        domains = json.loads(self.state.read_text(encoding="utf-8"))["domains"]
        self.assertEqual(domains["alpha"]["final_state"], "PASS")
        self.assertEqual(domains["beta"]["final_state"], "ESCALATED")
        self.assertEqual(domains["beta"]["escalation"]["reason"], "SDK 无对等物")

    def auditfix_plan(self) -> dict:
        def node(tid, stem, schema, parents):
            return {"id": tid, "kind": "agent", "agent": "a2h-domain-worker@2.1.0",
                    "prompt_file": f"spec/waves/prompts/auditfix/{stem}.txt", "model": "flagship",
                    "schema": schema, "parents": parents, "map_group": "auditfix-" + stem.split("-")[0],
                    "ownership": ["features/alpha/**"],
                    "result_path": f"spec/waves/results/auditfix/{stem}.json",
                    "resume_key": f"auditfix:{tid}"}
        return {"wave": "auditfix", "plan_version": "a2h-2.1.0",
                "contract_hash": "sha256:" + "0" * 64, "max_parallel": 0,
                "tasks": [node("audit:alpha", "audit-alpha", "auditFindings", []),
                          node("fix:alpha", "fix-alpha", "fixResult", ["audit:alpha"])]}

    def _af_result(self, stem: str, obj: dict) -> None:
        self._write(self.proj / "spec/waves/results/auditfix" / (stem + ".json"),
                    json.dumps(obj, ensure_ascii=False))

    def test_audit_and_fix_maintain_p0_open(self) -> None:
        path = self.proj / "spec" / "waves" / "plan-auditfix.json"
        self.write_plan(self.auditfix_plan(), path=path)
        self.next_batch(path=path)
        self._af_result("audit-alpha", FINDINGS_ALPHA)
        self.land(path=path)
        domains = json.loads(self.state.read_text(encoding="utf-8"))["domains"]
        self.assertEqual(domains["alpha"]["p0_open"], 1)        # audit：P0 findings 数

        self.next_batch(path=path)                              # fix 就绪
        self._af_result("fix-alpha", {"domain": "alpha", "fixed": ["#2 圆角已修"],
                                      "skipped": [{"finding_ref": 1, "reason": "跨白名单",
                                                   "required_owner": "infra-app-shell"}],
                                      "files_touched": ["features/alpha/A.ets"]})
        self.land(path=path)
        domains = json.loads(self.state.read_text(encoding="utf-8"))["domains"]
        self.assertEqual(domains["alpha"]["p0_open"], 1)        # skipped 引用 P0#1 → 仍开

    def test_fix_all_resolved_zeroes_p0(self) -> None:
        self._write(self.proj / "features/alpha/A.ets", "// fixture\n")   # A8：files_touched 须实存
        path = self.proj / "spec" / "waves" / "plan-auditfix.json"
        self.write_plan(self.auditfix_plan(), path=path)
        self.next_batch(path=path)
        self._af_result("audit-alpha", FINDINGS_ALPHA)
        self.land(path=path)
        self.next_batch(path=path)
        self._af_result("fix-alpha", {"domain": "alpha", "fixed": ["#1 已接线", "#2 圆角已修"],
                                      "skipped": [], "files_touched": ["features/alpha/A.ets"]})
        self.land(path=path)
        domains = json.loads(self.state.read_text(encoding="utf-8"))["domains"]
        self.assertEqual(domains["alpha"]["p0_open"], 0)


class TestSyncPagemapNoBuilders(unittest.TestCase):
    """V3：pages 目录有 .ets 却零 builder → FAIL（v3 实证 5/332 被判 PASS）；空目录仍空跑。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-nobuilder-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.pages = self.proj / "entry/src/main/ets/pages"

    def _run(self) -> subprocess.CompletedProcess:
        self.proj.mkdir(parents=True, exist_ok=True)
        return subprocess.run(
            [sys.executable, str(SYNC_PAGEMAP), "--project", str(self.proj), "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=120)

    def test_ets_present_zero_builders_fails(self) -> None:
        _write(self.pages / "alpha/AlphaPage.ets", "@Component struct AlphaPage {}\n")
        proc = self._run()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        out = json.loads(proc.stdout)
        self.assertTrue(out.get("no_builders"))
        self.assertIn("NO_BUILDERS", proc.stderr + proc.stdout)

    def test_empty_pages_dir_still_noop_pass(self) -> None:
        self.pages.mkdir(parents=True, exist_ok=True)
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout)


class TestRegisterState(unittest.TestCase):
    """V3：a3_finalize --op register-state 把 domain-map 域/页登记进 state（幂等）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-regstate-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        _write(self.proj / "spec/blueprint/domain-map.json", json.dumps(
            {"version": 1, "domains": [
                {"key": "alpha", "pages": ["page_0001_Main", "page_0002_Login"]},
                {"key": "beta", "pages": ["page_0003_Mine"]}]}))

    def _run(self) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["ARKTS_SKILL_DIR"] = str(SCRIPTS.parent)
        return subprocess.run(
            [sys.executable, str(A3_FINALIZE), "--op", "register-state",
             "--blueprint", "spec/blueprint"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj),
            env=env, timeout=120)

    def test_registers_domains_and_pages_idempotently(self) -> None:
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        state = json.loads((self.proj / "spec/state/state.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(state["domains"]), ["alpha", "beta"])
        self.assertEqual(len(state["pages"]), 3)
        self.assertEqual(state["pages"]["page_0001_Main"]["domain"], "alpha")
        self.assertEqual(state["pages"]["page_0001_Main"]["status"], "pending")
        proc2 = self._run()                                    # 幂等重跑
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        state2 = json.loads((self.proj / "spec/state/state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state2["pages"]), 3)
        self.assertEqual(len(state2["domains"]), 2)


class TestLintBlueprintG2Layers(unittest.TestCase):
    """V3/P5：G2 从存在性检查升级为逐层 probe 状态门（v3 实证 BLOCKED 链 30 秒过门）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-g2-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.bp = self.proj / "spec" / "blueprint"
        for name, body in (("domain-map.json", {"version": 1, "domains": [{"key": "a", "title": "A",
                                                "spec_file": "spec/domains/a.md", "pages": []}]}),
                           ("ownership.json", {"version": 1, "owners": {"domain:a": ["x/**"]},
                                               "mainloop_owned": []}),
                           ("decisions.json", {"version": 1, "decisions": []}),
                           ("workflow-params.json", {"profile": "flagship"})):
            _write(self.bp / name, json.dumps(body))
        _write(self.bp / "decision-ledger.md", "# ledger\n")

    def _set_golden(self, layers: list[dict]) -> None:
        _write(self.bp / "contracts.json", json.dumps(
            {"version": 1, "modules": [], "wires": [], "deferred": [], "acceptance": [],
             "chains": [{"chain_id": "auth", "layers": [
                 {"layer": l["layer"], "value_ref": "spec/data-chains/chain-auth.golden.json"}
                 for l in layers]}]}))
        _write(self.proj / "spec/data-chains/chain-auth.golden.json",
               json.dumps({"layers": layers}))

    def _g2_material(self) -> dict:
        proc = subprocess.run(
            [sys.executable, str(LINT_BLUEPRINT), "--blueprint", "spec/blueprint",
             "--gate", "approval", "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj), timeout=120)
        out = json.loads(proc.stdout)
        row = next(m for m in out["approval_materials"] if "chain-auth" in m["item"])
        g1 = next(c for c in out["checks"] if c["id"] == "G1")
        return {"row": row, "fails": [f for f in g1["fails"] if "chain-auth" in f]}

    def test_missing_probe_field_fails(self) -> None:
        self._set_golden([{"layer": "L0", "backend_contract": "已对齐"},
                          {"layer": "L3", "backend_contract": "未对齐（BLOCKED-PENDING-BACKEND）"}])
        res = self._g2_material()
        self.assertEqual(res["row"]["status"], "missing")
        self.assertTrue(any("BLOCKED" in f for f in res["fails"]), res["fails"])
        self.assertTrue(any("auth_probe" in f for f in res["fails"]), res["fails"])

    def test_all_layers_probed_pass(self) -> None:
        self._set_golden([{"layer": "L0", "probe": {"status": "pass", "evidence": "e/l0.json"}},
                          {"layer": "L3", "probe": {"status": "pass", "evidence": "e/l3.json"}}])
        self.assertEqual(self._g2_material()["row"]["status"], "ok")

    def test_waived_needs_signer(self) -> None:
        self._set_golden([{"layer": "L0", "probe": {"status": "pass"}},
                          {"layer": "L3", "probe": {"status": "waived", "waived_by": "mj-cjm"}}])
        res = self._g2_material()
        self.assertEqual(res["row"]["status"], "waived")
        self.assertIn("L3", res["row"]["detail"])
        self._set_golden([{"layer": "L0", "probe": {"status": "pass"}},
                          {"layer": "L3", "probe": {"status": "waived"}}])   # 缺 waived_by
        self.assertEqual(self._g2_material()["row"]["status"], "missing")


class TestReportStrict(unittest.TestCase):
    """V3：--strict 下无数据段非零退出 + meta.json 旁注（报告仍落盘）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-strict-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        (self.proj / "spec" / "blueprint").mkdir(parents=True)

    def _run(self, *flags: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(REPORT_AGG), "--project", str(self.proj),
             "--blueprint", str(self.proj / "spec/blueprint"),
             "--state", str(self.proj / "spec/state/state.json"), "--json", *flags],
            capture_output=True, text=True, encoding="utf-8", timeout=120)

    def test_strict_fails_on_nodata_and_writes_meta(self) -> None:
        proc = self._run("--strict")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        model = json.loads(proc.stdout)
        self.assertTrue(model["nodata_sections"])
        meta = self.proj / "spec/reports/migration-report.meta.json"
        self.assertTrue(meta.is_file())
        self.assertTrue(json.loads(meta.read_text(encoding="utf-8"))["nodata_sections"])
        self.assertTrue((self.proj / "spec/reports/migration-report.md").is_file())

    def test_default_stays_permissive(self) -> None:
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
