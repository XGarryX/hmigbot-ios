"""E53 回归：binding_gate 形态的 finding（kind/reason/class）进 closure-backlog 后 summary / suggested_action / anchor 不为空；
任务书渲染时无处方也不留空条目。立此闸的事实：AIPPT_0903 test4 closure 三轮 28 条 stack-align-misuse 任务书只剩代号，代理全回 PASS。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import closure_backlog as CB  # noqa: E402


class TestBacklogFields(unittest.TestCase):
    def test_binding_shape_keeps_reason_and_gets_canned_action(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "d.json").write_text(json.dumps({"findings": [
                {"severity": "FAIL", "kind": "stack-align-misuse", "class": "Card:14", "file": "entry/src/main/ets/components/x/Card.ets",
                 "reason": "Card.ets:14 Stack 子组件链上使用 .align(Alignment.…)——只对齐自身内容。改用 Stack({alignContent}) / RelativeContainer"},
                {"severity": "FAIL", "code": "skeleton-L2", "file": "entry/src/main/ets/features/a/A.ets", "message": "空实现", "suggested_action": "补齐 onClick"},
                {"severity": "FAIL", "kind": "weird-code", "file": "entry/src/main/ets/features/a/B.ets", "reason": "说明。改用 Foo 方案"},
            ]}), encoding="utf-8")
            items = CB.collect_findings({"detector_json_paths": {"binding": "d.json"}}, root)
            by = {i["code"]: i for i in items}
            sa = by["stack-align-misuse"]
            self.assertIn("Stack 子组件链", sa["summary"]); self.assertIn("alignContent", sa["suggested_action"]); self.assertEqual(sa["anchor"], "Card:14")
            self.assertEqual(by["skeleton-L2"]["suggested_action"], "补齐 onClick")          # detector 自带处方优先
            self.assertEqual(by["weird-code"]["suggested_action"], "改用 Foo 方案")           # 从说明抽「改用 …」


if __name__ == "__main__":
    unittest.main()
