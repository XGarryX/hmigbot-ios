#!/usr/bin/env python3
"""closure-scan 节点命令形制回归（AIPPT_915_test3 2026-09-01 实证驱动）。

事故：节点用 `;` 把 structural_loop iterate 与 closure_backlog 串成一条 run。但 plan 的
reduce.run 走 shlex.split + subprocess，**不经 shell**——分号连同后半条整体变成了前一条的
参数：

    structural_loop.py: error: unrecognized arguments: ; python3 .../closure_backlog.py ...

后果：扫描跑了、findings 也产出了（13 个 detector 齐全、62 条待办），但**汇账从未执行**，
closure-backlog.json 不生成，closure 修复波无从扇出。本轮靠主会话看到报错后手工补跑
closure_backlog.py 才绕过去——换个项目或换个模型未必会补这一刀。

修法：closure_backlog 增加 --run-iterate 自跑扫描，节点回归单条命令；退出码仍由
closure_backlog 收口（iterate 的 1=CONTINUE 是「要进修复波」，不是失败）。
"""
from __future__ import annotations

import shlex
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import generate_waves as G  # noqa: E402


class TestClosureScanNodeShape(unittest.TestCase):
    def _run(self):
        return G._closure_scan_node("spec/blueprint", [])["run"]

    def test_single_command_no_shell_metachars(self):
        """reduce.run 不经 shell——分号/管道/&& 一律不可用。"""
        run = self._run()
        for ch in (";", "&&", "||", "|"):
            self.assertNotIn(ch, run, "run 含 shell 元字符 %r，subprocess 会当字面参数" % ch)

    def test_shlex_split_yields_one_script(self):
        argv = shlex.split(self._run())
        scripts = [a for a in argv if a.endswith(".py")]
        self.assertEqual(len(scripts), 1, "一个 run 只能调一个脚本，得到 %s" % scripts)
        self.assertTrue(scripts[0].endswith("closure_backlog.py"))

    def test_carries_run_iterate_flag(self):
        """扫描必须由 closure_backlog 自己发起，否则 loop-result 不存在、汇账拿不到输入。"""
        self.assertIn("--run-iterate", self._run())

    def test_max_iter_passed_through(self):
        self.assertIn("--max-iter %d" % G.CLOSURE_MAX_ITER, self._run())

    def test_rescan_node_same_shape(self):
        """closure 波尾的 rescan 节点同源，形制必须一致。"""
        run = G._closure_scan_node("spec/blueprint", [], node_id="gate:closure-rescan")["run"]
        self.assertNotIn(";", run)
        self.assertIn("--run-iterate", run)


class TestReduceRunContract(unittest.TestCase):
    """所有 reduce 节点的 run 都不得依赖 shell——这是执行器的硬约束，不是风格问题。"""

    def test_no_wave_emits_shell_chained_run(self):
        import json, tempfile
        bad = []
        for wave in G.WAVE_ORDER:
            try:
                nodes = G.build_reduces(wave, "spec/blueprint") if hasattr(G, "build_reduces") else []
            except Exception:
                continue
            for n in nodes or []:
                run = str(n.get("run") or "")
                if any(ch in run for ch in (";", "&&", "||")):
                    bad.append((wave, n.get("id")))
        self.assertEqual(bad, [], "这些 reduce 节点的 run 依赖 shell：%s" % bad)


if __name__ == "__main__":
    unittest.main()
