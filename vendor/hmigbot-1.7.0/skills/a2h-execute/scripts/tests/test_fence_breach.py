#!/usr/bin/env python3
"""写盘围栏落账核验回归（land_results.fence_breach）。

立此闸的事实：ownership 白名单原先只进任务书（模型自觉遵守）、只用于 findings 归因
与续跑守卫，落账侧从不复核——围栏是散文约束。单域项目看不出；大项目并行扇出时
两个 worker 写同一文件会互相覆盖（设计里已标 P0）。

固定判据：
  · arkTs_diceRoller 实跑回执 fix:mainloop 的 4 个文件全在自身围栏内 → **必须零误报**
    （误报会让每轮落账都刷警告，闸随即被无视，等于没有）；
  · 越界写到同波另一任务地盘 → cross_owner（并发覆盖风险，最严重档）；
  · 越界写到无人认领的共享面 → unowned（记债待复核）；
  · 节点未声明 ownership → 不臆造约束，返回空；
  · 反斜杠路径先归一再判，不因 Windows 回执误报。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import land_results as L  # noqa: E402

# 取自 arkTs_diceRoller 2026-08-30 实跑的 plan-auditfix.json（两任务两围栏）
BY_ID = {
    "fix:main": {
        "id": "fix:main", "kind": "agent",
        "ownership": ["entry/src/main/ets/components/main/**",
                      "entry/src/main/ets/pages/MainPage.ets"],
    },
    "fix:mainloop": {
        "id": "fix:mainloop", "kind": "agent",
        "ownership": ["AppScope/**", "entry/src/main/ets/entryability/**",
                      "entry/src/main/ets/pages/Index.ets",
                      "entry/src/main/ets/pages/PageMapGen.ets",
                      "entry/src/main/module.json5",
                      "entry/src/main/resources/**",
                      "entry/src/main/ets/common/Constants.ets",
                      "entry/src/main/ets/common/ThemeTokens.ets",
                      "entry/src/main/ets/common/HttpCore.ets"],
    },
}
# fix:mainloop 实跑真实 files_touched
REAL_FILES = ["AppScope/app.json5", "entry/src/main/module.json5",
              "entry/src/main/ets/pages/Index.ets",
              "entry/src/main/ets/common/HttpCore.ets"]


class TestFenceBreach(unittest.TestCase):
    def test_real_receipt_no_false_positive(self):
        """实跑回执四文件全在围栏内——一条都不许报。"""
        self.assertEqual(L.fence_breach(BY_ID["fix:mainloop"], REAL_FILES, BY_ID), [])

    def test_cross_owner_detected(self):
        got = L.fence_breach(BY_ID["fix:mainloop"],
                             ["entry/src/main/ets/pages/MainPage.ets"], BY_ID)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["kind"], "cross_owner")
        self.assertEqual(got[0]["owner"], "fix:main")

    def test_unowned_recorded_as_debt(self):
        got = L.fence_breach(BY_ID["fix:mainloop"], ["build-profile.json5"], BY_ID)
        self.assertEqual([(g["file"], g["kind"]) for g in got],
                         [("build-profile.json5", "unowned")])
        self.assertNotIn("owner", got[0])

    def test_no_ownership_declared_means_no_constraint(self):
        """未声明围栏的节点不臆造约束——否则 reduce/无围栏波会被误判。"""
        self.assertEqual(L.fence_breach({"id": "x", "kind": "agent"},
                                        ["anything.ets"], BY_ID), [])

    def test_backslash_path_normalized(self):
        self.assertEqual(L.fence_breach(BY_ID["fix:mainloop"],
                                        ["entry\\src\\main\\module.json5"], BY_ID), [])

    def test_glob_star_star_matches_nested(self):
        self.assertEqual(L.fence_breach(BY_ID["fix:main"],
                                        ["entry/src/main/ets/components/main/a/b/C.ets"],
                                        BY_ID), [])


if __name__ == "__main__":
    unittest.main()
