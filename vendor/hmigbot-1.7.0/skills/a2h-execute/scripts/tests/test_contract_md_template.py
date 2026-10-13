"""E42 回归：CONTRACT.md 必须是模板全本；mapping 片段页面外壳不得再写 @Entry。
立此闸的事实：AIPPT_0903 test4 domains 波 73 页全 @Entry、零 PageBuilder，sync_pagemap NO_BUILDERS 升级停机（2026-09-04 21:52）。
"""
from __future__ import annotations

import subprocess
import sys
import re
import tempfile
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent.parent
GATE = SKILLS / "a2h-spec" / "scripts" / "hygiene_gate.py"
TEMPLATE = SKILLS / "a2h-execute" / "references" / "templates" / "CONTRACT.template.md"
MAPPING = SKILLS / "a2h-execute" / "references" / "fragments" / "mapping.md"


def _line(root: Path) -> str:
    r = subprocess.run([sys.executable, str(GATE), "--project-root", str(root)], capture_output=True, text=True)
    return next(l for l in (r.stdout + r.stderr).splitlines() if "CONTRACT.md 模板全本" in l)


class TestContractTemplate(unittest.TestCase):
    def test_brief_contract_fails_full_template_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "spec").mkdir()
            (root / "spec/CONTRACT.md").write_text("# X → HarmonyOS 实现契约\n\n## 实现边界\n- 页面统一使用 Navigation/NavDestination\n", encoding="utf-8")
            line = _line(root); self.assertIn("FAIL", line); self.assertIn("PageBuilder", line); self.assertIn("## 1.", line)
            raw = TEMPLATE.read_text(encoding="utf-8")
            # E240：只替换一个槽位的原始模板 = 手工填参痕迹（残留 {{…}} 与模板头注）→ FAIL
            (root / "spec/CONTRACT.md").write_text(raw.replace("{{APP_NAME}}", "X"), encoding="utf-8")
            self.assertIn("FAIL", _line(root))
            # contract_fill 式产物：剥掉头注（从契约正文标题起）、全部槽位落值 → PASS
            body = raw[raw.index("# {{APP_NAME}}"):]
            (root / "spec/CONTRACT.md").write_text(re.sub(r"\{\{[A-Z_]+\}\}", "X", body), encoding="utf-8")
            self.assertIn("PASS", _line(root))
            (root / "spec/CONTRACT.md").unlink()
            self.assertIn("FAIL", _line(root))

    def test_mapping_fragment_page_shell(self):
        t = MAPPING.read_text(encoding="utf-8")
        self.assertNotIn("`@Entry @ComponentV2`", t)
        self.assertIn("PageBuilder", t); self.assertIn("NavDestination", t)


if __name__ == "__main__":
    unittest.main()
