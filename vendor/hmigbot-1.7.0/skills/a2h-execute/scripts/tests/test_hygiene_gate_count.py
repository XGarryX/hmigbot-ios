"""hygiene_gate 计数漂移回归（第十五批 S8）。
DR_0903 冒烟：understand 波尾挂 3 个 reduce 后 plan-understand.tasks=4 ≠ 域数 1，闸假 FAIL，主会话把 plan 临时挪走才过。
判据：只数 kind=agent 的任务。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GATE = Path(__file__).resolve().parent.parent.parent.parent / "a2h-spec" / "scripts" / "hygiene_gate.py"


class TestHygieneCount(unittest.TestCase):
    def test_reduce_nodes_do_not_count_as_domains(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for d in ("spec/blueprint", "spec/waves", "spec/domains", "entry/src/main/ets"):
                (root / d).mkdir(parents=True)
            (root / "spec/blueprint/domain-map.json").write_text(json.dumps({"version": 1, "domains": [
                {"key": "main", "spec_file": "spec/domains/main.md", "pages": ["MainActivity"]}]}), encoding="utf-8")
            (root / "spec/blueprint/ownership.json").write_text(json.dumps({"version": 1, "owners": {
                "seed": [], "domain:main": ["entry/src/main/ets/features/main/**"]}, "mainloop_owned": []}), encoding="utf-8")
            (root / "spec/domains/main.md").write_text("# main\n", encoding="utf-8")
            (root / "spec/waves/plan-understand.json").write_text(json.dumps({"wave": "understand", "tasks": [
                {"id": "read:main", "kind": "agent"}, {"id": "reduce:harvest-literals", "kind": "reduce"},
                {"id": "reduce:seed-resources", "kind": "reduce"}, {"id": "gate:spec-depth", "kind": "reduce"}]}), encoding="utf-8")
            r = subprocess.run([sys.executable, str(GATE), "--spec-root", str(root / "spec"),
                                "--ets-root", str(root / "entry/src/main/ets")], capture_output=True, text=True)
            line = next(l for l in (r.stdout + r.stderr).splitlines() if "漂移" in l)
            self.assertIn("PASS", line); self.assertIn('"plan-understand.tasks": 1', line)

    def test_infra_only_ownership_before_a3_is_not_drift(self):
        """AIPPT_0903：infra_carve 提前建出只含 infra:* 的 ownership.json，页面域写权要到 A3 才有。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for d in ("spec/blueprint", "spec/waves", "spec/domains", "entry/src/main/ets"):
                (root / d).mkdir(parents=True)
            (root / "spec/blueprint/domain-map.json").write_text(json.dumps({"version": 1, "domains": [
                {"key": "home", "spec_file": "spec/domains/home.md", "pages": ["HomeActivity"]},
                {"key": "net", "spec_file": "spec/domains/net.md", "pages": [], "layer": "infra"}]}), encoding="utf-8")
            (root / "spec/blueprint/ownership.json").write_text(json.dumps({"version": 1, "owners": {
                "infra:net": ["entry/src/main/ets/infra/net/net/**"]}, "mainloop_owned": []}), encoding="utf-8")
            for k in ("home", "net"):
                (root / ("spec/domains/%s.md" % k)).write_text("# %s\n" % k, encoding="utf-8")
            (root / "spec/waves/plan-understand.json").write_text(json.dumps({"wave": "understand", "tasks": [
                {"id": "read:home", "kind": "agent"}, {"id": "read:net", "kind": "agent"}, {"id": "gate:spec-depth", "kind": "reduce"}]}), encoding="utf-8")
            r = subprocess.run([sys.executable, str(GATE), "--spec-root", str(root / "spec"),
                                "--ets-root", str(root / "entry/src/main/ets")], capture_output=True, text=True)
            line = next(l for l in (r.stdout + r.stderr).splitlines() if "漂移" in l)
            self.assertIn("PASS", line); self.assertIn("A3 未定稿", line)
            # A3 定稿后：页面域 1 = domain 条目 1，infra 1 = infra 条目 1 → PASS；少一条 → FAIL
            (root / "spec/blueprint/ownership.json").write_text(json.dumps({"version": 1, "owners": {
                "infra:net": ["x/**"], "domain:home": ["y/**"]}, "mainloop_owned": []}), encoding="utf-8")
            r = subprocess.run([sys.executable, str(GATE), "--spec-root", str(root / "spec"), "--ets-root", str(root / "entry/src/main/ets")], capture_output=True, text=True)
            self.assertIn("PASS", next(l for l in (r.stdout + r.stderr).splitlines() if "漂移" in l))
            (root / "spec/blueprint/ownership.json").write_text(json.dumps({"version": 1, "owners": {
                "domain:home": ["y/**"]}, "mainloop_owned": []}), encoding="utf-8")
            r = subprocess.run([sys.executable, str(GATE), "--spec-root", str(root / "spec"), "--ets-root", str(root / "entry/src/main/ets")], capture_output=True, text=True)
            self.assertIn("FAIL", next(l for l in (r.stdout + r.stderr).splitlines() if "漂移" in l))


if __name__ == "__main__":
    unittest.main()
