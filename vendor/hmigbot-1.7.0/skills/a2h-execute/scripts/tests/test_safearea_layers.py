"""DevEco-830 B3 链③：round0 沉浸式四层反查回归。
立此闸的事实：CONTRACT §5 承诺的 safearea_layers 脚本反查从未实现；test3 83 页 meta 全缺字段、expandSafeArea 0。
固定判据：无沉浸式页 → 零 findings；四层齐全 → 零 findings；无 L1/L2 各一条 P1；沉浸式页无前景避让 → 每页一条 P1；
子页自带 expandSafeArea → P2；未映射到 hmos 文件的页只进 detail 不报。
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


def _run(root: Path):
    env = dict(os.environ); env["ARKTS_SKILL_DIR"] = str(root / "no-skills")
    r = subprocess.run([sys.executable, str(SCRIPTS / "round0_precheck.py"), "--project", str(root),
                        "--blueprint", str(root / "spec/blueprint"), "--json"], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    chk = next(c for c in out["checks"] if c["name"] == "safearea-layers")
    rep = json.loads((root / "spec/reports/round0/x.json").read_text(encoding="utf-8"))
    return chk, [f for f in rep["findings"] if f["check"] == "safearea-layers"]


def _base(root: Path, flagged=("HomeActivity",), plain=("AboutActivity",)):
    _w(root / "spec/blueprint/ownership.json", json.dumps({"version": 1, "owners": {"domain:x": ["entry/src/main/ets/**"]}}))
    _w(root / "spec/blueprint/page-names.json", json.dumps({"domains": {"x": {"HomeActivity": "HomePage", "AboutActivity": "AboutPage", "GhostActivity": "GhostPage"}}}))
    for pg in flagged:
        _w(root / "spec/ui" / pg / "meta.json", json.dumps({"page_id": pg, "page_type": "full_screen_page", "needs_immersive_safearea": True}))
    for pg in plain:
        _w(root / "spec/ui" / pg / "meta.json", json.dumps({"page_id": pg, "page_type": "full_screen_page", "needs_immersive_safearea": False}))


class TestSafeareaLayers(unittest.TestCase):
    def test_no_immersive_pages_is_silent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _base(root, flagged=(), plain=("AboutActivity",))
            _w(root / "entry/src/main/ets/pages/AboutPage.ets", "struct A { build() { Column() {} } }\n")
            chk, f = _run(root)
            self.assertEqual((chk["status"], f), ("ok", [])); self.assertEqual(chk["detail"]["immersive_pages"], 0)

    def test_all_layers_present(self):
        # E267：根上写 L2 只在「全屏页全是沉浸式」时才合法，所以这里 plain=()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _base(root, plain=())
            _w(root / "entry/src/main/ets/entryability/EntryAbility.ets", "win.setWindowLayoutFullScreen(true)\n")
            _w(root / "entry/src/main/ets/pages/Index.ets", "build() { Navigation(this.stack) {}.expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP]) }\n")
            _w(root / "entry/src/main/ets/pages/HomePage.ets", "@Local windowModel: WindowModel = AppStorageV2.connect(WindowModel)!\nbuild() { NavDestination() { Row().padding({ top: this.windowModel.windowTopPadding + 6 }) } }\n")
            _w(root / "entry/src/main/ets/pages/AboutPage.ets", "struct A { build() { Column() {} } }\n")
            chk, f = _run(root)
            self.assertEqual(f, []); self.assertEqual(chk["detail"]["immersive_pages"], 1)

    def test_missing_layers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _base(root, flagged=("HomeActivity", "GhostActivity"))
            _w(root / "entry/src/main/ets/entryability/EntryAbility.ets", "// no fullscreen\n")
            _w(root / "entry/src/main/ets/pages/Index.ets", "build() { Navigation(this.stack) {} }\n")
            _w(root / "entry/src/main/ets/pages/HomePage.ets", "build() { NavDestination() { Row().padding({ top: 24 }) } }\n")
            _w(root / "entry/src/main/ets/pages/AboutPage.ets", "struct A {}\n")
            chk, f = _run(root)
            summ = sorted((x["severity"], Path(x["file"]).name, x["summary"][:6]) for x in f)
            self.assertEqual(summ, [("P1", "EntryAbility.ets", "L1 缺失："), ("P1", "HomePage.ets", "L3 缺失："), ("P1", "Index.ets", "L2 缺失：")])
            self.assertEqual(chk["detail"]["immersive_pages"], 2)      # GhostPage.ets 不存在 → 不重复报
            self.assertEqual(chk["detail"]["unmapped_pages"], [])

    def test_page_own_expand_counts_as_moved_l2_but_double_with_root_is_p2(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _base(root)
            _w(root / "entry/src/main/ets/entryability/EntryAbility.ets", "win.setWindowLayoutFullScreen(true)\n")
            _w(root / "entry/src/main/ets/pages/Index.ets", "build() { Navigation(this.stack) {} }\n")
            _w(root / "entry/src/main/ets/pages/HomePage.ets", "build() { Column().padding({ top: this.windowModel.windowTopPadding }).expandSafeArea([SafeAreaType.SYSTEM]) }\n")
            chk, f = _run(root)
            self.assertEqual(f, [])                                      # 根无、页自 expand = L2 搬到本页，成立
            _w(root / "entry/src/main/ets/pages/Index.ets", "build() { Navigation(this.stack) {}.expandSafeArea([SafeAreaType.SYSTEM]) }\n")
            chk, f = _run(root)
            # 根有 + 页有 = 双重穿透（P2）；且 2 个全屏页只有 1 个沉浸式，根上的 L2 会把非沉浸页也穿透（E267 的 P1）
            self.assertEqual(sorted((x["severity"], Path(x["file"]).name) for x in f),
                             [("P1", "Index.ets"), ("P2", "HomePage.ets")])

class TestE267SubsetPenetration(unittest.TestCase):
    """E267：沉浸式页是全屏页真子集时，L1/L2 都是窗口级，写在根上会把非沉浸页一起穿透。

    AIPPT 实证：安卓只有启动页用 windowFullscreen 主题，鸿蒙侧却无条件 setWindowLayoutFullScreen(true)
    + 根 Navigation expandSafeArea，24 个本不需要避让的页面被迫逐页补 L3（E259 的 18/19 误判由此而来）。
    """

    def _mk(self, root: Path, flagged, plain):
        _base(root, flagged=flagged, plain=plain)
        _w(root / "entry/src/main/ets/entryability/EntryAbility.ets", "win.setWindowLayoutFullScreen(true)\n")
        _w(root / "entry/src/main/ets/pages/HomePage.ets",
           "build() { NavDestination() { Row().padding({ top: this.windowModel.windowTopPadding }) } }\n")
        _w(root / "entry/src/main/ets/pages/AboutPage.ets", "struct A { build() { Column() {} } }\n")

    def test_root_l2_with_subset_is_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._mk(root, ("HomeActivity",), ("AboutActivity",))
            _w(root / "entry/src/main/ets/pages/Index.ets",
               "build() { Navigation(this.stack) {}.expandSafeArea([SafeAreaType.SYSTEM]) }\n")
            chk, f = _run(root)
            self.assertEqual([(x["severity"], Path(x["file"]).name) for x in f], [("P1", "Index.ets")])
            self.assertIn("只有 1 个是沉浸式", f[0]["summary"])
            self.assertEqual((chk["detail"]["immersive_pages"], chk["detail"]["full_screen_pages"]), (1, 2))

    def test_page_own_l2_with_subset_is_clean(self):
        """正解：穿透归沉浸页自己，非沉浸页交回系统默认避让。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._mk(root, ("HomeActivity",), ("AboutActivity",))
            _w(root / "entry/src/main/ets/pages/Index.ets", "build() { Navigation(this.stack) {} }\n")
            _w(root / "entry/src/main/ets/pages/HomePage.ets",
               "build() { NavDestination() { Row().padding({ top: this.windowModel.windowTopPadding }) }"
               ".expandSafeArea([SafeAreaType.SYSTEM]) }\n")
            self.assertEqual(_run(root)[1], [])

    def test_root_l2_when_all_full_screen_pages_immersive_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._mk(root, ("HomeActivity",), ())
            _w(root / "entry/src/main/ets/pages/Index.ets",
               "build() { Navigation(this.stack) {}.expandSafeArea([SafeAreaType.SYSTEM]) }\n")
            self.assertEqual(_run(root)[1], [])


if __name__ == "__main__":
    unittest.main()
