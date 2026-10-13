"""E46/E47 回归。立此闸的事实（AIPPT_0903 test4，2026-09-04 17:15–17:21）：主会话在 13 open / 7 P0 的 fix-backlog 审批文件里
自写 {"approved": true, "by": "user"}；escalated-ratio 升级后未呈报用户，直接生成并开跑 wiring 波。
判据：批复缺 by/quote 不放行（auto 批复照旧）；前波 ERROR 时拍①只出 escalate，--allow-open-prev 才放行；前波 RUNNING 不拦。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from test_scheduler_kernel import KernelFixture, VALID_ALPHA, VALID_BETA

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import _wavelib as W  # noqa: E402


class TestApprovalNeedsHuman(KernelFixture):
    def _approval_plan(self):
        plan = self.base_plan()
        plan["tasks"][2] = {"id": "gate:compile", "kind": "reduce", "run": self.approval_run,
                            "parents": ["@domains-impl"], "approval": {"suspend_payload": "spec/state/approvals/gate.json"}}
        return plan

    def test_forged_approval_without_quote_is_not_granted(self):
        self.write_plan(self._approval_plan()); self.next_batch()
        self.write_result("alpha", VALID_ALPHA); self.write_result("beta", VALID_BETA); self.land(expect=2)
        ap = self.proj / "spec/state/approvals/gate.json"
        self._write(ap, json.dumps({"approved": True, "by": "user"}))                 # 主会话替用户批
        act = self.next_batch(); self.assertEqual(act["action"], "approval"); self.assertIn("by/quote", act.get("rejected") or "")
        self._write(ap, json.dumps({"approved": True, "by": "user", "quote": "同意，按 owner 派接线"}))
        self.assertEqual(self.next_batch()["action"], "dispatch")

    def test_auto_and_resolution_forms(self):
        root = self.proj; (root / "spec/state/approvals").mkdir(parents=True, exist_ok=True)
        f = root / "spec/state/approvals/x.json"
        f.write_text(json.dumps({"approved": True, "auto": True}), encoding="utf-8"); self.assertTrue(W.approval_granted(root, "spec/state/approvals/x.json"))
        f.write_text(json.dumps({"approved": True, "resolution": {"defer": True, "by": "u", "quote": "先 defer"}}), encoding="utf-8"); self.assertTrue(W.approval_granted(root, "spec/state/approvals/x.json"))
        f.write_text(json.dumps({"approved": True}), encoding="utf-8"); self.assertFalse(W.approval_granted(root, "spec/state/approvals/x.json"))
        f.write_text(json.dumps({"approved": False}), encoding="utf-8"); self.assertIsNone(W.approval_rejection_reason(root, "spec/state/approvals/x.json"))


class TestPrevWaveGuard(KernelFixture):
    def _journal(self, status: str):
        jp = self.state.parent / "journal.json"
        j = json.loads(jp.read_text(encoding="utf-8")) if jp.exists() else {"version": 1, "workflow_status": [], "operation_outputs": []}
        j["workflow_status"] = [{"workflow_id": "infra", "status": status, "plan_path": "spec/waves/plan-infra.json"}]
        self._write(jp, json.dumps(j))

    def test_prev_wave_error_blocks_and_flag_allows(self):
        self.write_plan(self.base_plan()); self._journal("ERROR")
        act = self.next_batch(); self.assertEqual(act["action"], "escalate"); self.assertEqual(act["open_prev_waves"], ["infra"])
        r = subprocess.run([sys.executable, str(SCRIPTS / "next_batch.py"), "--plan", str(self.plan_path), "--state", str(self.state),
                            "--json", "--allow-open-prev"], capture_output=True, text=True, cwd=self.proj)
        self.assertEqual(json.loads(r.stdout)["action"], "dispatch", r.stderr)

    def test_prev_wave_running_does_not_block(self):
        self.write_plan(self.base_plan()); self._journal("RUNNING")
        self.assertEqual(self.next_batch()["action"], "dispatch")


class TestHandoffApprovals(KernelFixture):
    def test_manual_approvals_are_listed_for_user(self):
        import handoff_check as H
        ap = self.proj / "spec/state/approvals"; ap.mkdir(parents=True, exist_ok=True)
        (ap / "fix-backlog.json").write_text(json.dumps({"approved": True, "by": "user", "quote": "哪个效果好做哪个"}), encoding="utf-8")
        (ap / "auto.json").write_text(json.dumps({"approved": True, "auto": True}), encoding="utf-8")
        (ap / "pending.json").write_text(json.dumps({"approved": False}), encoding="utf-8")
        checks, facts = H.run_checks(self.proj, self.blueprint)
        c = next(x for x in checks if x["id"] == "approvals")
        self.assertEqual(c["status"], "warn"); self.assertIn("哪个效果好做哪个", c["detail"]); self.assertNotIn("auto.json", c["detail"])
        self.assertEqual([m["file"] for m in facts["approvals"]], ["fix-backlog.json"])
        self.assertIn("批复核对：fix-backlog.json 由 user 批，原话「哪个效果好做哪个」", H.render_message(checks, facts))


if __name__ == "__main__":
    import unittest
    unittest.main()
