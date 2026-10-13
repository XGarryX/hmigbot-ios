"""E259 界面形态落账核对 ui_form_lint（E264 后只剩结构性三条）。

离线实验：20 个安卓弹窗做成窗口级 930 20 / token2 6 / ds 3；toast 三次三种写法。
**E264**：全语料误判审计（8 个产物抽查 50 条 P1）判定 `immersive-l3-top` 18/19、`dialog-inline` 11/11 假报，
跨应用判不准且每补一条豁免就翻出漏报 → 整块撤回，这里只剩 `dialog-page-shell` / `dialog-page-mode` /
`toast-builder-context`（审计 0/20 误判，判的是有没有这个结构而不是够不够）。别名伪页、openCustomDialog 用的
@Builder、组件传入的 CustomBuilder 这些误判形态仍作反例锁住。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
LINT = SCRIPTS / "ui_form_lint.py"
sys.path.insert(0, str(SCRIPTS))
import ui_form_lint as U  # noqa: E402

ETS = "entry/src/main/ets/"


def _w(p: Path, t: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(t, encoding="utf-8")


def _project(root: Path):
    bp = root / "spec/blueprint"
    _w(bp / "ui-forms.json", json.dumps({"version": 1, "components": [
        {"android": "PayDialog", "kind": "dialog", "form": "navdest-dialog", "open": "route"},
        {"android": "TipsDialog", "kind": "dialog", "form": "navdest-dialog", "open": "route"},
        {"android": "_promoted_tips", "kind": "alias", "form": "navdest-dialog", "open": "route", "alias_of": ["TipsDialog"]},
    ], "immersive_pages": ["HomeActivity", "MineActivity", "PushActivity", "AboutActivity"], "toast": {"custom": True}}))
    _w(bp / "page-names.json", json.dumps({"version": 1, "domains": {"a": {
        "PayDialog": "PayDialogPage", "TipsDialog": "TipsDialogPage", "_promoted_tips": "PromotedTipsPage",
        "HomeActivity": "HomePage", "MineActivity": "MinePage", "PushActivity": "PushPage", "AboutActivity": "AboutPage"}}}))
    # E264 前提闸：沉浸式判据只在真进了沉浸态的工程上跑——L1 在 EntryAbility、L2 在根 Navigation
    _w(root / (ETS + "entryability/EntryAbility.ets"),
       "export default class EntryAbility extends UIAbility {\n  onWindowStageCreate(stage: window.WindowStage): void {\n"
       "    stage.getMainWindowSync().setWindowLayoutFullScreen(true);\n"
       "    const area = stage.getMainWindowSync().getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM);\n"
       "    WindowModel.ins().windowTopPadding = px2vp(area.topRect.height);\n  }\n}\n")
    _w(root / (ETS + "pages/Index.ets"),
       "@Entry\n@ComponentV2\nstruct Index {\n  build() { Navigation() { }.expandSafeArea([SafeAreaType.SYSTEM]) }\n}\n")
    # 弹窗页：PayDialogPage 是 STANDARD 路由页（缺 DIALOG 模式）；TipsDialogPage 没有 NavDestination 外壳
    _w(root / (ETS + "pages/PayDialogPage.ets"),
       "@ComponentV2\nexport struct PayDialogPage {\n  build() {\n    NavDestination() {\n      Stack() { Text('pay') }\n    }\n"
       "    .hideTitleBar(true)\n  }\n}\n@Builder\nexport function PayDialogPageBuilder(): void { PayDialogPage() }\n")
    _w(root / (ETS + "pages/TipsDialogPage.ets"),
       "@ComponentV2\nexport struct TipsDialogPage {\n  build() { Stack() { Text('tips') }.width('100%').height('100%') }\n}\n")
    _w(root / (ETS + "components/a/PayDialogPage/PayCard.ets"),
       "@ComponentV2\nexport struct PayCard {\n  @Param show: boolean = false;\n  build() { Stack() { Column() { Text('card') } }.width('100%').height('100%') }\n}\n")
    _w(root / (ETS + "components/a/PayDialogPage/PayGuarded.ets"),
       "@ComponentV2\nexport struct PayGuarded {\n  @Param show: boolean = false;\n"
       "  build() { Stack() { if (this.show) { Text('x') } }.hitTestBehavior(this.show ? HitTestMode.Default : HitTestMode.None) }\n}\n")
    _w(root / (ETS + "components/a/PayDialogPage/PayZero.ets"),
       "@ComponentV2\nexport struct PayZero {\n  build() { Column().width($r('app.float.d_0vp')).height($r('app.float.d_0vp')) }\n}\n")
    # 别名伪页：只包一层弹窗组件，不算宿主
    _w(root / (ETS + "pages/PromotedTipsPage.ets"),
       "import { PayCard } from '../components/a/PayDialogPage/PayCard';\n@ComponentV2\nexport struct PromotedTipsPage {\n  build(): void { PayCard() }\n}\n")
    # 宿主页：常驻内联 PayCard（P1）；条件内联（P2）；自带守卫 / 零尺寸（P2）；openCustomDialog 用的 @Builder（不报）
    _w(root / (ETS + "pages/HomePage.ets"),
       "import { PayCard } from '../components/a/PayDialogPage/PayCard';\n"
       "import { PayGuarded } from '../components/a/PayDialogPage/PayGuarded';\n"
       "import { PayZero } from '../components/a/PayDialogPage/PayZero';\n"
       "@ComponentV2\nexport struct HomePage {\n  @Local windowModel: WindowModel = new WindowModel();\n  @Local show: boolean = false;\n"
       "  @Builder dialogBody(): void { PayCard({ show: true }) }\n"
       "  open(): void { this.getUIContext().getPromptAction().openCustomDialog({ builder: (): void => { this.dialogBody(); } }); }\n"
       "  build() {\n    NavDestination() {\n      Stack() {\n        Text('home').padding({ top: this.windowModel.windowTopPadding })\n"
       "        PayCard({ show: this.show })\n        if (this.show) { PayCard({ show: true }) }\n        PayGuarded({ show: this.show })\n"
       "        PayZero()\n      }\n    }\n  }\n}\n")
    # 沉浸式页：MinePage 只做底部避让（P1 top）；AboutPage 用自建 Insets 的 topInset（放行）；PushPage 纯分发页（放行）
    _w(root / (ETS + "pages/MinePage.ets"),
       "@ComponentV2\nexport struct MinePage {\n  @Local windowModel: WindowModel = new WindowModel();\n"
       "  build() { NavDestination() { Column() { Text('mine') }.margin({ bottom: this.windowModel.windowBottomPadding }) } }\n}\n")
    _w(root / (ETS + "pages/AboutPage.ets"),
       "@ComponentV2\nexport struct AboutPage {\n  @Local insets: AboutInsets = new AboutInsets();\n"
       "  build() { NavDestination() { Column() { Text('about') }.padding({ top: this.insets.topInset, bottom: this.insets.bottomInset }) } }\n}\n")
    # 自建 Insets 辅助类：值确实取自系统避让区（E264 反查认它；若全工程没这处赋值 = 恒 0，另有用例判 P1）
    _w(root / (ETS + "components/a/_shared/AboutInsets.ets"),
       "export class AboutInsets {\n  topInset: number = 0;\n  bottomInset: number = 0;\n"
       "  update(w: window.Window): void {\n    const a = w.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM);\n"
       "    this.topInset = px2vp(a.topRect.height);\n    this.bottomInset = px2vp(a.bottomRect.height);\n  }\n}\n")
    _w(root / (ETS + "pages/PushPage.ets"),
       "@ComponentV2\nexport struct PushPage {\n  build() { NavDestination() { Stack() { } } }\n}\n")
    # toast：静态工具里直传全局 @Builder（P1）/ 箭头里直接实例化组件（P1）/ 组件传入的 CustomBuilder（不报）
    _w(root / (ETS + "infra/Toast.ets"),
       "@Builder\nfunction toastBody(): void { Text('t') }\n"
       "export class Toaster {\n  static a(): void { promptAction.openCustomDialog({ builder: toastBody }); }\n"
       "  static b(): void { promptAction.openCustomDialog({ builder: (): void => { PayCard({ show: true }) } }); }\n}\n"
       "export class Host {\n  body: CustomBuilder = undefined;\n  open(ui: UIContext): void { ui.getPromptAction().openCustomDialog({ builder: this.body }); }\n}\n")


class TestUiFormLint(unittest.TestCase):
    def run_lint(self, fix=False):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        _project(root)
        rep = U.analyze(root, None, fix)
        return root, rep

    def by(self, rep):
        out = {}
        for f in rep["findings"]:
            out.setdefault((f["code"], f["severity"]), []).append(f["file"].split("/")[-1])
        return out

    def test_codes_and_precision(self):
        _root, rep = self.run_lint()
        b = self.by(rep)
        self.assertEqual(b.get(("dialog-page-mode", "P1")), ["PayDialogPage.ets"])
        self.assertEqual(b.get(("dialog-page-shell", "P1")), ["TipsDialogPage.ets"])
        self.assertNotIn("PromotedTipsPage.ets", sum(b.values(), []))               # 别名伪页不算宿主
        # E264 撤回：内联渲染与沉浸式避让不再判（跨应用判不准）
        self.assertEqual({k[0] for k in b}, {"dialog-page-mode", "dialog-page-shell", "toast-builder-context"})
        self.assertEqual(b.get(("toast-builder-context", "P1")), ["Toast.ets", "Toast.ets"])   # this.body 不报
        self.assertFalse(rep["ok"])

    def test_fix_inserts_dialog_mode(self):
        root, rep = self.run_lint(fix=True)
        self.assertEqual([x["code"] for x in rep["fixed"]], ["dialog-page-mode"])
        txt = (root / (ETS + "pages/PayDialogPage.ets")).read_text(encoding="utf-8")
        self.assertIn("}\n    .mode(NavDestinationMode.DIALOG)\n    .hideTitleBar(true)", txt)
        self.assertNotIn(("dialog-page-mode", "P1"), self.by(rep))
        new, n = U.fix_dialog_mode("NavDestination() { Text('x') }.mode(NavDestinationMode.STANDARD)")
        self.assertEqual((n, "NavDestinationMode.DIALOG" in new, "STANDARD" in new), (1, True, False))

    def test_cli_files_scope_and_no_forms(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _project(root)
            r = subprocess.run([sys.executable, str(LINT), "--project", str(root), "--files", ETS + "pages/TipsDialogPage.ets", "--json"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stderr)
            rep = json.loads(r.stdout)
            self.assertEqual({f["code"] for f in rep["findings"]}, {"dialog-page-shell"})
            (root / "spec/blueprint/ui-forms.json").unlink()
            r = subprocess.run([sys.executable, str(LINT), "--project", str(root), "--json"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(json.loads(r.stdout)["skipped"], "no ui-forms.json")


class TestLandResultsHook(unittest.TestCase):
    def test_ui_form_check_retry_and_fixed_files(self):
        import land_results as LR
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _project(root)
            node = {"id": "impl:a:p1", "ownership": [ETS + "pages/PayDialogPage.ets", ETS + "pages/TipsDialogPage.ets"]}
            err, fixed = LR._ui_form_check(root, node, "impl:a:p1", [ETS + "pages/PayDialogPage.ets", ETS + "pages/TipsDialogPage.ets"])
            self.assertTrue(err.startswith("UI_FORM:"), err)
            self.assertIn("dialog-page-shell", err)                                  # 没有 NavDestination 外壳，机械补不了 → 退回
            self.assertNotIn("dialog-page-mode", err)                                # 机械补掉了，不退回
            self.assertEqual([x["file"] for x in fixed], [ETS + "pages/PayDialogPage.ets"])
            self.assertTrue((root / "spec/reports/ui-form/land-impl_a_p1.json").is_file())


if __name__ == "__main__":
    unittest.main()
