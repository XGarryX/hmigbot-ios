"""E34 错峰派发回归。立此闸的事实：AIPPT_0903 infra 波 51 秒内起跑 11 个代理，首分钟 >150 万 token，主会话与 10/11 代理同秒 429；
上午 27 个 understand 代理靠回执逐个补位零 429。固定判据：滚动窗口不变；每次拍①最多新派 dispatch_burst 个；stagger 秒内已派数
达到 burst → wait + retry_after_sec；时间过去后继续补位到窗口；burst=0 关闭错峰（行为回到 915）。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from test_scheduler_kernel import KernelFixture


def _plan_n(self, n: int, max_parallel: int) -> dict:
    plan = self.base_plan()
    def agent(key):
        return {"id": f"impl:{key}", "kind": "agent", "agent": "a2h-domain-worker@2.1.0", "map_group": "domains-impl",
                "prompt_file": f"spec/waves/prompts/domains/{key}.txt", "model": "flagship", "schema": "domainImpl",
                "parents": [], "ownership": [f"features/{key}/**"], "result_path": f"spec/waves/results/domains/{key}.json",
                "resume_key": f"domains:impl:{key}"}
    plan["tasks"] = [agent("d%d" % i) for i in range(n)] + [plan["tasks"][2]]
    plan["tasks"][-1]["parents"] = ["@domains-impl"]; plan["tasks"][-1]["on_fail"] = {"skip": [], "escalate": True}
    plan["max_parallel"] = max_parallel
    return plan


class TestDispatchPacing(KernelFixture):
    def _gates(self, **g):
        self._write(self.blueprint / "workflow-params.json", json.dumps({"gates": g}))

    def test_burst_then_wait_then_refill(self):
        self._gates(dispatch_burst=2, dispatch_stagger_sec=300)
        self.write_plan(_plan_n(self, 6, 5))
        out = self.next_batch()
        self.assertEqual(out["action"], "dispatch"); self.assertEqual(len(out["batch"]), 2)     # 窗口 5，只吐 burst=2
        self.assertEqual(out["more_ready"], 4); self.assertEqual(out["retry_after_sec"], 300)    # E80：机器提示还有就绪被扣住
        self.assertIn("即使没有回执也要再拍①", out["reason"])
        out = self.next_batch()
        self.assertEqual(out["action"], "wait"); self.assertGreaterEqual(out["retry_after_sec"], 1)
        self.assertIn("错峰", out["reason"])
        # 时间过去：把已派时刻拨回 400 秒前 → 再补 2 个（在途 2 + 新 2 = 4 ≤ 窗口 5）
        d = json.loads((self.proj / "spec/state/dispatch.json").read_text(encoding="utf-8"))
        past = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat(timespec="seconds")
        for rec in d["waves"]["domains"]["dispatched"].values():
            rec["last_dispatch_at"] = past
        (self.proj / "spec/state/dispatch.json").write_text(json.dumps(d), encoding="utf-8")
        out = self.next_batch()
        self.assertEqual(out["action"], "dispatch"); self.assertEqual(len(out["batch"]), 2)
        self.assertEqual({b["id"] for b in out["batch"]}, {"impl:d2", "impl:d3"})

    def test_max_in_flight_caps_plan_window_without_regeneration(self):
        """E35：账号只承受 2 个代理时，现场把 gates.max_in_flight 设 2——计划 max_parallel 仍 5、哈希不变，在途封顶 2。"""
        self._gates(dispatch_burst=0, max_in_flight=2)
        self.write_plan(_plan_n(self, 6, 5))
        out = self.next_batch()
        self.assertEqual(out["action"], "dispatch"); self.assertEqual(len(out["batch"]), 2)
        out = self.next_batch()
        self.assertEqual(out["action"], "wait"); self.assertIn("滚动窗口已满", out["reason"])

    def test_dispatch_paused_by_wave_list(self):
        """E36：gates.dispatch_paused 命中本波 → 拍①只出 wait；不命中 → 照常。"""
        self._gates(dispatch_burst=0, dispatch_paused=["domains"])
        self.write_plan(_plan_n(self, 3, 5))
        out = self.next_batch()
        self.assertEqual(out["action"], "wait"); self.assertTrue(out.get("paused")); self.assertIn("暂停派发", out["reason"])
        self._gates(dispatch_burst=0, dispatch_paused=["auditfix"])
        self.assertEqual(self.next_batch()["action"], "dispatch")

    def test_pacing_off_restores_full_window(self):
        self._gates(dispatch_burst=0)
        self.write_plan(_plan_n(self, 6, 5))
        out = self.next_batch()
        self.assertEqual(out["action"], "dispatch"); self.assertEqual(len(out["batch"]), 5)

    def test_default_pacing_without_config(self):
        self.write_plan(_plan_n(self, 6, 5))            # 夹具 workflow-params 为 {} → 默认 burst 4
        out = self.next_batch()
        self.assertEqual(len(out["batch"]), 4)
        self.assertEqual(self.next_batch()["action"], "wait")


if __name__ == "__main__":
    import unittest
    unittest.main()


import unittest  # noqa: E402


class TestE133RefillCommand(unittest.TestCase):
    def test_refill_cmd_attached_for_stagger_wait_and_more_ready(self):
        import next_batch as NB
        class A: plan = "spec/waves/plan-domains.json"; state = "spec/state/state.json"; dry_run = False
        a = {"action": "wait", "retry_after_sec": 37, "reason": "错峰派发：最近 60s 内已派 4 个", "batch": []}
        NB._attach_refill_cmd(a, A()); self.assertEqual(a["next"]["kind"], "beat1-refill"); self.assertTrue(a["next"]["cmd"].startswith("sleep 37; python3 ")); self.assertIn("--plan spec/waves/plan-domains.json --state spec/state/state.json --brief", a["next"]["cmd"])
        b = {"action": "dispatch", "retry_after_sec": 60, "more_ready": 7, "reason": "派发…", "batch": [{}]}
        NB._attach_refill_cmd(b, A()); self.assertIn("sleep 60;", b["next"]["cmd"]); self.assertIn("派出去后", b["next"]["why"])
        c = {"action": "dispatch", "reason": "派发", "batch": [{}]}; NB._attach_refill_cmd(c, A()); self.assertNotIn("next", c)     # 没被扣住 → 不附
        d = {"action": "wait", "retry_after_sec": 60, "reason": "在途任务未落账，等待回执", "batch": []}; NB._attach_refill_cmd(d, A()); self.assertNotIn("next", d)   # 等回执的 wait 不附
        e = {"action": "wait", "retry_after_sec": 5, "reason": "错峰派发", "batch": []}
        class D(A): dry_run = True
        NB._attach_refill_cmd(e, D()); self.assertNotIn("next", e)


class TestE134UnattendedBurstOff(unittest.TestCase):
    def test_burst_default_off_when_unattended(self):
        import json, tempfile
        from pathlib import Path
        import next_batch as NB
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "spec/blueprint").mkdir(parents=True)
            wp = root / "spec/blueprint/workflow-params.json"
            wp.write_text(json.dumps({"gates": {"unattended": True}}), encoding="utf-8")
            self.assertEqual(NB.dispatch_gates(root)[0], 0)                                   # 无人值守：错峰关
            wp.write_text(json.dumps({"gates": {"unattended": True, "dispatch_burst": 3}}), encoding="utf-8")
            self.assertEqual(NB.dispatch_gates(root)[0], 3)                                   # 显式给了就用
            wp.write_text(json.dumps({"gates": {}}), encoding="utf-8")
            self.assertEqual(NB.dispatch_gates(root)[0], NB.DEFAULT_DISPATCH_BURST)           # 有人值守：缺省 4
