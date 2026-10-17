#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""host_page A1 假 FAIL 回归：page-names.json 缺席 → launch-deferred（warning，exit 0），infra 波尾重跑落实启动入栈。

AIPPT_token3（2026-09-21）实证：host_page.py 在 A1 同期清单第 3 项与 infra 波尾 reduce:host-page 各跑一次；A1 时
spec/blueprint/page-names.json（A3 产物）必然不存在，启动类 SplashActivity 映射不到鸿蒙页名，旧逻辑记 violation 并 exit 1
（spec/reports/host-page.json ok=false）——每次 A1 都是一条假 FAIL。

用法示例:
    cd a2h-execute/scripts/tests && PYTHONPATH=.. python3 -m unittest test_host_page_launch_deferred
    python3 -m pytest a2h-execute/scripts/tests/test_host_page_launch_deferred.py -q

覆盖:
    A1 跑（无 page-names）→ exit 0 + warning launch-deferred + launch 标记块留 TODO（无 pushPathByName）+ 报告 ok=true；
    infra 波尾重跑（page-names + SplashPageBuilder 页）→ 宿主（本脚本 A1 写的）判 business，launch 块换成 push、TODO 消失、
    imports 块补参数类 import；第三次跑幂等（written/notes 为空、文件字节不变）；
    page-names 已存在但启动类无映射 → 仍是 violation（exit 1）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import host_page as H  # noqa: E402

HELLO_WORLD = """@Entry
@Component
struct Index {
  @State message: string = 'Hello World';
  build() { Row() { Text(this.message) } }
}
"""
ENTRY_ABILITY = """import { UIAbility } from '@kit.AbilityKit';
export default class EntryAbility extends UIAbility {
  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (err) => {});
  }
}
"""
SPLASH_PAGE = """export class SplashPageParams {
  hotLaunch: boolean;
  constructor(hotLaunch: boolean = false) { this.hotLaunch = hotLaunch; }
}
@ComponentV2
export struct SplashPage {
  @Consumer('navPathStack') navPathStack: NavPathStack = new NavPathStack();
  build() { NavDestination() { Text('splash') } }
}
@Builder export function SplashPageBuilder(p: SplashPageParams): void { SplashPage() }
"""


