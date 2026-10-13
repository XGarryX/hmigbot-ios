#!/usr/bin/env python3
"""F8 回归：欠账（PASS_WITH_DEBT）只对设备/账号类门生效——_wavelib.DEBT_ALLOWED_GATES 机械白名单。

此前「仅设备/账号类门允许欠账」只是散文；gates.stage_debt=true 一开，lint-blueprint / lint-plan-* / hygiene 这些静态门
同样修一次就 PASS_WITH_DEBT 放行。现在 stage_debt 开着但 gate 不在表内 → 与 stage_debt 未开完全同行为
（每次 FAIL 都 exit 1 + retry_hint，永不欠账、不落计数/欠账文件）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import _wavelib as W  # noqa: E402


def _repair_touch(root: Path) -> None:
    p = root / "spec" / "domains" / "_repair.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("repaired", encoding="utf-8")
    t = time.time() + 5
    os.utime(p, (t, t))


class TestDebtAllowed(unittest.TestCase):
    def test_table(self):
        self.assertEqual(W.DEBT_ALLOWED_GATES, ("auth-probe", "cold-start", "smoke-1page", "b4", "device-smoke"))
        for g in ("auth-probe", "cold-start", "smoke-1page", "b4", "device-smoke", "Cold-Start", "cold-start-hmos", "B4-r2"):
            self.assertTrue(W.debt_allowed(g), g)
        for g in ("lint-plan-all", "lint-plan-domains", "lint-blueprint", "hygiene", "interface", "depth-gate", "b45", "", None):
            self.assertFalse(W.debt_allowed(g), repr(g))


class _Proj(unittest.TestCase):
    stage_debt = True

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp) / "proj"
        (self.root / "spec/blueprint").mkdir(parents=True)
        gates = {"unattended": True}
        if self.stage_debt:
            gates["stage_debt"] = True
        (self.root / "spec/blueprint/workflow-params.json").write_text(json.dumps({"gates": gates}), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestStaticGateNeverDebts(_Proj):
    def test_stage_debt_on_but_gate_not_allowed(self):
        for gate in ("lint-plan-all", "lint-blueprint", "hygiene"):
            r1 = W.gate_policy(self.root, gate, True, [{"x": 1}], "fix", wave="plan")
            self.assertEqual((r1["mode"], r1["attempt"], r1["verdict"], r1["exit_code"]), ("unattended", 0, "FAIL", 1))
            self.assertEqual(r1["retry_hint"]["next"], W.GATE_RETRY_NEXT)
            self.assertIn("DEBT_ALLOWED_GATES", r1["retry_hint"]["note"])
            _repair_touch(self.root)
            r2 = W.gate_policy(self.root, gate, True, [{"x": 1}], "fix", wave="plan")
            self.assertEqual((r2["verdict"], r2["exit_code"], r2["debt_file"]), ("FAIL", 1, None))
            self.assertFalse((self.root / "spec/state/gate-attempts.json").exists())
            self.assertFalse((self.root / ("spec/reports/%s-debt.json" % gate)).exists())
        self.assertEqual(W.load_adjudications(self.root), [])

    def test_pass_on_static_gate_writes_nothing(self):
        r = W.gate_policy(self.root, "lint-blueprint", False, [], "fix")
        self.assertEqual((r["verdict"], r["exit_code"]), ("PASS", 0))
        self.assertFalse((self.root / "spec/state/gate-attempts.json").exists())


class TestDeviceGateStillDebts(_Proj):
    def test_allowed_gate_fail_fail_debt(self):
        r1 = W.gate_policy(self.root, "cold-start", True, ["no device"], "connect hdc", wave="stage")
        self.assertEqual((r1["attempt"], r1["verdict"], r1["exit_code"]), (1, "FAIL", 1))
        self.assertEqual(r1["retry_hint"]["next"], W.GATE_RETRY_NEXT_DEBT)
        self.assertNotIn("note", r1["retry_hint"])
        _repair_touch(self.root)
        r2 = W.gate_policy(self.root, "cold-start", True, ["no device"], "connect hdc", wave="stage")
        self.assertEqual((r2["attempt"], r2["verdict"], r2["exit_code"]), (2, "PASS_WITH_DEBT", 0))
        self.assertTrue((self.root / "spec/reports/cold-start-debt.json").is_file())
        self.assertEqual([e["kind"] for e in W.load_adjudications(self.root)], ["cold-start-debt"])

    def test_prefix_variant_allowed(self):
        r = W.gate_policy(self.root, "auth-probe-l3", True, ["blocked"], "fix")
        self.assertEqual(r["attempt"], 1)
        self.assertEqual(W.load_gate_attempts(self.root)["auth-probe-l3"]["attempts"], 1)


class TestStageDebtOffAllowedGate(_Proj):
    stage_debt = False

    def test_allowed_gate_without_switch_never_debts(self):
        r1 = W.gate_policy(self.root, "cold-start", True, ["x"], "fix")
        _repair_touch(self.root)
        r2 = W.gate_policy(self.root, "cold-start", True, ["x"], "fix")
        self.assertEqual((r1["exit_code"], r2["exit_code"], r2["verdict"]), (1, 1, "FAIL"))
        self.assertNotIn("note", r2["retry_hint"])
        self.assertFalse((self.root / "spec/state/gate-attempts.json").exists())


if __name__ == "__main__":
    unittest.main()
