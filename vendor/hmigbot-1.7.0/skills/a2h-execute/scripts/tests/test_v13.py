#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V13（toolkit 盲区框架化）单测：fact_tree_quality 四指标 / run_backfills 纯 fact-tree 插件 /
domain_split --exclude-hubs。合成 fact-tree，纯读写，无需 android 源。

用法示例:
    python3 arkts-skills/skills/a2h-execute/scripts/tests/test_v13.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SPEC_SCRIPTS = Path(__file__).resolve().parent.parent.parent.parent / "a2h-spec" / "scripts"
TOOLKIT_SCRIPTS = (Path(__file__).resolve().parent.parent.parent.parent
                   / "toolkit-fact-indexer" / "scripts")
QUALITY = SPEC_SCRIPTS / "fact_tree_quality.py"
BACKFILLS = TOOLKIT_SCRIPTS / "run_backfills.py"
DOMAIN_SPLIT = SPEC_SCRIPTS / "domain_split.py"


def _tree(pages, edges, nodes=None):
    return {"schema_version": "v2", "app": {"package": "com.x"},
            "pages": pages, "fragments": [], "dialogs": [],
            "flow_graph": {"nodes": nodes or [{"id": p["id"], "type": "page"} for p in pages],
                           "edges": edges}}


class TestQualityGate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-ftq-")
        self.addCleanup(self._tmp.cleanup)
        self.ft = Path(self._tmp.name) / "ft.json"

    def _run(self, tree, *extra):
        self.ft.write_text(json.dumps(tree), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(QUALITY), "--fact-tree", str(self.ft), "--json", *extra],
            capture_output=True, text=True, encoding="utf-8", timeout=60)

    def test_healthy_tree_passes(self):
        pages = [{"id": "A", "layout_file": "a.xml", "android_file": "A.kt"},
                 {"id": "B", "layout_file": "b.xml", "android_file": "B.kt"}]
        edges = [{"from": "A", "to": "B"}]
        proc = self._run(_tree(pages, edges))
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_null_layout_breach(self):
        pages = [{"id": p, "layout_file": None, "android_file": p + ".kt"} for p in "ABCDE"]
        proc = self._run(_tree(pages, [{"from": "A", "to": "B"}]))
        self.assertEqual(proc.returncode, 1, proc.stdout)
        out = json.loads(proc.stdout)
        self.assertTrue(any("null_layout" in b for b in out["breaches"]))

    def test_isolated_pages_breach(self):
        pages = [{"id": p, "layout_file": p + ".xml"} for p in "ABCDE"]
        proc = self._run(_tree(pages, [{"from": "A", "to": "B"}]))  # C/D/E 孤立 = 3/5=0.6
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertTrue(any("isolated" in b for b in json.loads(proc.stdout)["breaches"]))

    def test_threshold_override(self):
        pages = [{"id": p, "layout_file": None, "android_file": p + ".kt"} for p in "ABCDE"]
        proc = self._run(_tree(pages, []), "--thresholds", '{"null_layout_ratio":1.0,"isolated_page_ratio":1.0}')
        self.assertEqual(proc.returncode, 0, proc.stdout)


class TestBackfills(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-bf-")
        self.addCleanup(self._tmp.cleanup)
        self.ft = Path(self._tmp.name) / "ft.json"
        self.rep = Path(self._tmp.name) / "rep.json"

    def _run(self, tree, *extra):
        self.ft.write_text(json.dumps(tree), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(BACKFILLS), "--tree", str(self.ft),
             "--report", str(self.rep), "--json", *extra],
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout), json.loads(self.ft.read_text(encoding="utf-8"))

    def test_lambda_suffix_normalized(self):
        pages = [{"id": "Home", "layout_file": "h.xml"},
                 {"id": "HomeShowDialog", "layout_file": "d.xml"}]
        edges = [{"from": "Home", "to": "HomeShowDialog$1$1"}]
        out, tree = self._run(_tree(pages, edges))
        plug = {p["plugin"]: p for p in out["plugins"]}
        self.assertTrue(plug["lambda_suffix_norm"]["signal"])
        self.assertEqual(plug["lambda_suffix_norm"]["changed"], 1)
        self.assertEqual(tree["flow_graph"]["edges"][0]["to"], "HomeShowDialog")

    def test_promoted_nodes_merged(self):
        pages = [{"id": "Mine", "layout_file": "m.xml", "reach_paths": ["Home->Mine"]},
                 {"id": "_promoted_page_Mine", "components": ["btn1", "btn2"]}]
        out, tree = self._run(_tree(pages, []))
        plug = {p["plugin"]: p for p in out["plugins"]}
        self.assertTrue(plug["promoted_nodes"]["signal"])
        ids = [r["id"] for r in tree["pages"]]
        self.assertNotIn("_promoted_page_Mine", ids)          # 移出 pages
        mine = next(r for r in tree["pages"] if r["id"] == "Mine")
        self.assertIn("btn1", mine["components"])             # 组件并入实体
        self.assertTrue(any(r["id"] == "_promoted_page_Mine" for r in tree["_excluded_nodes"]))

    def test_no_signal_no_change(self):
        pages = [{"id": "A", "layout_file": "a.xml"}]
        out, tree = self._run(_tree(pages, []))
        self.assertEqual(out["total_changed"], 0)


