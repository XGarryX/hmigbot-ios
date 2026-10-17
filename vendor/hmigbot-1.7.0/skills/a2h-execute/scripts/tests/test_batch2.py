#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第二批 V6–V11 单测：device_smoke 三档 / thirdparty-sdk 拆分 / 决策按链投递 /
派生 PD 卡 / W4 域 infra 依赖 / R5 门禁拓扑 / infra 空补挂 contract-sync。

用法示例:
    python3 -m unittest discover -s arkts-skills/skills/a2h-execute/scripts/tests -v
    python3 arkts-skills/skills/a2h-execute/scripts/tests/test_batch2.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_generate_plan import PlanFixture

SCRIPTS = Path(__file__).resolve().parent.parent
PARSE_AGENT = SCRIPTS / "parse_agent_output.py"
LINT_PLAN = SCRIPTS.parent.parent / "a2h-plan" / "scripts" / "lint_plan.py"
LINT_BLUEPRINT = SCRIPTS.parent.parent / "a2h-plan" / "scripts" / "lint_blueprint.py"
ASSEMBLE = SCRIPTS / "assemble_prompt.py"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestThirdpartySdkSplit(unittest.TestCase):
    """V9：thirdparty-sdk 必带 side_effects；非 none 而同 location 无 forward-ref → 校验错。"""

    def _check(self, deferred: list) -> subprocess.CompletedProcess:
        obj = {"task": "domain:a", "final_state": "PASS", "files": ["a.ets"],
               "deferred_items": deferred}
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        tmp.write(json.dumps(obj))
        tmp.close()
        self.addCleanup(lambda: os.unlink(tmp.name))
        return subprocess.run(
            [sys.executable, str(PARSE_AGENT), "--file", tmp.name, "--schema", "impl",
             "--raw-json", "--json"], capture_output=True, text=True, encoding="utf-8", timeout=60)

    def test_none_side_effects_ok(self) -> None:
        proc = self._check([{"kind": "thirdparty-sdk", "location": "SdkStub.ets#init",
                             "trigger": {"type": "sdk-available", "arg": "@huawei/iap"},
                             "side_effects": "none"}])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_missing_side_effects_fails(self) -> None:
        proc = self._check([{"kind": "thirdparty-sdk", "location": "SdkStub.ets#init",
                             "trigger": {"type": "sdk-available", "arg": "@vendor/sdk"}}])
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("side_effects", proc.stderr)

    def test_effects_without_forward_ref_fails(self) -> None:
        # initThirdSdk 有 OAID→initUser 副作用但只桩 thirdparty-sdk（F-004 型）
        proc = self._check([{"kind": "thirdparty-sdk",
                             "location": {"file": "Launch.ets", "anchor": "initThirdSdk"},
                             "trigger": {"type": "sdk-available", "arg": "@vendor/sdk"},
                             "side_effects": ["调 initUser 上报设备"]}])
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("forward-ref", proc.stderr)

    def test_effects_with_forward_ref_ok(self) -> None:
        proc = self._check([
            {"kind": "thirdparty-sdk", "location": {"file": "Launch.ets", "anchor": "initThirdSdk"},
             "trigger": {"type": "sdk-available", "arg": "@vendor/sdk"},
             "side_effects": ["调 initUser"]},
            {"kind": "forward-ref", "location": {"file": "Launch.ets", "anchor": "initUser-call"},
             "trigger": {"type": "symbol-implemented", "arg": "Launch.ets#initUser"},
             "resolve_by": "wiring", "note": "接回业务副作用"}])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_freeform_trigger_fails(self) -> None:
        # E244：forward-ref 的判据由 contract_sync 生成桩位判据，代理写的散文只作参考 → 解析放行
        proc = self._check([{"kind": "forward-ref", "location": "A.ets#load",
                             "trigger": "等后端好了再接", "resolve_by": "wiring"}])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # 外部条件型（thirdparty-sdk 等）仍须结构化判据，散文照旧拒收
        proc = self._check([{"kind": "thirdparty-sdk", "location": "A.ets#load",
                             "trigger": "等后端好了再接", "side_effects": "none"}])
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("type:arg", proc.stderr)

    def test_note_must_be_string(self) -> None:
        proc = self._check([{"kind": "forward-ref", "location": "A.ets#load",
                             "trigger": "symbol-implemented:A.ets#loadImpl",
                             "resolve_by": "wiring", "note": ["散文"]}])
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("note", proc.stderr)


