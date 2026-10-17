#!/usr/bin/env python3
"""按波固定的 fork_turns 编排参数回归（对照参照运行 2026-08-28 的实际编排）。

参照运行 236 次 spawn_agent 的 fork_turns 逐波零例外：
    understand 28/28、infra 6/6、domains 34/34            → none
    c2 接线 39/39、audit 35/35、fix 48/48、wiring 23/23、
    closeout 10/10                                        → all

前三波是「读安卓源码产 spec」：任务书自带「先 Read 全文，严格按其执行」，是唯一输入，
继承父上下文纯属浪费——12 并行时每个 agent 各背一份 100KB+ 父上下文，还带来污染风险。
后几波是「按既有产物修复/接线」，需要父会话的来龙去脉。

**不写 = 交模型临场决定**，那正是「并行编排需要人工介入」的一部分，故机械落账到计划 IR。
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
CODEX = SCRIPTS.parents[2]

import generate_waves as G  # noqa: E402
import next_batch as NB  # noqa: E402


class TestForkTurnsMapping(unittest.TestCase):
    def test_read_waves_use_none(self):
        for w in ("understand", "infra", "domains"):
            self.assertEqual(G.WAVE_FORK_TURNS.get(w), "none",
                             "%s 波应为 none（任务书是唯一输入）" % w)

    def test_repair_waves_use_all(self):
        for w in ("auditfix", "wiring", "closure", "closeout"):
            self.assertEqual(G.WAVE_FORK_TURNS.get(w), "all",
                             "%s 波应为 all（需要父会话来龙去脉）" % w)

    def test_batch_entry_passes_it_through(self):
        """拍①下发时必须带上——否则主会话只能临场裁量。"""
        e = NB.batch_entry({"id": "x", "agent": "a@1", "fork_turns": "none"}, None)
        self.assertEqual(e.get("fork_turns"), "none")

    def test_absent_is_none_not_crash(self):
        e = NB.batch_entry({"id": "x", "agent": "a@1"}, None)
        self.assertIsNone(e.get("fork_turns"))


class TestWhitelistsAgree(unittest.TestCase):
    """plan.schema.json 与 lint_plan 的字段白名单是两份清单——必须一致。

    今日已因「两份清单漂移」吃过一次亏（structural_loop 的 detector 路径表 5 项 vs
    必跑集 13 项，六道 830 机械闸的判决被整体丢在地上）。此处把同型风险锁住。
    """

    def _schema_agent_props(self):
        s = json.loads((CODEX / "schemas" / "plan.schema.json").read_text(encoding="utf-8"))
        found = []

        def walk(o):
            if isinstance(o, dict):
                props = o.get("properties")
                if isinstance(props, dict) and "ownership" in props:
                    found.append(set(props))
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(s)
        self.assertTrue(found, "未在 schema 中定位到 agent 任务节点")
        return found[0]

    def _lint_allowed(self):
        src = (CODEX / "skills" / "a2h-plan" / "scripts" / "lint_plan.py").read_text(encoding="utf-8")
        m = re.search(r"AGENT_REQUIRED\s*=\s*\(([^)]*)\)", src)
        req = set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()
        m2 = re.search(r"AGENT_ALLOWED\s*=\s*set\(AGENT_REQUIRED\)\s*\|\s*\{([^}]*)\}", src, re.S)
        return req | set(re.findall(r'"([^"]+)"', m2.group(1)))

    def test_schema_and_lint_agent_fields_match(self):
        schema, lint = self._schema_agent_props(), self._lint_allowed()
        self.assertEqual(schema - lint, set(), "schema 有而 lint 白名单缺：合法计划会被门禁拒")
        self.assertEqual(lint - schema, set(), "lint 放行而 schema 缺：违规计划会漏过门禁")

    def test_fork_turns_present_in_both(self):
        self.assertIn("fork_turns", self._schema_agent_props())
        self.assertIn("fork_turns", self._lint_allowed())


if __name__ == "__main__":
    unittest.main()
