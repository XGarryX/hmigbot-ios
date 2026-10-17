# -*- coding: utf-8 -*-
"""product_write_audit strict 模式（AIPPT_930_token2：主会话手改产物只 WARN 从不拦）：--strict 或 gates.unattended=true →
mainloop_edit 记 FAIL、passed=false、exit 1、报告 mode=strict；attended 缺省仍 WARN / exit 0 / mode=warn，报告形态不变。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import product_write_audit as PWA  # noqa: E402

T0 = datetime(2026, 9, 21, 8, 0, 0, tzinfo=timezone.utc)


def _iso(sec: int) -> str:
    return (T0 + timedelta(seconds=sec)).isoformat(timespec="seconds")


def _touch(root: Path, rel: str, sec: int) -> None:
    p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text("// x\n", encoding="utf-8")
    ts = (T0 + timedelta(seconds=sec)).timestamp(); os.utime(p, (ts, ts))


def _fixture(root: Path, gates=None) -> Path:
    st = root / "spec/state"; st.mkdir(parents=True)
    (st / "state.json").write_text(json.dumps({"waves": {"domains": {"started_at": _iso(0), "tasks": [
        {"id": "impl:main", "status": "done", "at": _iso(600)}]}}}), encoding="utf-8")
    (st / "dispatch.json").write_text(json.dumps({"version": 1, "waves": {"domains": {
        "dispatched": {"impl:main": {"attempts": 1, "last_dispatch_at": _iso(100)}}}}}), encoding="utf-8")
    (st / "journal.json").write_text(json.dumps({"operation_outputs": []}), encoding="utf-8")
    bp = root / "spec/blueprint"; bp.mkdir(parents=True)
    (bp / "workflow-params.json").write_text(json.dumps({"gates": gates or {}}), encoding="utf-8")
    _touch(root, "entry/src/main/ets/pages/AgentPage.ets", 300)     # 代理窗口
    _touch(root, "entry/src/main/ets/pages/HandEdited.ets", 1200)   # 越权
    return st / "state.json"


def _run(sp: Path, *args):
    r = subprocess.run([sys.executable, str(SCRIPTS / "product_write_audit.py"), "--state", str(sp), "--wave", "domains", "--json"] + list(args),
                       capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout)


class TestStrict(unittest.TestCase):
    def test_attended_warn(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); sp = _fixture(root)
            rc, out = _run(sp)
            self.assertEqual((rc, out["mode"], out["mainloop_edits"]), (0, "warn", 1))
            rep = json.loads((root / "spec/reports/product-write-audit-domains.json").read_text(encoding="utf-8"))
            self.assertEqual((rep["mode"], rep["findings"][0]["severity"], rep["passed"]), ("warn", "WARN", False))
            self.assertEqual(rep["counts"], {"agent": 1, "script": 0, "quick_fix": 0, "mainloop_edit": 1})

    def test_strict_flag(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); sp = _fixture(root)
            rc, out = _run(sp, "--strict")
            self.assertEqual((rc, out["mode"], out["ok"]), (1, "strict", False))
            rep = json.loads((root / "spec/reports/product-write-audit-domains.json").read_text(encoding="utf-8"))
            self.assertEqual((rep["mode"], rep["findings"][0]["severity"], rep["passed"]), ("strict", "FAIL", False))
            self.assertEqual(rep["findings"][0]["code"], "mainloop_edit")

    def test_unattended_gate_from_blueprint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); sp = _fixture(root, gates={"unattended": True})
            rc, out = _run(sp)
            self.assertEqual((rc, out["mode"]), (1, "strict"))
            # --blueprint 显式指向另一份 attended 参数 → warn
            other = root / "bp2"; other.mkdir()
            (other / "workflow-params.json").write_text(json.dumps({"gates": {"unattended": False}}), encoding="utf-8")
            rc, out = _run(sp, "--blueprint", str(other))
            self.assertEqual((rc, out["mode"]), (0, "warn"))
            self.assertTrue(PWA.unattended_on(root / "spec/blueprint"))
            self.assertFalse(PWA.unattended_on(root / "nope"))

    def test_strict_clean_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); sp = _fixture(root, gates={"unattended": True})
            (root / "entry/src/main/ets/pages/HandEdited.ets").unlink()
            rc, out = _run(sp)
            self.assertEqual((rc, out["ok"], out["mode"]), (0, True, "strict"))


if __name__ == "__main__":
    unittest.main()
