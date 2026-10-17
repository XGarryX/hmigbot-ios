"""E24 产物写权审计回归。立此闸的事实：DR_0903 主会话在深度闸判浅后手改 MainPage.ets 凑到 0.42 并手动重跑闸，
depthfix 回派从未触发；915 唯一允许主循环亲手改产物的是编译门 quick_fix 窗口（conservative-mode §3）。
固定判据：代理窗口内 → agent；reduce started_at→ended_at 内 → script；quick_fix FAIL→下次重跑之间 → quick_fix（计数不算违规）；
其它 → mainloop_edit（WARN，exit 仍 0）；下界之前的旧文件不审；写产物的波尾都挂 reduce:product-write-audit，closeout/understand 不挂；
handoff_check 把 mainloop_edit 记 warn 欠账。
"""
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
sys.path.insert(0, str(SCRIPTS)); sys.path.insert(0, str(SCRIPTS / "tests"))
import product_write_audit as PWA  # noqa: E402
import generate_waves as G  # noqa: E402

T0 = datetime(2026, 9, 3, 8, 0, 0, tzinfo=timezone.utc)


def _iso(sec: int) -> str:
    return (T0 + timedelta(seconds=sec)).isoformat(timespec="seconds")


def _touch(root: Path, rel: str, sec: int) -> None:
    p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text("// x\n", encoding="utf-8")
    ts = (T0 + timedelta(seconds=sec)).timestamp(); os.utime(p, (ts, ts))


