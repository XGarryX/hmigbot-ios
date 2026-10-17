#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E282：fragments/index.json 每条 sdk_skills 指针必须指向真实存在的 `<skills>/<id>/SKILL.md`。

远端 28f8a794 把 android2hmos_resources_convert 的 SKILL.md 挪到连字符目录，index.json 这条没跟着改 →
组装期死链 AssembleError。AIPPT_930_gpt 主会话为绕开它，改用隔壁 09-21 旧快照的 generate_waves
生成了 20/23 份计划（本轮实际没测到打包版）。套件当时没有这条用例，合并后全绿也没拦住。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]          # skills/a2h-execute/scripts
SKILLS = SCRIPTS.parents[1]                             # skills 根
INDEX = SCRIPTS.parent / "references" / "fragments" / "index.json"
sys.path.insert(0, str(SCRIPTS))


class TestSdkPointersResolve(unittest.TestCase):
    def test_every_sdk_skill_id_has_skill_md(self):
        idx = json.loads(INDEX.read_text(encoding="utf-8"))
        dead = []
        for e in idx.get("sdk_skills", []):
            sid = e.get("id")
            if not (SKILLS / sid / "SKILL.md").is_file():
                dead.append(sid)
        self.assertEqual(dead, [], "sdk_skills 死链（id 即目录名）: %s" % dead)

    def test_pointer_field_agrees_with_id(self):
        """pointer 是给人看的，但不得与 id 指向不同目录（半截改名的另一种形态）。"""
        idx = json.loads(INDEX.read_text(encoding="utf-8"))
        bad = [(e.get("id"), e.get("pointer")) for e in idx.get("sdk_skills", [])
               if e.get("pointer") and e["pointer"] != "skills/%s/SKILL.md" % e.get("id")]
        self.assertEqual(bad, [])

    def test_resources_convert_scripts_path_unchanged(self):
        """改名只挪了 SKILL.md 等；脚本仍在下划线目录（resource_coverage_gate / runbook 按此调用）。"""
        self.assertTrue((SKILLS / "android2hmos_resources_convert" / "scripts" / "convert_resources.py").is_file())
        self.assertTrue((SKILLS / "android2hmos-resources-convert" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
