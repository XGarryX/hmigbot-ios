"""E251：决策缺口 blocking 判定优先级——代理明确写了（布尔 / 文字）即以它为准；类目明确是后端 / 环境（C15/C17、
server/backend）仍强制阻断；关键词兜底只在代理没写时生效。ds 实证：g_id `…dialog-loading-channel` 的 channel 被当「渠道」
判后端阻断，代理在 blocking 里写的是处置说明，domains、auditfix 两波 REDUCE_FAIL。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import merge_gaps as MG  # noqa: E402


class TestPrecedence(unittest.TestCase):
    def test_worker_statement_wins_over_keyword(self):
        prose = "AlgorithmFilingDialog 的 loading 由全局通道驱动；本域不得另造 loading 通道，等全局通道接线后自然可见。"
        self.assertFalse(MG._is_blocking({"g_id": "app-x-dialog-loading-channel", "category": "cross-domain-contract", "blocking": prose}))
        # 裸 false / 没写 → 关键词兜底照旧（v4/v5：代理对后端类缺口习惯性填 false）
        self.assertTrue(MG._is_blocking({"g_id": "app-x-dialog-loading-channel", "category": "ui", "blocking": False}))
        self.assertTrue(MG._is_blocking({"g_id": "app-x-dialog-loading-channel", "category": "ui"}))
        self.assertTrue(MG._is_blocking({"g_id": "GAP-androidid-substitute", "category": "C5", "blocking": "false"}))

    def test_strong_categories_still_force_blocking(self):
        self.assertTrue(MG._is_blocking({"g_id": "g1", "category": "C15", "blocking": False}))
        self.assertTrue(MG._is_blocking({"g_id": "g2", "category": "server-contract", "blocking": "非阻断"}))

    def test_string_normalization(self):
        for v, want in (("true", (True, False)), ("是", (True, False)), ("阻断", (True, False)), ("false", (False, False)),
                        ("非阻断", (False, False)), ("不影响主流程，走全局通道", (False, True)), ("", (None, False)), (None, (None, False))):
            self.assertEqual(MG.worker_blocking(v), want, v)

    def test_cli_report_keeps_note_and_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); res = root / "spec/waves/results/domains"; res.mkdir(parents=True)
            (res / "app-x-p1.json").write_text(json.dumps({"task": "impl:app-x:p1", "decision_gaps": [
                {"g_id": "app-x-dialog-loading-channel", "category": "cross-domain-contract",
                 "blocking": "loading 走全局通道，本域不另造"}]}, ensure_ascii=False), encoding="utf-8")
            r = subprocess.run([sys.executable, str(HERE / "merge_gaps.py"), "--results-dir", str(res), "--json"],
                               capture_output=True, text=True, cwd=root)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            rep = json.loads((root / "spec/reports/decision-gaps.json").read_text(encoding="utf-8"))
            self.assertEqual(rep["blocking"], 0)
            self.assertEqual(rep["gaps"][0]["blocking_note"], "loading 走全局通道，本域不另造")


if __name__ == "__main__":
    unittest.main()
