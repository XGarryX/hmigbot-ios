#!/usr/bin/env python3
"""F7 回归（AIPPT_930_token2 2026-09-20 实证）：closure 的 STALLED 按「修复轮」计数，不按「扫描次数」。

事故：wiring 波尾 gate:closure-scan 在一次构建修复后被重跑，两次扫描之间没有任何 closure/wiring 修复代理落地，
指纹当然相同 → loop_runner 按 STALLED_THRESHOLD=2 判 STALLED（round 2）→ U1 只放一轮 → closeout 把余下待办全记欠账。

修法：closure_backlog --run-iterate 前判「上次扫描以来有没有修复落地」（closure*/wiring* 回执 mtime、.ets mtime、journal
代理行 ended_at 三路取最新，与上一条 history.timestamp 比）；没有 → 给 structural_loop iterate 传 --replace-last，
让本次扫描替换而非追加上一条 history（round 不变、不触发 STALLED）；backlog 记 scan_kind。

本文件用「假扫描」（固定指纹）复现 structural_loop.cmd_iterate 的 state 序列（_load_state → _replace_last_entry →
evaluate → _history_entry → _save_state），只把 detector 部分换掉；closure_backlog 的判定与传参走真实代码。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SL_DIR = SCRIPTS.parent.parent / "arkts-structural-closure" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SL_DIR))

import closure_backlog as CB  # noqa: E402
import structural_loop as SL  # noqa: E402
from loop_runner import IterationState, evaluate  # noqa: E402

FP = [["entry/src/main/ets/pages/A.ets", 0, "dead-render-flag"],
      ["entry/src/main/ets/pages/B.ets", 0, "stack-align-misuse"]]
LR_REL = "spec/execution/autofix-log/round-latest/loop-result-latest-pipeline-final.json"


def _fake_scan(project: Path, lr_path: Path, max_iter: int, replace_last: bool = False, fp=None) -> None:
    """与 cmd_iterate 同序列的假扫描：固定指纹，只换掉 detector。"""
    fp = FP if fp is None else fp
    sf = CB.loop_state_path(lr_path)
    state = SL._load_state(sf)
    replaced = SL._replace_last_entry(state) if replace_last else None
    iter_n = len(state.get("history", []))
    cur = IterationState(iter=iter_n, audit_fail=len(fp), fingerprint=fp)
    hist = [IterationState.from_dict(h) for h in state.get("history", [])]
    v = evaluate(hist, cur, max_iter=max_iter)
    state.setdefault("history", []).append(SL._history_entry(iter_n, cur, ["audit"], [], ["audit"]))
    state["last_verdict"] = v.to_dict()
    state["max_iter"] = max_iter
    SL._save_state(sf, state)
    lr_path.parent.mkdir(parents=True, exist_ok=True)
    lr_path.write_text(json.dumps({"verdict": v.verdict.value, "iteration": iter_n, "reason": v.reason,
                                   "detector_json_paths": {}, "replaced_last": bool(replaced)}), encoding="utf-8")


def _utime(p: Path, delta: float) -> None:
    t = time.time() + delta
    os.utime(p, (t, t))


class _Proj(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "spec/blueprint").mkdir(parents=True)
        (self.root / "spec/blueprint/ownership.json").write_text(json.dumps({"owners": {}}), encoding="utf-8")
        self.ets = self.root / "entry/src/main/ets/pages/A.ets"
        self.ets.parent.mkdir(parents=True)
        self.ets.write_text("// a", encoding="utf-8")
        _utime(self.ets, -30)           # 工程文件早于任何扫描
        self.calls: list = []
        self._orig = CB._run_iterate

        def spy(project, lr_path, max_iter, replace_last=False):
            self.calls.append(replace_last)
            _fake_scan(project, lr_path, max_iter, replace_last)
        CB._run_iterate = spy

    def tearDown(self):
        CB._run_iterate = self._orig
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def scan(self) -> dict:
        argv = ["closure_backlog.py", "--project", str(self.root), "--blueprint", "spec/blueprint",
                "--loop-result", LR_REL, "--run-iterate", "--json"]
        old = sys.argv
        sys.argv = argv
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                rc = CB.main()
        finally:
            sys.argv = old
        self.assertEqual(rc, 0)
        line = json.loads(out.getvalue().strip().splitlines()[-1])
        backlog = json.loads((self.root / "spec/blueprint/closure-backlog.json").read_text(encoding="utf-8"))
        self.assertEqual(line["scan_kind"], backlog["scan_kind"])      # --json 输出与落账同源
        return backlog

    def state(self) -> dict:
        return json.loads((self.root / LR_REL).parent.joinpath("loop-state-pipeline-final.json").read_text(encoding="utf-8"))


class TestRescanWithoutRepair(_Proj):
    def test_two_scans_no_repair_keep_round_and_never_stall(self):
        b1 = self.scan()
        self.assertEqual((b1["round"], b1["verdict"], b1["scan_kind"]), (1, "CONTINUE", CB.SCAN_INITIAL))
        self.assertEqual(self.calls, [False])
        b2 = self.scan()                                            # 事故形态：紧接着重扫，中间什么都没修
        self.assertEqual((b2["round"], b2["verdict"], b2["scan_kind"]), (1, "CONTINUE", CB.SCAN_NO_REPAIR))
        self.assertEqual(self.calls, [False, True])
        b3 = self.scan()                                            # 再扫一次仍然不算轮次
        self.assertEqual((b3["round"], b3["verdict"]), (1, "CONTINUE"))
        st = self.state()
        self.assertEqual(len(st["history"]), 1)                     # 替换而非追加
        self.assertEqual(st["history"][0]["iter"], 0)
        self.assertEqual(len(st["replaced_entries"]), 2)
        self.assertTrue(st["history"][0]["timestamp"])

    def test_repair_then_rescan_increments_round_and_same_fingerprint_stalls(self):
        self.scan()
        (self.root / "entry/src/main/ets/pages/B.ets").write_text("// fixed", encoding="utf-8")   # 真修了东西
        _utime(self.root / "entry/src/main/ets/pages/B.ets", +5)
        b2 = self.scan()
        self.assertEqual(self.calls, [False, False])
        self.assertEqual((b2["round"], b2["scan_kind"]), (2, CB.SCAN_REPAIR))
        self.assertEqual(b2["verdict"], "STALLED")                  # 修了但指纹原样 → 这才是真 STALLED
        self.assertEqual(len(self.state()["history"]), 2)
        self.assertIn("ets", b2["repair_evidence"])
        self.assertTrue(b2["prev_scan_at"])

    def test_results_receipt_counts_as_repair(self):
        self.scan()
        r = self.root / "spec/waves/results/closure/closure-r1-domain:home.json"
        r.parent.mkdir(parents=True)
        r.write_text("{}", encoding="utf-8")
        _utime(r, +5)
        b2 = self.scan()
        self.assertEqual((b2["round"], b2["scan_kind"]), (2, CB.SCAN_REPAIR))

    def test_journal_agent_row_counts_as_repair(self):
        self.scan()
        from datetime import datetime, timedelta, timezone
        ended = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(timespec="seconds")
        (self.root / "spec/state").mkdir(parents=True, exist_ok=True)
        (self.root / "spec/state/journal.json").write_text(json.dumps({"operation_outputs": [
            {"workflow_id": "wiring", "task_id": "wiring:r2:home", "kind": "agent", "ended_at": ended},
            {"workflow_id": "wiring", "task_id": "gate:compile-w", "kind": "reduce", "ended_at": ended},   # reduce 不算修复
        ]}), encoding="utf-8")
        b2 = self.scan()
        self.assertEqual((b2["round"], b2["scan_kind"]), (2, CB.SCAN_REPAIR))
        self.assertEqual(b2["repair_evidence"]["journal"]["task"], "wiring:r2:home")

    def test_non_repair_journal_rows_ignored(self):
        self.scan()
        from datetime import datetime, timedelta, timezone
        ended = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(timespec="seconds")
        (self.root / "spec/state").mkdir(parents=True, exist_ok=True)
        (self.root / "spec/state/journal.json").write_text(json.dumps({"operation_outputs": [
            {"workflow_id": "auditfix", "task_id": "audit:home", "kind": "agent", "ended_at": ended},
        ]}), encoding="utf-8")
        b2 = self.scan()
        self.assertEqual((b2["round"], b2["scan_kind"]), (1, CB.SCAN_NO_REPAIR))


class TestRepairSinceUnit(unittest.TestCase):
    def test_no_state_is_initial(self):
        with tempfile.TemporaryDirectory() as td:
            r = CB.repair_since(Path(td), Path(td) / "missing.json")
        self.assertEqual((r["scan_kind"], r["repaired"]), (CB.SCAN_INITIAL, True))

    def test_legacy_state_without_timestamp_uses_mtime(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sf = root / "spec/execution/autofix-log/round-latest/loop-state-pipeline-final.json"
            sf.parent.mkdir(parents=True)
            sf.write_text(json.dumps({"history": [{"iter": 0, "fingerprint": []}]}), encoding="utf-8")
            ets = root / "entry/src/main/ets/X.ets"
            ets.parent.mkdir(parents=True)
            ets.write_text("x", encoding="utf-8")
            _utime(ets, -20)
            _utime(sf, -10)
            self.assertEqual(CB.repair_since(root, sf)["scan_kind"], CB.SCAN_NO_REPAIR)
            _utime(ets, +5)
            self.assertEqual(CB.repair_since(root, sf)["scan_kind"], CB.SCAN_REPAIR)


class TestStructuralLoopFlag(unittest.TestCase):
    def test_replace_last_on_empty_history_is_noop(self):
        st = {"history": []}
        self.assertIsNone(SL._replace_last_entry(st))
        self.assertEqual(st["history"], [])

    def test_replace_last_pops_and_records(self):
        st = {"history": [{"iter": 0, "fingerprint": [[1, 2, 3]], "timestamp": "2026-09-20T17:00:00+00:00"},
                          {"iter": 1, "fingerprint": [[1, 2, 3]], "timestamp": "2026-09-20T17:05:00+00:00"}]}
        popped = SL._replace_last_entry(st)
        self.assertEqual(popped["iter"], 1)
        self.assertEqual([h["iter"] for h in st["history"]], [0])
        self.assertEqual(st["replaced_entries"][0]["iter"], 1)

    def test_cli_accepts_replace_last(self):
        p = subprocess.run([sys.executable or "python3", str(SL_DIR / "structural_loop.py"), "iterate", "--help"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("--replace-last", p.stdout)

    def test_history_entry_has_timestamp(self):
        e = SL._history_entry(3, IterationState(iter=3, audit_fail=1, fingerprint=[["f", 1, "k"]]))
        self.assertEqual(e["iter"], 3)
        self.assertTrue(e["timestamp"].startswith("20"))


if __name__ == "__main__":
    unittest.main()
