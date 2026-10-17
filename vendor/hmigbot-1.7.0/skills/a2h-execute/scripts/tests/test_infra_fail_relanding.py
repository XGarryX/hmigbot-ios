#!/usr/bin/env python3
"""--infra-fail 事后改判回归（AIPPT_915_test1 2026-08-30 事故驱动）。

事故：两个最大的域被 429 打死，主会话当时只能用 --missing-as-failed 落账，记成
RETRY_NEEDED；耗尽重试配额后判 RETRY_EXHAUSTED 卡死。事后才明确死因是限流——按 K7
设计基础设施失败**不消耗重试配额**（有效计数 = attempts − waived），本该改判即可恢复。

但 land_results 循环开头的守卫 `if attempt <= landed_idx[tid]: continue` 会把已落账任务
直接跳过，于是 --infra-fail 对它们**静默失效**，且无任何受支持的补救路径
（--resume 重生成不重置 attempts：dispatch.json 按 wave 分区、attempts 只增不减）。

而「事后才知道真因」正是该用这个通道的时刻——改判必须能作用于已落账任务。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
PY = sys.executable or "python3"

TID = "read:dom-a"


def _fixture(root: Path, attempts: int, waived_rows: int):
    (root / "spec/waves/results/understand").mkdir(parents=True)
    (root / "spec/state").mkdir(parents=True)
    plan = {
        "wave": "understand", "plan_version": "a2h-2.1.0",
        "contract_hash": "sha256:" + "0" * 64, "max_parallel": 8,
        "tasks": [{"id": TID, "kind": "agent", "agent": "a2h-domain-worker@2.1.0",
                   "schema": "understandSummary", "parents": [], "map_group": "g",
                   "prompt_file": "spec/waves/prompts/understand/dom-a.txt",
                   "result_path": "spec/waves/results/understand/dom-a.json",
                   "resume_key": "understand:" + TID}],
    }
    (root / "spec/waves/plan-understand.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    (root / "spec/state/state.json").write_text(json.dumps({
        "version": 1, "pages": {}, "domains": {}, "gates": {},
        "waves": {"understand": {"run_id": "plan:x", "done": 0, "failed": 1,
                                 "tasks": [{"id": TID, "status": "failed",
                                            "files_touched": []}]}},
    }, ensure_ascii=False), encoding="utf-8")
    (root / "spec/state/dispatch.json").write_text(json.dumps({
        "version": 1, "waves": {"understand": {
            "contract_hash": plan["contract_hash"],
            "plan_path": "spec/waves/plan-understand.json",
            "dispatched": {TID: {"attempts": attempts,
                                 "agent": "a2h-domain-worker@2.1.0",
                                 "result_path": "spec/waves/results/understand/dom-a.json",
                                 "last_dispatch_at": "2026-08-30T12:00:00+00:00"}}}},
    }, ensure_ascii=False), encoding="utf-8")
    rows = [{"workflow_id": "understand", "task_id": TID, "kind": "agent",
             "status": "INFRA_FAIL", "attempt": i + 1} for i in range(waived_rows)]
    rows += [{"workflow_id": "understand", "task_id": TID, "kind": "agent",
              "status": "RETRY_NEEDED", "attempt": attempts}]
    (root / "spec/state/journal.json").write_text(json.dumps({
        "version": 1, "workflow_status": [], "operation_outputs": rows},
        ensure_ascii=False), encoding="utf-8")


def _effective(root: Path):
    import _wavelib as W
    jr = json.loads((root / "spec/state/journal.json").read_text(encoding="utf-8"))
    dp = json.loads((root / "spec/state/dispatch.json").read_text(encoding="utf-8"))
    a = int(dp["waves"]["understand"]["dispatched"][TID]["attempts"])
    return a - int(W.infra_waived(jr, "understand").get(TID, 0) or 0)


def _status(root: Path):
    st = json.loads((root / "spec/state/state.json").read_text(encoding="utf-8"))
    return st["waves"]["understand"]["tasks"][0]["status"]


def _run(root: Path, *extra):
    return subprocess.run(
        [PY, str(SCRIPTS / "land_results.py"),
         "--plan", "spec/waves/plan-understand.json",
         "--state", "spec/state/state.json", *extra],
        cwd=str(root), capture_output=True, text=True)


class TestInfraFailRelanding(unittest.TestCase):
    def test_reclassifies_already_landed_task(self):
        """事故复刻：attempts=3 waived=1（有效 2/2 已耗尽）→ 改判后有效 1/2，状态回 pending。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root, attempts=3, waived_rows=1)
            self.assertEqual(_effective(root), 2)       # 耗尽
            _run(root, "--infra-fail", TID, "--json")
            self.assertEqual(_effective(root), 1)       # 恢复配额
            self.assertEqual(_status(root), "pending")  # 可被下一拍重派

    def test_without_flag_landed_task_untouched(self):
        """没有显式声明时，已落账任务仍不得被重复落账——守卫本身不能失效。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root, attempts=3, waived_rows=1)
            _run(root, "--json")
            self.assertEqual(_effective(root), 2)
            self.assertEqual(_status(root), "failed")


if __name__ == "__main__":
    unittest.main()


class TestReclassifyDoesNotTripHealthProbe(unittest.TestCase):
    """事后改判不得顶穿 K7 健康探测（AIPPT_915_test1 2026-08-31 死结）。

    探测器数的是「journal 尾部连续 INFRA_FAIL 落账」，不问这些失败对应的派发是何时发生。
    于是批量改判 10 个历史失败后尾部计数瞬间到 19，探测器认定平台正在崩，此后每一拍都
    要 --assume-healthy 才能派发——**越是正确地把限流记成 INFRA_FAIL，越是被自己拦住**。
    """

    def _count(self, rows):
        sys.path.insert(0, str(SCRIPTS))
        import _wavelib as W
        return W.trailing_infra_fails({"operation_outputs": rows}, "w")

    def _row(self, status, **kw):
        return dict({"workflow_id": "w", "kind": "agent", "task_id": "t",
                     "status": status}, **kw)

    def test_reclassified_rows_not_counted(self):
        rows = [self._row("OK")] + [self._row("INFRA_FAIL", reclassified=True)] * 10
        self.assertEqual(self._count(rows), 0, "改判行不得计入平台健康判据")

    def test_reclassified_rows_do_not_break_the_run(self):
        """改判行既不计数也不打断连续性——否则它会把真实的连续 INFRA_FAIL 截断。"""
        rows = [self._row("INFRA_FAIL"), self._row("INFRA_FAIL", reclassified=True),
                self._row("INFRA_FAIL")]
        self.assertEqual(self._count(rows), 2)

    def test_real_infra_fails_still_counted(self):
        self.assertEqual(self._count([self._row("OK")] + [self._row("INFRA_FAIL")] * 3), 3)

    def test_success_still_resets(self):
        rows = [self._row("INFRA_FAIL")] * 5 + [self._row("OK")]
        self.assertEqual(self._count(rows), 0)
