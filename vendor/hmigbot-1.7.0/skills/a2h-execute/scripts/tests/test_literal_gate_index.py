"""literal_gate 消费性对账回归（第十五批 E16）。
立此闸的事实：seed_resources 把全部收割文案播进 string.json 后，旧判据「文案出现在 string.json」对任何
文案都成立，闸失去意义。新判据：有资源名的文案只认 $r('app.string.<name>') 引用；裸字面量写在 .ets 记
hardcoded；既无引用也无裸值的页面级文案 FAIL。无资源名的文案沿用旧判据。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "literal_gate.py"


def _project(root: Path):
    el = root / "entry/src/main/resources/base/element"; el.mkdir(parents=True)
    (el / "string.json").write_text(json.dumps({"string": [
        {"name": "btn_ok", "value": "确定"}, {"name": "s_aa", "value": "暂无数据"}, {"name": "s_bb", "value": "退款成功"}]}, ensure_ascii=False), encoding="utf-8")
    (el / "color.json").write_text(json.dumps({"color": []}), encoding="utf-8")
    pages = root / "entry/src/main/ets/pages"; pages.mkdir(parents=True)
    (pages / "A.ets").write_text("Text($r('app.string.btn_ok'))\nText('暂无数据')\n", encoding="utf-8")
    (root / "spec/baseline").mkdir(parents=True)
    (root / "spec/baseline/resource-index.json").write_text(json.dumps({"texts": {"确定": "btn_ok", "暂无数据": "s_aa", "退款成功": "s_bb"}}, ensure_ascii=False), encoding="utf-8")
    (root / "spec/baseline/literal-ledger.json").write_text(json.dumps({"texts": [
        {"value": "确定", "page_level": True, "sources": ["p1"]},
        {"value": "暂无数据", "page_level": True, "sources": ["p1"]},
        {"value": "退款成功", "page_level": True, "sources": ["p2"]},
        {"value": "无资源名文案", "page_level": False, "sources": ["p3"]},
    ], "colors": [], "dims": [], "durations_ms": []}, ensure_ascii=False), encoding="utf-8")


class TestLiteralGateIndex(unittest.TestCase):
    def test_referenced_hardcoded_unreferenced(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _project(root)
            r = subprocess.run([sys.executable, str(SCRIPT), "--project", str(root), "--json",
                                "--output-json", str(root / "out.json")], capture_output=True, text=True)
            rep = json.loads((root / "out.json").read_text(encoding="utf-8"))
            st = rep["stats"]["texts"]
            self.assertEqual((st["referenced"], st["hardcoded"], st["unreferenced_page"]), (1, 1, 1))
            codes = [f["code"] for f in rep["findings"]]
            self.assertIn("literal-text-hardcoded", codes)          # 暂无数据：裸字面量
            self.assertIn("literal-text-unreferenced", codes)       # 退款成功：播种了没人用 → FAIL
            self.assertIn("literal-text-missing-ref", codes)        # 无资源名文案：旧判据 ref 级 WARN
            self.assertEqual(r.returncode, 1)                        # 有 FAIL


if __name__ == "__main__":
    unittest.main()
