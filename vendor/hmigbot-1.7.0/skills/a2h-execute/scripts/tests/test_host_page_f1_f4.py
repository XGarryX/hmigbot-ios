#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F1 宿主单写 / F4 渲染期静态回退 / F9 product-writes 无人值守阻断 单测。

AIPPT_930_token2（2026-09-21）：DevEco 骨架入口页 pages/MainPage，主会话手拼 Navigation 外壳漏 @Provider('navPathStack')，
59 页各自 new 私有栈、导航全部静默失效而接线闸 38/38 全绿；device_smoke=off 下 handoff_check 把 b4/smoke-1page 全记 skip，
零渲染期检查。

用法示例:
    python3 -m unittest a2h-execute/scripts/tests/test_host_page_f1_f4.py
    python3 -m pytest a2h-execute/scripts/tests/test_host_page_f1_f4.py -q

覆盖:
    host_page     main_pages.json 首项解析 / 缺失回退 pages/Index 并回写；缺失或模板宿主整文件生成（Provider + 启动入栈
                  new X() vs undefined）；业务宿主机械补 Provider / 改绑 / navDestination / 启动入栈；EntryAbility loadContent 改写；
                  幂等；check-only 不写；launch_route 未解析 → violation
    sync_pagemap  宿主按 main_pages 解析；provider-missing 两型判 FAIL；写模式先机械修宿主；host_launch 已注册
    generate_waves  infra 尾 reduce:host-page / gate:resource-coverage（infra 空 → 挂 domains）；closeout off → gate:render-static，hmos 无
    render_static_gate  三段 JSON 形状；宿主缺 Provider → FAIL
    handoff_check   off 档 cold-start / smoke-1page 读 render-static.json 三态；product-writes unattended → blocked
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
import sync_pagemap as S  # noqa: E402
import handoff_check as HC  # noqa: E402

from test_generate_plan import PlanFixture  # noqa: E402

SPLASH_PAGE = """import { NavDestination } from '@kit.ArkUI';
export class SplashPageParams {
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
BUSINESS_HOST = """import { hilog } from '@kit.PerformanceAnalysisKit';

