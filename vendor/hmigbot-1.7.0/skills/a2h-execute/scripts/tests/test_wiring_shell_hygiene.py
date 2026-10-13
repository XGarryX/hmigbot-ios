#!/usr/bin/env python3
"""接线壳卫生回归：禁 import 聚合凑构建图（AIPPT_915_test3：24 个壳里出现 100+ 行纯 import 堆叠）。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS)); sys.path.insert(0, str(Path(__file__).resolve().parent))

import mount_wiring as MW  # noqa: E402
import test_orphanwire_wave as OW  # noqa: E402


class TestShellHygiene(unittest.TestCase):
    def test_orphanwire_brief_forbids_import_aggregation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); OW._blueprint(root, OW.TASKS); OW._gen(root)
            prompt = (root / "spec/waves/prompts/orphanwire/orphanwire-domain-main-p1.txt").read_text(encoding="utf-8")
        self.assertIn("禁止 import 聚合", prompt)
        self.assertIn("mount()", prompt)

    def test_suspect_shells_flags_unused_imports_only(self):
        with tempfile.TemporaryDirectory() as td:
            w = Path(td) / "wiring"; w.mkdir()
            (w / "bad.ets").write_text(
                "import { A, B as Bee, C } from '../f/x';\nexport function mount(): void { A.init(); }\n", encoding="utf-8")
            (w / "good.ets").write_text(
                "import { A } from '../f/x';\nexport function mount(): void { new A().register(); }\n", encoding="utf-8")
            sus = MW.suspect_shells(sorted(w.glob("*.ets")))
        self.assertEqual([s["file"] for s in sus], ["bad.ets"])
        self.assertEqual(sorted(sus[0]["unused"]), ["Bee", "C"])


if __name__ == "__main__":
    unittest.main()
