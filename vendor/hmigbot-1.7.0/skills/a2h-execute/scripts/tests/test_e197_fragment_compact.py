# -*- coding: utf-8 -*-
"""E197：片段注入剥 HTML 注释 + 折叠空行。（E198 已撤回，E204）"""
from __future__ import annotations
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assemble_prompt as ap  # noqa: E402


class TestE197LoadFragment(unittest.TestCase):
    def test_strips_html_comments_and_collapses_blank_lines(self):
        with tempfile.TemporaryDirectory() as td:
            frag = Path(td) / "references" / "fragments"
            frag.mkdir(parents=True)
            (frag / "x.md").write_text(
                "<!-- GAP: 维护者备注 -->\n# x — 标题\n\n规则 A `a()`\n\n\n\n规则 B\n<!-- source: a/b.md:L1-2 -->\n",
                encoding="utf-8")
            old = os.environ.get("ARKTS_SKILL_DIR")
            os.environ["ARKTS_SKILL_DIR"] = td
            try:
                out = ap.load_fragment("x")
            finally:
                if old is None:
                    del os.environ["ARKTS_SKILL_DIR"]
                else:
                    os.environ["ARKTS_SKILL_DIR"] = old
        self.assertEqual(out, "# x — 标题\n\n规则 A `a()`\n\n规则 B")
        self.assertNotIn("<!--", out)


if __name__ == "__main__":
    unittest.main()
