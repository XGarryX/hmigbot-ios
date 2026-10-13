"""DevEco-830 B3：meta.json page_type / needs_immersive_safearea 机械生产回归。
立此闸的事实：schema 有字段、注入代码有、无人生产——830/test3/DR_0903 全缺，产物 expandSafeArea=0。
固定判据：Activity 继承**真穿透**的 BaseActivity（实参取真）→ full_screen_page + true（证据含基类）；E267 起只设字色 / 被开关守住且开关恒 false 的 ImmersionBar 不算；无信号 Activity → false；
Manifest 主题 windowTranslucentStatus → true；DialogFragment → dialog + false；Fragment → fragment + false；幂等：已有字段不覆盖，--force 覆盖。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SPEC = SCRIPTS.parent.parent / "a2h-spec" / "scripts"


def _w(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8")


class TestImmersiveMeta(unittest.TestCase):
    def test_signals_and_idempotence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); android = root / "android"; proj = root / "proj"
            src = android / "app/src/main/java/com/x"
            _w(src / "BaseActivity.kt", "abstract class BaseActivity : AppCompatActivity() {\n  override fun onCreate(s: Bundle?) { immersionBar { transparentStatusBar() } }\n}\n")
            _w(src / "HomeActivity.kt", "class HomeActivity : BaseActivity() {\n  fun x() {}\n}\n")
            _w(src / "PlainActivity.kt", "class PlainActivity : AppCompatActivity() {}\n")
            _w(src / "ThemedActivity.kt", "class ThemedActivity : AppCompatActivity() {}\n")
            _w(src / "PayDialog.kt", "class PayDialog : BottomSheetDialogFragment() {}\n")
            _w(src / "HomeFragment.kt", "class HomeFragment : Fragment() { init { ImmersionBar.with(this) } }\n")
            _w(android / "app/src/main/AndroidManifest.xml", '<manifest><application>\n<activity android:name=".ThemedActivity" android:theme="@style/AppTheme.Immersive"/>\n<activity android:name=".PlainActivity"/>\n</application></manifest>')
            _w(android / "app/src/main/res/values/styles.xml", '<resources>\n<style name="AppTheme" parent="Theme.AppCompat"><item name="colorPrimary">#fff</item></style>\n<style name="AppTheme.Immersive"><item name="android:windowTranslucentStatus">true</item></style>\n</resources>')
            for page, act in (("HomeActivity", "com.x.HomeActivity"), ("PlainActivity", "PlainActivity"), ("ThemedActivity", "com.x.ThemedActivity"),
                              ("PayDialog", "PayDialog"), ("HomeFragment", "com.x.HomeFragment")):
                _w(proj / "spec/ui" / page / "meta.json", json.dumps({"page_id": page, "activity": act, "layout_sources": []}))
            _w(proj / "spec/ui/Pre/meta.json", json.dumps({"activity": "PlainActivity", "page_type": "dialog", "needs_immersive_safearea": True}))
            r = subprocess.run([sys.executable, str(SPEC / "immersive_meta.py"), "--project", str(proj), "--android-src", str(android), "--json"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = json.loads(r.stdout); self.assertEqual(out["stats"]["filled"], 5); self.assertEqual(out["stats"]["kept"], 1)
            def m(page):
                return json.loads((proj / "spec/ui" / page / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual((m("HomeActivity")["page_type"], m("HomeActivity")["needs_immersive_safearea"]), ("full_screen_page", True))
            self.assertTrue(any("transparentStatusBar" in e for e in m("HomeActivity")["immersive_evidence"]))
            self.assertEqual((m("PlainActivity")["page_type"], m("PlainActivity")["needs_immersive_safearea"]), ("full_screen_page", False))
            self.assertEqual(m("ThemedActivity")["needs_immersive_safearea"], True)
            self.assertTrue(any("windowTranslucentStatus" in e for e in m("ThemedActivity")["immersive_evidence"]))
            self.assertEqual((m("PayDialog")["page_type"], m("PayDialog")["needs_immersive_safearea"]), ("dialog", False))
            self.assertEqual((m("HomeFragment")["page_type"], m("HomeFragment")["needs_immersive_safearea"]), ("fragment", False))
            self.assertEqual(m("Pre")["page_type"], "dialog")                       # 幂等：已有字段不覆盖
            r2 = subprocess.run([sys.executable, str(SPEC / "immersive_meta.py"), "--project", str(proj), "--android-src", str(android), "--force", "--json"],
                                capture_output=True, text=True)
            self.assertEqual(json.loads(r2.stdout)["stats"]["filled"], 6)
            self.assertEqual(m("Pre")["page_type"], "full_screen_page")


class TestE267ArgumentValues(unittest.TestCase):
    """E267：ImmersionBar 只看「出现过」→ AIPPT 全 25 页假阳性。只认实参取真的穿透，开关顺基类链查 override。"""

    def _run(self, base_body: str, subs: dict) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); android = root / "android"; proj = root / "proj"
            src = android / "app/src/main/java/com/x"
            _w(src / "BaseBiz.kt", "abstract class BaseBiz : AppCompatActivity() {\n%s\n}\n" % base_body)
            _w(android / "app/src/main/AndroidManifest.xml", "<manifest><application></application></manifest>")
            for page, body in subs.items():
                _w(src / ("%s.kt" % page), "class %s : BaseBiz() {\n%s\n}\n" % (page, body))
                _w(proj / "spec/ui" / page / "meta.json", json.dumps({"page_id": page, "activity": "com.x.%s" % page, "layout_sources": []}))
            r = subprocess.run([sys.executable, str(SPEC / "immersive_meta.py"), "--project", str(proj),
                                "--android-src", str(android), "--json"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return {p: json.loads((proj / "spec/ui" / p / "meta.json").read_text(encoding="utf-8")) for p in subs}

    AIPPT_BASE = ("  protected open var fitWindow = false\n"
                  "  protected open var statusBarTransparent = false\n"
                  "  protected open var fullScreen = false\n"
                  "  protected open fun immersionBar() { immersionBar {\n"
                  "    if (fitWindow) { setFitsSystemWindows() }\n"
                  "    if (statusBarTransparent) { transparentStatusBar() }\n"
                  "    fullScreen(fullScreen)\n"
                  "    statusBarDarkFont(true)\n"
                  "  } }")

    def test_guarded_call_with_gate_off_is_not_immersive(self):
        """AIPPT 真形态：穿透调用被 `if (开关)` 守住、开关全工程无 override → 不判沉浸式。"""
        got = self._run(self.AIPPT_BASE, {"HomeActivity": "  fun x() {}"})
        self.assertEqual(got["HomeActivity"]["needs_immersive_safearea"], False)
        self.assertEqual(got["HomeActivity"]["immersive_evidence"], [])

    def test_gate_overridden_true_is_immersive(self):
        """子类把开关 override 成 true → 判沉浸式，证据点名开关与所在类。"""
        got = self._run(self.AIPPT_BASE, {"SplashActivity": "  override var statusBarTransparent = true"})
        self.assertEqual(got["SplashActivity"]["needs_immersive_safearea"], True)
        self.assertTrue(any("statusBarTransparent=true@SplashActivity" == e for e in got["SplashActivity"]["immersive_evidence"]))

    def test_literal_true_argument_is_immersive(self):
        """无条件 fullScreen(true) 仍算——撤的是「只看名字」，不是「不看这个库」。"""
        got = self._run("  fun go() { immersionBar { fullScreen(true) } }", {"VideoActivity": "  fun x() {}"})
        self.assertEqual(got["VideoActivity"]["needs_immersive_safearea"], True)
        self.assertTrue(any("fullScreen(true)" in e for e in got["VideoActivity"]["immersive_evidence"]))

    def test_dark_font_only_is_not_immersive(self):
        """只设状态栏字色不是穿透。"""
        got = self._run("  fun go() { immersionBar { statusBarDarkFont(true) } }", {"MineActivity": "  fun x() {}"})
        self.assertEqual(got["MineActivity"]["needs_immersive_safearea"], False)


if __name__ == "__main__":
    unittest.main()
