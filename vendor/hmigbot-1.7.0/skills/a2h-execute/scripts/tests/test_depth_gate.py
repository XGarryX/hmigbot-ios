#!/usr/bin/env python3
"""还原深度闸回归。既有六道门全守结构健康，一个 121 行的页和 241 行的在所有判据下一样绿。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
PY = sys.executable or "python3"
SPEC = """# d
## 2. 屏幕
### 2.1 HomeActivity
- a
- b
- c
- d
- e
- f
| 列 | 值 |
|---|---|
| x | 1 |
| y | 2 |
### 2.2 TinyActivity
- only
### 2.3 GoneActivity
- a
- b
- c
- d
- e
"""


def _setup(root: Path, home_nodes: int):
    bp = root / "spec/blueprint"; bp.mkdir(parents=True)
    (root / "spec/domains").mkdir(); (root / "spec/reports").mkdir()
    (root / "spec/domains/d.md").write_text(SPEC, encoding="utf-8")
    (bp / "domain-map.json").write_text(json.dumps({"version": 1, "domains": [
        {"key": "d", "spec_file": "spec/domains/d.md", "pages": ["HomeActivity", "TinyActivity", "GoneActivity"]}]}),
        encoding="utf-8")
    (bp / "page-names.json").write_text(json.dumps({"domains": {"d": {
        "HomeActivity": "HomePage", "TinyActivity": "TinyPage", "GoneActivity": "GonePage"}}}), encoding="utf-8")
    (bp / "workflow-params.json").write_text('{"version":1,"gates":{"depth_min_ratio":0.4}}', encoding="utf-8")
    pages = root / "entry/src/main/ets/pages"; pages.mkdir(parents=True)
    (pages / "HomePage.ets").write_text("struct H{build(){" + "Column(){Text('x')}" * (home_nodes // 2) + "}}",
                                        encoding="utf-8")
    (pages / "TinyPage.ets").write_text("struct T{build(){}}", encoding="utf-8")   # expected=1 <4 → 不判


def _run(root: Path):
    r = subprocess.run([PY, str(SCRIPTS / "depth_gate.py"), "--project", str(root),
                        "--blueprint", str(root / "spec/blueprint"), "--json"], capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout), json.loads((root / "spec/reports/depth-gate.json").read_text(encoding="utf-8"))


class TestDepthGate(unittest.TestCase):
    def test_shallow_page_fails_with_dispatch_sheet(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _setup(root, home_nodes=2)      # 8 要点 → 2 节点 = 0.25 < 0.4
            rc, out, rep = _run(root)
            tasks = json.loads((root / "spec/reports/depth-tasks.json").read_text(encoding="utf-8"))
        self.assertEqual(rc, 1)
        codes = {(f["page"], f["code"]) for f in rep["findings"]}
        self.assertIn(("HomeActivity", "depth-shallow"), codes)
        self.assertIn(("GoneActivity", "page-missing"), codes)
        self.assertNotIn(("TinyActivity", "depth-shallow"), codes)      # 样本太小不判
        self.assertEqual(sorted(tasks["domains"]["d"]), ["GoneActivity", "HomeActivity"])
        home = [f for f in rep["findings"] if f["page"] == "HomeActivity"][0]
        self.assertEqual(home["expected"], 8)                             # 6 列表项 + 2 表格数据行
        self.assertEqual(home["owner"], "domain:d")
        self.assertTrue(home["file"].endswith("pages/HomePage.ets"))

    def test_deep_page_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _setup(root, home_nodes=8)
            (root / "entry/src/main/ets/pages/GonePage.ets").write_text("Column(){Text()Text()Text()}", encoding="utf-8")
            rc, out, rep = _run(root)
        self.assertEqual(rc, 0, rep["findings"])
        self.assertEqual(rep["stats"]["shallow"], 0)


    def test_page_components_dir_counts_toward_depth(self):
        """第十五批：复合控件拆进 components/<域>/<页>/** 后，页面文件本身变薄——闸必须连子组件一起数。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _setup(root, home_nodes=2)      # 页面文件本身 0.25，单看会判浅
            (root / "entry/src/main/ets/pages/GonePage.ets").write_text("Column(){Text()Text()Text()}", encoding="utf-8")
            comp = root / "entry/src/main/ets/components/d/HomePage"; comp.mkdir(parents=True)
            (comp / "HomeCard.ets").write_text("@ComponentV2 struct HomeCard{build(){" + "Row(){Text('y')}" * 4 + "}}", encoding="utf-8")
            # E169：子组件按真实 import 可达计数（页面必须真的 import 并使用 HomeCard），不再按目录位置充数
            page = root / "entry/src/main/ets/pages/HomePage.ets"
            page.write_text("import { HomeCard } from '../components/d/HomePage/HomeCard'; struct HomePage{build(){Column(){HomeCard()}}}", encoding="utf-8")
            rc, out, rep = _run(root)
        self.assertEqual(rc, 0, rep["findings"])
        home = [r for r in rep["rows"] if r["page"] == "HomeActivity"][0]
        self.assertEqual(home["components"], 1)
        self.assertGreaterEqual(home["actual"], 8)

if __name__ == "__main__":
    unittest.main()
