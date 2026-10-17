"""fence_audit.py 回归：cross_owner 越界未经确认不放行编译。
立此闸的事实：AIPPT_915_test3 5 条 cross_owner（写进同波另一任务围栏）落账后无人复核，
静默过了编译门。fence_breach 的设计是只记账（判失败会触发整轮重派），本门把「记账」变成
「必须有人看一眼」：exit 1 → on_fail 升级呈报；人把 {task, file} 写进 fence-ack.json 放行。
forbidden 已在落账时判 FAIL 并还原，unowned 记债，二者只入报告不阻断。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SCRIPT = SCRIPTS / "fence_audit.py"
sys.path.insert(0, str(SCRIPTS))
import fence_audit as FA  # noqa: E402

STATE = {"version": 1, "waves": {"domains": {"run_id": "r", "tasks": [
    {"id": "impl:home", "status": "done", "fence_breach": [
        {"file": "entry/src/main/ets/features/pay/PayVM.ets", "kind": "cross_owner", "owner": "impl:pay"},
        {"file": "build-profile.json5", "kind": "unowned"}]},
    {"id": "impl:pay", "status": "failed", "files_touched": ["entry/src/main/ets/features/pay/PayVM.ets"],
     "fence_breach": [{"file": "spec/domains/pay.md", "kind": "forbidden"}]},
    {"id": "impl:user", "status": "done", "files_touched": []},
]}}}


class TestAudit(unittest.TestCase):
    def test_blocking_only_unacked_cross_owner(self):
        rep = FA.audit(STATE, "domains", None)
        self.assertEqual(rep["status"], "FAIL")
        self.assertEqual([(r["task"], r["file"]) for r in rep["blocking"]],
                         [("impl:home", "entry/src/main/ets/features/pay/PayVM.ets")])
        self.assertEqual(rep["counts"], {"cross_owner": 1, "forbidden": 1, "unowned": 1})

    def test_ack_releases(self):
        ack = {"acked": [{"task": "impl:home", "file": "entry/src/main/ets/features/pay/PayVM.ets"}]}
        self.assertEqual(FA.audit(STATE, "domains", ack)["status"], "PASS")
        self.assertEqual(FA.audit(STATE, "domains", {"ack_all_waves": ["domains"]})["status"], "PASS")
        self.assertEqual(FA.audit(STATE, "domains", {"ack_all_waves": ["infra"]})["status"], "FAIL")

    def test_auto_ack_when_owner_did_not_touch(self):
        """E14：owner 本波没碰过的文件被别人写了，不是双写——自动放行，不等人。"""
        st = json.loads(json.dumps(STATE))
        st["waves"]["domains"]["tasks"][1]["files_touched"] = ["entry/src/main/ets/features/pay/Other.ets"]
        rep = FA.audit(st, "domains", None)
        self.assertEqual(rep["status"], "PASS")
        row = rep["rows"]["cross_owner"][0]
        self.assertTrue(row["acked"]); self.assertIn("auto_acked", row)

    def test_other_wave_or_no_breach_passes(self):
        self.assertEqual(FA.audit(STATE, "infra", None)["status"], "PASS")

    def test_cli_exit_codes_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "spec/state").mkdir(parents=True)
            sp = root / "spec/state/state.json"; sp.write_text(json.dumps(STATE), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), "--state", str(sp), "--wave", "domains", "--json"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            out = json.loads(r.stdout); self.assertEqual(out["status"], "FAIL"); self.assertIn("how_to_release", out)
            rep = json.loads((root / "spec/reports/fence-audit-domains.json").read_text(encoding="utf-8"))
            self.assertEqual(rep["counts"]["cross_owner"], 1)
            (root / "spec/state/fence-ack.json").write_text(json.dumps(
                {"acked": [{"task": "impl:home", "file": "entry/src/main/ets/features/pay/PayVM.ets"}]}), encoding="utf-8")
            r2 = subprocess.run([sys.executable, str(SCRIPT), "--state", str(sp), "--wave", "domains", "--json"],
                                capture_output=True, text=True)
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)


if __name__ == "__main__":
    unittest.main()