class TestDecisionChainDelivery(unittest.TestCase):
    """V8：决策 symbols 所在 chain 的 owner 域也收到该决策（不只 emits 命中域）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-deliver-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.bp = self.proj / "spec" / "blueprint"
        _write(self.bp / "domain-map.json", json.dumps({"version": 1, "domains": [
            {"key": "account", "title": "A", "spec_file": "spec/domains/account.md", "pages": []},
            {"key": "infra-network", "title": "N", "spec_file": "spec/domains/infra-network.md",
             "pages": []}]}))
        _write(self.bp / "ownership.json", json.dumps({"version": 1, "owners": {
            "domain:account": ["features/account/**"],
            "domain:infra-network": ["common/net/**"]}, "mainloop_owned": []}))
        _write(self.bp / "contracts.json", json.dumps({"version": 1, "modules": [],
            "wires": [], "deferred": [], "acceptance": [],
            "chains": [{"chain_id": "token", "symbols": ["interceptTokenExpired"],
                        "layers": [{"layer": "L1", "owner": "domain:account"},
                                   {"layer": "L2", "owner": "domain:infra-network"}]}]}))
        _write(self.bp / "decisions.json", json.dumps({"version": 1, "decisions": [
            {"id": "PD-03", "category": "C9", "status": "approved", "title": "-1001 跳登录",
             "approved_by": "u", "approved_at": "t", "emits": ["account"],
             "symbols": ["interceptTokenExpired"]}]}))
        _write(self.bp / "workflow-params.json", json.dumps({"version": 1, "profile": "flagship",
            "project": {"root": str(self.proj), "android_src": "/x", "build_cmd": "true",
                        "encoding": "utf-8"},
            "waves": {"domains": {"model": "flagship", "fragments_default": []}},
            "gates": {"prompt_budget_bytes": 40960}}))
        _write(self.bp / "decision-ledger.md", "# ledger\n")
        _write(self.proj / "spec/domains/account.md", "# account\n")
        _write(self.proj / "spec/domains/infra-network.md", "# net\n")

    def _prompt(self, key: str) -> str:
        env = dict(os.environ)
        env["ARKTS_SKILL_DIR"] = str(SCRIPTS.parent)
        proc = subprocess.run(
            [sys.executable, str(ASSEMBLE), "--blueprint", "spec/blueprint",
             "--wave", "domains", "--task", key, "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj),
            env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)["prompt"]

    def test_pd_reaches_both_chain_owners(self) -> None:
        self.assertIn("PD-03", self._prompt("account"))            # emits 命中
        self.assertIn("PD-03", self._prompt("infra-network"))      # V8：chain owner 也命中


class TestLintPlanTopology(PlanFixture):
    """V10/R5：--all 跨 plan 门禁拓扑——缺某类门禁即 FAIL。"""

    def test_full_set_passes(self) -> None:
        for w in ("infra", "domains", "auditfix", "closeout"):
            self.gen(w)
        proc = self._run(LINT_PLAN, "--all", "spec/waves", "--blueprint", "spec/blueprint", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)

    def test_missing_gate_class_fails(self) -> None:
        self.gen("domains")   # 只有 domains：缺 escalated-ratio / report / handoff-check
        proc = self._run(LINT_PLAN, "--all", "spec/waves", "--blueprint", "spec/blueprint", "--json")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        out = json.loads(proc.stdout)
        self.assertTrue(any("handoff-check" in e for e in out["errors"]), out["errors"])


class TestInfraEmptyContractSync(PlanFixture):
    """V10：infra 波为空（contracts 无 infra:* 模块）时，contract-sync 改挂 domains 波。"""

    def test_contract_sync_moves_to_domains(self) -> None:
        # 去掉 infra 模块组：contracts.modules owner 改非 infra
        c = json.loads((self.blueprint / "contracts.json").read_text(encoding="utf-8"))
        c["modules"] = []
        self._write(self.blueprint / "contracts.json", json.dumps(c))
        # ownership 去掉 infra:core
        o = json.loads((self.blueprint / "ownership.json").read_text(encoding="utf-8"))
        o["owners"].pop("infra:core", None)
        self._write(self.blueprint / "ownership.json", json.dumps(o))
        self.gen("domains")
        by_id = {t["id"]: t for t in self.plan("domains")["tasks"]}
        self.assertIn("gate:contract-sync", by_id)                 # V10：补挂到 domains
        self.assertEqual(by_id["gate:contract-sync"]["parents"], ["@domains-impl"])
        self.assertIn("gate:contract-sync", by_id["reduce:probe"]["parents"]); self.assertEqual(by_id["reduce:build-domains"]["parents"], ["reduce:probe"])
        self.assertTrue(self.lint("domains")["ok"])


class TestLintBlueprintBatch2(unittest.TestCase):
    """V6 device_smoke 布尔 WARN / V7 派生卡缺字段 FAIL / W4 域 infra 依赖 WARN。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-lb2-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.bp = self.proj / "spec" / "blueprint"
        _write(self.bp / "domain-map.json", json.dumps({"version": 1, "domains": [
            {"key": "a", "title": "A", "spec_file": "spec/domains/a.md", "pages": []}]}))
        _write(self.bp / "ownership.json", json.dumps({"version": 1,
            "owners": {"domain:a": ["x/**"]}, "mainloop_owned": []}))
        _write(self.bp / "contracts.json", json.dumps({"version": 1, "modules": [],
            "wires": [], "deferred": [], "chains": [], "acceptance": []}))
        _write(self.bp / "decision-ledger.md", "# ledger\n")

    def _wp(self, device_smoke) -> None:
        _write(self.bp / "workflow-params.json", json.dumps({"version": 1, "profile": "flagship",
            "project": {"root": str(self.proj), "android_src": "/x", "build_cmd": "true",
                        "encoding": "utf-8"},
            "waves": {}, "api_inventory_status": "ready", "pollution_blocklist": [],
            "gates": {"compile_fix_max": 20, "escalated_block_ratio": 0.1,
                      "quick_fix_threshold": 15, "lens_shard_loc_threshold": 50000,
                      "prompt_budget_bytes": 40960, "device_smoke": device_smoke}}))

    def _decisions(self, decs) -> None:
        _write(self.bp / "decisions.json", json.dumps({"version": 1, "decisions": decs}))

    def _run(self):
        proc = subprocess.run(
            [sys.executable, str(LINT_BLUEPRINT), "--blueprint", "spec/blueprint",
             "--gate", "approval", "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj), timeout=120)
        return json.loads(proc.stdout)

    def _check(self, out, cid):
        return next(c for c in out["checks"] if c["id"] == cid)

    def test_device_smoke_bool_warns(self) -> None:
        self._wp(True)
        self._decisions([])
        out = self._run()
        # 布尔 device_smoke 不判「非法」FAIL（兼容读作 dual），审批材料档位项标注布尔兼容
        self.assertFalse(any("device_smoke" in f and "非法" in f
                             for c in out["checks"] for f in c["fails"]))
        tier_mat = next(m for m in out["approval_materials"] if "冒烟档位" in m["item"])
        self.assertIn("布尔兼容", tier_mat["detail"])

    def test_device_smoke_illegal_fails(self) -> None:
        self._wp("maybe")            # 非 off|hmos|dual 且非布尔
        self._decisions([])
        out = self._run()
        tier_mat = next(m for m in out["approval_materials"] if "冒烟档位" in m["item"])
        self.assertEqual(tier_mat["status"], "missing")

    def test_derived_pd_missing_boundary_fails(self) -> None:
        self._wp("hmos")
        self._decisions([{"id": "PD-10", "category": "C9", "status": "approved",
                          "title": "派生行为", "approved_by": "u", "approved_at": "t",
                          "derived_from": "PD-03"}])   # 缺 boundary/on_device_check
        out = self._run()
        w6 = self._check(out, "W6")
        self.assertEqual(w6["status"], "FAIL", w6)
        self.assertTrue(any("boundary" in f for f in w6["fails"]))

    def test_derived_pd_complete_passes(self) -> None:
        self._wp("hmos")
        self._decisions([{"id": "PD-10", "category": "C9", "status": "approved",
                          "title": "派生", "approved_by": "u", "approved_at": "t",
                          "derived_from": "PD-03", "boundary": "登录页外才跳",
                          "on_device_check": "登录页内点验证码手机号不清空"}])
        self.assertNotEqual(self._check(self._run(), "W6")["status"], "FAIL")

    def test_domain_no_infra_dep_warns(self) -> None:
        self._wp("hmos")
        self._decisions([])
        w4 = self._check(self._run(), "W4")
        self.assertEqual(w4["status"], "WARN")   # 域 a 无 depends_on_infra 也没被引用


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
