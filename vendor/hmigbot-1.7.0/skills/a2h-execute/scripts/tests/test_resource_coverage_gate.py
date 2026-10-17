#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resource_coverage_gate.py 回归：安卓源码引用集 vs 鸿蒙 resources 现有集。

缺一个 → FAIL missing-resource；有状态 selector 只剩一个文件 → FAIL selector-flattened；
库/APK 才有的名字缺席只 WARN；dimen 数值漂移只 WARN；期望集为空 → FAIL；安卓根不可得 → exit 2。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import resource_coverage_gate as gate  # noqa: E402

PY = sys.executable or "python3"
SCRIPT = SCRIPTS / "resource_coverage_gate.py"


def _w(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_android(root: Path) -> Path:
    a = root / "android"
    res = a / "app/src/main/res"
    _w(res / "values/strings.xml", '<resources><string name="hello">Hi</string><string name="bad-name">x</string></resources>')
    _w(res / "values/colors.xml", '<resources><color name="primary">#111111</color></resources>')
    _w(res / "values/dimens.xml", '<resources><dimen name="pad">16dp</dimen></resources>')
    _w(res / "values/arrays.xml", '<resources><string-array name="opts"><item>a</item></string-array><integer-array name="nums"><item>1</item></integer-array></resources>')
    _w(res / "layout/activity_main.xml",
       '<LinearLayout xmlns:android="x" android:text="@string/hello" android:background="@drawable/bg" '
       'android:textColor="@color/primary" android:padding="@dimen/pad" android:src="@mipmap/ic_launcher" '
       'android:foo="@android:color/white" android:id="@+id/root" android:theme="@style/AppTheme" android:x="@string/bad-name"/>')
    _w(res / "menu/main.xml", '<menu xmlns:android="x"><item android:icon="@drawable/ic_share" android:title="@string/lib_title"/></menu>')
    _w(res / "drawable/bg.xml", '<shape xmlns:android="x"><solid android:color="@color/primary"/></shape>')
    _w(res / "drawable/toggle.xml", '<selector xmlns:android="x"><item android:state_checked="true" android:drawable="@drawable/bg"/><item android:drawable="@drawable/bg"/></selector>')
    _w(res / "mipmap-xxhdpi/ic_launcher.png", "png")
    _w(res / "raw/data.json", "{}")
    _w(res / "font/my_font.ttf", "ttf")
    _w(a / "app/src/main/AndroidManifest.xml", '<manifest android:label="@string/hello" android:icon="@mipmap/ic_launcher"/>')
    _w(a / "app/src/main/java/x/Main.kt",
       "val a = R.string.hello\nval b = com.x.R.array.opts\nval c = R.array.nums\nval d = R.plurals.items\n"
       "val e = R.raw.data\nval f = R.font.my_font\nval g = android.R.string.ok\nval h = R.id.root\nval i = R.layout.activity_main\n"
       "val j = R.drawable.toggle\nval k = R.integer.max_n\nval l = R.bool.flag\n")
    _w(a / "app/build/generated/R.java", "int x = R.string.generated_junk;")
    _w(a / "app/src/test/java/T.kt", "val t = R.string.test_only")
    return a


def make_hmos(root: Path, *, full: bool = True) -> Path:
    p = root / "hmos"
    res = p / "entry/src/main/resources"

    def el(q, kind, rows):
        _w(res / q / "element" / ("%s.json" % kind), json.dumps({kind: rows}))

    el("base", "string", [{"name": "hello", "value": "Hi"}, {"name": "bad_name", "value": "x"}, {"name": "lib_title", "value": "L"}])
    el("base", "color", [{"name": "primary", "value": "#FF111111"}])
    el("base", "float", [{"name": "pad", "value": "16vp"}])
    el("base", "strarray", [{"name": "opts", "value": [{"value": "a"}]}])
    el("base", "intarray", [{"name": "nums", "value": [{"value": 1}]}])
    el("base", "plural", [{"name": "items", "value": [{"quantity": "other", "value": "%d"}]}])
    el("base", "integer", [{"name": "max_n", "value": 3}])
    el("base", "boolean", [{"name": "flag", "value": True}])
    _w(res / "base/media/bg.svg", "<svg/>")
    _w(res / "base/media/toggle.svg", "<svg/>")
    if full:
        _w(res / "base/media/toggle_checked.svg", "<svg/>")
    _w(res / "base/media/ic_share.svg", "<svg/>")
    _w(res / "xxldpi/media/ic_launcher.png", "png")
    _w(res / "rawfile/data.json", "{}")
    _w(res / "rawfile/fonts/my_font.ttf", "ttf")
    _w(p / "spec/reports/resource-conversion.json", json.dumps({"selectors": {
        "toggle": {"default": "base/media/toggle.svg", "states": {"checked": "base/media/toggle_checked.svg"} if full else {},
                   "stateful": True, "source": "app/src/main/res/drawable/toggle.xml"},
        "flat_ok": {"default": "base/media/bg.svg", "states": {}, "stateful": False}}}))
    _w(p / "spec/baseline/android-literals.json", json.dumps({"values_map": {"dimens": {"pad": "16dp"}, "strings": {}, "colors": {}}}))
    return p


def run(*args, cwd=None):
    return subprocess.run([PY, str(SCRIPT), *args], capture_output=True, text=True, cwd=cwd)


class Gate(unittest.TestCase):
    def test_pass_full(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a, p = make_android(root), make_hmos(root)
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            rep = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertTrue(rep["ok"])
            self.assertEqual(rep["missing"], [])
            self.assertEqual(rep["selector_flattened"], [])
            self.assertEqual(rep["coverage_ratio"], 1.0)
            self.assertEqual(rep["retry_hint"], gate.RETRY_HINT)
            exp = json.loads((p / "spec/reports/resource-coverage.json").read_text())["expected"]
            # id/layout/style/@android: 不计；build/ 与 test/ 不扫
            self.assertEqual(exp, rep["expected"])
            self.assertTrue((p / "spec/reports/resource-coverage.json").is_file())
            self.assertIn("PASS resource-coverage", r.stderr)

    def test_expected_set_excludes_noise(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a = make_android(root)
            expected, defined = gate.scan_android(a)
            names = {(t, n) for (t, n) in expected}
            self.assertIn(("string", "hello"), names)
            self.assertIn(("array", "opts"), names)
            self.assertIn(("plurals", "items"), names)
            self.assertIn(("raw", "data"), names)
            self.assertIn(("font", "my_font"), names)
            self.assertIn(("drawable", "ic_share"), names)
            self.assertIn(("mipmap", "ic_launcher"), names)
            self.assertIn(("string", "bad-name"), names)
            for bad in (("string", "ok"), ("string", "generated_junk"), ("string", "test_only")):
                self.assertNotIn(bad, names)
            self.assertFalse(any(t in ("id", "layout", "style") for t, _ in names))
            self.assertEqual(expected[("string", "hello")], "app/src/main/AndroidManifest.xml")
            self.assertIn(("string", "hello"), defined)
            self.assertIn(("array", "opts"), defined)
            self.assertIn(("array", "nums"), defined)
            self.assertIn(("font", "my_font"), defined)
            self.assertIn(("raw", "data"), defined)
            self.assertIn(("drawable", "toggle"), defined)
            self.assertIn(("mipmap", "ic_launcher"), defined)
            self.assertNotIn(("drawable", "ic_share"), defined)

    def test_missing_resource_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a, p = make_android(root), make_hmos(root)
            (p / "entry/src/main/resources/base/media/bg.svg").unlink()
            (p / "entry/src/main/resources/base/element/float.json").unlink()
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 1)
            rep = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertFalse(rep["ok"])
            miss = {(m["type"], m["name"]): m for m in rep["missing"]}
            self.assertIn(("drawable", "bg"), miss)
            self.assertIn(("dimen", "pad"), miss)
            self.assertEqual(miss[("drawable", "bg")]["item"], "missing-resource")
            self.assertTrue(miss[("drawable", "bg")]["file"].endswith(".xml"))   # 首见文件（按路径排序：drawable/toggle.xml）
            self.assertTrue(miss[("dimen", "pad")]["file"].endswith("layout/activity_main.xml"))
            self.assertLess(rep["coverage_ratio"], 1.0)
            self.assertIn("missing=2", r.stderr)

    def test_library_only_is_warn(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a, p = make_android(root), make_hmos(root)
            (p / "entry/src/main/resources/base/media/ic_share.svg").unlink()   # 只在 menu 里引用，安卓工程没定义
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            rep = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertTrue(rep["ok"])
            w = [x for x in rep["warnings"] if x["item"] == "library-resource-missing"]
            self.assertEqual([(x["type"], x["name"]) for x in w], [("drawable", "ic_share")])
            self.assertLess(rep["coverage_ratio"], 1.0)

    def test_selector_flattened_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a, p = make_android(root), make_hmos(root, full=False)
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 1)
            rep = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertEqual(rep["missing"], [])
            self.assertEqual(len(rep["selector_flattened"]), 1)
            self.assertEqual(rep["selector_flattened"][0]["name"], "toggle")
            self.assertEqual(rep["selector_flattened"][0]["files"], ["base/media/toggle.svg"])

    def test_dimen_drift_warns(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a, p = make_android(root), make_hmos(root)
            _w(p / "entry/src/main/resources/base/element/float.json", json.dumps({"float": [{"name": "pad", "value": "18vp"}]}))
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            rep = json.loads(r.stdout.strip().splitlines()[-1])
            drift = [x for x in rep["warnings"] if x["item"] == "dimen-value-drift"]
            self.assertEqual(len(drift), 1)
            self.assertEqual((drift[0]["android"], drift[0]["harmony"]), ("16dp", "18vp"))

    def test_android_src_from_workflow_params_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a, p = make_android(root), make_hmos(root)
            r = run("--project", str(p), "--json")
            self.assertEqual(r.returncode, 2)
            self.assertIn("android", r.stderr.lower())
            self.assertIn("--android-src", r.stderr)
            _w(p / "spec/blueprint/workflow-params.json", json.dumps({"project": {"android_src": str(a)}}))
            r = run("--project", str(p), "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            r = run("--project", str(p), "--android-src", str(root / "nope"), "--json")
            self.assertEqual(r.returncode, 2)

    def test_empty_expected_set_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a = root / "android"
            _w(a / "app/src/main/java/Nothing.kt", "val x = 1\n")
            p = make_hmos(root)
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 1)
            rep = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertFalse(rep["ok"])
            self.assertEqual(rep["expected"], 0)
            self.assertIn("expected set is empty", rep["reason"])
            self.assertIn("expected set is empty", r.stderr)

    def test_sanitize_agrees_with_converter(self):
        conv = SCRIPTS.parents[1] / "android2hmos_resources_convert" / "scripts"
        self.assertTrue((conv / "convert_resources.py").is_file())
        sys.path.insert(0, str(conv))
        from convert_resources import sanitize_name as conv_sanitize  # noqa: E402
        for n in ("$mtrl_x__0", "ic-a.b", "9start", "ok_name", "", "$$", "zh-rCN", "a b"):
            self.assertEqual(gate._local_sanitize(n), conv_sanitize(n), n)
            self.assertEqual(gate.sanitize_name(n), conv_sanitize(n), n)


class SelectorFallback(unittest.TestCase):
    """E225 补：有状态 selector 的真值直接从安卓源码推导，不依赖 convert_resources 的报告。"""

    def test_flattened_detected_without_conversion_report(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a, p = make_android(root), make_hmos(root)
            rep_path = p / "spec/reports/resource-conversion.json"
            if rep_path.is_file():
                rep_path.unlink()
            media = p / "entry/src/main/resources/base/media"
            for f in media.glob("toggle_*"):
                f.unlink()
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 1, r.stderr + r.stdout)
            rep = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertEqual([x["name"] for x in rep["selector_flattened"]], ["toggle"])
            self.assertEqual(rep["selector_flattened"][0]["source"], "app/src/main/res/drawable/toggle.xml")

    def test_color_state_list_requires_state_entries(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a, p = make_android(root), make_hmos(root)
            _w(a / "app/src/main/res/color/txt_sel.xml",
               '<selector xmlns:android="x"><item android:state_pressed="true" android:color="#ff0000"/><item android:color="#000000"/></selector>')
            _w(a / "app/src/main/java/x/C.kt", "val z = R.color.txt_sel\n")
            cj = p / "entry/src/main/resources/base/element/color.json"
            data = json.loads(cj.read_text(encoding="utf-8"))
            data["color"].append({"name": "txt_sel", "value": "#ff000000"})
            cj.write_text(json.dumps(data), encoding="utf-8")
            r = run("--project", str(p), "--android-src", str(a), "--json")
            rep = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertIn("txt_sel", [x["name"] for x in rep["selector_flattened"]])
            data["color"].append({"name": "txt_sel_pressed", "value": "#ffff0000"})
            cj.write_text(json.dumps(data), encoding="utf-8")
            r2 = run("--project", str(p), "--android-src", str(a), "--json")
            rep2 = json.loads(r2.stdout.strip().splitlines()[-1])
            self.assertNotIn("txt_sel", [x["name"] for x in rep2["selector_flattened"]])

    def test_scan_android_selectors_ignores_stateless(self):
        with tempfile.TemporaryDirectory() as d:
            a = make_android(Path(d))
            _w(a / "app/src/main/res/drawable/plain_sel.xml",
               '<selector xmlns:android="x"><item android:drawable="@drawable/bg"/></selector>')
            sel = gate.scan_android_selectors(a)
            self.assertIn("toggle", sel)
            self.assertNotIn("plain_sel", sel)


def _conv_report(p: Path, **fields):
    """改写转换报告（保留 make_hmos 写的 selectors）。"""
    rp = p / "spec/reports/resource-conversion.json"
    data = json.loads(rp.read_text(encoding="utf-8")) if rp.is_file() else {}
    data.update(fields)
    _w(rp, json.dumps(data))


def _apk_file(path: Path, mtime: float = 1_700_000_000.0) -> Path:
    _w(path, "PK-fake")
    os.utime(str(path), (mtime, mtime))
    return path


def _rep(r):
    return json.loads(r.stdout.strip().splitlines()[-1])


class ApkUsage(unittest.TestCase):
    """AIPPT_token3：有现成 APK 却只转了源码 res（344 vs 1780 个文件），库资源只 WARN，闸照过。"""

    def test_report_says_apk_available_but_unused_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a, p = make_android(root), make_hmos(root)
            _conv_report(p, resource_source="source_res", apk_available=True,
                         apk={"path": "/x/app-debug.apk", "decompile": "failed:java not found"})
            (p / "entry/src/main/resources/base/media/ic_share.svg").unlink()     # 只有库/APK 才有的名字
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 1, r.stderr)
            rep = _rep(r)
            self.assertFalse(rep["ok"])
            anu = rep["apk_not_used"]
            self.assertEqual([(x["item"], x["apk"], x["decompile"], x["evidence"]) for x in anu],
                             [("apk-not-used", "/x/app-debug.apk", "failed:java not found", "report")])
            lib = [m for m in rep["missing"] if m["item"] == "library-resource-missing"]
            self.assertEqual([(m["type"], m["name"], m["in_apk"]) for m in lib], [("drawable", "ic_share", None)])
            self.assertFalse([w for w in rep["warnings"] if w["item"] == "library-resource-missing"])
            self.assertIn("/x/app-debug.apk", rep["reason"])
            self.assertIn("auto-discovers and decompiles the APK", rep["retry_hint"])
            self.assertIn("--apk-res", rep["retry_hint"])
            self.assertIn("apk_not_used=1", r.stderr)
            self.assertIn("source=source_res", r.stderr)

    def test_apk_used_library_fail_vs_dangling_warn(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a, p = make_android(root), make_hmos(root)
            _w(a / "app/src/main/java/x/Ghost.kt", "val g = R.drawable.ghost_icon\n")   # 源码和 APK 里都没有
            dec_rel = "spec/a2h/_work/resources-apk/apk-decoded/res"
            _w(p / dec_rel / "drawable/ic_share.xml", "<vector/>")
            _w(p / dec_rel / "values/strings.xml", '<resources><string name="lib_title">L</string></resources>')
            _conv_report(p, resource_source="decompiled_apk+source_res", apk_available=True,
                         apk={"path": "/x/app-debug.apk", "decompile": "ok", "res_dir": dec_rel})   # 相对路径按工程根解析
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            rep = _rep(r)
            self.assertEqual(rep["apk_not_used"], [])
            self.assertEqual((rep["apk"]["available"], rep["apk"]["used"]), (True, True))
            dang = [w for w in rep["warnings"] if w["item"] == "dangling-reference"]
            self.assertEqual([(w["type"], w["name"], w["in_apk"]) for w in dang], [("drawable", "ghost_icon", False)])
            self.assertLess(rep["coverage_ratio"], 1.0)
            # APK 里有、却没转出来 → FAIL
            (p / "entry/src/main/resources/base/media/ic_share.svg").unlink()
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 1)
            rep = _rep(r)
            lib = [m for m in rep["missing"] if m["item"] == "library-resource-missing"]
            self.assertEqual([(m["type"], m["name"], m["in_apk"]) for m in lib], [("drawable", "ic_share", True)])
            self.assertEqual(rep["apk_not_used"], [])

    def test_library_missing_is_warn_when_no_apk_anywhere(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a, p = make_android(root), make_hmos(root)
            _conv_report(p, resource_source="source_res", apk_available=False,
                         apk={"path": None, "decompile": "skipped:no APK found under --android-src"})
            (p / "entry/src/main/resources/base/media/ic_share.svg").unlink()
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            rep = _rep(r)
            self.assertEqual((rep["apk"]["available"], rep["apk"]["used"]), (False, False))
            self.assertEqual([(w["item"], w["name"]) for w in rep["warnings"] if w["item"] != "dimen-value-drift"],
                             [("library-resource-missing", "ic_share")])
            # 报告说没有 APK，但现在安卓根下有了 → 报告过期，同样 FAIL
            apk = _apk_file(a / "app/build/outputs/apk/debug/app-debug.apk")
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 1)
            rep = _rep(r)
            anu = rep["apk_not_used"][0]
            self.assertEqual((Path(anu["apk"]).resolve(), anu["evidence"]), (apk.resolve(), "discovery"))
            self.assertIn("stale report", anu["decompile"])
            self.assertEqual([m["item"] for m in rep["missing"]], ["library-resource-missing"])

    def test_no_report_discovers_apk(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a, p = make_android(root), make_hmos(root)
            (p / "spec/reports/resource-conversion.json").unlink()
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 0, r.stderr)                               # 没报告也没 APK：照旧
            self.assertEqual(_rep(r)["apk"]["available"], False)
            _apk_file(a / "app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk")   # 测试包不算
            self.assertEqual(run("--project", str(p), "--android-src", str(a), "--json").returncode, 0)
            apk = _apk_file(a / "app/build/outputs/apk/debug/app-debug.apk")
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 1)
            anu = _rep(r)["apk_not_used"][0]
            self.assertEqual(Path(anu["apk"]).resolve(), apk.resolve())
            self.assertEqual((anu["evidence"], anu["decompile"]), ("discovery", "no spec/reports/resource-conversion.json"))

    def test_legacy_report(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a, p = make_android(root), make_hmos(root)            # make_hmos 的报告只有 selectors = 旧版报告
            _apk_file(a / "app/build/outputs/apk/debug/app-debug.apk")
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 1)
            anu = _rep(r)["apk_not_used"][0]
            self.assertIn("legacy conversion report", anu["decompile"])
            # 旧版报告里有 kind=apk 的来源（当年用 --apk-res 跑的）→ 算用过
            _conv_report(p, sources=[{"path": str(root / "apk/res"), "label": "apk-res", "kind": "apk", "rank": 0}])
            r = run("--project", str(p), "--android-src", str(a), "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(_rep(r)["apk"]["resource_source"], "decompiled_apk+source_res")

    def test_converter_work_dir_apk_is_ignored(self):
        # 鸿蒙工程建在安卓根里：转换器的 apktool 框架缓存 1.apk 不算「有 APK」
        with tempfile.TemporaryDirectory() as d:
            a = make_android(Path(d))
            p = make_hmos(a)
            fw = _apk_file(p / gate.APK_WORK_REL / "apktool-framework/1.apk")
            info = gate.check_apk(p, a)
            self.assertEqual((info["available"], info["used"], info["evidence"]), (False, False, "discovery"))
            self.assertIsNone(gate._local_discover_apks(a, exclude=[p / gate.APK_WORK_REL])["chosen"])
            self.assertEqual(gate._local_discover_apks(a)["chosen"], fw.as_posix())

    def test_discovery_reuses_converter_and_local_copy_agrees(self):
        conv = SCRIPTS.parents[1] / "android2hmos_resources_convert" / "scripts"
        sys.path.insert(0, str(conv))
        import convert_resources  # noqa: E402
        self.assertIs(gate.discover_apks, convert_resources.discover_apks)
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / "android"
            self.assertEqual(gate._local_discover_apks(a)["chosen"], None)
            t = 1_700_000_000.0
            out = a / "app/build/outputs/apk"
            _apk_file(out / "debug/app-debug.apk", t - 100)
            _apk_file(out / "free/debug/app-free-debug.apk", t - 10)
            _apk_file(out / "release/app-release.apk", t)
            _apk_file(out / "debug/app-debug-unaligned.apk", t + 50)
            _apk_file(out / "staging/app-staging-unsigned.apk", t - 500)
            _apk_file(out / "androidTest/debug/app-debug-androidTest.apk", t + 60)
            _apk_file(a / "app/build/intermediates/apk/debug/app-debug.apk", t + 70)
            _apk_file(a / ".gradle/x-debug.apk", t + 80)
            _apk_file(a / "app/src/main/assets/plugin-debug.apk", t + 90)
            _apk_file(a / "releases/app_1.0_debug.apk", t + 100)
            full, local = convert_resources.discover_apks(a), gate._local_discover_apks(a)
            self.assertEqual(local["chosen"], full["chosen"])
            self.assertTrue(full["chosen"].endswith("free/debug/app-free-debug.apk"))
            self.assertEqual([c["path"] for c in local["candidates"]],
                             [c["path"] for c in full["candidates"] if c["status"] != "excluded"])


if __name__ == "__main__":
    unittest.main()
