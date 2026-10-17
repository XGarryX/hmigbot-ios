# -*- coding: utf-8 -*-
"""E200（S2 深度自检替代 depthfix 独立波）：depth_gate --pages 只判指定页；land_results 落账复核本块页面，
首次浅判 RETRY（DEPTH_SHALLOW），达标 None；任务书页面块带自检段，gates.depth_selfcheck=false 关闭。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import assemble_prompt as ap  # noqa: E402
import land_results  # noqa: E402

SPEC = """# d
### APage
- 要点 1
- 要点 2
- 要点 3
- 要点 4
- 要点 5
- 要点 6
### BPage
- 要点 1
- 要点 2
- 要点 3
- 要点 4
- 要点 5
- 要点 6
"""
SHALLOW = "@ComponentV2\nstruct APage {\n  build() {\n    Column() {\n      Text('a')\n    }\n  }\n}\n"
DEEP = ("@ComponentV2\nstruct BPage {\n  build() {\n    Column() {\n" + "      Text('x')\n" * 8 + "    }\n  }\n}\n")


def make_project(td: Path):
    bp = td / "spec" / "blueprint"; bp.mkdir(parents=True)
    (bp / "domain-map.json").write_text(json.dumps({"domains": [{"key": "d", "pages": ["APage", "BPage"],
                                                                  "spec_file": "spec/domains/d.md"}]}), encoding="utf-8")
    (bp / "page-names.json").write_text(json.dumps({"domains": {"d": {"APage": "APage", "BPage": "BPage"}}}), encoding="utf-8")
    (bp / "workflow-params.json").write_text(json.dumps({"gates": {}}), encoding="utf-8")
    (td / "spec" / "domains").mkdir(); (td / "spec" / "domains" / "d.md").write_text(SPEC, encoding="utf-8")
    pages = td / "entry" / "src" / "main" / "ets" / "pages"; pages.mkdir(parents=True)
    (pages / "APage.ets").write_text(SHALLOW, encoding="utf-8")
    (pages / "BPage.ets").write_text(DEEP, encoding="utf-8")


def run_gate(td: Path, pages: str):
    proc = subprocess.run([sys.executable, str(SCRIPTS / "depth_gate.py"), "--project", str(td), "--blueprint", "spec/blueprint",
                           "--pages", pages, "--out", "spec/reports/dg.json", "--json"], capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


class TestDepthGatePages(unittest.TestCase):
    def test_pages_filter(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); make_project(td)
            rc, out = run_gate(td, "BPage")
            self.assertEqual((rc, out["ok"], out["stats"]["pages_checked"]), (0, True, 1), out)
            rc, out = run_gate(td, "APage")
            self.assertEqual((rc, out["ok"], out["shallow_pages"]), (1, False, ["APage"]), out)


class TestLandDepthCheck(unittest.TestCase):
    def test_shallow_block_returns_error_deep_block_none(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); make_project(td)
            shallow = {"id": "impl:d:p1", "schema": "domainImpl", "_variant": "p1",
                       "ownership": ["entry/src/main/ets/pages/APage.ets", "entry/src/main/ets/components/d/APage/**"]}
            deep = dict(shallow, id="impl:d:p2", _variant="p2", ownership=["entry/src/main/ets/pages/BPage.ets"])
            err = land_results._depth_check(td, shallow, "impl:d:p1")
            self.assertTrue(err and err.startswith("DEPTH_SHALLOW"), err)
            self.assertIn("APage", err)
            self.assertTrue((td / "spec/reports/depth-selfcheck/land-impl_d_p1.json").is_file())
            self.assertIsNone(land_results._depth_check(td, deep, "impl:d:p2"))
            # 关闭开关（E265-④：质量底线开关只认「带理由关」，裸 false 不予关闭）
            (td / "spec/blueprint/workflow-params.json").write_text(
                json.dumps({"gates": {"depth_selfcheck": False, "depth_selfcheck_off_reason": "实验臂 E0 不测深度"}}),
                encoding="utf-8")
            self.assertIsNone(land_results._depth_check(td, shallow, "impl:d:p1"))

    def test_no_pages_in_ownership_skips(self):
        self.assertIsNone(land_results._depth_check(Path("/nonexistent"), {"ownership": ["entry/src/main/ets/features/d/**"]}, "impl:d:p1"))


class TestBriefText(unittest.TestCase):
    def test_section_on_off(self):
        bp = {"workflow_params": {"gates": {}}}
        txt = ap._depth_selfcheck_text(bp, ["APage", "BPage"], "d-p1")
        self.assertIn("--pages APage,BPage", txt)
        self.assertIn("depth-selfcheck/d-p1.json", txt)
        self.assertIn("RETRY_NEEDED", txt)
        self.assertEqual(ap._depth_selfcheck_text({"workflow_params": {"gates": {"depth_selfcheck": False}}}, ["APage"], "d-p1"), "")
        self.assertEqual(ap._depth_selfcheck_text(bp, [], "d-p1"), "")


if __name__ == "__main__":
    unittest.main()


class TestE214SelfcheckNotForbidden(unittest.TestCase):
    def test_selfcheck_report_is_exempt_from_fence(self):
        import _wavelib
        self.assertFalse(_wavelib.is_forbidden("spec/reports/depth-selfcheck/app-recommend-p1.json"))
        self.assertFalse(_wavelib.is_forbidden("spec/reports/depth-selfcheck/depth-tasks.json"))
        self.assertTrue(_wavelib.is_forbidden("spec/reports/depth-gate.json"))
