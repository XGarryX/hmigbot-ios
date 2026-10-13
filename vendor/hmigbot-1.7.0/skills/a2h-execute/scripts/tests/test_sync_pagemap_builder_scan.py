"""sync_pagemap 扫描器回归（第十五批 E22）。
DR_0903 冒烟：规范写法 `@Builder export function XPageBuilder()`（test3 77 处）旧正则不认 → NO_BUILDERS 假 FAIL；
未去注释扫描让被注释掉的一行当 builder → 假 PASS。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import sync_pagemap as S  # noqa: E402


class TestBuilderScan(unittest.TestCase):
    def test_both_orders_recognized_and_comments_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "Home.ets").write_text("@Builder export function HomePageBuilder(): void { HomePage() }\n", encoding="utf-8")
            (d / "Guide.ets").write_text("export @Builder function GuidePageBuilder(): void { GuidePage() }\n", encoding="utf-8")
            (d / "Multi.ets").write_text("@Builder\nexport function MultiPageBuilder(): void {\n  MultiPage()\n}\n", encoding="utf-8")
            (d / "Dead.ets").write_text("// export @Builder function DeadPageBuilder()\n/* @Builder export function GhostPageBuilder() {} */\nstruct Dead {}\n", encoding="utf-8")
            (d / "Bad.ets").write_text("@Builder export function BadPageBuilder(): void { return }\n", encoding="utf-8")
            builders, violations = S.scan_pages(d)
            self.assertEqual(sorted(b["name"] for b in builders), ["BadPageBuilder", "GuidePageBuilder", "HomePageBuilder", "MultiPageBuilder"])
            self.assertEqual([v["builder"] for v in violations], ["BadPageBuilder"])     # 规范写法的 return 检测也生效

    def test_duplicate_builder_names_are_violations(self):
        """E43：AIPPT_0903 test4 适配器 + 页面内同名 PageBuilder → PageMapGen 重复 import 16 错；改为扫描期断言。"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "AppLoadDialogPage.ets").write_text("@Builder export function AppLoadDialogPageBuilder(): void { AppLoadDialogPage() }\n", encoding="utf-8")
            (d / "PageRouteAdapter.ets").write_text("@Builder export function AppLoadDialogPageBuilder(): void { AppLoadDialogPage() }\n"
                                                    "@Builder export function OtherPageBuilder(): void { OtherPage() }\n", encoding="utf-8")
            builders, violations = S.scan_pages(d)
            self.assertEqual(sorted(b["name"] for b in builders), ["AppLoadDialogPageBuilder", "OtherPageBuilder"])   # 去重后只留一个
            self.assertEqual(sorted(v["file"] for v in violations), sorted([str(d / "AppLoadDialogPage.ets"), str(d / "PageRouteAdapter.ets")]))
            self.assertTrue(all("重名" in v["issue"] for v in violations))
            gen = S.gen_pagemap_ets(builders, d)
            self.assertEqual(gen.count("import { AppLoadDialogPageBuilder }"), 1)


class TestE88Report(unittest.TestCase):
    def test_report_written_and_summary_line(self):
        import subprocess, sys as _s, json as _j
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); d = root / "entry/src/main/ets/pages"; d.mkdir(parents=True)
            for i in range(8):
                (d / ("P%dPage.ets" % i)).write_text("@Builder export function P%dPageBuilder(): void { P%dPage() }\n" % (i, i), encoding="utf-8")
            (d / "Adapter.ets").write_text("".join("@Builder export function P%dPageBuilder(): void { P%dPage() }\n" % (i, i) for i in range(8)), encoding="utf-8")
            r = subprocess.run([_s.executable, str(SCRIPTS / "sync_pagemap.py"), "--project", str(root), "--check-only"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            rep = _j.loads((root / "spec/reports/pagemap-check.json").read_text(encoding="utf-8"))
            self.assertEqual(len(rep["violations"]), 16)
            self.assertIn("PageBuilder 重名共 16 处", r.stderr); self.assertIn("pagemap-check.json", r.stderr)


if __name__ == "__main__":
    unittest.main()


class TestRouteNamesAndParams(unittest.TestCase):
    def test_e86_route_aliases_and_e87_default_param(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "AppTipsDialogPage.ets").write_text("@Builder\nexport function AppTipsDialogPageBuilder(): void { AppTipsDialogPage() }\n", encoding="utf-8")
            (d / "LoginPage.ets").write_text("@Builder\nexport function LoginPagePageBuilder(param: object = new LoginRouteParams()): void { LoginPage() }\n", encoding="utf-8")
            builders, violations = S.scan_pages(d)
            self.assertEqual(violations, [])
            routes = dict(S.route_table(builders))
            # 长名（契约页名）与旧短名都登记
            self.assertEqual(set(routes), {"AppTipsDialogPage", "AppTipsDialog", "LoginPagePage", "LoginPage"})
            self.assertEqual(routes["AppTipsDialogPage"]["name"], "AppTipsDialogPageBuilder")
            self.assertEqual(routes["LoginPage"]["name"], "LoginPagePageBuilder")
            gen = S.gen_pagemap_ets(builders, d)
            self.assertIn("if (name === 'AppTipsDialog') {", gen); self.assertIn("} else if (name === 'AppTipsDialogPage') {", gen)
            self.assertIn("LoginPagePageBuilder(param as object)", gen)          # E87：默认值不进 as
            self.assertNotIn("= new", gen)
            self.assertEqual(gen.count("import { AppTipsDialogPageBuilder }"), 1)

    def test_e87_first_param_type_strips_default(self):
        self.assertEqual(S._first_param_type("param: object = new XRouteParams()"), "object")
        self.assertEqual(S._first_param_type("p: PayParams"), "PayParams")
        self.assertIsNone(S._first_param_type(""))


class TestE136ParamTypeImports(unittest.TestCase):
    def test_param_types_are_imported_from_declaring_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); pages = root / "pages"; pages.mkdir(); feat = root / "features" / "works"; feat.mkdir(parents=True)
            (feat / "WorksModels.ets").write_text("export class WorksRouteParams { tab: number = 0 }\nexport interface GuideParams { id: string }\n", encoding="utf-8")
            (pages / "WorksPage.ets").write_text("@Builder export function WorksPageBuilder(params: WorksRouteParams = new WorksRouteParams()): void { WorksPage() }\n", encoding="utf-8")
            (pages / "GuidePage.ets").write_text("@Builder export function GuidePageBuilder(p: GuideParams): void { GuidePage() }\n", encoding="utf-8")
            (pages / "HomePage.ets").write_text("@Builder export function HomePageBuilder(param: object): void { HomePage() }\n", encoding="utf-8")
            (pages / "LostPage.ets").write_text("@Builder export function LostPageBuilder(p: GhostParams): void { LostPage() }\n", encoding="utf-8")
            builders, violations = S.scan_pages(pages); self.assertEqual(violations, [])
            unresolved = []
            gen = S.gen_pagemap_ets(builders, pages, root, unresolved)
            self.assertIn("import { WorksRouteParams } from '../features/works/WorksModels';", gen)
            self.assertIn("import { GuideParams } from '../features/works/WorksModels';", gen)
            self.assertNotIn("import { object }", gen)                                       # 内置类型不 import
            self.assertIn("WorksPageBuilder(param as WorksRouteParams)", gen); self.assertIn("HomePageBuilder(param as object)", gen)
            self.assertEqual([(u["builder"], u["type"]) for u in unresolved], [("LostPageBuilder", "GhostParams")])
            self.assertEqual(gen.count("import { WorksRouteParams }"), 1)
