# -*- coding: utf-8 -*-
"""落账期自检链（AIPPT_930_token2）：land_results._static_runtime_check 对本任务白名单跑 static_runtime_lint --fix，
剩余 P0 → STATIC_RUNTIME 错误串（走重试配额）、P1/P2 只落报告；_theme_check 对页面块跑 theme_gate --pages，
回执缺项 → THEME_RECEIPT；两者受 gates.static_runtime_check / gates.theme_selfcheck 开关、闸不可用不判。
theme_gate --pages：逐页按 activity 主题推导必填键、只聚合本页分片、detector JSON 带 pages 摘要。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import land_results  # noqa: E402

SVC = """export class ApiService {
  constructor() { this.t = AppStorage.get<string>('token') ?? ''; }
}
export const api = new ApiService();
export class Repo {
  static instance = new ApiService();
}
"""
HOME = """@Entry @ComponentV2 struct HomePage {
  build() {
    Column().backgroundColor($r('app.color.bar'))
      .padding({ top: this.area.topRect.height })
  }
}
"""
THEME = {"themes": {"AppTheme": {"modes": {"day": {
    "decor": {"action_bar": {"visible": True, "background": {"value": "#FF112233"}, "title_color": {"value": "#FFFFFFFF"}},
              "status_bar": {"color": "#FF112233"}},
    "widget_defaults": {"Button": {"corner_radius_dp": {"value": 4}, "background": {"value": "#FF112233"}}}}}}},
    "activities": {"_default": "AppTheme", "HomeActivity": "AppTheme"}}


def make_project(td: Path, gates=None):
    bp = td / "spec/blueprint"; bp.mkdir(parents=True)
    (bp / "workflow-params.json").write_text(json.dumps({"gates": gates or {}}), encoding="utf-8")
    (bp / "page-names.json").write_text(json.dumps({"domains": {"d": {"HomeActivity": "HomePage", "OtherActivity": "OtherPage"}}}), encoding="utf-8")
    ets = td / "entry/src/main/ets"
    (ets / "services").mkdir(parents=True); (ets / "pages").mkdir()
    (ets / "services/ApiService.ets").write_text(SVC, encoding="utf-8")
    (ets / "pages/HomePage.ets").write_text(HOME, encoding="utf-8")
    (ets / "pages/OtherPage.ets").write_text("struct OtherPage { build() { Button('x') } }\n", encoding="utf-8")
    (td / "spec/baseline").mkdir(parents=True)
    (td / "spec/baseline/resolved-theme.json").write_text(json.dumps(THEME), encoding="utf-8")
    return td


class TestStaticRuntimeCheck(unittest.TestCase):
    def test_p0_returns_error_and_fix_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            td = make_project(Path(td))
            node = {"id": "impl:d:p1", "schema": "domainImpl", "_variant": "p1",
                    "ownership": ["entry/src/main/ets/pages/HomePage.ets", "entry/src/main/ets/services/**"]}
            err, fixed = land_results._static_runtime_check(td, node, "impl:d:p1", ["entry/src/main/ets/pages/HomePage.ets"])
            self.assertTrue(err and err.startswith("STATIC_RUNTIME"), err)
            self.assertIn("ApiService.ets:4", err)          # 顶层 export const 仍是 P0
            self.assertIn("惰性 getter", err)
            self.assertTrue((td / "spec/reports/static-runtime/land-impl_d_p1.json").is_file())
            rep = json.loads((td / "spec/reports/static-runtime/land-impl_d_p1.json").read_text(encoding="utf-8"))
            self.assertEqual({x["code"] for x in rep["fixed"]}, {"module-init-runtime-dependency", "avoid-area-px-as-vp"})
            self.assertEqual({x["code"] for x in fixed}, {"module-init-runtime-dependency", "avoid-area-px-as-vp"})
            # --fix 已落盘：static 字段变惰性 getter、padding 包了 px2vp
            self.assertIn("static get instance(): ApiService", (td / "entry/src/main/ets/services/ApiService.ets").read_text(encoding="utf-8"))
            self.assertIn("px2vp(this.area.topRect.height)", (td / "entry/src/main/ets/pages/HomePage.ets").read_text(encoding="utf-8"))
            # 第二次：P0（顶层 const）仍在、fixed 为空
            err2, fixed2 = land_results._static_runtime_check(td, node, "impl:d:p1", None)
            self.assertTrue(err2 and err2.startswith("STATIC_RUNTIME"))
            self.assertEqual(fixed2, [])

    def test_p1_only_no_retry_but_report(self):
        with tempfile.TemporaryDirectory() as td:
            td = make_project(Path(td))
            node = {"id": "impl:d:p2", "schema": "domainImpl", "_variant": "p2", "ownership": ["entry/src/main/ets/pages/HomePage.ets"]}
            err, fixed = land_results._static_runtime_check(td, node, "impl:d:p2", None)
            self.assertIsNone(err)
            self.assertEqual([x["code"] for x in fixed], ["avoid-area-px-as-vp"])
            self.assertTrue((td / "spec/reports/static-runtime/land-impl_d_p2.json").is_file())

    def test_switch_off_and_no_targets(self):
        with tempfile.TemporaryDirectory() as td:
            # E265-④：质量底线开关只认「带理由关」，裸 false 不予关闭
            td = make_project(Path(td), gates={"static_runtime_check": False,
                                               "static_runtime_check_off_reason": "本工程无 ets 产物，实验臂 E0"})
            node = {"id": "impl:d:p1", "schema": "domainImpl", "_variant": "p1", "ownership": ["entry/src/main/ets/services/**"]}
            self.assertEqual(land_results._static_runtime_check(td, node, "impl:d:p1", None), (None, []))
        with tempfile.TemporaryDirectory() as td:
            td = make_project(Path(td))
            node = {"id": "impl:x", "schema": "domainImpl", "ownership": ["entry/src/main/ets/features/nope/**"]}
            self.assertEqual(land_results._static_runtime_check(td, node, "impl:x", ["entry/src/main/ets/pages/HomePage.ets"]), (None, []))

    def test_target_files_declared_outside_ownership_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            td = make_project(Path(td))
            node = {"ownership": ["entry/src/main/ets/pages/OtherPage.ets"]}
            self.assertEqual(land_results._task_target_files(td, node, ["entry/src/main/ets/services/ApiService.ets"]),
                             ["entry/src/main/ets/pages/OtherPage.ets"])
            self.assertEqual(land_results._task_target_files(td, {}, ["entry/src/main/ets/services/ApiService.ets", "spec/x.json"]),
                             ["entry/src/main/ets/services/ApiService.ets"])


class TestThemeCheck(unittest.TestCase):
    def test_missing_receipt_then_satisfied(self):
        with tempfile.TemporaryDirectory() as td:
            td = make_project(Path(td))
            node = {"id": "impl:d:p1", "schema": "domainImpl", "_variant": "p1", "ownership": ["entry/src/main/ets/pages/HomePage.ets"]}
            err = land_results._theme_check(td, node, "impl:d:p1")
            self.assertTrue(err and err.startswith("THEME_RECEIPT"), err)
            self.assertIn("action_bar", err); self.assertIn("status_bar", err); self.assertIn("HomePage", err)
            self.assertNotIn("button_shape", err)   # HomePage 无 Button(
            rep = json.loads((td / "spec/reports/theme-selfcheck/land-impl_d_p1.json").read_text(encoding="utf-8"))
            self.assertEqual(rep["pages"]["HomePage"]["missing"], ["action_bar", "status_bar"])
            self.assertEqual(rep["pages"]["HomePage"]["shards"], [])
            rd = td / "spec/execution/theme-receipts"; rd.mkdir(parents=True)
            (rd / "HomeActivity.json").write_text(json.dumps({"action_bar": "entry/src/main/ets/pages/HomePage.ets:3",
                                                              "status_bar": "entry/src/main/ets/pages/HomePage.ets:3"}), encoding="utf-8")
            self.assertIsNone(land_results._theme_check(td, node, "impl:d:p1"))
            # 悬空回执照样 FAIL
            (rd / "HomeActivity.json").write_text(json.dumps({"action_bar": "entry/src/main/ets/pages/Gone.ets:3",
                                                              "status_bar": "entry/src/main/ets/pages/HomePage.ets:3"}), encoding="utf-8")
            err = land_results._theme_check(td, node, "impl:d:p1")
            self.assertIn("不存在的文件", err or "")

    def test_button_page_requires_shape_and_other_page_shard_not_counted(self):
        with tempfile.TemporaryDirectory() as td:
            td = make_project(Path(td))
            rd = td / "spec/execution/theme-receipts"; rd.mkdir(parents=True)
            (rd / "HomeActivity.json").write_text(json.dumps({"action_bar": "entry/src/main/ets/pages/HomePage.ets:3",
                                                              "status_bar": "entry/src/main/ets/pages/HomePage.ets:3",
                                                              "button_shape": "entry/src/main/ets/pages/HomePage.ets:3"}), encoding="utf-8")
            node = {"id": "impl:d:p2", "schema": "domainImpl", "_variant": "p2", "ownership": ["entry/src/main/ets/pages/OtherPage.ets"]}
            err = land_results._theme_check(td, node, "impl:d:p2")
            self.assertTrue(err and "OtherPage" in err and "button_shape" in err, err)

    def test_switch_off_no_theme_no_pages(self):
        with tempfile.TemporaryDirectory() as td:
            # E265-④：质量底线开关只认「带理由关」，裸 false 不予关闭
            td = make_project(Path(td), gates={"theme_selfcheck": False,
                                               "theme_selfcheck_off_reason": "本工程无主题基线，实验臂 E0"})
            node = {"id": "impl:d:p1", "schema": "domainImpl", "_variant": "p1", "ownership": ["entry/src/main/ets/pages/HomePage.ets"]}
            self.assertIsNone(land_results._theme_check(td, node, "impl:d:p1"))
        with tempfile.TemporaryDirectory() as td:
            td = make_project(Path(td))
            (td / "spec/baseline/resolved-theme.json").unlink()
            node = {"id": "impl:d:p1", "schema": "domainImpl", "_variant": "p1", "ownership": ["entry/src/main/ets/pages/HomePage.ets"]}
            self.assertIsNone(land_results._theme_check(td, node, "impl:d:p1"))
            self.assertIsNone(land_results._theme_check(td, {"ownership": ["entry/src/main/ets/services/**"]}, "impl:i"))


class TestThemeGatePagesCli(unittest.TestCase):
    def test_pages_receipts_only(self):
        with tempfile.TemporaryDirectory() as td:
            td = make_project(Path(td))
            out = td / "tg.json"
            proc = subprocess.run([sys.executable, str(SCRIPTS / "theme_gate.py"), "--project", str(td), "--pages", "HomePage,OtherPage",
                                   "--output-json", str(out), "--json"], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1, proc.stderr)
            rep = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(rep["passed"]); self.assertIn("receipts-only", rep["reason"])
            self.assertEqual(rep["pages"]["HomePage"]["required"], ["action_bar", "status_bar"])
            self.assertEqual(rep["pages"]["OtherPage"]["required"], ["action_bar", "button_shape", "status_bar"])
            self.assertEqual({f["code"] for f in rep["findings"]}, {"theme-receipt-missing"})   # 无工程级色值/形状判定
            # 全局模式不受影响：无 --pages 仍走闭集聚合（任一分片提供即收货）+ 工程级检查
            proc = subprocess.run([sys.executable, str(SCRIPTS / "theme_gate.py"), "--project", str(td), "--output-json", str(out), "--json"],
                                  capture_output=True, text=True)
            rep = json.loads(out.read_text(encoding="utf-8"))
            self.assertNotIn("pages", rep)
            self.assertIn("theme-button-shape-default-capsule", {f["code"] for f in rep["findings"]})


if __name__ == "__main__":
    unittest.main()