@Entry
@ComponentV2
struct MainPage {
  @Local stack: NavPathStack = new NavPathStack();
  build() {
    Navigation(this.stack) {
      Column() { Text('x') }
    }
    .hideTitleBar(true)
    .mode(NavigationMode.Stack)
  }
}
"""


def _w(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run(script: str, root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), "--project", str(root), *args],
                          capture_output=True, text=True, encoding="utf-8", cwd=str(root), timeout=300)


def _json_out(proc: subprocess.CompletedProcess) -> dict:
    raw = proc.stdout
    return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])


class HostFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-hostpage-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "proj"
        self.ets = self.root / "entry" / "src" / "main" / "ets"
        self.pages = self.ets / "pages"
        self.main_pages = self.root / "entry" / "src" / "main" / "resources" / "base" / "profile" / "main_pages.json"
        self.bp = self.root / "spec" / "blueprint"
        self.pages.mkdir(parents=True)
        _w(self.root / "spec" / "journeys.json", json.dumps({"start": ["SplashActivity"]}))
        _w(self.bp / "page-names.json", json.dumps({"domains": {"app-splash": {"SplashActivity": "SplashPage"}}, "overrides": {}}))

    def host_run(self, *args: str) -> dict:
        proc = _run("host_page.py", self.root, "--json", *args)
        out = _json_out(proc)
        out["_rc"] = proc.returncode
        return out


class TestHostResolution(HostFixture):
    def test_main_pages_first_entry_is_host(self) -> None:
        _w(self.main_pages, json.dumps({"src": ["pages/MainPage"]}))
        h = H.resolve_host(self.root)
        self.assertEqual((h["host_rel"], h["host_name"], h["source"]), ("pages/MainPage", "MainPage", "main_pages"))
        self.assertEqual(h["host_file"], self.pages / "MainPage.ets")

    def test_missing_main_pages_falls_back_and_writes(self) -> None:
        h = H.resolve_host(self.root)
        self.assertEqual((h["host_rel"], h["source"]), ("pages/Index", "fallback"))
        out = self.host_run()
        self.assertEqual(out["_rc"], 0, out)
        self.assertEqual(json.loads(self.main_pages.read_text(encoding="utf-8")), {"src": ["pages/Index"]})
        self.assertEqual(out["host"], "pages/Index")

    def test_launch_route_resolution_chain(self) -> None:
        self.assertEqual(H.resolve_launch(self.root, self.bp)["page"], "SplashPage")
        # journeys 缺 → fact-tree launcher_short；page-names overrides 也算
        (self.root / "spec" / "journeys.json").unlink()
        _w(self.root / "spec" / "toolkit-fact-tree.json", json.dumps({"app": {"launcher_short": "MainActivity"}}))
        _w(self.bp / "page-names.json", json.dumps({"domains": {"x": {}}, "overrides": {"MainActivity": "MainActivityPage"}}))
        lr = H.resolve_launch(self.root, self.bp)
        self.assertEqual((lr["page"], lr["source"]), ("MainActivityPage", "fact-tree.launcher_short"))
        # 全无 → None
        (self.root / "spec" / "toolkit-fact-tree.json").unlink()
        self.assertIsNone(H.resolve_launch(self.root, self.bp)["page"])


class TestHostWrite(HostFixture):
    def test_missing_host_written_with_provider_and_undefined_launch(self) -> None:
        """infra 期：builder 尚不存在 → 传 undefined，无 violation。"""
        out = self.host_run()
        self.assertEqual(out["_rc"], 0, out)
        self.assertEqual((out["host_state"], out["launch_route"], out["launch_param"]), ("missing", "SplashPage", "undefined"))
        host = (self.pages / "Index.ets").read_text(encoding="utf-8")
        self.assertIn("@Provider('navPathStack') navPathStack: NavPathStack = new NavPathStack();", host)
        self.assertIn(".navDestination(AppPageMap)", host)
        self.assertIn("this.navPathStack.pushPathByName('SplashPage', undefined);", host)
        self.assertIn("@Entry\n@ComponentV2\nstruct Index {", host)
        self.assertNotIn("common/Router", host)
        gen = (self.pages / "PageMapGen.ets").read_text(encoding="utf-8")
        self.assertIn("export function AppPageMap(name: string, param: object)", gen)
        self.assertIn("entry/src/main/ets/pages/PageMapGen.ets", out["written"])
        # 幂等
        out2 = self.host_run()
        self.assertEqual((out2["_rc"], out2["written"], out2["notes"]), (0, [], []))

    def test_template_host_replaced_and_new_x_when_ctor_zero_arg(self) -> None:
        _w(self.main_pages, json.dumps({"src": ["pages/Index"]}))
        _w(self.pages / "Index.ets", HELLO_WORLD)
        _w(self.pages / "SplashPage.ets", SPLASH_PAGE)
        out = self.host_run()
        self.assertEqual(out["_rc"], 0, out)
        self.assertEqual((out["host_state"], out["launch_param"], out["launch_builder"]), ("template", "new SplashPageParams()", "SplashPageBuilder"))
        host = (self.pages / "Index.ets").read_text(encoding="utf-8")
        self.assertNotIn("Hello World", host)
        self.assertIn("import { SplashPageParams } from './SplashPage';", host)
        self.assertIn("this.navPathStack.pushPathByName('SplashPage', new SplashPageParams());", host)

    def test_required_ctor_param_gives_undefined_and_violation(self) -> None:
        _w(self.pages / "SplashPage.ets", SPLASH_PAGE.replace("constructor(hotLaunch: boolean = false)", "constructor(hotLaunch: boolean)"))
        out = self.host_run()
        self.assertEqual(out["_rc"], 1, out)
        self.assertEqual(out["launch_param"], "undefined")
        self.assertTrue(any("接受 undefined" in v["issue"] for v in out["violations"]), out["violations"])
        self.assertIn("pushPathByName('SplashPage', undefined)", (self.pages / "Index.ets").read_text(encoding="utf-8"))

    def test_unresolved_launch_route_leaves_todo_and_violation(self) -> None:
        (self.root / "spec" / "journeys.json").unlink()
        out = self.host_run()
        self.assertEqual(out["_rc"], 1, out)
        self.assertIsNone(out["launch_route"])
        self.assertTrue(any("启动路由未解析" in v["issue"] for v in out["violations"]))
        host = (self.pages / "Index.ets").read_text(encoding="utf-8")
        self.assertIn("TODO(host_page)", host)
        self.assertIn("@Provider('navPathStack')", host)
        self.assertNotIn("pushPathByName", host)

    def test_business_host_gets_provider_navdestination_and_launch_mechanically(self) -> None:
        _w(self.main_pages, json.dumps({"src": ["pages/MainPage", "pages/Index"]}))
        _w(self.pages / "MainPage.ets", BUSINESS_HOST)
        _w(self.pages / "Index.ets", HELLO_WORLD)
        _w(self.pages / "SplashPage.ets", SPLASH_PAGE)
        _w(self.ets / "entryability" / "EntryAbility.ets", ENTRY_ABILITY)
        out = self.host_run()
        self.assertEqual(out["_rc"], 0, out)
        self.assertEqual(out["host_state"], "business")
        host = (self.pages / "MainPage.ets").read_text(encoding="utf-8")
        self.assertIn("@Provider('navPathStack') stack: NavPathStack = new NavPathStack();", host)   # 给既有字段加装饰，不插第二个
        self.assertEqual(host.count("NavPathStack = new NavPathStack()"), 1)
        self.assertIn(".navDestination(AppPageMap)", host)
        self.assertIn("import { AppPageMap } from './PageMapGen';", host)
        self.assertIn("this.stack.pushPathByName('SplashPage', new SplashPageParams());", host)   # 用真实字段名
        self.assertIn("import { hilog }", host)                                                  # 块外一行不动
        # Hello World 残留删除 + main_pages 只剩宿主 + loadContent 改写
        self.assertFalse((self.pages / "Index.ets").exists())
        self.assertEqual(out["removed"], ["entry/src/main/ets/pages/Index.ets"])
        self.assertEqual(json.loads(self.main_pages.read_text(encoding="utf-8")), {"src": ["pages/MainPage"]})
        self.assertIn("loadContent('pages/MainPage'", (self.ets / "entryability" / "EntryAbility.ets").read_text(encoding="utf-8"))
        self.assertEqual(out["violations"], [])
        out2 = self.host_run()
        self.assertEqual((out2["written"], out2["removed"], out2["notes"]), ([], [], []))

    def test_business_host_rebinds_navigation_to_existing_provider_field(self) -> None:
        _w(self.main_pages, json.dumps({"src": ["pages/MainPage"]}))
        _w(self.pages / "MainPage.ets", BUSINESS_HOST.replace("@Local stack: NavPathStack = new NavPathStack();",
                                                              "@Provider('navPathStack') navPathStack: NavPathStack = new NavPathStack();\n  private stack: NavPathStack = new NavPathStack();"))
        out = self.host_run()
        self.assertEqual(out["_rc"], 0, out)
        host = (self.pages / "MainPage.ets").read_text(encoding="utf-8")
        self.assertIn("Navigation(this.navPathStack)", host)
        self.assertTrue(any("改绑" in n for n in out["notes"]), out["notes"])

    def test_business_host_without_navigation_is_reported_not_overwritten(self) -> None:
        _w(self.main_pages, json.dumps({"src": ["pages/MainPage"]}))
        big = "@Entry\n@ComponentV2\nstruct MainPage {\n" + "".join("  @Local v%d: number = %d;\n" % (i, i) for i in range(45)) + "  build() { Column() { Text('biz') } }\n}\n"
        _w(self.pages / "MainPage.ets", big)
        out = self.host_run()
        self.assertEqual((out["_rc"], out["host_state"]), (1, "business-no-navigation"))
        self.assertEqual((self.pages / "MainPage.ets").read_text(encoding="utf-8"), big)

    def test_business_page_in_main_pages_is_reported_not_deleted(self) -> None:
        _w(self.main_pages, json.dumps({"src": ["pages/Index", "pages/DetailPage"]}))
        _w(self.pages / "DetailPage.ets", "@Entry\n@ComponentV2\nstruct DetailPage { build() { Column() { Text('d') } } }\n")
        out = self.host_run()
        self.assertEqual(out["_rc"], 1, out)
        self.assertTrue(any("pages/DetailPage" in v["issue"] for v in out["violations"]))
        self.assertEqual(json.loads(self.main_pages.read_text(encoding="utf-8")), {"src": ["pages/Index", "pages/DetailPage"]})

    def test_check_only_writes_nothing_and_reports(self) -> None:
        _w(self.pages / "Index.ets", HELLO_WORLD)
        _w(self.ets / "entryability" / "EntryAbility.ets", ENTRY_ABILITY.replace("pages/Index", "pages/Other"))
        out = self.host_run("--check-only")
        self.assertEqual(out["_rc"], 1, out)
        self.assertEqual(out["written"], [])
        self.assertIn("Hello World", (self.pages / "Index.ets").read_text(encoding="utf-8"))
        issues = " | ".join(v["issue"] for v in out["violations"])
        self.assertIn("模板", issues); self.assertIn("loadContent", issues)
        self.assertTrue((self.root / "spec" / "reports" / "host-page.json").is_file())
        # 写一遍后 check-only 全绿
        self.assertEqual(self.host_run()["_rc"], 0)
        self.assertEqual(self.host_run("--check-only")["_rc"], 0)


class TestSyncPagemapProviders(HostFixture):
    def _seed_pages(self, host_text: str, host_rel: str = "pages/MainPage") -> None:
        _w(self.main_pages, json.dumps({"src": [host_rel]}))
        _w(self.pages / (host_rel.split("/")[-1] + ".ets"), host_text)
        _w(self.pages / "SplashPage.ets", SPLASH_PAGE)

    def test_provider_missing_on_host_fails_check_only(self) -> None:
        self._seed_pages(BUSINESS_HOST)
        proc = _run("sync_pagemap.py", self.root, "--check-only", "--json")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        out = _json_out(proc)
        self.assertEqual(out["host"], "entry/src/main/ets/pages/MainPage.ets")      # 宿主按 main_pages 解析，不再硬编码 Index.ets
        self.assertEqual([v["code"] for v in out["provider_violations"]], ["provider-missing"])
        self.assertIn("MainPage.ets", out["provider_violations"][0]["file"])
        self.assertEqual(sorted(out["consumers"]), ["navPathStack"])
        rep = json.loads((self.root / "spec/reports/pagemap-check.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rep["provider_violations"]), 1); self.assertFalse(rep["ok"])
        self.assertIn("provider-missing", " ".join(str(v) for v in rep["violations"]))

    def test_write_mode_repairs_host_first_then_passes(self) -> None:
        self._seed_pages(BUSINESS_HOST)
        proc = _run("sync_pagemap.py", self.root, "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = _json_out(proc)
        self.assertEqual(out["provider_violations"], [])
        self.assertTrue(out["host_page"]["ok"])
        self.assertEqual(out["host_launch"], {"file": str((self.pages / "MainPage.ets").resolve()), "route": "SplashPage", "registered": True})
        host = (self.pages / "MainPage.ets").read_text(encoding="utf-8")
        self.assertIn("@Provider('navPathStack') stack", host)
        self.assertIn("this.stack.pushPathByName('SplashPage', new SplashPageParams());", host)
        self.assertIn("SplashPageBuilder(param as SplashPageParams)", (self.pages / "PageMapGen.ets").read_text(encoding="utf-8"))

    def test_other_key_consumer_without_provider_fails(self) -> None:
        self._seed_pages(BUSINESS_HOST.replace("@Local stack", "@Provider('navPathStack') stack"))
        _w(self.pages / "SplashPage.ets", SPLASH_PAGE.replace("@Consumer('navPathStack') navPathStack: NavPathStack = new NavPathStack();",
                                                             "@Consumer('navPathStack') navPathStack: NavPathStack = new NavPathStack();\n  @Consumer('homeViewModel') vm: HomeViewModel = new HomeViewModel();"))
        self.assertEqual(_run("host_page.py", self.root, "--json").returncode, 0)     # 宿主先由单写者补启动入栈（check-only 不写）
        proc = _run("sync_pagemap.py", self.root, "--check-only", "--json")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        out = _json_out(proc)
        self.assertEqual([(v["code"], v["builder"]) for v in out["provider_violations"]], [("provider-missing", "homeViewModel")])
        # 有人 @Provider('homeViewModel') 后即过
        _w(self.pages / "HomePage.ets", "@ComponentV2 export struct HomePage { @Provider('homeViewModel') vm: HomeViewModel = new HomeViewModel(); build() { NavDestination() {} } }\n@Builder export function HomePageBuilder(): void { HomePage() }\n")
        proc = _run("sync_pagemap.py", self.root, "--check-only", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(_json_out(proc)["provider_violations"], [])

    def test_unit_reconcile_and_scanner(self) -> None:
        _w(self.pages / "A.ets", "@ComponentV2 struct A { @Consumer('navPathStack') navPathStack: NavPathStack = new NavPathStack(); @Consumer() theme: string = ''; }\n")
        _w(self.pages / "B.ets", "// @Provider('theme') fake\n@ComponentV2 struct B { @Provider('theme') theme: string = 'x'; }\n")
        providers, consumers = S.collect_provider_consumer(self.ets)
        self.assertEqual(sorted(providers), ["theme"]); self.assertEqual(sorted(consumers), ["navPathStack", "theme"])
        v = S.reconcile_providers(self.pages / "Index.ets", providers, consumers)
        self.assertEqual([(x["code"], x["builder"]) for x in v], [("provider-missing", "navPathStack")])   # 宿主不存在但有 consumer
        self.assertEqual(S.reconcile_providers(self.pages / "Index.ets", {}, {}), [])                       # 无宿主无消费者：不报（旧夹具兼容）


class TestGenerateWavesNodes(PlanFixture):
    def _set_smoke(self, tier) -> None:
        wp = json.loads((self.blueprint / "workflow-params.json").read_text(encoding="utf-8"))
        wp.setdefault("gates", {})["device_smoke"] = tier
        self._write(self.blueprint / "workflow-params.json", json.dumps(wp))

    def test_infra_tail_has_host_page_and_resource_coverage_before_build(self) -> None:
        self.gen("infra")
        by_id = {t["id"]: t for t in self.plan("infra")["tasks"]}
        self.assertIn("host_page.py --project . --blueprint spec/blueprint --require-launch --json", by_id["reduce:host-page"]["run"])
        self.assertIn("resource_coverage_gate.py --project . --blueprint spec/blueprint --json", by_id["gate:resource-coverage"]["run"])
        for nid in ("reduce:host-page", "gate:resource-coverage"):
            self.assertEqual(by_id[nid]["parents"], ["@infra-impl"]); self.assertEqual(by_id[nid]["on_fail"], {"escalate": True})
            self.assertIn(nid, by_id["reduce:probe"]["parents"])      # E37：probe 接管 build 的父集
        self.assertTrue(self.lint("infra")["ok"])

    def test_empty_infra_relocates_both_to_domains(self) -> None:
        c = json.loads((self.blueprint / "contracts.json").read_text(encoding="utf-8")); c["modules"] = []
        self._write(self.blueprint / "contracts.json", json.dumps(c))
        o = json.loads((self.blueprint / "ownership.json").read_text(encoding="utf-8")); o["owners"].pop("infra:core", None)
        self._write(self.blueprint / "ownership.json", json.dumps(o))
        self.gen("domains")
        by_id = {t["id"]: t for t in self.plan("domains")["tasks"]}
        for nid in ("gate:contract-sync", "reduce:host-page", "gate:resource-coverage"):
            self.assertEqual(by_id[nid]["parents"], ["@domains-impl"]); self.assertIn(nid, by_id["reduce:probe"]["parents"])
        self.assertTrue(self.lint("domains")["ok"])
        # infra 非空时 domains 不重复挂
        self.gen("domains")

    def test_domains_with_infra_does_not_duplicate(self) -> None:
        self.gen("domains")
        ids = [t["id"] for t in self.plan("domains")["tasks"]]
        self.assertNotIn("reduce:host-page", ids); self.assertNotIn("gate:resource-coverage", ids)

    def test_closeout_off_has_render_static_hmos_not(self) -> None:
        self._set_smoke("off"); self.gen("closeout")
        by_id = {t["id"]: t for t in self.plan("closeout")["tasks"]}
        rs = by_id["gate:render-static"]
        self.assertIn("render_static_gate.py --project . --blueprint spec/blueprint --out spec/reports/smoke/render-static.json --json", rs["run"])
        self.assertEqual((rs["parents"], rs["on_fail"]), (["gate:compile-4"], {"escalate": True}))
        self.assertIn("gate:render-static", by_id["reduce:report"]["parents"])
        self.assertTrue(self.lint("closeout")["ok"])
        self._set_smoke("hmos"); self.gen("closeout")
        by_id = {t["id"]: t for t in self.plan("closeout")["tasks"]}
        self.assertNotIn("gate:render-static", by_id); self.assertIn("gate:cold-start", by_id); self.assertIn("gate:smoke-1page", by_id)
        self.assertNotIn("gate:render-static", by_id["reduce:report"]["parents"])


class TestRenderStaticGate(HostFixture):
    def test_shape_pass_then_fail_on_missing_provider(self) -> None:
        _w(self.main_pages, json.dumps({"src": ["pages/MainPage"]}))
        _w(self.pages / "MainPage.ets", BUSINESS_HOST)
        _w(self.pages / "SplashPage.ets", SPLASH_PAGE)
        self.assertEqual(_run("host_page.py", self.root, "--json").returncode, 0)
        proc = _run("render_static_gate.py", self.root, "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = _json_out(proc)
        self.assertEqual((out["ok"], out["mode"]), (True, "static"))
        self.assertEqual(sorted(out["checks"]), ["host", "pagemap", "runtime_lint"])
        self.assertIn(out["checks"]["runtime_lint"]["status"], ("pass", "skipped"))
        self.assertEqual(out["checks"]["pagemap"]["status"], "pass"); self.assertEqual(out["checks"]["host"]["status"], "pass")
        self.assertEqual(out["findings"], [])
        rep = json.loads((self.root / "spec/reports/smoke/render-static.json").read_text(encoding="utf-8"))
        self.assertTrue(rep["ok"])
        # 宿主 Provider 被人改掉 → 静态回退 FAIL，findings 指到 provider-missing
        p = self.pages / "MainPage.ets"
        p.write_text(p.read_text(encoding="utf-8").replace("@Provider('navPathStack') stack", "@Local stack"), encoding="utf-8")
        proc = _run("render_static_gate.py", self.root, "--json")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        out = _json_out(proc)
        self.assertFalse(out["ok"]); self.assertEqual(out["checks"]["pagemap"]["status"], "fail")
        self.assertIn("provider-missing", [f["code"] for f in out["findings"]])
        self.assertFalse(json.loads((self.root / "spec/reports/smoke/render-static.json").read_text(encoding="utf-8"))["ok"])
        self.assertIn("@Local stack", p.read_text(encoding="utf-8"))      # 门禁只校不写


class TestHandoffStaticFallback(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-handoff-f4-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "proj"
        self.bp = self.root / "spec" / "blueprint"
        _w(self.bp / "domain-map.json", json.dumps({"version": 1, "domains": [{"key": "alpha"}]}))
        self._params(unattended=False)

    def _params(self, unattended: bool) -> None:
        _w(self.bp / "workflow-params.json", json.dumps({"gates": {"device_smoke": "off", "unattended": unattended}}))

    def _by(self) -> dict:
        checks, _ = HC.run_checks(self.root, self.bp)
        return {c["id"]: c for c in checks}

    def test_missing_report_blocks(self) -> None:
        by = self._by()
        for cid in ("cold-start", "smoke-1page"):
            self.assertEqual(by[cid]["status"], "blocked"); self.assertIn("gate:render-static 未跑", by[cid]["detail"])
        self.assertEqual(by["b4"]["status"], "skip")

    def test_ok_report_is_ok_with_static_detail(self) -> None:
        _w(self.root / "spec/reports/smoke/render-static.json", json.dumps({"ok": True, "mode": "static", "checks": {}, "findings": []}))
        by = self._by()
        for cid in ("cold-start", "smoke-1page"):
            self.assertEqual((by[cid]["status"], by[cid]["detail"]), ("ok", "static fallback (device_smoke=off)"))

    def test_failed_report_blocks_with_first_findings(self) -> None:
        _w(self.root / "spec/reports/smoke/render-static.json", json.dumps({"ok": False, "mode": "static", "checks": {}, "findings": [
            {"source": "pagemap", "code": "provider-missing", "file": "pages/MainPage.ets", "message": "x"},
            {"source": "runtime_lint", "code": "module-level-new", "file": "common/Net.ets", "message": "y"}]}))
        by = self._by()
        self.assertEqual(by["smoke-1page"]["status"], "blocked"); self.assertIn("provider-missing pages/MainPage.ets", by["smoke-1page"]["detail"])
        self.assertEqual(by["cold-start"]["status"], "blocked")

    def test_hmos_tier_unchanged(self) -> None:
        _w(self.bp / "workflow-params.json", json.dumps({"gates": {"device_smoke": "hmos"}}))
        by = self._by()
        self.assertNotIn("cold-start", by)
        self.assertEqual(by["smoke-1page"]["status"], "blocked"); self.assertIn("one-page.json 缺失", by["smoke-1page"]["detail"])

    def test_product_writes_blocked_only_when_unattended(self) -> None:
        _w(self.root / "spec/reports/product-write-audit-domains.json", json.dumps(
            {"wave": "domains", "findings": [{"code": "mainloop_edit", "file": "entry/src/main/ets/pages/MainPage.ets"}]}))
        self.assertEqual(self._by()["product-writes"]["status"], "warn")
        self._params(unattended=True)
        c = self._by()["product-writes"]
        self.assertEqual(c["status"], "blocked"); self.assertIn("unattended", c["detail"])
        _w(self.root / "spec/reports/product-write-audit-domains.json", json.dumps({"wave": "domains", "findings": []}))
        self.assertEqual(self._by()["product-writes"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
