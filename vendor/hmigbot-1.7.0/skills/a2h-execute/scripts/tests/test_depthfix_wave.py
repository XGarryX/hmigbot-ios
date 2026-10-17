"""depthfix 条件波回归（第十五批 E15）：gate:depth 判浅的页按页面块回派一轮。
立此闸的事实：depth 闸判浅只出派发单（test3 shallow=11），next_batch 不消费——浅页留到人工。
固定判据：
  · WAVE_ORDER 里 depthfix 紧随 domains；
  · 只重派含浅页的块（其它块不动），id/写权与 domains 波页面块同形，父为空；
  · 任务书带「深度闸判定」明细（要点/节点/ratio）；
  · 无派发单 / 无浅页 / 本波已跑过 → next_batch 跳过（有界一次）；
  · gate:depth 在 domains 波不再升级等人（escalate=False），depthfix 波尾有 compile-2c + depth-2。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS)); sys.path.insert(0, str(SCRIPTS / "tests"))
import _wavelib as W  # noqa: E402
import generate_waves as G  # noqa: E402
import next_batch as NB  # noqa: E402
import test_page_chunks as TPC  # noqa: E402


def _gen(root: Path, wave: str):
    import os, subprocess
    env = dict(os.environ); env["ARKTS_SKILL_DIR"] = str(SCRIPTS.parent)
    r = subprocess.run([sys.executable, str(SCRIPTS / "generate_waves.py"), "--blueprint", "spec/blueprint",
                        "--out", "spec/waves", "--wave", wave, "--json"], capture_output=True, text=True,
                       encoding="utf-8", cwd=str(root), env=env, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads((root / ("spec/waves/plan-%s.json" % wave)).read_text(encoding="utf-8"))


def _with_depth(root: Path, shallow_pages):
    bp = TPC._blueprint(root)
    rep = root / "spec/reports"; rep.mkdir(parents=True, exist_ok=True)
    rows = [{"domain": "big", "page": p, "expected": 9, "actual": 2 if p in shallow_pages else 12,
             "ratio": 0.22 if p in shallow_pages else 1.33} for p in TPC.PAGES if "$" not in p]
    findings = [{"severity": "FAIL", "code": "depth-shallow", "domain": "big", "page": p} for p in shallow_pages]
    (rep / "depth-gate.json").write_text(json.dumps({"stats": {"min_ratio": 0.4}, "rows": rows, "findings": findings}), encoding="utf-8")
    (rep / "depth-tasks.json").write_text(json.dumps({"min_ratio": 0.4, "domains": {"big": list(shallow_pages)}}), encoding="utf-8")
    return bp


class TestDepthfix(unittest.TestCase):
    def test_wave_order(self):
        self.assertEqual(W.WAVE_ORDER.index("depthfix"), W.WAVE_ORDER.index("domains") + 1)

    def test_only_chunks_with_shallow_pages_and_prompt_has_findings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _with_depth(root, ["SearchActivity"])          # 夹具里 SearchActivity 在第 3 块
            plan = _gen(root, "depthfix")
            ag = [t for t in plan["tasks"] if t["kind"] == "agent"]
            self.assertEqual([t["id"] for t in ag], ["impl:big:p3"])
            self.assertEqual(ag[0]["parents"], []); self.assertEqual(ag[0]["map_group"], "depthfix-impl")
            self.assertTrue(any(g.endswith("SearchPage.ets") for g in ag[0]["ownership"]))
            reduces = [t["id"] for t in plan["tasks"] if t["kind"] == "reduce"]
            self.assertEqual(reduces, ["reduce:pagemap", "reduce:resource-sweep", "gate:fence-audit",
                                       "reduce:probe", "reduce:build-depthfix", "gate:compile-2c", "gate:depth-2",
                                       "reduce:wires-check", "reduce:product-write-audit"])   # I5：wires-check 挂 build 之后
            prompt = (root / ag[0]["prompt_file"]).read_text(encoding="utf-8")
            self.assertIn("wave=depthfix，深度闸回派", prompt)
            self.assertIn("深度闸判定", prompt); self.assertIn("SearchActivity：spec 要点 9，产物 ArkUI 节点 2", prompt)
            self.assertIn("判浅", prompt)

    def test_domains_depth_gate_no_longer_escalates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _with_depth(root, [])
            plan = _gen(root, "domains")
            g = next(t for t in plan["tasks"] if t["id"] == "gate:depth")
            self.assertEqual(g["on_fail"], {"escalate": False})

    def test_next_hint_routes_to_depthfix_once(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _with_depth(root, ["SearchActivity"])
            plan = _gen(root, "domains"); pp = (root / "spec/waves/plan-domains.json").resolve()
            h = NB._next_hint(plan, pp, root.resolve())
            self.assertEqual((h["kind"], h["wave"]), ("wave", "depthfix"))
            # 本波已跑过 → 不再出 depthfix（有界一次）。
            # E265⑤：但派发单还非空 = 返工机会用尽仍不达标，原实现直接 `continue` 往下走（静默跳过），
            # 现在必须出 escalate 呈报，不能当成正常收尾。
            (root / "spec/state").mkdir(parents=True, exist_ok=True)
            (root / "spec/state/state.json").write_text(json.dumps({"waves": {"depthfix": {"tasks": []}}}), encoding="utf-8")
            h2 = NB._next_hint(plan, pp, root.resolve())
            self.assertEqual(h2["kind"], "escalate")
            self.assertEqual(h2["tasks"], "spec/reports/depth-tasks.json")
            self.assertIn("SearchActivity", h2["pages"])
            # 无浅页 → 跳过
            (root / "spec/reports/depth-tasks.json").write_text(json.dumps({"domains": {}}), encoding="utf-8")
            (root / "spec/state/state.json").unlink()
            h3 = NB._next_hint(plan, pp, root.resolve())
            self.assertNotEqual(h3 and h3.get("wave"), "depthfix")


if __name__ == "__main__":
    unittest.main()
