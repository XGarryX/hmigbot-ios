"""DevEco-830 A4：lint_plan R6（能力↔调用方）/ R7（round0 前置输入）回归。
立此闸的事实：op page/op ac 零调用方、check_slice_wiring 因无 wires 整套 skip，lint 四条规则都不覆盖，跑完两轮无人看见。
固定判据：--all 模式 WARN 列出 `--op ac` 无调用方；含 round0 的 plan 在 wires 空且无 feature-plan.md 时 WARN check_slice_wiring；
补上 wires 后该 WARN 消失；JSON 带 capability_gaps / round0_will_skip。
"""
from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent.parent
LINT = SCRIPTS.parent.parent / "a2h-plan" / "scripts" / "lint_plan.py"


def _run(root: Path, *args):
    env = dict(os.environ); env["ARKTS_SKILL_DIR"] = str(SCRIPTS.parent)
    return subprocess.run([sys.executable, str(LINT), *args, "--blueprint", "spec/blueprint", "--json"],
                          capture_output=True, text=True, cwd=str(root), env=env, timeout=120)


class TestR6R7(unittest.TestCase):
    def test_round0_prefers_local_install_and_explicit_precedence(self):
        # E173（AIPPT_930 移植）：round0 无 ARKTS_SKILL_DIR 时优先本脚本所在的安装根；显式 CLI / env 仍优先
        round0 = runpy.run_path(str(SCRIPTS / "round0_precheck.py"), run_name="round0_skill_root_test")
        local = SCRIPTS.parent.parent
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(round0["resolve_skills_root"](None), local)
            self.assertEqual(round0["resolve_skills_root"]("/explicit/skills"), Path("/explicit/skills"))
        with tempfile.TemporaryDirectory() as td:
            explicit = Path(td)
            (explicit / "SKILL.md").write_text("# explicit", encoding="utf-8")
            with patch.dict(os.environ, {"ARKTS_SKILL_DIR": str(explicit)}, clear=True):
                self.assertEqual(round0["resolve_skills_root"](None), explicit.parent)

    def test_capability_gap_and_round0_prereq(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); bp = root / "spec/blueprint"; bp.mkdir(parents=True); waves = root / "spec/waves"; waves.mkdir()
            for n in ("contracts.json", "decisions.json", "domain-map.json", "ownership.json", "workflow-params.json"):
                (bp / n).write_text("{}", encoding="utf-8")
            (bp / "decision-ledger.md").write_text("# l\n", encoding="utf-8")
            (waves / "plan-auditfix.json").write_text(json.dumps({"wave": "auditfix", "tasks": [
                {"id": "gate:round0", "kind": "reduce", "run": "python3 $SKILLS/a2h-execute/scripts/round0_precheck.py --project . --json", "parents": ["@x"]},
                {"id": "gate:compile-3", "kind": "reduce", "run": "python3 gate_check.py --gate compile#3", "parents": ["gate:round0"]},
                {"id": "gate:fix-backlog", "kind": "reduce", "run": "x", "parents": ["gate:compile-3"]},
                {"id": "gate:escalated-ratio", "kind": "reduce", "run": "x", "parents": ["gate:fix-backlog"]},
                {"id": "gate:handoff-check", "kind": "reduce", "run": "x", "parents": ["gate:escalated-ratio"]},
                {"id": "gate:contract-sync", "kind": "reduce", "run": "x", "parents": ["gate:handoff-check"]}]}), encoding="utf-8")
            r = _run(root, "--all", "spec/waves")
            out = json.loads(r.stdout)
            self.assertTrue(any("--op ac" in w for w in out["warnings"]), out)
            self.assertTrue(any("check_slice_wiring" in w for w in out["warnings"]), out)
            self.assertTrue(any(g["capability"].endswith("--op ac") for g in out["capability_gaps"]))
            self.assertTrue(any(s["check"] == "check_slice_wiring" for s in out["round0_will_skip"]))
            (bp / "contracts.json").write_text(json.dumps({"wires": [{"kind": "vm-instantiation"}]}), encoding="utf-8")
            out2 = json.loads(_run(root, "--all", "spec/waves").stdout)
            self.assertFalse(any("check_slice_wiring" in w for w in out2["warnings"]), out2)


if __name__ == "__main__":
    unittest.main()
