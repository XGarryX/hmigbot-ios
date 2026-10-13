# -*- coding: utf-8 -*-
"""E279：状态行必须读判决，不能读文件存在性。

ds4 实测：状态行打印 `handoff=True` 的同一时刻，handoff-check.json 是 ok=False、7 项 blocked，
交棒消息第一行是「BLOCKED…未过本门禁止交棒」。同一函数里 debts 也只数文件名不看内容，
既漏报任务级 RETRY_EXHAUSTED，又把 status=PASS 的审计误计成欠账。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import a2h_run as R  # noqa: E402


def _mk(root: Path, rel: str, obj):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


class TestHandoffVerdict(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_message_file_alone_is_not_pass(self):
        """只有 handoff-message.md、没有判决 → 未判（None），不是 True。"""
        (self.root / "spec/reports").mkdir(parents=True)
        (self.root / "spec/reports/handoff-message.md").write_text("x", encoding="utf-8")
        s = R.status(self.root)
        self.assertIsNone(s["handoff"])
        self.assertTrue(s["handoff_message"])
        self.assertEqual(R._handoff_text(s), "未判")

    def test_blocked_verdict_reported_with_list(self):
        _mk(self.root, "spec/reports/handoff-check.json",
            {"ok": False, "blocked": ["build-graph", "smoke-1page"]})
        (self.root / "spec/reports/handoff-message.md").write_text("x", encoding="utf-8")
        s = R.status(self.root)
        self.assertFalse(s["handoff"])
        self.assertEqual(s["handoff_blocked"], ["build-graph", "smoke-1page"])
        self.assertIn("BLOCKED(build-graph,smoke-1page)", R._handoff_text(s))

    def test_pass_verdict(self):
        _mk(self.root, "spec/reports/handoff-check.json", {"ok": True, "blocked": []})
        s = R.status(self.root)
        self.assertTrue(s["handoff"])
        self.assertEqual(R._handoff_text(s), "PASS")

    def test_unreadable_verdict_is_not_pass(self):
        """读不出=证明不了达标（E265⑧ 同口径），不能当 True。"""
        p = self.root / "spec/reports/handoff-check.json"
        p.parent.mkdir(parents=True)
        p.write_text("{ 坏 json", encoding="utf-8")
        s = R.status(self.root)
        self.assertIsNone(s["handoff"])


class TestDebtByContent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "spec/reports").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_passing_audit_is_not_debt(self):
        """ds4 现场：fence-audit-debt.json 内容 status=PASS/blocking=[]，不该计成欠账。"""
        _mk(self.root, "spec/reports/fence-audit-debt.json",
            {"status": "PASS", "blocking": [], "counts": {"cross_owner": 0}})
        self.assertEqual(R._real_debts(self.root), [])

    def test_blocking_nonempty_is_debt(self):
        _mk(self.root, "spec/reports/x-debt.json", {"status": "PASS", "blocking": ["a"]})
        self.assertEqual(R._real_debts(self.root), ["x-debt.json"])

    def test_fail_status_is_debt(self):
        _mk(self.root, "spec/reports/y-debt.json", {"status": "FAIL", "blocking": []})
        self.assertEqual(R._real_debts(self.root), ["y-debt.json"])

    def test_passed_true_field_also_clears(self):
        """有的报告用 passed:true 而不是 status:PASS（ds4 的 product-write-audit-debt.json）。"""
        _mk(self.root, "spec/reports/p-debt.json", {"passed": True, "blocking": []})
        self.assertEqual(R._real_debts(self.root), [])

    def test_empty_report_is_debt_not_cleared(self):
        """E265⑧：没有通过标记 = 证明不了达标 = 仍算欠账（不能「没 FAIL 就放行」）。"""
        _mk(self.root, "spec/reports/hygiene-debt.json", {})
        self.assertEqual(R._real_debts(self.root), ["hygiene-debt.json"])

    def test_unreadable_counts_as_debt(self):
        p = self.root / "spec/reports/z-debt.json"
        p.write_text("{坏", encoding="utf-8")
        self.assertEqual(R._real_debts(self.root), ["z-debt.json"])

    def test_task_level_retry_exhausted_is_counted(self):
        """ds4 现场：两个任务 status=failed/RETRY_EXHAUSTED，旧口径始终显示欠账 0。"""
        _mk(self.root, "spec/state/state.json", {"waves": {"domains": {"tasks": [
            {"id": "impl:a", "status": "done"},
            {"id": "impl:b", "status": "failed", "reason": "RETRY_EXHAUSTED: WIRES_TODO_UNMET"},
        ]}}})
        self.assertEqual(R._retry_exhausted(self.root), ["domains/impl:b"])

    def test_debt_text_shows_both(self):
        self.assertEqual(R._debt_text({"debts": [], "task_debts": []}), "0 份")
        self.assertEqual(R._debt_text({"debts": ["a"], "task_debts": ["x", "y"]}), "1 份 + 任务级 2")


if __name__ == "__main__":
    unittest.main()