def _w(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class LaunchDeferredFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-hostpage-deferred-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "proj"
        self.ets = self.root / "entry" / "src" / "main" / "ets"
        self.pages = self.ets / "pages"
        self.host = self.pages / "Index.ets"
        self.bp = self.root / "spec" / "blueprint"
        # A1 同期清单第 3 项时的真实盘面：DevEco 骨架 + journeys.json（interface_prefill 产）+ 无 page-names.json
        _w(self.root / "entry" / "src" / "main" / "resources" / "base" / "profile" / "main_pages.json",
           json.dumps({"src": ["pages/Index"]}))
        _w(self.host, HELLO_WORLD)
        _w(self.ets / "entryability" / "EntryAbility.ets", ENTRY_ABILITY)
        _w(self.root / "spec" / "journeys.json", json.dumps({"start": ["SplashActivity"]}))
        self.bp.mkdir(parents=True, exist_ok=True)

    def run_host(self, *args: str) -> dict:
        proc = subprocess.run([sys.executable, str(SCRIPTS / "host_page.py"), "--project", str(self.root), "--json", *args],
                              capture_output=True, text=True, encoding="utf-8", cwd=str(self.root), timeout=120)
        raw = proc.stdout
        out = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        out["_rc"] = proc.returncode
        out["_stderr"] = proc.stderr
        return out

    def a3_page_names(self, mapping: dict) -> None:
        _w(self.bp / "page-names.json", json.dumps({"version": 1, "overrides": {}, "domains": mapping}))


class TestLaunchDeferred(LaunchDeferredFixture):
    def test_a1_then_infra_tail_then_idempotent(self) -> None:
        # ── A1：page-names.json 缺席 → 推迟，不是 FAIL ──
        a1 = self.run_host()
        self.assertEqual(a1["_rc"], 0, a1)
        self.assertTrue(a1["ok"], a1)
        self.assertEqual(a1["violations"], [])
        self.assertTrue(a1["launch_deferred"])
        self.assertIsNone(a1["launch_route"])
        self.assertEqual(a1["launch_android"], "SplashActivity")
        self.assertEqual(a1["host_state"], "template")
        self.assertTrue(any(w.startswith("launch-deferred:") and "infra 波尾 reduce:host-page" in w for w in a1["warnings"]),
                        a1["warnings"])
        self.assertIn("launch-deferred", a1["_stderr"])
        host = self.host.read_text(encoding="utf-8")
        launch_block = host.split(H.MARK_LAUNCH_BEGIN, 1)[1].split(H.MARK_LAUNCH_END, 1)[0]
        self.assertIn("TODO(host_page): launch-deferred", launch_block)
        self.assertIn("SplashActivity", launch_block)
        self.assertNotIn("pushPathByName", host)
        self.assertIn("@Provider('navPathStack') navPathStack: NavPathStack = new NavPathStack();", host)
        self.assertNotIn("Hello World", host)
        report = json.loads((self.root / "spec" / "reports" / "host-page.json").read_text(encoding="utf-8"))
        self.assertTrue(report["ok"])
        self.assertTrue(report["launch_deferred"])

        # ── infra 波尾 reduce:host-page：A3 已产 page-names.json、启动页 builder 已存在 ──
        self.a3_page_names({"app-splash-1": {"LaunchAgreementDialog": "LaunchAgreementDialogPage"},
                            "app-splash-2": {"ShortCutActivity": "ShortCutPage", "SplashActivity": "SplashPage"}})
        _w(self.pages / "SplashPage.ets", SPLASH_PAGE)
        tail = self.run_host()
        self.assertEqual(tail["_rc"], 0, tail)
        self.assertEqual(tail["host_state"], "business")          # A1 由本脚本写成的宿主已有 Navigation(
        self.assertFalse(tail["launch_deferred"])
        self.assertEqual((tail["launch_route"], tail["launch_param"], tail["launch_builder"]),
                         ("SplashPage", "new SplashPageParams()", "SplashPageBuilder"))
        self.assertEqual((tail["violations"], tail["warnings"]), ([], []))
        self.assertIn("entry/src/main/ets/pages/Index.ets", tail["written"])
        host = self.host.read_text(encoding="utf-8")
        self.assertNotIn("TODO(host_page)", host)
        self.assertIn("this.navPathStack.pushPathByName('SplashPage', new SplashPageParams());", host)
        imports_block = host.split(H.MARK_IMPORTS_BEGIN, 1)[1].split(H.MARK_IMPORTS_END, 1)[0]
        self.assertIn("import { SplashPageParams } from './SplashPage';", imports_block)
        self.assertEqual(host.count("@Provider('navPathStack') navPathStack: NavPathStack"), 1)   # 不插第二个 Provider 字段
        self.assertEqual(host.count(H.MARK_LAUNCH_BEGIN), 1)

        # ── 第三次：幂等 ──
        before = self.host.read_bytes()
        third = self.run_host()
        self.assertEqual(third["_rc"], 0, third)
        self.assertEqual((third["written"], third["notes"], third["violations"]), ([], [], []))
        self.assertEqual(self.host.read_bytes(), before)

    def test_a1_rerun_is_idempotent_while_still_deferred(self) -> None:
        self.assertEqual(self.run_host()["_rc"], 0)
        before = self.host.read_bytes()
        again = self.run_host()
        self.assertEqual((again["_rc"], again["written"], again["notes"]), (0, [], []))
        self.assertTrue(again["launch_deferred"])
        self.assertEqual(self.host.read_bytes(), before)

    def test_page_names_present_but_launcher_unmapped_stays_violation(self) -> None:
        self.a3_page_names({"app-home": {"HomeActivity": "HomePage"}})
        out = self.run_host()
        self.assertEqual(out["_rc"], 1, out)
        self.assertFalse(out["launch_deferred"])
        self.assertTrue(any("启动路由未解析" in v["issue"] and "SplashActivity" in v["issue"] for v in out["violations"]),
                        out["violations"])
        self.assertFalse(any(w.startswith("launch-deferred") for w in out["warnings"]))
        self.assertIn("TODO(host_page): 启动路由未解析", self.host.read_text(encoding="utf-8"))

    def test_deferred_also_without_any_launcher_source(self) -> None:
        """A1 早于 interface_prefill（无 journeys）且 fact-tree 无 launcher_short：page-names 缺席时同样推迟。"""
        (self.root / "spec" / "journeys.json").unlink()
        lr = H.resolve_launch(self.root, self.bp)
        self.assertEqual((lr["android"], lr["page"], lr["page_names_present"]), (None, None, False))
        self.assertTrue(H.launch_deferred(lr))
        out = self.run_host()
        self.assertEqual((out["_rc"], out["violations"]), (0, []))
        self.assertTrue(out["launch_deferred"])


if __name__ == "__main__":
    unittest.main()
