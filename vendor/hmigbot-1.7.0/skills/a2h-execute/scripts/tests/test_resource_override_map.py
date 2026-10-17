"""DevEco-830 B1 生成期：资源覆写生效值表回归。
立此闸的事实：AIPPT basic 定义主按钮 #04B0FF/#027CFF，app 覆写 #3C2AF8/#7C25FF、圆角 10dp→30dp，域读代理直读库值。
固定判据：app > library；同模块自定义 res 目录（platform-res）> main；同值不入表；@color 引用链解析；drawable 同名覆写取 app；
两个 library 冲突标 ambiguous；understand 与 domains 任务书都注入生效值段；无表/零覆写不注入。
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
SPEC = SCRIPTS.parent.parent / "a2h-spec" / "scripts"
sys.path.insert(0, str(SCRIPTS)); sys.path.insert(0, str(SCRIPTS / "tests")); sys.path.insert(0, str(SPEC))
import resource_override_map as ROM  # noqa: E402
import test_page_chunks as TPC  # noqa: E402


def _w(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8")


def _android(root: Path):
    _w(root / "settings.gradle", "include ':app', ':basic', ':pay'\n")
    _w(root / "app/build.gradle", "apply plugin: 'com.android.application'\nandroid { sourceSets { main { res.srcDirs += 'src/main/platform-res' } } }\n")
    _w(root / "basic/build.gradle", "apply plugin: 'com.android.library'\n")
    _w(root / "pay/build.gradle", "apply plugin: 'com.android.library'\n")
    _w(root / "app/src/main/res/values/colors.xml", '<resources><color name="color_main">#3C2AF8</color><color name="same">#111111</color><color name="ref">@color/color_main</color></resources>')
    _w(root / "app/src/main/res/values/dimens.xml", '<resources><dimen name="radius">30dp</dimen></resources>')
    _w(root / "app/src/main/platform-res/values/colors.xml", '<resources><color name="plat">#00FF00</color></resources>')
    _w(root / "app/src/main/platform-res/drawable/bg.xml", "<shape/>")
    _w(root / "basic/src/main/res/values/colors.xml", '<resources><color name="color_main">#ff04B0FF</color><color name="same">#111111</color><color name="plat">#FF0000</color><color name="ref">#000000</color><color name="lib_only">#222222</color><color name="clash">#AAAAAA</color></resources>')
    _w(root / "basic/src/main/res/values/dimens.xml", '<resources><dimen name="radius">10dp</dimen></resources>')
    _w(root / "basic/src/main/res/drawable/bg.xml", "<shape/>")
    _w(root / "pay/src/main/res/values/colors.xml", '<resources><color name="clash">#BBBBBB</color></resources>')


class TestMap(unittest.TestCase):
    def test_build_map(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _android(root)
            d = ROM.build_map(root)
            by = {(o["type"], o["name"]): o for o in d["overrides"]}
            self.assertEqual(by[("color", "color_main")]["effective"], {"module": "app", "value": "#3C2AF8", "file": "app/src/main/res/values/colors.xml"})
            self.assertEqual(by[("dimen", "radius")]["effective"]["value"], "30dp")
            self.assertEqual(by[("color", "plat")]["effective"]["module"], "app")          # 自定义 res 目录 > basic
            self.assertEqual(by[("color", "ref")]["effective"]["resolved"], "#3C2AF8")     # 引用链解析
            self.assertNotIn(("color", "same"), by)                                          # 同值不入表
            self.assertNotIn(("color", "lib_only"), by)
            self.assertTrue(by[("color", "clash")]["ambiguous"])                            # 两 library 冲突
            self.assertEqual([o["name"] for o in d["drawable_overrides"]], ["bg"])
            self.assertEqual(d["drawable_overrides"][0]["effective"]["module"], "app")
            self.assertEqual(d["stats"]["same_value"], 1)
            r = subprocess.run([sys.executable, str(SPEC / "resource_override_map.py"), "--android-src", str(root),
                                "--out", str(root / "spec/ref/resource-override-map.json"), "--json"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(json.loads(r.stdout)["stats"]["overrides"], 5)

    def test_prompt_injection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); TPC._blueprint(root)
            env = dict(os.environ); env["ARKTS_SKILL_DIR"] = str(SCRIPTS.parent)
            def gen(wave):
                r = subprocess.run([sys.executable, str(SCRIPTS / "generate_waves.py"), "--blueprint", "spec/blueprint",
                                    "--out", "spec/waves", "--wave", wave, "--json"], capture_output=True, text=True,
                                   cwd=str(root), env=env, timeout=180)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                plan = json.loads((root / ("spec/waves/plan-%s.json" % wave)).read_text(encoding="utf-8"))
                t = next(t for t in plan["tasks"] if t["kind"] == "agent")
                return (root / t["prompt_file"]).read_text(encoding="utf-8")
            self.assertNotIn("资源覆写生效值表", gen("understand"))          # 无表不注入
            _w(root / "spec/ref/resource-override-map.json", json.dumps({"overrides": [
                {"type": "color", "name": "color_main", "effective": {"module": "app", "value": "#3C2AF8"},
                 "shadowed": [{"module": "basic", "value": "#ff04B0FF"}], "ambiguous": False}],
                "drawable_overrides": [{"name": "app_round_corner_bg", "effective": {"module": "app"}}]}))
            for wave in ("understand", "domains"):
                text = gen(wave)
                self.assertIn("资源覆写生效值表", text, wave)
                self.assertIn("color/color_main = #3C2AF8（app；被覆写：basic=#ff04B0FF）", text, wave)
                self.assertIn("app_round_corner_bg", text, wave)


if __name__ == "__main__":
    unittest.main()