class TestExcludeHubs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-hub-")
        self.addCleanup(self._tmp.cleanup)
        self.ft = Path(self._tmp.name) / "ft.json"
        self.out = Path(self._tmp.name) / "dm.json"

    def test_hub_backfilled_to_common(self):
        # AppTips 被 6 页调用（入度 6 出度 0）——hub；6 个业务页各自跳 AppTips
        pages = [{"id": "P%d" % i, "type": "page", "layout_file": "p%d.xml" % i,
                  "android_file": "P%d.kt" % i, "package": "com.x.p%d" % i} for i in range(6)]
        pages.append({"id": "AppTips", "type": "dialog", "layout_file": "tips.xml",
                      "android_file": "AppTips.kt", "package": "com.x.basic"})
        edges = [{"from": "P%d" % i, "to": "AppTips"} for i in range(6)]
        self.ft.write_text(json.dumps(_tree(
            [p for p in pages if p["type"] == "page"], edges,
            nodes=[{"id": p["id"], "type": p["type"]} for p in pages])), encoding="utf-8")
        # AppTips 放 dialogs
        tree = json.loads(self.ft.read_text(encoding="utf-8"))
        tree["dialogs"] = [p for p in pages if p["type"] == "dialog"]
        self.ft.write_text(json.dumps(tree), encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, str(DOMAIN_SPLIT), "--fact-tree", str(self.ft),
             "--out", str(self.out), "--exclude-hubs", "--hub-min-indeg", "5", "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        dm = json.loads(self.out.read_text(encoding="utf-8"))
        common = next((d for d in dm["domains"] if d["key"] == "common"), None)
        self.assertIsNotNone(common, dm["domains"])
        self.assertIn("AppTips", common["pages"])
        self.assertTrue(common.get("draft_evidence", {}).get("hub_backfill"))
        self.assertTrue(any("hub 剥离" in w for w in dm["draft_warnings"]))


class TestResumeGuard(unittest.TestCase):
    """V14：resume_guard 对有半成品的任务生成 .resume.txt；next_batch 优先用它。"""

    def setUp(self):
        import os
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-resume-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "proj"
        (self.root / "spec/waves/prompts/domains").mkdir(parents=True)
        (self.root / "features/alpha").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.root)], timeout=30)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "t@t"], timeout=30)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "t"], timeout=30)
        self.plan = self.root / "spec/waves/plan-domains.json"
        self._prompt = self.root / "spec/waves/prompts/domains/alpha.txt"
        self._prompt.write_text("原任务书正文\n", encoding="utf-8")
        self.plan.write_text(json.dumps({
            "wave": "domains", "plan_version": "a2h-2.1.0",
            "contract_hash": "sha256:" + "0" * 64, "max_parallel": 0,
            "tasks": [{"id": "impl:alpha", "kind": "agent", "agent": "a2h-domain-worker@2.1.0",
                       "prompt_file": "spec/waves/prompts/domains/alpha.txt",
                       "ownership": ["features/alpha/**"], "schema": "domainImpl", "parents": [],
                       "map_group": "domains-impl",
                       "result_path": "spec/waves/results/domains/alpha.json",
                       "resume_key": "domains:impl:alpha"}]}), encoding="utf-8")

    RESUME_GUARD = Path(__file__).resolve().parent.parent / "resume_guard.py"

    def test_dirty_generates_resume(self):
        # 半成品：白名单下有未跟踪文件
        (self.root / "features/alpha/A.ets").write_text("// 半成品\n", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(self.RESUME_GUARD), "--plan", str(self.plan),
             "--tasks", "impl:alpha", "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(len(out["guarded"]), 1)
        resume = self._prompt.with_name("alpha.txt.resume.txt")
        self.assertTrue(resume.is_file())
        body = resume.read_text(encoding="utf-8")
        self.assertIn("原任务书正文", body)              # 保留原 prompt
        self.assertIn("半成品审查", body)
        self.assertIn("features/alpha/A.ets", body)

    def test_clean_no_resume(self):
        proc = subprocess.run(
            [sys.executable, str(self.RESUME_GUARD), "--plan", str(self.plan),
             "--tasks", "impl:alpha", "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["clean"], ["impl:alpha"])
        self.assertFalse(self._prompt.with_name("alpha.txt.resume.txt").exists())


def main():
    unittest.main()


if __name__ == "__main__":
    main()
