"""DevEco-830 C1：round0 UI 静态 lint 四条回归。
立此闸的事实：症状 4（Web 首帧空 src 创建、onReady 再赋值）、6（ListItem 撑满）、7b（状态栏双重下移）在 GLM 产物上 2/1/5/1 有信号，
Opus 5 产物 0/0/0/1；test3 有 4 处 Web 无条件创建。固定判据：该响的响（坏样本各 1 条）、不该响的不响（条件创建 / loadUrl / @Local / 内层 100% / 无 statusBar）。
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


def _w(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8")


class TestUiLint(unittest.TestCase):
    def test_four_rules(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); pages = root / "entry/src/main/ets/pages"
            _w(root / "spec/blueprint/ownership.json", json.dumps({"version": 1, "owners": {"domain:x": ["entry/src/main/ets/pages/**"]}}))
            _w(pages / "WebBad.ets", "@ComponentV2 struct A {\n  private url: string = ''\n  ctrl = new webview.WebviewController()\n  build() {\n    Column() {\n      Web({ src: this.url, controller: this.ctrl })\n    }\n  }\n  aboutToAppear() { this.url = 'http://x' }\n}\n")
            _w(pages / "WebGood.ets", "@ComponentV2 struct B {\n  @Local url: string = ''\n  build() {\n    Column() {\n      if (this.url.length > 0) {\n        Web({ src: this.url, controller: this.ctrl })\n      }\n    }\n  }\n  aboutToAppear() { this.url = 'http://x' }\n}\n")
            _w(pages / "WebLoad.ets", "struct C {\n  private url = ''\n  build() { Web({ src: this.url, controller: this.ctrl }) }\n  onReady() { this.url = 'u'; this.ctrl.loadUrl(this.url) }\n}\n")
            _w(pages / "ImgBad.ets", "@ComponentV2 struct D {\n  private template: string = ''\n  build() { Image(this.template).width(10).height(10) }\n  aboutToAppear() { this.template = 'a.png' }\n}\n")
            _w(pages / "ImgGood.ets", "@ComponentV2 struct E {\n  @Local template: string = ''\n  build() { Image(this.template) }\n  aboutToAppear() { this.template = 'a.png' }\n}\n")
            _w(pages / "StatusBad.ets", "struct F {\n  build() {\n    Column() {\n      Image($r('app.media.t')).margin({ top: 61 })\n    }.padding({ top: AppContext.statusBarHeight })\n  }\n}\n")
            _w(pages / "StatusOk.ets", "struct G {\n  build() {\n    Column() {\n      Image($r('app.media.t')).margin({ top: 61 })\n    }.padding({ top: 12 })\n  }\n}\n")
            _w(pages / "ListBad.ets", "struct H {\n  build() {\n    List() {\n      ForEach(this.items, (b: Bean) => {\n        ListItem() {\n          this.chip(b)\n        }\n        .width('100%')\n      })\n    }\n  }\n}\n")
            _w(pages / "ListGood.ets", "struct I {\n  build() {\n    List() {\n      ListItem() {\n        Row() { Text('x') }.width('100%')\n      }\n      .width('100%')\n    }\n  }\n}\n")
            env = dict(os.environ); env["ARKTS_SKILL_DIR"] = str(root / "no-skills")
            r = subprocess.run([sys.executable, str(SCRIPTS / "round0_precheck.py"), "--project", str(root),
                                "--blueprint", str(root / "spec/blueprint"), "--json"], capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            rep = json.loads((root / "spec/reports/round0/x.json").read_text(encoding="utf-8"))
            by = {}
            for f in rep["findings"]:
                by.setdefault(f["check"], []).append(Path(f["file"]).name)
            self.assertEqual(by.get("ui-web-src-timing"), ["WebBad.ets"])
            self.assertEqual(by.get("ui-image-src-binding"), ["ImgBad.ets"])
            self.assertEqual(by.get("ui-statusbar-double-inset"), ["StatusBad.ets"])
            self.assertEqual(by.get("ui-listitem-fullwidth"), ["ListBad.ets"])
            sev = {f["check"]: f["severity"] for f in rep["findings"]}
            self.assertEqual((sev["ui-web-src-timing"], sev["ui-statusbar-double-inset"]), ("P1", "P1"))
            self.assertEqual((sev["ui-image-src-binding"], sev["ui-listitem-fullwidth"]), ("P2", "P2"))
            out = json.loads(r.stdout)
            self.assertTrue(any(c["name"] == "ui-web-src-timing" and c["status"] == "ok" for c in out["checks"]))


if __name__ == "__main__":
    unittest.main()