class TestClassify(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        st = root / "spec/state"; st.mkdir(parents=True)
        (st / "state.json").write_text(json.dumps({"waves": {"domains": {"started_at": _iso(0), "tasks": [
            {"id": "impl:main", "status": "done", "at": _iso(600)}]}}}), encoding="utf-8")
        (st / "dispatch.json").write_text(json.dumps({"version": 1, "waves": {"domains": {
            "dispatched": {"impl:main": {"attempts": 1, "last_dispatch_at": _iso(100)}}}}}), encoding="utf-8")
        (st / "journal.json").write_text(json.dumps({"operation_outputs": [
            {"workflow_id": "domains", "task_id": "reduce:pagemap", "kind": "reduce", "status": "REDUCE_PASS",
             "started_at": _iso(700), "ended_at": _iso(710)},
            {"workflow_id": "domains", "task_id": "gate:compile-2", "kind": "reduce", "status": "REDUCE_FAIL",
             "started_at": _iso(720), "ended_at": _iso(800), "error": "gate compile#2: verdict=quick_fix errors=2"},
            {"workflow_id": "domains", "task_id": "gate:compile-2", "kind": "reduce", "status": "REDUCE_PASS",
             "started_at": _iso(1000), "ended_at": _iso(1060)},
            {"workflow_id": "domains", "task_id": "gate:depth", "kind": "reduce", "status": "REDUCE_FAIL",
             "started_at": _iso(1061), "ended_at": _iso(1062), "error": "depth shallow"},
            {"workflow_id": "domains", "task_id": "gate:compile-2b", "kind": "reduce", "status": "REDUCE_FAIL",
             "started_at": _iso(1400), "ended_at": _iso(1401), "error": "gate compile#2b: verdict=per_domain_builders errors=66"},
            {"workflow_id": "domains", "task_id": "gate:compile-2b", "kind": "reduce", "status": "REDUCE_PASS",
             "started_at": _iso(1700), "ended_at": _iso(1760)},
            {"workflow_id": "domains", "task_id": "gate:depth", "kind": "reduce", "status": "REDUCE_PASS",
             "started_at": _iso(1300), "ended_at": _iso(1302)},
        ]}), encoding="utf-8")
        _touch(root, "entry/src/main/ets/pages/AgentPage.ets", 300)        # 代理窗口
        _touch(root, "entry/src/main/ets/pages/RouteTable.ets", 705)       # reduce 窗口
        _touch(root, "entry/src/main/ets/pages/QuickFixed.ets", 900)       # quick_fix 窗口（合法）
        _touch(root, "entry/src/main/ets/pages/HandEdited.ets", 1200)      # depth FAIL 后手改 → 越权
        _touch(root, "entry/src/main/ets/pages/BuilderFixed.ets", 1550)     # per_domain_builders 窗口（hmos-builder 侧代理修）→ 合法
        _touch(root, "entry/src/main/ets/entryability/Old.ets", -5000)     # 下界之前，不审
        return st / "state.json"

    def test_windows_and_findings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); sp = self._fixture(root)
            r = subprocess.run([sys.executable, str(SCRIPTS / "product_write_audit.py"), "--state", str(sp),
                                "--wave", "domains", "--json"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = json.loads(r.stdout); self.assertFalse(out["ok"])
            rep = json.loads((root / "spec/reports/product-write-audit-domains.json").read_text(encoding="utf-8"))
            self.assertEqual(rep["counts"], {"agent": 1, "script": 1, "quick_fix": 2, "mainloop_edit": 1})
            self.assertEqual([f["file"] for f in rep["findings"]], ["entry/src/main/ets/pages/HandEdited.ets"])
            self.assertEqual(sorted(q["file"] for q in rep["quick_fix_edits"]), ["entry/src/main/ets/pages/BuilderFixed.ets", "entry/src/main/ets/pages/QuickFixed.ets"])
            kinds = sorted({w["kind"] for w in rep["windows"]}); self.assertEqual(kinds, ["agent", "quick_fix", "script"])
            # 第二次审计：下界 = 上次报告 at（现在），旧文件全部不审
            rep2 = PWA.audit(root, sp, "domains"); self.assertEqual(rep2["counts"]["mainloop_edit"], 0)

    def test_windows_aggregate_across_waves(self):
        """E45：domains 波审计节点被阻断没跑 → depthfix 审计下界落到更早；domains 代理窗口内的写入仍判 agent。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); sp = self._fixture(root)
            st = json.loads(sp.read_text(encoding="utf-8")); st["waves"]["depthfix"] = {"started_at": _iso(2000), "tasks": [{"id": "impl:main:p1", "status": "done", "at": _iso(2500)}]}
            sp.write_text(json.dumps(st), encoding="utf-8")
            d = json.loads((sp.parent / "dispatch.json").read_text(encoding="utf-8"))
            d["waves"]["depthfix"] = {"dispatched": {"impl:main:p1": {"attempts": 1, "last_dispatch_at": _iso(2100)}}}
            (sp.parent / "dispatch.json").write_text(json.dumps(d), encoding="utf-8")
            _touch(root, "entry/src/main/ets/pages/DepthPage.ets", 2300)     # depthfix 代理窗口
            rep = PWA.audit(root, sp, "depthfix")                             # 无上一份报告 → 下界 = depthfix started_at? 不：state 有 started_at=2000
            self.assertEqual(rep["counts"]["mainloop_edit"], 0)
            # 把下界拨回 domains 波之前（模拟 domains 审计没跑、上一份报告更早）：domains 代理写的 AgentPage 仍是 agent
            (root / "spec/reports").mkdir(parents=True, exist_ok=True)
            (root / "spec/reports/product-write-audit-infra.json").write_text(json.dumps({"at": _iso(-100)}), encoding="utf-8")
            rep = PWA.audit(root, sp, "depthfix")
            by = {f["file"] for f in rep["findings"]}
            self.assertNotIn("entry/src/main/ets/pages/AgentPage.ets", by)
            self.assertNotIn("entry/src/main/ets/pages/RouteTable.ets", by)
            self.assertNotIn("entry/src/main/ets/pages/DepthPage.ets", by)
            self.assertEqual(by, {"entry/src/main/ets/pages/HandEdited.ets"})

    def test_legacy_reduce_row_without_started_at_uses_short_window(self):
        wins = PWA.build_windows({}, {}, {"operation_outputs": [
            {"workflow_id": "w", "task_id": "gate:x", "kind": "reduce", "status": "REDUCE_PASS", "ended_at": _iso(100)}]}, "w")
        self.assertEqual(len(wins), 1)
        self.assertAlmostEqual(wins[0]["end"] - wins[0]["start"], PWA.LEGACY_REDUCE_SEC + 2 * PWA.SLACK_SEC)


class TestWaveTail(unittest.TestCase):
    def test_audit_node_appended_only_for_product_waves(self):
        nodes = [{"id": "impl:a", "kind": "agent", "map_group": "domains-impl", "parents": []},
                 {"id": "reduce:build", "kind": "reduce", "parents": ["@domains-impl"]},
                 {"id": "gate:compile-2", "kind": "reduce", "parents": ["reduce:build"]},
                 {"id": "gate:depth", "kind": "reduce", "parents": ["gate:compile-2"]}]
        out = G._append_product_write_audit(nodes, "domains")
        self.assertEqual(out[-1]["id"], "reduce:product-write-audit")
        self.assertEqual(out[-1]["parents"], ["gate:depth"])
        # E265①：写权审计属「不可修门」（越权写盘是既成事实，派代理改 .ets 修不好）→ 失败即升级，不再只记账继续
        self.assertEqual(out[-1]["on_fail"], {"escalate": True})
        self.assertIn("--wave domains", out[-1]["run"])
        self.assertEqual(G._append_product_write_audit(nodes, "understand"), nodes)
        self.assertEqual(G._append_product_write_audit(nodes, "closeout"), nodes)


if __name__ == "__main__":
    unittest.main()
