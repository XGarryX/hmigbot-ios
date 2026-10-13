#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第三批 + 第二批收尾单测：approval_request 材料 / device_triage 命中链 / a2h-retrospect 存在。

用法示例:
    python3 arkts-skills/skills/a2h-execute/scripts/tests/test_batch3.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent.parent.parent.parent.parent
APPROVAL_REQ = BUNDLE / "skills" / "a2h-plan" / "scripts" / "approval_request.py"
DEVICE_TRIAGE = BUNDLE / "skills" / "arkts-visual-verify" / "scripts" / "device_triage.py"


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj) if not isinstance(obj, str) else obj, encoding="utf-8")


class TestApprovalRequest(unittest.TestCase):
    """V6/V7：审批材料三层 + 派生卡逐张标注 + 设备档位 blocker（--no-device-probe）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-ar-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.bp = self.proj / "spec" / "blueprint"
        _write(self.bp / "domain-map.json", {"version": 1, "domains": [
            {"key": "a", "title": "A", "tier": "core"}]})
        _write(self.bp / "workflow-params.json", {"version": 1,
            "gates": {"device_smoke": "hmos"}, "api_inventory_status": "ready"})
        _write(self.bp / "decisions.json", {"version": 1, "decisions": [
            {"id": "PD-01", "category": "C9", "status": "pending-approval", "title": "普通卡"},
            {"id": "PD-02", "category": "C9", "status": "pending-approval", "title": "派生卡",
             "derived_from": "PD-01", "boundary": "登录页外才跳",
             "on_device_check": "登录页内点验证码手机号不清空"}]})
        # E147：审批前置——A 段两道门已处置（本类测的是材料结构与设备档位，不是前置本身）
        _write(self.proj / "spec" / "reports" / "hygiene-gate.json", {"verdict": "PASS"})
        _write(self.proj / "spec" / ".a2h" / "open-findings.json", {"sections": {"spec/lint_coverage": {"findings": []}}})

    def _run(self, *extra):
        return subprocess.run(
            [sys.executable, str(APPROVAL_REQ), "--blueprint", "spec/blueprint",
             "--waves-dir", "spec/waves", "--out", "spec/state/approval-request.json",
             "--json", *extra],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj), timeout=60)

    def test_material_structure(self):
        proc = self._run("--no-device-probe")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        mat = json.loads((self.proj / "spec/state/approval-request.json").read_text(encoding="utf-8"))
        self.assertEqual(len(mat["layer2_pd_cards"]), 2)
        derived = next(c for c in mat["layer2_pd_cards"] if c["id"] == "PD-02")
        self.assertTrue(derived["_requires_individual_approval"])   # 派生卡逐张
        self.assertEqual(derived["boundary"], "登录页外才跳")
        self.assertEqual(mat["layer1_summary"]["device_smoke"], "hmos")
        self.assertFalse(mat["device_probe"]["checked"])            # --no-device-probe

    def test_off_tier_no_device_blocker(self):
        _write(self.bp / "workflow-params.json", {"version": 1,
            "gates": {"device_smoke": "off"}, "api_inventory_status": "ready"})
        proc = self._run()   # 不带 no-device-probe，但 off 档不检查设备
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["blockers"], [])


class TestDeviceTriageHitChain(unittest.TestCase):
    """V16：hit_chain 纯函数——覆盖坐标的全部节点，识别 Block 死区。"""

    def test_hit_chain_identifies_block(self):
        sys.path.insert(0, str(DEVICE_TRIAGE.parent))
        import device_triage
        tree = {"attributes": {"bounds": "[0,0][1080,2000]", "type": "Stack"},
                "children": [
                    {"attributes": {"bounds": "[0,0][1080,2000]", "type": "Column",
                                    "hitTestBehavior": "Block"},
                     "children": [
                         {"attributes": {"bounds": "[400,1100][680,1300]", "type": "Button",
                                         "text": "同意", "clickable": "true"}, "children": []}]}]}
        chain = device_triage.hit_chain(tree, 540, 1200)
        self.assertEqual(len(chain), 3)                            # Stack/Column/Button 都覆盖
        self.assertEqual(chain[-1]["type"], "Button")             # 树序最后=实际命中
        self.assertTrue(any(n["hitTestBehavior"] == "Block" for n in chain))

    def test_hit_chain_empty_off_point(self):
        sys.path.insert(0, str(DEVICE_TRIAGE.parent))
        import device_triage
        tree = {"attributes": {"bounds": "[0,0][100,100]", "type": "Stack"}, "children": []}
        self.assertEqual(device_triage.hit_chain(tree, 500, 500), [])


class TestRetrospectRestored(unittest.TestCase):
    """V18：a2h-retrospect 恢复入 bundle（feature-coverage-auditor 引用不再悬空）。"""

    def test_skill_and_references_present(self):
        skill = BUNDLE / "skills" / "a2h-retrospect" / "SKILL.md"
        self.assertTrue(skill.is_file())
        text = skill.read_text(encoding="utf-8")
        self.assertIn("backend-facts", text)                       # V18 后端事实沉淀节
        self.assertIn("V18", text)
        self.assertTrue((BUNDLE / "skills" / "a2h-retrospect" / "references").is_dir())


def main():
    unittest.main()


if __name__ == "__main__":
    main()
