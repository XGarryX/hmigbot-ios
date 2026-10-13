#!/usr/bin/env python3
"""E243：skipped[].finding_ref 按本任务书精确匹配（land_results._settle_finding_refs + parse_result 集成）。"""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import land_results as LR  # noqa: E402

BRIEF = """## 待办
- BK-14 首页模板卡接线（owner app-home）
- P-DOM-AR-002 预览页 previewPPTFile
- APPP2-004 分享端口
- S-5 导航边 PPTTemplatePreviewPage→FillPPTQueryDialog
- 自检项 theme-receipt
"""


def _refs(items):
    return [it["finding_ref"] for it in items]


class TestSettle(unittest.TestCase):
    def run_settle(self, refs):
        data = {"skipped": [{"finding_ref": r, "reason": "x"} for r in refs]}
        notes = LR._settle_finding_refs(data, BRIEF)
        return _refs(data["skipped"]), notes

    def test_exact_and_index_pass_without_notes(self):
        refs, notes = self.run_settle(["P-DOM-AR-002", "APPP2-004", "theme-receipt", 3, "7"])
        self.assertEqual(refs, ["P-DOM-AR-002", "APPP2-004", "theme-receipt", 3, "7"])
        self.assertEqual(notes, [])

    def test_composite_extracts_single_brief_id(self):
        refs, notes = self.run_settle(["BK-14-seed", "S-5 / nav_edges:PPTTemplatePreviewPage→FillPPTQueryDialog"])
        self.assertEqual(refs, ["BK-14", "S-5"])
        self.assertTrue(all("抽出" in n for n in notes))

    def test_mangled_or_boundary_or_ambiguous_stay_and_warn(self):
        refs, notes = self.run_settle(["APPP-004", "BK-1", "BK-14 / P-DOM-AR-002", "app-home-p1-sk1"])
        self.assertEqual(refs, ["APPP-004", "BK-1", "BK-14 / P-DOM-AR-002", "app-home-p1-sk1"])
        self.assertEqual(len(notes), 4)
        self.assertTrue(all("unresolved" in n for n in notes))

    def test_no_brief_is_noop(self):
        data = {"skipped": [{"finding_ref": "APPP-004", "reason": "x"}]}
        self.assertEqual(LR._settle_finding_refs(data, None), [])
        self.assertEqual(data["skipped"][0]["finding_ref"], "APPP-004")


class TestParseResultIntegration(unittest.TestCase):
    def test_receipt_not_rejected_and_ref_extracted(self):
        with tempfile.TemporaryDirectory() as td:
            res = Path(td) / "r.json"
            res.write_text(json.dumps({"task": "wiring:app-home", "final_state": "PASS", "files": [],
                                       "skipped": [{"finding_ref": "BK-14-seed", "reason": "outside whitelist"},
                                                   {"finding_ref": "APPP-004", "reason": "gap"}]}, ensure_ascii=False),
                           encoding="utf-8")
            data, err, notes = LR.parse_result(res, "impl", [], "wiring:app-home", brief=BRIEF)
            self.assertIsNone(err, err)
            self.assertEqual(_refs(data["skipped"]), ["BK-14", "APPP-004"])
            self.assertTrue(any("抽出" in n for n in notes) and any("unresolved" in n for n in notes))

    def test_read_brief(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "spec/waves/prompts/w").mkdir(parents=True)
            (root / "spec/waves/prompts/w/t.txt").write_text(BRIEF, encoding="utf-8")
            self.assertEqual(LR._read_brief(root, {"prompt_file": "spec/waves/prompts/w/t.txt"}), BRIEF)
            self.assertIsNone(LR._read_brief(root, {"prompt_file": "missing.txt"}))
            self.assertIsNone(LR._read_brief(root, {}))


class TestExtractionShape(unittest.TestCase):
    def test_domain_and_file_names_are_not_extracted(self):
        brief = BRIEF + "\n域：app-splash-2；配置 module.json5；BK-9 另一条\n"
        data = {"skipped": [{"finding_ref": r, "reason": "x"} for r in ("app-splash-2-p1-bk1", "module.json5-orientation", "BK-9-extra")]}
        notes = LR._settle_finding_refs(data, brief)
        self.assertEqual(_refs(data["skipped"]), ["app-splash-2-p1-bk1", "module.json5-orientation", "BK-9"])
        self.assertEqual(sum("unresolved" in n for n in notes), 2)


if __name__ == "__main__":
    unittest.main()
