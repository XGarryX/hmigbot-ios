"""E249：接线核验四处误判（AIPPT_930_ds 终版 wires-check 未接 5 条全是误判 + 契约 92 条 nav-edge 里 18 对重复）。
① route 边被消费方 import 目标页 struct 并内联渲染也算接通；② 路由名是别的文件里的常量时沿 import 取值；
③ 事实树 / spec 补边的目标类名在起点安卓源码里只出现在注释中 → 丢弃；④ 同 (from,to) 多条按起点页 owner 域去重。
核销一律去注释（注释里写的 push / 渲染示例不算接通）；非页面起点在鸿蒙侧无同名文件 → unresolved。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(SKILLS / "a2h-execute" / "scripts"))
sys.path.insert(0, str(SKILLS / "a2h-spec" / "scripts"))
import verify_wires as VW  # noqa: E402
import interface_prefill as IP  # noqa: E402

A3 = SKILLS / "a2h-plan" / "scripts" / "a3_finalize.py"


def _w(p: Path, t: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(t, encoding="utf-8")


class TestConsumerSide(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.ets = Path(tmp.name) / "entry/src/main/ets"
        _w(self.ets / "pages/TipsPage.ets", "@Builder export function TipsPageBuilder() { TipsPage() }\n"
                                            "@ComponentV2 export struct TipsPage { build() {} }\n")

    def _files(self, page):
        return VW.consumer_files(self.ets, page, None)

    def test_route_edge_rendered_inline_counts_as_wired(self):
        _w(self.ets / "pages/FilePage.ets", "import { TipsPage } from './TipsPage';\n"
                                            "@ComponentV2 struct FilePage { @Local show: boolean = false;\n"
                                            "  build() { Stack() { if (this.show) { TipsPage({ onConfirm: () => {} }) } } } }\n")
        self.assertTrue(VW.consumer_wired(self._files("FilePage"), "TipsPage", "route", aliases=("TipsDialog",)))

    def test_target_own_builder_and_comment_render_do_not_count(self):
        # 目标页自身文件里的 `TipsPage()`（它的 Builder）沿 import 被追进来也不算；注释里的渲染示例不算
        _w(self.ets / "pages/FilePage.ets", "import { TipsPage } from './TipsPage';\n"
                                            "// 以后改成 TipsPage({ onConfirm }) 内联承载\n"
                                            "@ComponentV2 struct FilePage { build() { Text(TipsPage.name) } }\n")
        self.assertFalse(VW.consumer_wired(self._files("FilePage"), "TipsPage", "route", aliases=("TipsDialog",)))

    def test_route_name_from_constant_in_imported_file(self):
        _w(self.ets / "features/mine/MineRouteNames.ets", "export class MineRouteNames {\n"
                                                        "  static readonly MEMBER_CENTER: string = 'MemberCenterPage';\n}\n")
        _w(self.ets / "pages/AccountPage.ets", "import { MineRouteNames } from '../features/mine/MineRouteNames';\n"
                                               "@ComponentV2 struct AccountPage { build() { Button('vip').onClick(() => {\n"
                                               "  this.navPathStack.pushPathByName(MineRouteNames.MEMBER_CENTER, undefined) }) } }\n")
        self.assertTrue(VW.consumer_wired(self._files("AccountPage"), "MemberCenterPage", "route"))
        self.assertFalse(VW.consumer_wired(self._files("AccountPage"), "OtherPage", "route"))

    def test_push_only_in_comment_is_not_wiring(self):
        _w(self.ets / "pages/AboutPage.ets", "/** 导航：`this.navPathStack.pushPathByName('HelpPage', undefined)` */\n"
                                             "@ComponentV2 struct AboutPage { build() {} }\n")
        self.assertFalse(VW.consumer_wired(self._files("AboutPage"), "HelpPage", "route"))


KT_HOME = """package com.x.home
class HomeActivity : BaseActivity() {
    override fun initView() {
        binding.btnPay.setOnClickListener { PayDialog.newInstance().show(supportFragmentManager, "pay") }
        /*if (firstRun) {
            GuideActivity.openGuidePage(this)
        }*/
        // AboutActivity.start(this)
    }
}
"""


class TestEdgeSources(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.android = root / "android"; self.proj = root / "proj"; self.bp = self.proj / "spec/blueprint"
        _w(self.android / "app/src/main/java/com/x/home/HomeActivity.kt", KT_HOME)
        for cls, parent in (("GuideActivity", "BaseActivity"), ("AboutActivity", "BaseActivity"), ("HelpActivity", "BaseActivity")):
            _w(self.android / ("app/src/main/java/com/x/misc/%s.kt" % cls), "package com.x.misc\nclass %s : %s()\n" % (cls, parent))
        _w(self.android / "app/src/main/java/com/x/pay/PayDialog.kt", "package com.x.pay\nclass PayDialog : BaseDialogFragment()\n")
        _w(self.android / "base/src/main/java/com/x/base/Base.kt", "package com.x.base\nopen class BaseActivity : Activity()\nopen class BaseDialogFragment : DialogFragment()\n")
        _w(self.bp / "domain-map.json", json.dumps({"version": 1, "domains": [
            {"key": "home", "spec_file": "spec/domains/home.md", "pages": ["HomeActivity"], "android_files": ["app/src/main/java/com/x/home/HomeActivity.kt"]},
            {"key": "misc", "spec_file": "spec/domains/misc.md", "pages": ["GuideActivity", "AboutActivity", "HelpActivity"],
             "android_files": ["app/src/main/java/com/x/misc/GuideActivity.kt", "app/src/main/java/com/x/misc/AboutActivity.kt",
                               "app/src/main/java/com/x/misc/HelpActivity.kt"]},
            {"key": "pay", "spec_file": "spec/domains/pay.md", "pages": ["PayDialog"], "android_files": ["app/src/main/java/com/x/pay/PayDialog.kt"]}]}))
        _w(self.proj / "spec/toolkit-fact-tree.json", json.dumps({"schema_version": 1,
            "pages": [{"id": "HomeActivity"}, {"id": "GuideActivity"}, {"id": "AboutActivity"}, {"id": "HelpActivity"}], "dialogs": [{"id": "PayDialog"}],
            "flow_graph": {"nodes": [], "edges": [
                {"from": "HomeActivity", "to": "PayDialog", "trigger": "click"},
                {"from": "HomeActivity", "to": "GuideActivity", "trigger": "code"},      # 只在块注释里
                {"from": "HomeActivity", "to": "AboutActivity", "trigger": "click"},     # 只在行注释里
                {"from": "HomeActivity", "to": "HelpActivity", "trigger": "click"}]}}))  # 起点源码没提到（证据在别处）→ 保留
        for n in ("contracts.json", "decisions.json", "ownership.json", "workflow-params.json"):
            _w(self.bp / n, json.dumps({"version": 1, "owners": {}} if n == "ownership.json" else
                                       {"version": 1, "modules": [], "wires": [], "deferred": [], "chains": [], "acceptance": []} if n == "contracts.json" else
                                       {"version": 1, "project": {"android_src": str(self.android)}} if n == "workflow-params.json" else {"version": 1}))
        _w(self.bp / "decision-ledger.md", "# ledger\n")

    def test_prefill_drops_comment_only_fact_tree_edges(self):
        pre = IP.build_prefill(self.proj, self.android)
        edges = {(e["from"], e["to"]) for d in pre["domains"].values() for e in d["nav_edges"]}
        self.assertIn(("HomeActivity", "PayDialog"), edges)
        self.assertIn(("HomeActivity", "HelpActivity"), edges)
        self.assertNotIn(("HomeActivity", "GuideActivity"), edges)
        self.assertNotIn(("HomeActivity", "AboutActivity"), edges)
        self.assertEqual(sorted(d["to"] for d in pre["dropped_edges"]), ["AboutActivity", "GuideActivity"])

    def test_a3_dedupes_by_owner_and_drops_comment_only_spec_edges(self):
        (self.bp / "interface-prefill.json").write_text(json.dumps(IP.build_prefill(self.proj, self.android)), encoding="utf-8")
        # ds 形态：非 owner 域的 spec 也列了别域起点页的边——misc 补 HomeActivity→PayDialog（与 home 预填重复）；
        # pay 补 HomeActivity→GuideActivity（安卓只在块注释里）
        hdr = ("## INTERFACE\n### nav_edges\n| from | to | to_domain | trigger | params | back | modality |\n|---|---|---|---|---|---|---|\n")
        _w(self.proj / "spec/domains/misc.md", "# misc\n\n" + hdr + "| HomeActivity | PayDialog | pay | click | - | - | route |\n")
        _w(self.proj / "spec/domains/pay.md", "# pay\n\n" + hdr + "| HomeActivity | GuideActivity | misc | code | - | - | route |\n")
        _w(self.proj / "spec/domains/home.md", "# home\n\n" + hdr + "| HomeActivity | PayDialog | pay | click | - | - | route |\n")
        r = subprocess.run([sys.executable, str(A3), "--op", "wires", "--blueprint", str(self.bp)], capture_output=True, text=True, cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        nav = [w for w in json.loads((self.bp / "contracts.json").read_text(encoding="utf-8"))["wires"] if w["kind"] == "nav-edge"]
        pay = [w for w in nav if (w["from"], w["to"]) == ("HomeActivity", "PayDialog")]
        self.assertEqual(len(pay), 1)
        self.assertEqual(pay[0]["consumer_domain"], "home")              # 起点页 owner 域那条留下
        self.assertFalse(any(w["to"] == "GuideActivity" for w in nav))   # 注释证据的 spec 补边丢弃
        self.assertIn("重复边去 1 条", r.stdout)
        self.assertIn("注释证据丢弃 1 条", r.stdout)


class TestNavSitesUnresolved(unittest.TestCase):
    def test_non_page_source_without_counterpart_is_unresolved(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td); ets = proj / "entry/src/main/ets"
            _w(ets / "pages/TipsPage.ets", "@Builder export function TipsPageBuilder() { TipsPage() }\n@ComponentV2 struct TipsPage { build() {} }\n")
            _w(proj / "spec/reports/source-inventory.json", json.dumps({
                "files": {"app/src/main/java/x/CheckUpdateService.kt": {"classes": ["CheckUpdateService"]}},
                "classes": {"a": {"name": "CheckUpdateService", "kind": "other"}, "b": {"name": "TipsDialog", "kind": "dialog"}},
                "nav_sites": [{"from_file": "app/src/main/java/x/CheckUpdateService.kt", "to_class": "TipsDialog",
                               "to_file": "app/src/main/java/x/TipsDialog.kt", "to_ui": True}]}))
            rep = VW.verify_nav_sites(proj, ets, {"TipsDialog": "TipsPage"}, {"wires": []})
        self.assertEqual(rep["counts"], {"unresolved": 1})


if __name__ == "__main__":
    unittest.main()
