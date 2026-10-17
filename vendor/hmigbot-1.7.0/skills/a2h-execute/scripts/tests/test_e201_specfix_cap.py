# -*- coding: utf-8 -*-
"""E201（已撤回 E218：缺省不设限）：显式设 gates.specfix_domain_max_rounds 时，单域达上限后不再派代理并记 spec-debt.json；
缺省 0 = 不设限。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS)); sys.path.insert(0, str(SCRIPTS / "tests"))
import test_page_chunks as TPC  # noqa: E402


def _gen(root: Path, wave: str):
    env = dict(os.environ); env["ARKTS_SKILL_DIR"] = str(SCRIPTS.parent)
    r = subprocess.run([sys.executable, str(SCRIPTS / "generate_waves.py"), "--blueprint", "spec/blueprint",
                        "--out", "spec/waves", "--wave", wave, "--json"], capture_output=True, text=True,
                       encoding="utf-8", cwd=str(root), env=env, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads((root / ("spec/waves/plan-%s.json" % wave)).read_text(encoding="utf-8")), r.stderr


def _journal(root: Path, rows):
    (root / "spec/state").mkdir(parents=True, exist_ok=True)
    (root / "spec/state/journal.json").write_text(json.dumps(
        {"workflow_status": [], "operation_outputs": [{"workflow_id": "specfix", "kind": "agent", "task_id": t, "status": "OK"} for t in rows]}),
        encoding="utf-8")


class TestSpecfixCap(unittest.TestCase):
    def _root(self, td):
        root = Path(td); TPC._blueprint(root)
        (root / "spec/reports").mkdir(parents=True, exist_ok=True)
        (root / "spec/reports/spec-tasks.json").write_text(json.dumps(
            {"domains": {"big": ["SearchActivity"], "small": ["AActivity"]},
             "depth_gate_findings": {"big": [{"rule": "X", "subject": "big.md::SearchActivity"}]}}), encoding="utf-8")
        return root

    def _set_cap(self, root, cap):
        wp = root / "spec/blueprint/workflow-params.json"
        doc = json.loads(wp.read_text(encoding="utf-8")); doc.setdefault("gates", {})["specfix_domain_max_rounds"] = cap
        wp.write_text(json.dumps(doc), encoding="utf-8")

    def test_capped_domain_skipped_and_debt_recorded(self):
        """E266④：派满仍薄 → 台账带逐条剩余薄页 + 派发实证，然后放行（exit 0），未到顶的域照常派修。"""
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td); self._set_cap(root, 2)
            _journal(root, ["read:big", "read:r2:big", "read:r2:big", "read:small"])   # big 两轮（同轮重试不重复计）、small 一轮
            plan, err = _gen(root, "specfix")
            ids = [t["id"] for t in plan["tasks"] if t["kind"] == "agent"]
            self.assertEqual(ids, ["read:r3:small"], (ids, err))
            self.assertIn("E266④", err)
            self.assertIn("已真派满 2 轮", err)
            debt = json.loads((root / "spec/reports/spec-debt.json").read_text(encoding="utf-8"))
            self.assertEqual(debt["domains"]["big"]["rounds"], 2)
            self.assertEqual(debt["domains"]["big"]["pages"], ["SearchActivity"])
            self.assertEqual(debt["domains"]["big"]["findings"][0]["rule"], "X")
            self.assertIn("journal", debt["domains"]["big"]["dispatch_evidence"])
            self.assertEqual((debt["converged"], debt["escalate"], debt["deferred"]), (False, False, True))
            self.assertEqual(debt["dispatchable_domains"], 1)
            adj = json.loads((root / "spec/state/auto-adjudications.json").read_text(encoding="utf-8"))
            cap_rows = [e for e in adj if e.get("kind") == "specfix-cap"]
            self.assertEqual([e["id"] for e in cap_rows], ["big"])
            self.assertIn("SearchActivity", cap_rows[0]["detail"])

    def test_no_prior_rounds_dispatches_all(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            plan, _ = _gen(root, "specfix")
            self.assertEqual(sorted(t["id"] for t in plan["tasks"] if t["kind"] == "agent"), ["read:big", "read:small"])
            self.assertFalse((root / "spec/reports/spec-debt.json").is_file())

    def test_default_unlimited(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            _journal(root, ["read:big", "read:r2:big", "read:r3:big"])
            plan, _ = _gen(root, "specfix")
            self.assertIn("read:r4:big", [t["id"] for t in plan["tasks"] if t["kind"] == "agent"])


if __name__ == "__main__":
    unittest.main()
