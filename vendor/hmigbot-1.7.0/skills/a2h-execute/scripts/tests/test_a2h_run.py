# -*- coding: utf-8 -*-
"""E208 一键起跑：模板渲染、自检各分支、runner 命令拼装、--status 快照。不起真实会话。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import a2h_run  # noqa: E402

TPL = "工程 {{project_name}} 源 {{android_src}} 结束"


def make_project(td: Path, *, skill=True, template=True, sdk_line=True):
    root = td / "Proj_X"; root.mkdir()
    if skill:
        s = root / ".agents/skills/a2h-execute/scripts"; s.mkdir(parents=True)
        (s / "unattended_runner.py").write_text("# stub\n", encoding="utf-8")
    if template:
        t = root / ".agents/templates"; t.mkdir(parents=True, exist_ok=True)
        (t / "CODEX_PROMPT.md").write_text(TPL, encoding="utf-8")
    (root / "local.properties").write_text("hwsdk.dir=%s\n" % td if sdk_line else "", encoding="utf-8")
    src = td / "android"; src.mkdir(exist_ok=True)
    fake_codex = td / "codex"; fake_codex.write_text("#!/bin/sh\n", encoding="utf-8"); fake_codex.chmod(0o755)
    return root, src, fake_codex


class TestRender(unittest.TestCase):
    def test_render_and_leftover(self):
        self.assertEqual(a2h_run.render_prompt(TPL, "P", "/a"), "工程 P 源 /a 结束")
        with self.assertRaises(ValueError):
            a2h_run.render_prompt("x {{unknown}}", "P", "/a")


class TestPreflight(unittest.TestCase):
    def test_all_good_renders_prompt_and_builds_cmd(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); root, src, cx = make_project(td)
            problems, env = a2h_run.preflight(root, str(src), str(cx))
            self.assertEqual(problems, [], problems)
            out = a2h_run.write_prompt(root, str(src))
            txt = out.read_text(encoding="utf-8")
            self.assertIn("工程 Proj_X", txt); self.assertIn(str(src.resolve()), txt)

            class A: max_restarts = 3; backoff = 300
            cmd = a2h_run.runner_cmd(root, env, A())
            self.assertIn("--prompt", cmd); self.assertIn(str(cx), cmd); self.assertIn("--max-restarts", cmd)

    def test_missing_pieces_reported(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); root, src, cx = make_project(td, skill=False, template=False, sdk_line=False)
            os.environ.pop("DEVECO_SDK_HOME", None)
            problems, env = a2h_run.preflight(root, None, "/nonexistent/codex", fix=False)
            joined = "\n".join(problems)
            self.assertIn("未装 skill", joined)
            self.assertIn("codex", joined)
            self.assertIn("--android-src", joined)

    def test_sdk_backfill(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); root, src, cx = make_project(td, sdk_line=False)
            os.environ["DEVECO_SDK_HOME"] = str(td)
            try:
                sdk, notes = a2h_run.ensure_sdk(root, fix=True)
            finally:
                del os.environ["DEVECO_SDK_HOME"]
            self.assertEqual(sdk, str(td)); self.assertTrue(notes)
            self.assertIn("hwsdk.dir=%s" % td, (root / "local.properties").read_text(encoding="utf-8"))

    def test_existing_prompt_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); root, src, cx = make_project(td)
            (root / "CODEX_PROMPT.md").write_text("mine", encoding="utf-8")
            problems, env = a2h_run.preflight(root, None, str(cx))
            self.assertEqual(problems, [])
            self.assertEqual((root / "CODEX_PROMPT.md").read_text(encoding="utf-8"), "mine")


class TestStatus(unittest.TestCase):
    def test_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); root, src, cx = make_project(td)
            (root / "spec/state").mkdir(parents=True); (root / "spec/reports").mkdir(parents=True)
            (root / "spec/state/journal.json").write_text(json.dumps({"workflow_status": [{"workflow_id": "infra", "status": "SUCCESS"}], "operation_outputs": []}), encoding="utf-8")
            (root / "spec/state/unattended-runner.json").write_text(json.dumps({"runs": [{"status": "crashed"}, {"status": "completed"}]}), encoding="utf-8")
            (root / "spec/reports/hygiene-debt.json").write_text("{}", encoding="utf-8")
            (root / "spec/state/hotfix-ledger.json").write_text(json.dumps([{"file": "a"}, {"file": "b"}]), encoding="utf-8")
            s = a2h_run.status(root)
            self.assertEqual(s["waves"], {"infra": "SUCCESS"}); self.assertEqual(s["sessions"], 2)
            self.assertEqual(s["crash_restarts"], 1)
            self.assertEqual(s["debts"], ["hygiene-debt.json"]); self.assertEqual(s["hotfixes"], 2); self.assertFalse(s["handoff"])

    def test_cli_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); root, src, cx = make_project(td)
            r = subprocess.run([sys.executable, str(SCRIPTS / "a2h_run.py"), "--project", str(root), "--android-src", str(src), "--codex", str(cx), "--dry-run"],
                               capture_output=True, text=True, env=dict(os.environ, DEVECO_SDK_HOME=str(td)))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("unattended_runner.py", r.stdout); self.assertIn("--max-restarts", r.stdout)


if __name__ == "__main__":
    unittest.main()
