"""spec 深度闸 + specfix 条件波回归（第十五批 S5）。
立此闸的事实：understand 任务书只有散文要求，test3 73 页里 11 页无分节、27 页 <3 要点。
固定判据：缺分节 → spec-missing；view 节点 ≥4 且要点 < max(3, 0.4·节点) → spec-shallow；小页 0 要点 → shallow；
派发单按域列页；specfix 只回派判薄域，写权与 understand 同形，任务书带判定明细与每页机械底线；
next_batch 在 understand 之后按派发单进 specfix，且有界一次。
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
GATE = SCRIPTS.parent.parent / "a2h-spec" / "scripts" / "spec_depth_gate.py"
sys.path.insert(0, str(SCRIPTS)); sys.path.insert(0, str(SCRIPTS / "tests"))
sys.path.insert(0, str(SCRIPTS.parent.parent / "a2h-spec" / "scripts"))
import spec_depth_gate as SDG  # noqa: E402
import next_batch as NB  # noqa: E402
import test_page_chunks as TPC  # noqa: E402


def _view(root: Path, page: str, nodes: int):
    d = root / "spec/ui" / page; d.mkdir(parents=True, exist_ok=True)
    (d / "view.xml").write_text('<hierarchy synthesized="true">' + "<node/>" * nodes + "</hierarchy>", encoding="utf-8")
    (d / "meta.json").write_text("{}", encoding="utf-8")


def _gen(root: Path, wave: str):
    env = dict(os.environ); env["ARKTS_SKILL_DIR"] = str(SCRIPTS.parent)
    r = subprocess.run([sys.executable, str(SCRIPTS / "generate_waves.py"), "--blueprint", "spec/blueprint",
                        "--out", "spec/waves", "--wave", wave, "--json"], capture_output=True, text=True,
                       encoding="utf-8", cwd=str(root), env=env, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads((root / ("spec/waves/plan-%s.json" % wave)).read_text(encoding="utf-8"))


class TestJudge(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(SDG.judge(None, 10, 0.4), "spec-missing")
        self.assertEqual(SDG.judge(2, 10, 0.4), "spec-shallow")      # 需 ≥4
        self.assertIsNone(SDG.judge(4, 10, 0.4))
        self.assertEqual(SDG.judge(0, 2, 0.4), "spec-shallow")       # 小页 0 要点
        self.assertIsNone(SDG.judge(1, 2, 0.4))                     # 小页有内容不判
        self.assertIsNone(SDG.judge(1, None, 0.4))                  # 无 view.xml 只判缺分节


class TestSectionMatching(unittest.TestCase):
    """DR_0903 冒烟实证：agent 写 `## ### MainActivity` + 七维三级标题，旧匹配判无分节 → 误回派。"""

    def test_hierarchical_heading_and_single_page_fallback(self):
        spec = ("# MainActivity 域规格\n\n## 范围\n- 略\n\n## ### MainActivity\n\n### SCREENS\n- 骰子图\n- 按钮\n- 文本\n\n"
                "### BEHAVIOR\n- 点击掷骰\n\n## 资源\n- 不计\n")
        secs = SDG.page_sections(spec, ["MainActivity"])
        self.assertEqual(len(secs), 1); self.assertEqual(secs[0][0], "MainActivity")
        self.assertEqual(SDG.section_points(spec, ["MainActivity"]), 4)
        spec2 = "## 2. 页面\n\n### 2.3 HomeActivity\n- a\n- b\n\n### 2.4 GuideActivity\n- c\n"
        self.assertEqual(SDG.section_points(spec2, ["HomeActivity"]), 2)
        spec3 = "# X 域\n- 一\n- 二\n"
        self.assertEqual(SDG.section_points(spec3, ["MainActivity"], single_page=True), 2)
        self.assertIsNone(SDG.section_points(spec3, ["MainActivity"]))


class TestGateAndSpecfix(unittest.TestCase):
    def test_gate_flags_and_specfix_only_redoes_flagged_domain(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); TPC._blueprint(root)
            # 夹具 big 域 spec 里 SearchActivity 只有一行；GuideActivity 有 4 要点。给 SearchActivity 12 个 view 节点 → 判薄；
            # small 域两页无 view.xml 且有分节 → 只判缺分节，故不判
            _view(root, "SearchActivity", 12); _view(root, "GuideActivity", 2)   # Guide 是小页且有内容 → 不判
            (root / "spec/domains/small.md").write_text("# small\n\n### AActivity\n- 一行\n\n### BActivity\n- 一行\n", encoding="utf-8")
            r = subprocess.run([sys.executable, str(GATE), "--project", str(root), "--json"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            rep = json.loads((root / "spec/reports/spec-depth.json").read_text(encoding="utf-8"))
            flagged = {(f["domain"], f["page"], f["code"]) for f in rep["findings"]}
            self.assertIn(("big", "SearchActivity", "spec-shallow"), flagged)
            self.assertFalse(any(f["page"] == "GuideActivity" for f in rep["findings"]))
            tasks = json.loads((root / "spec/reports/spec-tasks.json").read_text(encoding="utf-8"))
            self.assertEqual(list(tasks["domains"]), ["big"])
            # specfix：只回派 big，写权 = 域 spec 文件，任务书带判定明细与机械底线
            plan = _gen(root, "specfix")
            ag = [t for t in plan["tasks"] if t["kind"] == "agent"]
            self.assertEqual([t["id"] for t in ag], ["read:big"]); self.assertEqual(ag[0]["map_group"], "specfix-read")
            self.assertIn("spec/domains/big.md", ag[0]["ownership"])
            self.assertEqual([t["id"] for t in plan["tasks"] if t["kind"] == "reduce"], ["gate:spec-depth-2", "gate:interface-2"])   # I6
            prompt = (root / ag[0]["prompt_file"]).read_text(encoding="utf-8")
            self.assertIn("wave=specfix，spec 深度闸回派", prompt)
            self.assertIn("SearchActivity：分节要点", prompt); self.assertIn("每页的机械底线", prompt)
            self.assertIn("SearchActivity：view.xml 节点 12 → SCREENS 分节要点不少于 5 条", prompt)
            # 六件不齐（grill 前）也必须能生成 specfix——AIPPT_0903 实证 decisions.json/decision-ledger.md 缺席时 exit 1
            for name in ("decisions.json", "decision-ledger.md", "contracts.json", "ownership.json"):
                (root / "spec/blueprint" / name).rename(root / "spec/blueprint" / (name + ".hold"))
            plan_lite = _gen(root, "specfix")
            self.assertEqual([t["id"] for t in plan_lite["tasks"] if t["kind"] == "agent"], ["read:big"])
            for name in ("decisions.json", "decision-ledger.md", "contracts.json", "ownership.json"):
                (root / "spec/blueprint" / (name + ".hold")).rename(root / "spec/blueprint" / name)
            # understand 任务书也带机械底线；波尾有 gate:spec-depth
            und = _gen(root, "understand")
            self.assertIn("gate:spec-depth", [t["id"] for t in und["tasks"]])
            up = (root / next(t for t in und["tasks"] if t["id"] == "read:big")["prompt_file"]).read_text(encoding="utf-8")
            self.assertIn("每页的机械底线", up)
            # next_hint：understand 之后进 specfix；跑过一次后不再出 specfix（有界一次）。
            # E265⑤：跑完 spec-tasks.json 还非空 = 返工机会用尽仍不达标——原实现静默跳过，现在出 escalate。
            pp = (root / "spec/waves/plan-understand.json").resolve()
            h = NB._next_hint(und, pp, root.resolve()); self.assertEqual((h["kind"], h["wave"]), ("wave", "specfix"))
            (root / "spec/state").mkdir(parents=True, exist_ok=True)
            (root / "spec/state/state.json").write_text(json.dumps({"waves": {"specfix": {"tasks": []}}}), encoding="utf-8")
            h2 = NB._next_hint(und, pp, root.resolve())
            self.assertEqual(h2["kind"], "escalate")
            self.assertEqual(h2["tasks"], "spec/reports/spec-tasks.json")


if __name__ == "__main__":
    unittest.main()
