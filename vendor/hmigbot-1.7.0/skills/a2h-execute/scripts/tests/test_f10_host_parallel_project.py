#!/usr/bin/env python3
"""F10(8) 回归：host_parallel_check 接受并忽略 --project（AIPPT_930_token 2026-09-20 06:33 热改记录：主会话按其它装机脚本
惯例传 --project，argparse 直接拒收、装机自检被一条无害参数打断）。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "host_parallel_check.py"
PY = sys.executable or "python3"


class TestProjectFlagIgnored(unittest.TestCase):
    def _run(self, *extra):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "config.toml").write_text("[agents]\nmax_concurrent_threads_per_session = 16\n", encoding="utf-8")
            p = subprocess.run([PY, str(SCRIPT), "--codex-home", td, "--json", *extra],
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
        return p

    def test_project_accepted(self):
        p = self._run("--project", ".")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(json.loads(p.stdout)["ok"])

    def test_same_result_without_project(self):
        a, b = self._run(), self._run("--project", "/some/where")
        self.assertEqual(json.loads(a.stdout)["configured"], json.loads(b.stdout)["configured"])

    def test_unknown_flag_still_rejected(self):
        p = self._run("--bogus")
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main()
