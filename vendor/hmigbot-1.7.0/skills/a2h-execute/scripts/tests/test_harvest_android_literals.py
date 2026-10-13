#!/usr/bin/env python3
"""安卓字面量机械收割回归（830 资源管线回填；AIPPT_915_test3 质量对比驱动）。

830 的 string.json 621 条不是 strings.xml（19 条）给的，是逐页从 layout/代码收割的；v915 靠 spec
提取只得 texts=67，worker 拿稀疏台账索性硬编码（223 处 hex）。收割必须机械前置。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
HARVEST = SCRIPTS.parents[1] / "a2h-spec" / "scripts" / "harvest_android_literals.py"
PY = sys.executable or "python3"


def _android(root: Path):
    a = root / "android"
    (a / "app/src/main/res/values").mkdir(parents=True)
    (a / "app/src/main/res/layout").mkdir(parents=True)
    (a / "basic/src/main/platform-res/layout").mkdir(parents=True)   # 变体资源目录
    (a / "app/src/main/java/x").mkdir(parents=True)
    (a / "app/build/res/layout").mkdir(parents=True)                  # 必须被跳过
    (a / "app/src/main/res/values/strings.xml").write_text(
        '<resources><string name="str_about">关于我们</string><string name="fmt">已用 %1$s 次</string></resources>',
        encoding="utf-8")
    (a / "app/src/main/res/values/colors.xml").write_text(
        '<resources><color name="c1">#F7F7F7</color><color name="c2">#ff112233</color></resources>', encoding="utf-8")
    (a / "app/src/main/res/values/dimens.xml").write_text(
        '<resources><dimen name="d1">42dp</dimen></resources>', encoding="utf-8")
    (a / "app/src/main/res/layout/activity_home.xml").write_text(
        '<LinearLayout xmlns:android="x">'
        '<TextView android:text="首页" android:textColor="#333333" android:padding="12dp" android:textSize="@dimen/d1"/>'
        '<TextView android:text="@string/str_about" android:background="@color/c1"/>'
        '<TextView android:hint="@string/fmt"/>'
        '<View android:background="@color/missing"/></LinearLayout>', encoding="utf-8")
    (a / "basic/src/main/platform-res/layout/dialog_x.xml").write_text(
        '<FrameLayout xmlns:android="x"><Button android:text="确定" android:textColor="@color/c2"/></FrameLayout>',
        encoding="utf-8")
    (a / "app/build/res/layout/junk.xml").write_text('<TextView android:text="不该被扫到"/>', encoding="utf-8")
    (a / "app/src/main/java/x/A.kt").write_text(
        'val t = "网络错误"\nval c = Color.parseColor("#FF00FF00")\nval d = 0xFF112233\nval e = "plain"\n'
        'fun show() { setContentView(R.layout.activity_home); DialogXBinding.inflate(layoutInflater) }\n',   # E258：布局被用到
        encoding="utf-8")
    return a


def _project(root: Path):
    (root / "spec/baseline").mkdir(parents=True)
    (root / "spec/toolkit-fact-tree.json").write_text(json.dumps({
        "pages": [{"id": "HomeActivity", "layout_file": "app/src/main/res/layout/activity_home.xml"}],
        "fragments": [], "dialogs": [{"id": "XDialog", "layout_file": "dialog_x.xml"}]}), encoding="utf-8")
    (root / "spec/baseline/literal-ledger.json").write_text(json.dumps({
        "generated_by": "extract_literals", "texts": [{"value": "首页", "sources": ["spec:a"], "page_level": False}],
        "colors": [], "dims": [], "durations_ms": []}), encoding="utf-8")


def _run(root: Path, android: Path):
    return subprocess.run([PY, str(HARVEST), "--project", str(root), "--android-src", str(android), "--json"],
                          capture_output=True, text=True)


class TestHarvest(unittest.TestCase):
    def test_layouts_values_refs_and_variant_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); a = _android(root); _project(root)
            r = _run(root, a)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = json.loads((root / "spec/baseline/android-literals.json").read_text(encoding="utf-8"))
        self.assertEqual(out["layouts"], 2)                       # build/ 下的不算
        home = out["by_layout"]["activity_home.xml"]
        self.assertEqual(home["texts"], ["首页", "关于我们", "已用 %1$s 次"])   # @string 已解析
        self.assertIn("#333333", home["colors"]); self.assertIn("#F7F7F7", home["colors"])   # @color 已解析
        self.assertIn("12dp", home["dims"]); self.assertIn("42dp", home["dims"])           # @dimen 已解析
        self.assertIn("dialog_x.xml", out["by_layout"])            # platform-res 变体目录被扫到
        self.assertEqual(out["by_layout"]["dialog_x.xml"]["colors"], ["#FF112233"])
        self.assertEqual(out["by_page"]["HomeActivity"]["layout"], "activity_home.xml")   # 路径形态
        # values_map：名值对随产物落盘（seed_resources 播种沿用安卓资源名；此前只有计数）
        self.assertEqual(len(out["values_map"]["strings"]), out["values"]["strings"])
        self.assertEqual(out["values_map"]["strings"]["str_about"], "关于我们")
        self.assertEqual(out["values_map"]["colors"]["c2"], "#ff112233")
        self.assertEqual(out["by_page"]["XDialog"]["layout"], "dialog_x.xml")             # 基名形态
        self.assertIn("网络错误", out["code_texts"]); self.assertNotIn("plain", out["code_texts"])
        self.assertIn("#FF00FF00", out["code_colors"]); self.assertIn("#FF112233", out["code_colors"])

    def test_ledger_merge_is_idempotent_and_marks_page_level(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); a = _android(root); _project(root)
            _run(root, a); once = json.loads((root / "spec/baseline/literal-ledger.json").read_text(encoding="utf-8"))
            _run(root, a); twice = json.loads((root / "spec/baseline/literal-ledger.json").read_text(encoding="utf-8"))
        self.assertEqual({k: len(once[k]) for k in ("texts", "colors", "dims")},
                         {k: len(twice[k]) for k in ("texts", "colors", "dims")})
        by = {e["value"]: e for e in once["texts"]}
        self.assertTrue(by["首页"]["page_level"])               # 既有 spec 条目被 layout 来源升为页面级
        self.assertIn("android:layout/activity_home.xml", by["首页"]["sources"])
        self.assertIn("spec:a", by["首页"]["sources"])           # 原来源保留
        self.assertTrue(by["已用 %1$s 次"]["templated"])          # 模板串标记，闸只做前缀漂移
        self.assertFalse(by["网络错误"]["page_level"])            # 代码来源不是页面级

    def test_no_layout_is_failure_not_silent_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "android/app/src/main/java").mkdir(parents=True); _project(root)
            r = _run(root, root / "android")
        self.assertEqual(r.returncode, 1)


class TestE245SyntaxAndCompiledValues(unittest.TestCase):
    """E245：代码字面量语法级抽取；values 只读默认目录、app 覆盖库模块、APK 默认值覆盖源码；按主语言过滤。"""

    def _android(self, root: Path, *, kotlin: str, app_strings: str, lib_dimen: str = "8dp", app_dimen: str = "30dp"):
        a = root / "android"
        (a / "app/src/main/res/values").mkdir(parents=True)
        (a / "app/src/main/res/values-sw").mkdir(parents=True)
        (a / "app/src/main/res/layout").mkdir(parents=True)
        (a / "basic/src/main/res/values").mkdir(parents=True)
        (a / "app/src/main/java/x").mkdir(parents=True)
        (a / "app/build.gradle").write_text("plugins { id 'com.android.application' }", encoding="utf-8")
        (a / "basic/build.gradle").write_text("plugins { id 'com.android.library' }", encoding="utf-8")
        (a / "app/src/main/res/values/strings.xml").write_text(app_strings, encoding="utf-8")
        (a / "app/src/main/res/values-sw/strings.xml").write_text(
            '<resources><string name="copy">Nakili</string></resources>', encoding="utf-8")
        (a / "app/src/main/res/values/dimens.xml").write_text(
            '<resources><dimen name="btn_radius">%s</dimen></resources>' % app_dimen, encoding="utf-8")
        (a / "basic/src/main/res/values/dimens.xml").write_text(
            '<resources><dimen name="btn_radius">%s</dimen></resources>' % lib_dimen, encoding="utf-8")
        (a / "app/src/main/res/layout/a.xml").write_text('<TextView android:text="x"/>', encoding="utf-8")
        (a / "app/src/main/java/x/A.kt").write_text(kotlin, encoding="utf-8")
        return a

    def _harvest(self, root, a):
        (root / "spec/baseline").mkdir(parents=True, exist_ok=True)
        r = _run(root, a)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads((root / "spec/baseline/android-literals.json").read_text(encoding="utf-8"))

    def test_cjk_app_literals_decoded_no_comments_no_templates(self):
        kt = ('// toast("注释里的中文")\n/* show("块注释里的") */\n'
              'val a = "\\uD83C\\uDFEB 教育教学培训"\nval b = "你好 $name"\nval c = "保存成功"\nval d = "Plain english words"\n')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = self._harvest(root, self._android(root, kotlin=kt,
                                app_strings='<resources><string name="copy">复制</string><string name="t">标题</string></resources>'))
        self.assertEqual(out["extraction"]["ui_lang"], "cjk")
        self.assertIn("🏫 教育教学培训", out["code_texts"])
        self.assertIn("保存成功", out["code_texts"])
        for bad in ("注释里的中文", "块注释里的", "你好 $name", "Plain english words"):
            self.assertNotIn(bad, out["code_texts"])
        self.assertEqual(out["extraction"]["code_templates_skipped"], 1)
        self.assertEqual(out["values_map"]["strings"]["copy"], "复制")          # values-sw 不混进默认
        self.assertEqual(out["values_map"]["dimens"]["btn_radius"], "30dp")   # app 覆盖库模块

    def test_latin_app_keeps_natural_sentences_only(self):
        kt = ('val a = "Episode downloaded successfully"\nval b = "SELECT * FROM feeds WHERE id = ?"\n'
              'val c = "https://example.com/feed"\nval d = "TAG"\nval e = "Failed: %1$s"\n')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = self._harvest(root, self._android(root, kotlin=kt,
                                app_strings='<resources><string name="copy">Copy</string><string name="t">Subscriptions \\u2014 all</string></resources>'))
        self.assertEqual(out["extraction"]["ui_lang"], "latin")
        self.assertEqual(out["code_texts"], ["Episode downloaded successfully"])
        self.assertEqual(out["values_map"]["strings"]["t"], "Subscriptions — all")   # aapt \\u 解码

    def test_apk_default_values_override_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = self._android(root, kotlin='val c = "保存成功"\n',
                              app_strings='<resources><string name="copy">复制</string></resources>', app_dimen="30dp")
            apk = root / "spec/a2h/_work/resources-apk/apk-decoded/res/values"
            apk.mkdir(parents=True)
            (apk / "dimens.xml").write_text('<resources><dimen name="btn_radius">31.0dp</dimen></resources>', encoding="utf-8")
            (apk / "strings.xml").write_text('<resources><string name="lib_only">Done</string></resources>', encoding="utf-8")
            out = self._harvest(root, a)
        self.assertEqual(out["extraction"]["values_source"], "apk+source")
        self.assertEqual(out["values_map"]["dimens"]["btn_radius"], "31.0dp")
        self.assertEqual(out["values_map"]["strings"]["lib_only"], "Done")
        self.assertEqual(out["values_map"]["strings"]["copy"], "复制")



class TestE257LayoutNamespaces(unittest.TestCase):
    """E257：布局属性按命名空间 URI 归类——tools（设计期预览）不收；自定义控件的文案属性（app:bar_leftText…）要收。
    ds 实证：50 条 tools:text 假数据被播种、写进任务书「逐条落成 $r()」，退款页拿「40001234344」当回落值；
    「我的」页 7 个 app:bar_leftText 入口文案没收到，E252 因此把它们当 spec 独有降级。"""

    def _run_layout(self, xml: str, strings: str = '<resources><string name="contact">联系我们</string></resources>'):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); a = root / "android"
            (a / "app/src/main/res/values").mkdir(parents=True)
            (a / "app/src/main/res/layout").mkdir(parents=True)
            (a / "app/src/main/res/values/strings.xml").write_text(strings, encoding="utf-8")
            (a / "app/src/main/res/layout/fragment_mine.xml").write_text(xml, encoding="utf-8")
            (root / "spec/baseline").mkdir(parents=True)
            r = _run(root, a)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = json.loads((root / "spec/baseline/android-literals.json").read_text(encoding="utf-8"))
            ledger = json.loads((root / "spec/baseline/literal-ledger.json").read_text(encoding="utf-8"))
        return out, {e["value"] for e in ledger["texts"]}

    def test_custom_text_attrs_in_design_time_out(self):
        xml = ('<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"'
               ' xmlns:app="http://schemas.android.com/apk/res-auto" xmlns:tools="http://schemas.android.com/tools"'
               ' xmlns:tool="http://schemas.android.com/tools">'
               '<TextView android:text="保存本地" tools:text="40001234344" tools:layout_editor_absoluteX="15dp"/>'
               '<com.x.CommonItemBar app:bar_leftText="作品库" app:bar_rightText="@string/contact"'
               ' app:bar_leftTextColor="#FF333333" app:bar_leftTextSize="14sp" app:donut_show_text="true"'
               ' app:bar_titleGravity="center_vertical"/>'
               '<com.google.android.material.textfield.TextInputLayout app:helperText="最多 20 字" app:hintEnabled="false"/>'
               '<TextView android:text="@string/contact" tool:text="张三"/>'
               '</LinearLayout>')
        out, ledger_texts = self._run_layout(xml)
        rec = out["by_layout"]["fragment_mine.xml"]
        self.assertEqual(rec["texts"], ["保存本地", "作品库", "联系我们", "最多 20 字"])
        for bad in ("40001234344", "张三", "true", "center_vertical"):
            self.assertNotIn(bad, rec["texts"])
            self.assertNotIn(bad, ledger_texts)                  # 不进台账，也就不会被闸逼着写进页面
        self.assertIn("#FF333333", rec["colors"])                # 样式属性照旧收色值/尺寸
        self.assertIn("14sp", rec["dims"])
        self.assertNotIn("15dp", rec["dims"])                    # 设计期尺寸同样不收
        self.assertEqual(out["extraction"]["layout_design_time_skipped"], 3)
        self.assertEqual(out["extraction"]["layout_custom_text_attrs"], 3)

    def test_name_tokens(self):
        sys.path.insert(0, str(HARVEST.parent))
        import harvest_android_literals as H
        self.assertTrue(H._custom_text_attr("bar_leftText"))
        self.assertTrue(H._custom_text_attr("srlTextPulling"))
        for n in ("titleTextColor", "hintTextAppearance", "srlTextSizeTitle", "textAllCaps", "donut_show_text",
                  "tl_textBold", "bar_leftIcon"):
            self.assertFalse(H._custom_text_attr(n), n)


if __name__ == "__main__":
    unittest.main()
