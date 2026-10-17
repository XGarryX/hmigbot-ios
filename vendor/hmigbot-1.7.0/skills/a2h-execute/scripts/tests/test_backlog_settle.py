"""backlog_settle.py 回归（第十五批 P11：wiring 波尾销账）。
立此闸的事实：test3 wiring 18/18 完成、compile-w 绿，fix-backlog 仍 open=75——没有节点把回执核销回台账，
handoff-check 卡死只能手工 defer。固定判据：BK id 强匹配与 file#anchor 文件匹配销账；仅 files 触达不销账
但留痕；skipped 指名保持 open 并带原因；items 只留 open 条目、resolved_items 另列；open 归零自动写审批。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SCRIPT = SCRIPTS / "backlog_settle.py"
sys.path.insert(0, str(SCRIPTS))
import backlog_settle as BS  # noqa: E402

ITEMS = [
    {"id": "BK-1", "required_owner": "mainloop", "severity": "P0", "file": "entry/src/main/ets/wiring/a.ets", "summary": "a"},
    {"id": "BK-2", "required_owner": "app-home", "severity": "P1", "file": "entry/src/main/ets/pages/HomePage.ets", "summary": "b"},
    {"id": "BK-3", "required_owner": "app-home", "severity": "P1", "file": "entry/src/main/ets/pages/GuidePage.ets", "summary": "c"},
    {"id": "BK-4", "required_owner": "seed", "severity": "P0", "file": "entry/src/main/ets/common/HttpCore.ets", "summary": "d"},
]
RECEIPTS = [
    ("wiring-mainloop.json", {"resolved_refs": ["BK-1 已接线", "entry/src/main/ets/wiring/a.ets#mount"], "files": ["entry/src/main/ets/wiring/a.ets"]}),
    ("wiring-app-home.json", {"resolved_refs": ["entry/src/main/ets/pages/HomePage.ets#onSearch"],
                              "files": ["entry/src/main/ets/pages/HomePage.ets", "entry/src/main/ets/pages/GuidePage.ets"]}),
    ("wiring-seed.json", {"skipped": [{"finding_ref": "BK-4", "reason": "outside task whitelist"}], "files": []}),
]


class TestSettle(unittest.TestCase):
    def test_three_tiers(self):
        out = BS.settle({"version": 1, "open": 4, "items": ITEMS}, RECEIPTS)
        self.assertEqual(out["open"], 2)
        self.assertEqual({r["id"]: r["evidence"] for r in out["resolved_items"]}, {"BK-1": "strong", "BK-2": "file"})
        open_by = {i["id"]: i for i in out["items"]}
        self.assertEqual(open_by["BK-3"]["evidence"], "touched_only")                 # 只碰过文件不算销账
        self.assertEqual(open_by["BK-4"]["evidence"], "skipped"); self.assertIn("whitelist", open_by["BK-4"]["skipped_reason"])
        self.assertEqual(out["by_owner"], {"app-home": ["BK-3"], "seed": ["BK-4"]})
        self.assertEqual(out["settle_stats"], {"receipts": 3, "strong": 1, "file": 1, "touched_only": 1, "skipped": 1})

    def test_idempotent_and_accumulates_resolved(self):
        out1 = BS.settle({"version": 1, "open": 4, "items": ITEMS}, RECEIPTS)
        out2 = BS.settle(out1, RECEIPTS)
        self.assertEqual(out2["open"], 2); self.assertEqual(len(out2["resolved_items"]), 2)

    def test_cli_writes_both_files_and_auto_approves_when_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "spec/reports").mkdir(parents=True); (root / "spec/blueprint").mkdir(parents=True)
            (root / "spec/waves/results/wiring").mkdir(parents=True)
            (root / "spec/reports/fix-backlog.json").write_text(json.dumps({"version": 1, "open": 2, "items": ITEMS[:2]}), encoding="utf-8")
            (root / "spec/waves/results/wiring/wiring-mainloop.json").write_text(
                "回执\n```json\n" + json.dumps(RECEIPTS[0][1]) + "\n```\n", encoding="utf-8")
            (root / "spec/waves/results/wiring/wiring-app-home.json").write_text(json.dumps(RECEIPTS[1][1]), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), "--project", str(root), "--json"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            s = json.loads(r.stdout); self.assertEqual((s["open_before"], s["open_after"], s["approval"]), (2, 0, "auto"))
            rep = json.loads((root / "spec/reports/fix-backlog.json").read_text(encoding="utf-8"))
            bp = json.loads((root / "spec/blueprint/wiring-backlog.json").read_text(encoding="utf-8"))
            self.assertEqual(rep["open"], 0); self.assertEqual(rep["items"], []); self.assertEqual(bp["open"], 0)
            pay = json.loads((root / "spec/state/approvals/fix-backlog.json").read_text(encoding="utf-8"))
            self.assertTrue(pay["approved"] and pay["settled"])

    # ── E166（AIPPT_930 移植）：分 owner 记账 ─────────────────────────────────────
    def test_three_consumers_all_required_and_old_skip_not_replayed(self):
        backlog = {"items": [{"id": "BK-2", "required_owner": "provider", "file": "cover.ets"}]}
        old = ("wiring-provider.json", {"skipped": [
            {"finding_ref": "BK-2", "required_owner": owner, "reason": "bind " + owner}
            for owner in ("mine", "outline", "preview")]})
        first = BS.settle(backlog, [old], legal={"provider", "mine", "outline", "preview"})
        self.assertEqual(first["by_owner"], {"mine": ["BK-2"], "outline": ["BK-2"], "preview": ["BK-2"]})
        self.assertEqual(first["items"][0]["required_owner"], "mine")     # 转交后 required_owner 不再指向原 owner
        one = ("wiring-r2-mine.json", {"resolved_refs": ["BK-2"]})
        second = BS.settle(first, [old, one])
        self.assertEqual(second["open"], 1)
        self.assertEqual(set(second["by_owner"]), {"outline", "preview"})
        all_receipts = [old, one] + [("wiring-r2-" + owner + ".json", {"resolved_refs": ["BK-2"]}) for owner in ("outline", "preview")]
        final = BS.settle(second, all_receipts)
        self.assertEqual(final["open"], 0)
        self.assertEqual(len(final["resolved_items"][0]["owner_obligations"]), 3)
        self.assertEqual(BS.settle(final, all_receipts)["resolved_items"], final["resolved_items"])

    def test_round_supersession_and_same_round_skip_veto(self):
        backlog = {"items": [{"id": "BK-1", "required_owner": "home", "file": "home.ets"}]}
        skip = ("wiring-home.json", {"skipped": [{"finding_ref": "BK-1", "reason": "unfinished", "required_owner": "home"}]})
        proof = ("wiring-r2-home.json", {"resolved_refs": ["BK-1"]})
        self.assertEqual(BS.settle(backlog, [proof, skip])["open"], 0)      # 首轮 skip 不再永久压住第二轮 resolved
        contradictory = ("wiring-r2-home.md", {"skipped": [{"finding_ref": "BK-1", "required_owner": "home", "reason": "still unfinished"}]})
        self.assertEqual(BS.settle(backlog, [proof, skip, contradictory])["open"], 1)
        newer_skip = ("wiring-r3-home.json", contradictory[1])
        self.assertEqual(BS.settle(backlog, [proof, newer_skip])["open"], 1)

    def test_wrong_owner_cannot_settle_and_invalid_transfer_is_loud(self):
        backlog = {"items": [{"id": "BK-1", "required_owner": "home", "file": "home.ets"}]}
        self.assertEqual(BS.settle(backlog, [("wiring-r2-other.json", {"resolved_refs": ["BK-1"]})])["open"], 1)
        with self.assertRaisesRegex(ValueError, "illegal required_owner"):
            BS.settle(backlog, [("wiring-home.json", {"skipped": [{"finding_ref": "BK-1", "required_owner": "unknown", "reason": "x"}]})], legal={"home"})

    def test_file_match_cannot_settle_multiple_consumer_obligations(self):
        backlog = {"items": [{"id": "BK-1", "file": "cover.ets", "owner_obligations": [
            {"owner": "a", "status": "open"}, {"owner": "b", "status": "open"}]}]}
        out = BS.settle(backlog, [("wiring-r2-a.json", {"resolved_refs": ["cover.ets#load"]})])
        self.assertEqual(set(out["by_owner"]), {"a", "b"})

    def test_skip_without_required_owner_keeps_same_owner_open(self):
        backlog = {"items": [{"id": "BK-1", "required_owner": "home", "file": "home.ets"}]}
        out = BS.settle(backlog, [("wiring-home.json", {"skipped": [{"finding_ref": "BK-1", "reason": "cannot"}]})])
        self.assertEqual(out["by_owner"], {"home": ["BK-1"]})
        self.assertEqual(out["items"][0]["evidence"], "skipped")

    def test_missing_backlog_fails_loud(self):
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run([sys.executable, str(SCRIPT), "--project", td, "--json"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
