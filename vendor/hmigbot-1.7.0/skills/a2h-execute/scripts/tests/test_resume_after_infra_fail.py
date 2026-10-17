#!/usr/bin/env python3
"""INFRA_FAIL 改判后的续派回归（AIPPT_915_test1 2026-08-31 停摆事故驱动）。

事故：19 个任务被 --infra-fail 改判、退回 state=pending 且配额充裕，next_batch 却一个
都派不出去，四拍循环就地停摆——全工程 50 分钟零写入，无人值守的一夜白跑。

死角成因（三个条件同时成立才触发，故此前从未暴露）：
  · 改判把任务退回 **pending**（不是 failed）→ retryable 分支只收 status==failed，不匹配；
  · 此前还有一次**非** INFRA_FAIL 的失败（当时只能用 --missing-as-failed）→ eff>0
    → fresh 分支要 eff<=0，也不匹配；
  · 于是落到兜底 escalate，而 stuck 只收 waiting/blocked/failed，这些 ready 任务不在其中
    → **返回一个 missing 为空的升级请求**，看起来像「要人裁决」，实则无事可裁。

配额未耗尽的就绪任务本就该派。eff 只该管重试上限（exhausted 另有判据），不该管「能不能派」。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
PY = sys.executable or "python3"


def _fixture(root: Path, n: int, attempts: int, waived_rows: int, state_status: str):
    (root / "spec/waves/prompts/w").mkdir(parents=True)
    (root / "spec/waves/results/w").mkdir(parents=True)
    (root / "spec/state").mkdir(parents=True)
    tasks, disp, rows, sts = [], {}, [], []
    for i in range(n):
        tid = "read:d%d" % i
        (root / ("spec/waves/prompts/w/d%d.txt" % i)).write_text("task", encoding="utf-8")
        tasks.append({"id": tid, "kind": "agent", "agent": "a2h-domain-worker@2.1.0",
                      "schema": "understandSummary", "parents": [], "map_group": "g",
                      "prompt_file": "spec/waves/prompts/w/d%d.txt" % i,
                      "result_path": "spec/waves/results/w/d%d.json" % i,
                      "resume_key": "w:" + tid})
        disp[tid] = {"attempts": attempts, "agent": "a2h-domain-worker@2.1.0",
                     "result_path": "spec/waves/results/w/d%d.json" % i,
                     "last_dispatch_at": "2026-08-30T12:00:00+00:00"}
        rows += [{"workflow_id": "w", "task_id": tid, "kind": "agent",
                  "status": "INFRA_FAIL", "attempt": j + 1} for j in range(waived_rows)]
        # 补齐落账行，使 landed == attempts（否则会被算成在途）
        rows += [{"workflow_id": "w", "task_id": tid, "kind": "agent",
                  "status": "RETRY_NEEDED", "attempt": attempts}
                 for _ in range(max(0, attempts - waived_rows))]
        sts.append({"id": tid, "status": state_status, "files_touched": []})
    plan = {"wave": "w", "plan_version": "a2h-2.1.0", "contract_hash": "sha256:" + "0" * 64,
            "max_parallel": 8, "tasks": tasks}
    (root / "spec/waves/plan-w.json").write_text(json.dumps(plan), encoding="utf-8")
    (root / "spec/state/state.json").write_text(json.dumps({
        "version": 1, "pages": {}, "domains": {}, "gates": {},
        "waves": {"w": {"run_id": "p:x", "done": 0, "failed": 0, "tasks": sts}}}), encoding="utf-8")
    (root / "spec/state/dispatch.json").write_text(json.dumps({
        "version": 1, "waves": {"w": {"contract_hash": plan["contract_hash"],
                                      "plan_path": "spec/waves/plan-w.json",
                                      "dispatched": disp}}}), encoding="utf-8")
    (root / "spec/state/journal.json").write_text(json.dumps({
        "version": 1, "workflow_status": [], "operation_outputs": rows}), encoding="utf-8")


def _run(root: Path, *extra):
    p = subprocess.run([PY, str(SCRIPTS / "next_batch.py"),
                        "--plan", "spec/waves/plan-w.json",
                        "--state", "spec/state/state.json", "--json", *extra],
                       cwd=str(root), capture_output=True, text=True)
    return json.loads(p.stdout)


class TestResumeAfterInfraFail(unittest.TestCase):
    def test_pending_with_quota_left_is_dispatched(self):
        """事故复刻：19 个 pending、attempts=2 waived=1（eff=1<2）→ 必须派发，不得停摆。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root, 19, attempts=2, waived_rows=1, state_status="pending")
            r = _run(root, "--assume-healthy")
        self.assertEqual(r["action"], "dispatch", r.get("reason"))
        self.assertEqual(len(r["batch"]), 8, "应按 max_parallel 补满槽位")

    def test_does_not_dispatch_when_quota_exhausted(self):
        """配额耗尽（eff=2）时不得靠本分支绕过重试上限。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root, 3, attempts=2, waived_rows=0, state_status="pending")
            r = _run(root, "--assume-healthy")
        self.assertNotEqual(r["action"], "dispatch",
                            "eff 已达 MAX_ATTEMPTS，不该继续派发")

    def test_never_dispatched_still_uses_fresh_branch(self):
        """从未派发的任务照旧走 fresh 分支（整组吐出语义不得被本分支改写）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root, 3, attempts=0, waived_rows=0, state_status="pending")
            r = _run(root, "--assume-healthy")
        self.assertEqual(r["action"], "dispatch")
        self.assertNotIn("resume", r, "应由 fresh 分支处理，而非续派分支")

    def test_no_empty_escalate(self):
        """兜底 escalate 不得在 missing 为空时触发——那是「看起来要人裁决、实则无事可裁」。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root, 5, attempts=2, waived_rows=1, state_status="pending")
            r = _run(root, "--assume-healthy")
        if r["action"] == "escalate":
            self.fail("不该升级：%s" % r.get("reason"))


if __name__ == "__main__":
    unittest.main()


class TestNoDeadEndInDecisionSpace(unittest.TestCase):
    """穷举 next_batch 的决策空间，确保没有「无分支接住」的状态。

    单个死角（pending + eff>0）已让一夜无人值守跑批白费；穷举后又查出 3 个同型兄弟
    （pending + eff≥MAX_ATTEMPTS）——配额耗尽的任务若不在 failed 态，就进不了 exhausted
    清单，兜底 escalate 于是 missing/exhausted 全空，人看到一个「无事可裁」的升级请求。

    本用例把「每种状态都有分支接住，且升级请求必带可裁决清单」锁成不变式。
    """

    def test_no_empty_escalate_or_wait_in_any_state(self):
        import itertools
        bad = []
        for ss, at, wv in itertools.product(("pending", "failed", "done"),
                                            (0, 1, 2, 3), (0, 1, 2)):
            if wv > at:
                continue
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                _fixture(root, 1, attempts=at, waived_rows=wv, state_status=ss)
                r = _run(root, "--assume-healthy")
            act = r.get("action")
            empty_esc = (act == "escalate" and not r.get("missing")
                         and not r.get("exhausted") and not r.get("failed_gates"))
            empty_wait = (act == "wait" and not r.get("missing")
                          and not r.get("health_probe"))
            if empty_esc or empty_wait:
                bad.append((ss, at, wv, act, str(r.get("reason"))[:50]))
        self.assertEqual(bad, [], "存在无分支接住的状态：%s" % bad)

    def test_exhausted_listed_even_when_state_is_pending(self):
        """配额耗尽但状态为 pending（改判所致）时，升级请求必须列出它。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root, 2, attempts=2, waived_rows=0, state_status="pending")
            r = _run(root, "--assume-healthy")
        self.assertEqual((r["action"], r.get("settled")), ("done", True))  # E266：不再停机，改记欠账放行
        self.assertEqual(len(r.get("exhausted") or []), 2,
                         "pending 态的配额耗尽任务也须进 exhausted 清单")
