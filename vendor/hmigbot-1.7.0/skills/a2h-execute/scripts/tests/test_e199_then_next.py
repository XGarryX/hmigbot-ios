# -*- coding: utf-8 -*-
"""E199（M2 拍④⑤合一）：land_results --then-next 落账后代跑拍①，输出含 action/batch；
之后再亲手跑 next_batch 只得 wait（E41 在途语义不变，不会重派）。"""
from __future__ import annotations

import json
import unittest

from test_scheduler_kernel import KernelFixture, VALID_BETA, LAND_RESULTS, NEXT_BATCH


class TestThenNext(KernelFixture):
    def _land(self, *extra):
        proc = self._run(LAND_RESULTS, "--plan", str(self.plan_path), "--state", str(self.state), *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        return proc

    def test_json_embeds_beat1_action_and_no_double_dispatch(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("beta", VALID_BETA)
        out = json.loads(self._land("--json", "--then-next").stdout)
        nxt = out["next"]
        self.assertTrue(nxt["ran"])
        self.assertEqual(nxt["rc"], 0, nxt)
        self.assertIn(nxt["action"]["action"], ("dispatch", "wait", "gate", "done", "approval", "escalate"))
        # 已在途的任务不会被再吐一次：亲手再跑拍①不出新 batch 里的同一任务
        proc = self._run(NEXT_BATCH, "--plan", str(self.plan_path), "--state", str(self.state), "--json")
        again = json.loads(proc.stdout)
        first_ids = {t["id"] for t in (nxt["action"].get("batch") or [])}
        self.assertFalse(first_ids & {t["id"] for t in (again.get("batch") or [])}, (first_ids, again))

    def test_brief_mode_appends_beat1_text(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("beta", VALID_BETA)
        proc = self._land("--then-next")
        self.assertIn("── 拍①（已代跑，E199）──", proc.stdout)
        self.assertIn("action=", proc.stdout)

    def test_without_flag_unchanged(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("beta", VALID_BETA)
        out = json.loads(self._land("--json").stdout)
        self.assertNotIn("ran", out["next"])
        self.assertIn("next_batch.py", out["next"]["cmd"])


if __name__ == "__main__":
    unittest.main()
