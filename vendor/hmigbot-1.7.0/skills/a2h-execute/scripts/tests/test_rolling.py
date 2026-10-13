#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V20 滚动窗口四件套（AIPPT-v4 实证）：缺 result = 在途 pending 不判违纪；--missing-as-failed /
--stale-minutes 才按缺失落账；batch 元素带 dispatch_prompt 指针；understand 任务 infra 先行；
max_parallel 不写缺省 12。

用法示例:
    python3 -m unittest discover -s arkts-skills/skills/a2h-execute/scripts/tests -v
输入:  复用 KernelFixture 合成工程（subprocess 黑盒）+ generate_waves.build_tasks 纯函数。
输出:  unittest 标准输出。无副作用。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from test_scheduler_kernel import KernelFixture, VALID_BETA, SCRIPTS, LAND_RESULTS

sys.path.insert(0, str(SCRIPTS))
import generate_waves  # noqa: E402


class TestPendingSemantics(KernelFixture):
    """缺 result 的在途任务不被判违纪；显式标记或超时才按缺失处理。"""

    def _land_raw(self, *extra: str) -> dict:
        proc = self._run(LAND_RESULTS, "--plan", str(self.plan_path),
                         "--state", str(self.state), "--json", *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        return json.loads(proc.stdout)

    def test_missing_result_is_pending_not_retry(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("beta", VALID_BETA)                     # alpha 仍在跑
        out = self._land_raw()
        self.assertEqual({r["id"]: r["status"] for r in out["landed"]}, {"impl:beta": "OK"})
        self.assertEqual(out["pending"], ["impl:alpha"])         # 在途，不落账
        act = self.next_batch()                                  # max_parallel=0：非终态未落账 → wait
        self.assertEqual(act["action"], "wait")
        self.assertIn("impl:alpha", act["missing"])
        journal = json.loads((self.proj / "spec/state/journal.json").read_text(encoding="utf-8"))
        self.assertNotIn("RETRY_NEEDED", json.dumps(journal, ensure_ascii=False))  # 未被冤枉

    def test_missing_as_failed_flag_lands_retry(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("beta", VALID_BETA)
        out = self._land_raw("--missing-as-failed", "impl:alpha")
        self.assertEqual({r["id"]: r["status"] for r in out["landed"]},
                         {"impl:alpha": "RETRY_NEEDED", "impl:beta": "OK"})
        self.assertEqual(out["pending"], [])
        act = self.next_batch()
        self.assertEqual(act["action"], "dispatch")             # 重派 alpha
        self.assertEqual([b["id"] for b in act["batch"]], ["impl:alpha"])

    def test_stale_dispatch_is_reported_not_judged(self) -> None:
        """E50：超时在途只报不判（宿主休眠 1h41m 后两个仍存活的代理被 90 分钟阈值误判重派的实证）。"""
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("beta", VALID_BETA)
        out = self._land_raw("--stale-minutes", "0")             # 立即视为超时
        self.assertEqual({r["id"]: r["status"] for r in out["landed"]}, {"impl:beta": "OK"})
        self.assertEqual(out["pending"], ["impl:alpha"])
        self.assertEqual(out["stale_dispatches"], ["impl:alpha"]); self.assertIn("--missing-as-failed impl:alpha", out["stale_hint"])

    def test_stale_dispatch_becomes_retry_only_with_flag(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("beta", VALID_BETA)
        out = self._land_raw("--stale-minutes", "0", "--stale-as-missing")
        self.assertEqual({r["id"]: r["status"] for r in out["landed"]},
                         {"impl:alpha": "RETRY_NEEDED", "impl:beta": "OK"})


class TestDispatchPrompt(KernelFixture):
    def test_batch_entry_carries_pointer_prompt(self) -> None:
        self.write_plan(self.base_plan())
        act = self.next_batch()
        self.assertEqual(act["action"], "dispatch")
        for b in act["batch"]:
            self.assertIn("dispatch_prompt", b)
            self.assertIn("先 Read 该文件全文", b["dispatch_prompt"])
            self.assertIn(b["prompt_file"].split("/")[-1], b["dispatch_prompt"])   # 指向任务书文件


class TestUnderstandOrderAndDefault(unittest.TestCase):
    def test_infra_domains_first(self) -> None:
        bp = {"domain_map": {"domains": [
            {"key": "home", "depends_on_infra": ["net", "common"]},
            {"key": "pay", "depends_on_infra": ["net"]},
            {"key": "net", "depends_on_infra": []},
            {"key": "infra-push", "depends_on_infra": []},
            {"key": "common", "depends_on_infra": []},
        ]}}
        keys = [t["key"] for t in generate_waves.build_tasks(bp, "understand")]
        self.assertEqual(keys[:3], ["net", "infra-push", "common"])   # 被引用者与 infra- 前缀稳定在前
        self.assertEqual(keys[3:], ["home", "pay"])

    def test_default_max_parallel_is_12(self) -> None:
        self.assertEqual(generate_waves.DEFAULT_MAX_PARALLEL, 12)


if __name__ == "__main__":
    unittest.main()
