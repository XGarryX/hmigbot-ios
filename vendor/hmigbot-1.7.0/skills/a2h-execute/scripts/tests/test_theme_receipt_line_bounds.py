"""theme_gate 回执行号越界（AIPPT_930 移植）：`file:line` 的 line 为 0/负数时窗口切片退化成文件头部、可能误 PASS；
超出文件行数时只报『无绑定痕迹』误导排查。固定判据：越界行号一律 theme-receipt-format FAIL，合法行号照旧对账。"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "theme_gate.py"
_spec = importlib.util.spec_from_file_location("theme_gate_line_bounds_test", SCRIPT)
TG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(TG)

TARGET = "entry/src/main/ets/pages/HomePage.ets"


def _fixture(root: Path, line) -> None:
    f = root / TARGET
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("@Entry @Component struct HomePage {\n"
                 "  build() {\n"
                 "    Column().backgroundColor($r('app.color.bar'))\n"
                 "  }\n"
                 "}\n", encoding="utf-8")
    r = root / "spec/execution/theme-receipts/HomeActivity.json"
    r.parent.mkdir(parents=True, exist_ok=True)
    r.write_text(json.dumps({"action_bar": "%s:%s" % (TARGET, line)}), encoding="utf-8")


def _findings(root: Path):
    gate = TG.Gate(root)
    gate.check_receipt({"action_bar"})
    return gate.findings


class ReceiptLineBounds(unittest.TestCase):
    def test_zero_negative_and_past_eof_lines_fail_as_format(self):
        for line in (0, -1, 6, 100):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td); _fixture(root, line)
                codes = [f["code"] for f in _findings(root)]
                self.assertIn("theme-receipt-format", codes, line)
                self.assertNotIn("theme-receipt-mismatch", codes, line)

    def test_line_zero_no_longer_passes_on_file_head_window(self):
        # 行号 0 之前会切出 lines[0:5]，恰好含绑定痕迹而静默通过
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _fixture(root, 0)
            self.assertTrue(any(f["severity"] == "FAIL" for f in _findings(root)))

    def test_valid_line_still_binds(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _fixture(root, 3)
            self.assertEqual([f for f in _findings(root) if f["code"].startswith("theme-receipt")], [])

    def test_valid_line_without_binding_is_mismatch_not_format(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _fixture(root, 5)
            (root / TARGET).write_text("\n".join("// filler %d" % i for i in range(20)), encoding="utf-8")
            codes = [f["code"] for f in _findings(root)]
            self.assertIn("theme-receipt-mismatch", codes)
            self.assertNotIn("theme-receipt-format", codes)


if __name__ == "__main__":
    unittest.main()
