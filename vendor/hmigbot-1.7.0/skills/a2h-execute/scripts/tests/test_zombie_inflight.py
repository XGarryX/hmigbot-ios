#!/usr/bin/env python3
"""僵尸在飞检测回归（AIPPT_915_test1 2026-08-30 会话重启事故驱动）。

事故：Codex 会话重启后，12 个已派 agent 随之消亡，但 dispatch 账上仍记为在飞、占满
全部 12 个并行槽位；land_results 判「在途→缺失」只有一个固定阈值 --stale-minutes
（缺省 90），于是管线只能以 3 并行爬行、白等 63 分钟。而同一波重派的任务 7 分钟就出货
——判定基线明明就在手边，没人拿来用。

两条判据都要锁：
  · 完成时刻必须取**回执文件 mtime**，不能取 state 的 at。at 是「落账」时刻，要等下一拍④
    才写，被四拍循环延迟灌水（实测 app-mine 真实 6.7 分钟 / at 算成 16.4 分钟，基线虚高
    2.4 倍，阈值跟着虚高，僵尸恰好漏判）。
  · 只报不判：SKILL.md §15-4「限流时代理多半仍存活」，误判重派 = 双倍付费 + 两份半成品。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import land_results as L  # noqa: E402


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


class TestZombieSuspects(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "res").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _landed(self, tid, dispatched_min_ago, took_min):
        """造一个已完成任务：回执文件 mtime = 派发时刻 + 耗时。"""
        rp = "res/%s.json" % tid.replace(":", "-")
        f = self.root / rp
        f.write_text("{}", encoding="utf-8")
        disp_at = self.now - timedelta(minutes=dispatched_min_ago)
        done_at = disp_at + timedelta(minutes=took_min)
        os.utime(f, (done_at.timestamp(), done_at.timestamp()))
        return rp, _iso(disp_at)

    def test_reproduces_session_restart_incident(self):
        """1 个 7 分钟完成 + 9 个在飞 49 分钟 → 9 个全部报出。"""
        rp, disp_at = self._landed("read:app-mine", 20, 7)
        dispatched = {"read:app-mine": {"last_dispatch_at": disp_at, "result_path": rp}}
        ghosts = ["read:g%d" % i for i in range(9)]
        for g in ghosts:
            dispatched[g] = {"last_dispatch_at": _iso(self.now - timedelta(minutes=49))}
        wave_rec = {"dispatched": dispatched}
        state_wave = {"tasks": [{"id": "read:app-mine", "status": "done",
                                 "at": _iso(self.now)}]}   # at 故意灌水到 20 分钟
        got = L.zombie_suspects(wave_rec, state_wave, ghosts, self.root)
        self.assertEqual(len(got), 9)
        self.assertAlmostEqual(got[0]["baseline_median_minutes"], 7.0, delta=0.6,
                               msg="基线必须取回执 mtime（7 分钟），不能取被灌水的 at（20 分钟）")

    def test_at_inflation_does_not_raise_threshold(self):
        """回执 mtime 缺席才回退 at——mtime 在时绝不用 at。"""
        rp, disp_at = self._landed("read:a", 30, 5)
        wave_rec = {"dispatched": {
            "read:a": {"last_dispatch_at": disp_at, "result_path": rp},
            "read:z": {"last_dispatch_at": _iso(self.now - timedelta(minutes=25))}}}
        state_wave = {"tasks": [{"id": "read:a", "status": "done", "at": _iso(self.now)}]}
        got = L.zombie_suspects(wave_rec, state_wave, ["read:z"], self.root)
        self.assertEqual([g["task"] for g in got], ["read:z"])

    def test_fresh_tasks_not_flagged(self):
        rp, disp_at = self._landed("read:a", 20, 7)
        wave_rec = {"dispatched": {
            "read:a": {"last_dispatch_at": disp_at, "result_path": rp},
            "read:fresh": {"last_dispatch_at": _iso(self.now - timedelta(minutes=3))}}}
        state_wave = {"tasks": [{"id": "read:a", "status": "done", "at": _iso(self.now)}]}
        self.assertEqual(L.zombie_suspects(wave_rec, state_wave, ["read:fresh"], self.root), [])

    def test_floor_prevents_jitter_false_alarm(self):
        """极快的波（中位数 1 分钟）不得把 5 分钟的在飞判成僵尸——20 分钟地板兜底。"""
        rp, disp_at = self._landed("read:a", 10, 1)
        wave_rec = {"dispatched": {
            "read:a": {"last_dispatch_at": disp_at, "result_path": rp},
            "read:b": {"last_dispatch_at": _iso(self.now - timedelta(minutes=5))}}}
        state_wave = {"tasks": [{"id": "read:a", "status": "done", "at": _iso(self.now)}]}
        self.assertEqual(L.zombie_suspects(wave_rec, state_wave, ["read:b"], self.root), [])

    def test_no_baseline_means_no_verdict(self):
        """本波一个都没完成时不得凭空判——没有基线就没有判据。"""
        wave_rec = {"dispatched": {"read:z": {"last_dispatch_at":
                                              _iso(self.now - timedelta(hours=5))}}}
        self.assertEqual(L.zombie_suspects(wave_rec, {"tasks": []}, ["read:z"], self.root), [])


if __name__ == "__main__":
    unittest.main()


class TestZombieRecommendationChannel(unittest.TestCase):
    """僵尸清理通道必须按**配额影响**机械裁决，不由人凭印象挑。

    AIPPT_915_test1 实证：8 个僵尸若照原先无脑推荐的 --missing-as-failed 清理，会当场
    全部判 RETRY_EXHAUSTED（有效 2/2），等于报废三分之一的波；它们实为同一场 429 所杀，
    改判 INFRA_FAIL 后回到 1/2 全部复活。工具给错建议比不给建议更危险。
    """

    def _land(self, root, attempts, waived_rows, age_min):
        """造一个「已完成 1 个 + N 个超时在飞」的波，返回 land_results 的 result。"""
        import subprocess
        (root / "spec/waves/results/w").mkdir(parents=True)
        (root / "spec/state").mkdir(parents=True)
        now = datetime.now(timezone.utc)
        done_disp = now - timedelta(minutes=30)
        rp = "spec/waves/results/w/done.json"
        f = root / rp
        f.write_text(json.dumps({"area": "d", "specFile": "spec/domains/d.md",
                                 "screens": ["A"], "apis": [], "risks": []}),
                      encoding="utf-8")
        done_at = done_disp + timedelta(minutes=5)
        os.utime(f, (done_at.timestamp(), done_at.timestamp()))
        tasks = [{"id": "read:done", "kind": "agent", "schema": "understandSummary",
                  "parents": [], "map_group": "g", "result_path": rp,
                  "prompt_file": "p.txt", "resume_key": "w:read:done"}]
        disp = {"read:done": {"attempts": 1, "result_path": rp,
                              "last_dispatch_at": _iso(done_disp)}}
        rows = []
        for i in range(3):
            tid = "read:z%d" % i
            tasks.append({"id": tid, "kind": "agent", "schema": "understandSummary",
                          "parents": [], "map_group": "g",
                          "result_path": "spec/waves/results/w/%d.json" % i,
                          "prompt_file": "p.txt", "resume_key": "w:" + tid})
            disp[tid] = {"attempts": attempts,
                         "result_path": "spec/waves/results/w/%d.json" % i,
                         "last_dispatch_at": _iso(now - timedelta(minutes=age_min))}
            rows += [{"workflow_id": "w", "task_id": tid, "kind": "agent",
                      "status": "INFRA_FAIL", "attempt": j + 1} for j in range(waived_rows)]
        plan = {"wave": "w", "plan_version": "a2h-2.1.0",
                "contract_hash": "sha256:" + "0" * 64, "max_parallel": 8, "tasks": tasks}
        (root / "spec/waves/plan-w.json").write_text(json.dumps(plan), encoding="utf-8")
        (root / "spec/state/state.json").write_text(json.dumps({
            "version": 1, "pages": {}, "domains": {}, "gates": {},
            "waves": {"w": {"run_id": "p:x", "done": 0, "failed": 0, "tasks": [
                {"id": t["id"], "status": "pending", "files_touched": []} for t in tasks]}},
        }), encoding="utf-8")
        (root / "spec/state/dispatch.json").write_text(json.dumps({
            "version": 1, "waves": {"w": {"contract_hash": plan["contract_hash"],
                                          "plan_path": "spec/waves/plan-w.json",
                                          "dispatched": disp}}}), encoding="utf-8")
        (root / "spec/state/journal.json").write_text(json.dumps({
            "version": 1, "workflow_status": [], "operation_outputs": rows}), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "land_results.py"),
             "--plan", "spec/waves/plan-w.json", "--state", "spec/state/state.json", "--json"],
            cwd=str(root), capture_output=True, text=True)
        return json.loads(proc.stdout)

    def test_recommends_infra_fail_when_missing_would_exhaust(self):
        """配额已到 2/2：主推 --infra-fail，并说明照 missing 走会打挂几个。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            r = self._land(Path(td), attempts=2, waived_rows=0, age_min=40)
        z = r.get("zombie_suspects")
        self.assertIsNotNone(z, "应报出僵尸")
        self.assertIn("--infra-fail", z["cmd"])
        self.assertIn("RETRY_EXHAUSTED", z.get("why_infra", ""))
        self.assertIn("--missing-as-failed", z.get("cmd_if_content_failure", ""))

    def test_recommends_missing_when_quota_is_safe(self):
        """配额充裕（1/2）：主推 --missing-as-failed，但仍备注限流通道。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            r = self._land(Path(td), attempts=1, waived_rows=0, age_min=40)
        z = r.get("zombie_suspects")
        self.assertIsNotNone(z)
        self.assertIn("--missing-as-failed", z["cmd"])
        self.assertIn("--infra-fail", z.get("cmd_if_rate_limited", ""))

    def test_flags_mass_death_when_ages_identical(self):
        """在飞时长完全一致 = 整批同时消亡，指向平台事件而非各自失败。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            r = self._land(Path(td), attempts=1, waived_rows=0, age_min=40)
        self.assertIn("mass_death", r.get("zombie_suspects", {}))
