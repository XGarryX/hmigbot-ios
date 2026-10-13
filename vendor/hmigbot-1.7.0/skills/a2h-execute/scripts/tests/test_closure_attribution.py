#!/usr/bin/env python3
"""closure-backlog 归属链回归（arkTs_diceRoller 2026-08-30 空转事故驱动）。

事故形态：FV-1 扫出 7 条 findings，closure-backlog 只收到 1 条且 owned=0，
closure 波无 owner 可扇出 → 空转到 MAX_ITER 才 escalate，零修复。三处断点：

  ① structural_loop._collect_detector_paths 的 pipeline 清单硬编码只有 5 项，
     与 _REQUIRED_DETECTORS 的 13 项漂移——六道 830 机械闸照常跑、findings 照常写，
     但路径不登记，下游整体收不到；
  ② closure_backlog.owners_of 只读 ownership.json 的 `owners`，看不见
     `mainloop_owned`（导航壳/Ability/module.json5/AppScope/resources 存在那里），
     落在这些面上的缺陷永远判无主；
  ③ 六道闸的 findings 形制是 {severity,code,message}——**无 file 键**，
     而路径按约定写在 message 里（dead_shell/hit_test 形如 "rel:line: ..."）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent.parent / "arkts-structural-closure" / "scripts"))

import closure_backlog as CB  # noqa: E402
import structural_loop as SL  # noqa: E402

# arkTs_diceRoller 实跑的 ownership.json（owners 缺 mainloop 面，全在 mainloop_owned）
OWNERSHIP = {
    "version": 1,
    "owners": {
        "seed": ["entry/src/main/ets/common/Constants.ets"],
        "domain:main": ["entry/src/main/ets/components/main/**",
                        "entry/src/main/ets/pages/MainPage.ets"],
    },
    "mainloop_owned": ["AppScope/**", "entry/src/main/ets/entryability/**",
                       "entry/src/main/ets/pages/Index.ets",
                       "entry/src/main/ets/pages/PageMapGen.ets",
                       "entry/src/main/module.json5",
                       "entry/src/main/resources/**"],
}


class TestDetectorPathCoverage(unittest.TestCase):
    def test_pipeline_paths_cover_required_detectors(self):
        """路径清单必须与必跑集同源——两份清单漂移会静默丢掉整批闸的判决。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wd = root / "wd"
            wd.mkdir()
            for name in SL._REQUIRED_DETECTORS["pipeline"]:
                (wd / f"{name}-pipeline-iter2.json").write_text("{}", encoding="utf-8")
            got = SL._collect_detector_paths(wd, "pipeline", "final", 2, root)
        self.assertEqual(set(got), SL._REQUIRED_DETECTORS["pipeline"])
        for gate in ("theme", "literal", "deadshell", "carrier", "hittest", "resname"):
            self.assertIsNotNone(got.get(gate), f"830 机械闸 {gate} 的产物路径未登记")

    def test_non_pipeline_modes_use_target_scope(self):
        """stage/slice/group 的文件名用 target 作 scope，不能被 pipeline 改法带偏。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wd = root / "wd"
            wd.mkdir()
            (wd / "audit-mytarget-iter1.json").write_text("{}", encoding="utf-8")
            got = SL._collect_detector_paths(wd, "stage", "mytarget", 1, root)
        self.assertEqual(set(got), {"audit"})
        self.assertTrue(got["audit"].endswith("audit-mytarget-iter1.json"))


class TestOwnerSynthesis(unittest.TestCase):
    def test_mainloop_owner_synthesized(self):
        owners = CB.owners_of(OWNERSHIP)
        self.assertIn("mainloop", owners)
        self.assertEqual(
            CB.match_owner("entry/src/main/resources/base/element/string.json", owners),
            "mainloop")

    def test_domain_and_seed_still_win_their_own_globs(self):
        """合成 mainloop 不得抢走既有 owner 的地盘。"""
        owners = CB.owners_of(OWNERSHIP)
        self.assertEqual(CB.match_owner("entry/src/main/ets/pages/MainPage.ets", owners),
                         "domain:main")
        self.assertEqual(CB.match_owner("entry/src/main/ets/common/Constants.ets", owners),
                         "seed")

    def test_no_mainloop_owned_means_no_synthetic_owner_beyond_keynodes(self):
        owners = CB.owners_of({"owners": {"seed": ["a.ets"]}})
        self.assertEqual(set(owners["mainloop"]), set(CB.MAINLOOP_KEYNODES))

    def test_explicit_mainloop_owner_not_overwritten(self):
        own = {"owners": {"mainloop": ["custom/**"]}, "mainloop_owned": ["other/**"]}
        self.assertEqual(CB.owners_of(own)["mainloop"], ["custom/**"])


class TestPathHarvest(unittest.TestCase):
    def test_leading_rel_path_convention(self):
        """dead_shell / hit_test 约定把 rel[:line] 写在 message 句首。"""
        self.assertEqual(
            CB.path_in_text("entry/src/main/ets/pages/MainPage.ets:203: Stack "
                            "HitTestMode.Block 挂在含交互子节点的容器上"),
            "entry/src/main/ets/pages/MainPage.ets")

    def test_embedded_path_in_theme_receipt_message(self):
        self.assertEqual(
            CB.path_in_text("回执 page.background=entry/src/main/ets/pages/MainPage.ets:85 "
                            "的 ±5 行窗口内无对应绑定痕迹"),
            "entry/src/main/ets/pages/MainPage.ets")

    def test_no_path_stays_unowned(self):
        """无路径线索时必须回空——猜一个 owner 会把缺陷误派给无关的人。"""
        self.assertEqual(
            CB.path_in_text("回执缺必填键 action_bar（resolved-theme 推导的收货闭集）"), "")
        self.assertEqual(CB.path_in_text("[Theme.DiceRoller] 状态栏色 #FF3700B3 未绑定"), "")

    def test_non_path_tokens_not_mistaken(self):
        self.assertEqual(CB.path_in_text("模块 entry 的 build 失败"), "")
        self.assertEqual(CB.path_in_text(None, 123, ""), "")


if __name__ == "__main__":
    unittest.main()
