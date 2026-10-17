#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调度内核（next_batch/land_results/lint_plan）单测：合成 plan+state fixture 走全链 + 四条拒绝规则。

用法示例:
    python3 -m unittest discover -s arkts-skills/skills/a2h-execute/scripts/tests -v
    python3 arkts-skills/skills/a2h-execute/scripts/tests/test_scheduler_kernel.py

输入:  被测脚本按仓库相对位置寻址（../next_batch.py 等）；每用例在临时目录合成
       <proj>/spec/{blueprint,state,waves} + registry/agents + 假门禁脚本，全 subprocess 黑盒调用。
输出:  unittest 标准输出。无副作用（tempfile 目录用后即删）。

覆盖:
    全链   dispatch → 伪造回执 → land（含裸 JSON 结果自动包围栏）→ reduce 执行 → 补派 → done
    规则 1 派发未落账 → wait + 缺失清单
    规则 2 contract_hash 与本 wave 分区派发记录不一致 → exit 1（next_batch 与 land_results 双侧）
    跨 wave dispatch.json 按 wave 分区：前一 wave 完成后，新 wave 复用同 task id 且携新
           contract_hash 能正常派发（新分区自然放行，不串账）；旧扁平结构直接拒绝
    规则 3 审批节点未批复 → land exit 2 + next_batch 输出 approval；批复文件落盘后放行
    审批材料生成失败（run rc!=0 / suspend_payload 未实存）→ 不进挂起态，走常规 REDUCE_FAIL
    规则 4 校验不合格记 RETRY_NEEDED → 重派一次 → 仍不合格 → escalate
    on_fail 门禁失败 → skip 目标记 SKIPPED（state 侧 folded）+ escalate exit 2
    lint   contract_hash 实算比对 / agent 实存 / map 组 ownership 互斥 / 组成员缺 ownership 判 ERROR
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent           # skills/a2h-execute/scripts
NEXT_BATCH = SCRIPTS / "next_batch.py"
LAND_RESULTS = SCRIPTS / "land_results.py"
LINT_PLAN = SCRIPTS.parent.parent / "a2h-plan" / "scripts" / "lint_plan.py"

VALID_ALPHA = {"task": "domain:alpha", "final_state": "PASS", "files": ["features/alpha/A.ets"]}
VALID_BETA = {"task": "domain:beta", "final_state": "PASS", "files": ["features/beta/B.ets"]}
VALID_FINAL = {"task": "domain:final", "final_state": "PASS", "files": ["reports/final.md"]}

FAKE_GATE = """\
import sys
from pathlib import Path
marker = Path(sys.argv[1])
sys.exit(int(marker.read_text(encoding="utf-8").strip()) if marker.exists() else 0)
"""

# 审批材料生成器：把挂起材料写到 argv[1]（F4 起审批节点 run 必须实产 suspend_payload 才进挂起态）
FAKE_APPROVAL = """\
import sys
from pathlib import Path
p = Path(sys.argv[1])
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text('{"summary": "pending decision"}', encoding="utf-8")
"""


class KernelFixture(unittest.TestCase):
    """公共 fixture：临时工程 + 契约六件 + registry + 假门禁；lint 实算并回填 contract_hash。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-kernel-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.proj = self.root / "proj"
        self.state = self.proj / "spec" / "state" / "state.json"
        self.blueprint = self.proj / "spec" / "blueprint"
        self.registry = self.root / "registry" / "agents"
        self.plan_path = self.proj / "spec" / "waves" / "plan-domains.json"

        for name, body in (("contracts.json", "{}"), ("decisions.json", "{}"),
                           ("domain-map.json", "{}"), ("ownership.json", "{}"),
                           ("workflow-params.json", "{}"), ("decision-ledger.md", "# ledger\n")):
            self._write(self.blueprint / name, body)
        self._write(self.registry / "a2h-domain-worker.json", json.dumps(
            {"id": "a2h-domain-worker", "version": "2.0.0", "model": "flagship"}))
        gate_dir = self.proj / "tools"
        self._write(gate_dir / "fake_gate.py", FAKE_GATE)
        self._write(gate_dir / "fake_approval.py", FAKE_APPROVAL)
        self.gate_rc = gate_dir / "gate_rc.txt"
        self.gate_run = f"python3 {gate_dir / 'fake_gate.py'} {self.gate_rc}"
        self.approval_run = f"python3 {gate_dir / 'fake_approval.py'} spec/state/approvals/gate.json"

    # ── fixture 工具 ──────────────────────────────────────────────────────

    def _write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def base_plan(self) -> dict:
        def agent(key: str, group: str | None, parents: list[str]) -> dict:
            t = {"id": f"impl:{key}", "kind": "agent", "agent": "a2h-domain-worker@2.1.0",
                 "prompt_file": f"spec/waves/prompts/domains/{key}.txt", "model": "flagship",
                 "schema": "domainImpl", "parents": parents,
                 "ownership": [f"features/{key}/**"],
                 "result_path": f"spec/waves/results/domains/{key}.json",
                 "resume_key": f"domains:impl:{key}"}
            if group:
                t["map_group"] = group
            return t

        return {"wave": "domains", "plan_version": "a2h-2.1.0",
                "contract_hash": "sha256:" + "0" * 64, "max_parallel": 0,
                "tasks": [
                    agent("alpha", "domains-impl", []),
                    agent("beta", "domains-impl", []),
                    {"id": "gate:compile", "kind": "reduce", "run": self.gate_run,
                     "parents": ["@domains-impl"],
                     "on_fail": {"skip": ["impl:final"], "escalate": True}},
                    agent("final", None, ["gate:compile"]),
                ]}

    def write_plan(self, plan: dict, *, fix_hash: bool = True, path: Path | None = None) -> None:
        path = path or self.plan_path
        self._write(path, json.dumps(plan, ensure_ascii=False, indent=2))
        if fix_hash:
            out = self.lint(path=path)  # 先按错 hash lint 拿实算值，再回填复核
            plan["contract_hash"] = out["computed_contract_hash"]
            self._write(path, json.dumps(plan, ensure_ascii=False, indent=2))

    def _touch_declared(self, obj) -> None:
        """A8（DevEco-830）：落账核验回执 files/files_touched 实存——夹具代表真写了文件的 worker，声明即落盘。"""
        if not isinstance(obj, dict):
            return
        for key in ("files", "files_touched"):
            v = obj.get(key)
            for f in ([v] if isinstance(v, str) else (v or [])):   # 标量形态（K2 规范化夹具）也落盘
                if isinstance(f, str) and f and not any(ch in f for ch in "*?[") and not (self.proj / f).exists():
                    self._write(self.proj / f, "// fixture\n")

    def write_result(self, key: str, obj: dict | None, *, fenced: bool = True,
                     garbage: bool = False) -> None:
        path = self.proj / "spec" / "waves" / "results" / "domains" / f"{key}.json"
        self._touch_declared(obj)
        if garbage:
            self._write(path, "worker 崩了，这里不是 JSON。\n")
        elif fenced:
            self._write(path, "worker 日志…\n```json\n" +
                        json.dumps(obj, ensure_ascii=False) + "\n```\n")
        else:
            self._write(path, json.dumps(obj, ensure_ascii=False, indent=2))

    # ── subprocess 封装 ───────────────────────────────────────────────────

    def _run(self, script: Path, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["ARKTS_SKILL_DIR"] = str(SCRIPTS.parent)  # a2h-execute skill 目录
        return subprocess.run([sys.executable, str(script), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              cwd=str(self.proj), env=env, timeout=120)

    def lint(self, expect: int | None = None, path: Path | None = None) -> dict:
        proc = self._run(LINT_PLAN, "--plan", str(path or self.plan_path),
                         "--blueprint", str(self.blueprint),
                         "--registry", str(self.registry), "--json")
        if expect is not None:
            self.assertEqual(proc.returncode, expect, proc.stderr)
        return json.loads(proc.stdout)

    def next_batch(self, expect: int = 0, path: Path | None = None) -> dict:
        proc = self._run(NEXT_BATCH, "--plan", str(path or self.plan_path),
                         "--state", str(self.state), "--json")
        self.assertEqual(proc.returncode, expect, proc.stderr + proc.stdout)
        return json.loads(proc.stdout)

    def land(self, expect: int = 0, path: Path | None = None) -> dict:
        proc = self._run(LAND_RESULTS, "--plan", str(path or self.plan_path),
                         "--state", str(self.state), "--json")
        self.assertEqual(proc.returncode, expect, proc.stderr + proc.stdout)
        return json.loads(proc.stdout)

    def state_task(self, tid: str) -> dict:
        state = json.loads(self.state.read_text(encoding="utf-8"))
        for t in state["waves"]["domains"]["tasks"]:
            if t["id"] == tid:
                return t
        raise AssertionError(f"state 中无任务 {tid}")


class TestLintPlan(KernelFixture):

    def test_hash_check_and_pass(self) -> None:
        self.write_plan(self.base_plan(), fix_hash=False)
        out = self.lint(expect=1)
        self.assertTrue(any("contract_hash" in e for e in out["errors"]), out["errors"])
        self.write_plan(self.base_plan())   # 回填实算 hash
        out = self.lint(expect=0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["agents_checked"], 3)

    def test_unknown_agent_and_group_overlap(self) -> None:
        plan = self.base_plan()
        plan["tasks"][0]["agent"] = "no-such-agent@1.0.0"
        plan["tasks"][1]["ownership"] = ["features/alpha/**"]  # 与 alpha 同组相交
        self.write_plan(plan)
        out = self.lint(expect=1)
        self.assertTrue(any("no-such-agent" in e for e in out["errors"]), out["errors"])
        self.assertTrue(any("glob 相交" in e for e in out["errors"]), out["errors"])

    def test_structural_rules(self) -> None:
        plan = self.base_plan()
        plan["tasks"][2]["parents"] = ["@no-such-group"]
        plan["tasks"][3]["resume_key"] = "domains:impl:alpha"  # 与 alpha 重复
        self.write_plan(plan)
        out = self.lint(expect=1)
        self.assertTrue(any("no-such-group" in e for e in out["errors"]), out["errors"])
        self.assertTrue(any("resume_key" in e for e in out["errors"]), out["errors"])

    def test_map_group_member_requires_ownership(self) -> None:
        # F6：kind=agent 且带 map_group 的任务缺 ownership / ownership 为空数组 → ERROR
        plan = self.base_plan()
        del plan["tasks"][0]["ownership"]        # alpha 缺 ownership
        plan["tasks"][1]["ownership"] = []       # beta 空数组
        self.write_plan(plan)
        out = self.lint(expect=1)
        hits = [e for e in out["errors"] if "缺 ownership 或为空数组" in e]
        self.assertEqual(len(hits), 2, out["errors"])
        # 不带 map_group 的 impl:final 缺 ownership 不受此规则约束
        plan = self.base_plan()
        del plan["tasks"][3]["ownership"]
        self.write_plan(plan)
        self.lint(expect=0)


class TestFullChain(KernelFixture):

    def test_dispatch_land_reduce_done(self) -> None:
        self.write_plan(self.base_plan())

        act = self.next_batch()
        self.assertEqual(act["action"], "dispatch")
        ids = {b["id"] for b in act["batch"]}
        self.assertEqual(ids, {"impl:alpha", "impl:beta"})     # 整个就绪 map 组一次吐出
        for b in act["batch"]:
            for key in ("id", "agent", "prompt_file", "result_path", "resume_key", "model"):
                self.assertTrue(b.get(key), f"batch 项缺 {key}: {b}")
        self.assertTrue((self.state.parent / "dispatch.json").exists())

        self.write_result("alpha", VALID_ALPHA)                 # 围栏回执
        self.write_result("beta", VALID_BETA, fenced=False)     # 裸 JSON 回执（自动包围栏路径）
        out = self.land()
        self.assertEqual({r["id"]: r["status"] for r in out["landed"]},
                         {"impl:alpha": "OK", "impl:beta": "OK"})
        self.assertEqual(out["reduces"], [{"id": "gate:compile", "status": "REDUCE_PASS"}])
        self.assertEqual(self.state_task("impl:alpha")["status"], "done")
        self.assertEqual(self.state_task("impl:alpha")["files_touched"], VALID_ALPHA["files"])

        act = self.next_batch()
        self.assertEqual(act["action"], "dispatch")
        self.assertEqual([b["id"] for b in act["batch"]], ["impl:final"])

        self.write_result("final", VALID_FINAL)
        out = self.land()
        self.assertEqual(out["workflow_status"], "SUCCESS")
        journal = json.loads((self.state.parent / "journal.json").read_text(encoding="utf-8"))
        self.assertEqual(len(journal["workflow_status"]), 1)
        agent_rows = [r for r in journal["operation_outputs"] if r["kind"] == "agent"]
        self.assertEqual(len(agent_rows), 3)

        act = self.next_batch()
        self.assertEqual(act["action"], "done")


class TestRejectionRules(KernelFixture):

    def test_rule1_wait_when_unlanded(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()                                        # 首派
        act = self.next_batch()                                  # 未落账再取批
        self.assertEqual(act["action"], "wait")
        self.assertEqual(sorted(act["missing"]), ["impl:alpha", "impl:beta"])

    def test_rule2_contract_hash_mismatch(self) -> None:
        plan = self.base_plan()
        self.write_plan(plan)
        self.next_batch()                                        # 首派记录 contract_hash
        plan["contract_hash"] = "sha256:" + "f" * 64             # 契约漂移
        self._write(self.plan_path, json.dumps(plan, ensure_ascii=False, indent=2))
        proc = self._run(NEXT_BATCH, "--plan", str(self.plan_path),
                         "--state", str(self.state), "--json")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertTrue(json.loads(proc.stdout).get("contract_violation"))
        proc = self._run(LAND_RESULTS, "--plan", str(self.plan_path),
                         "--state", str(self.state), "--json")
        self.assertEqual(proc.returncode, 1, proc.stderr)

    def test_rule3_approval_gate(self) -> None:
        plan = self.base_plan()
        # run 用材料生成器：F4 起挂起态要求 run rc==0 且 suspend_payload 实产落盘
        plan["tasks"][2] = {"id": "gate:compile", "kind": "reduce", "run": self.approval_run,
                            "parents": ["@domains-impl"],
                            "approval": {"suspend_payload": "spec/state/approvals/gate.json"}}
        self.write_plan(plan)
        self.next_batch()
        self.write_result("alpha", VALID_ALPHA)
        self.write_result("beta", VALID_BETA)
        out = self.land(expect=2)                                # 呈审批材料
        self.assertEqual(out["approval"]["task"], "gate:compile")

        act = self.next_batch()                                  # 未批复 → approval
        self.assertEqual(act["action"], "approval")
        self.assertEqual(act["suspend_payload"], "spec/state/approvals/gate.json")

        self._write(self.proj / "spec" / "state" / "approvals" / "gate.json",
                    json.dumps({"approved": True, "by": "tester", "quote": "批准，继续"}))   # E47：人工批复须带 by + quote
        act = self.next_batch()                                  # 批复后放行下游
        self.assertEqual(act["action"], "dispatch")
        self.assertEqual([b["id"] for b in act["batch"]], ["impl:final"])

    def test_rule4_retry_then_escalate(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("alpha", None, garbage=True)           # 校验不合格
        self.write_result("beta", VALID_BETA)
        out = self.land()
        self.assertEqual({r["id"]: r["status"] for r in out["landed"]},
                         {"impl:alpha": "RETRY_NEEDED", "impl:beta": "OK"})
        self.assertIn("RETRY_NEEDED", self.state_task("impl:alpha")["reason"])

        act = self.next_batch()                                  # 重派一次
        self.assertEqual(act["action"], "dispatch")
        self.assertTrue(act.get("retry"))
        self.assertEqual([b["id"] for b in act["batch"]], ["impl:alpha"])

        self.write_result("alpha", None, garbage=True)           # 仍不合格
        out = self.land()
        self.assertEqual(out["landed"], [{"id": "impl:alpha", "attempt": 2, "status": "FAIL",
                                          "error": out["landed"][0]["error"]}])
        act = self.next_batch()                                  # 超限 → escalate
        self.assertEqual((act["action"], act.get("settled")), ("done", True))  # E266：不再停机，改记欠账放行
        self.assertEqual(act["exhausted"], ["impl:alpha"])


class TestCrossWaveDispatch(KernelFixture):
    """F1：dispatch.json 按 wave 分区——跨 wave 复用同 task id 不串账，同 wave 内 hash pin 语义保持。"""

    def infra_plan(self) -> dict:
        """wave=infra 单任务 plan，故意与 domains wave 复用同一 task id impl:alpha。"""
        return {"wave": "infra", "plan_version": "a2h-2.1.0",
                "contract_hash": "sha256:" + "0" * 64, "max_parallel": 0,
                "tasks": [{
                    "id": "impl:alpha", "kind": "agent", "agent": "a2h-domain-worker@2.1.0",
                    "prompt_file": "spec/waves/prompts/infra/alpha.txt", "model": "flagship",
                    "schema": "domainImpl", "parents": [],
                    "ownership": ["features/alpha/**"],
                    "result_path": "spec/waves/results/infra/alpha.json",
                    "resume_key": "infra:impl:alpha"}]}

    def test_same_task_id_new_wave_new_hash_dispatches(self) -> None:
        # 1) wave=infra 首派 → 落账 → done
        infra_path = self.proj / "spec" / "waves" / "plan-infra.json"
        self.write_plan(self.infra_plan(), path=infra_path)
        act = self.next_batch(path=infra_path)
        self.assertEqual([b["id"] for b in act["batch"]], ["impl:alpha"])
        self._touch_declared(VALID_ALPHA)
        self._write(self.proj / "spec" / "waves" / "results" / "infra" / "alpha.json",
                    "```json\n" + json.dumps(VALID_ALPHA, ensure_ascii=False) + "\n```\n")
        out = self.land(path=infra_path)
        self.assertEqual(out["workflow_status"], "SUCCESS")
        self.assertEqual(self.next_batch(path=infra_path)["action"], "done")

        # 2) 契约变更（新 contract_hash）+ wave=domains 复用 impl:alpha → 新分区自然放行
        self._write(self.blueprint / "contracts.json", '{"changed": true}')
        self.write_plan(self.base_plan())        # lint 实算并回填新 hash
        act = self.next_batch()                  # 不因 infra 分区旧 pin exit 1、不串 attempts
        self.assertEqual(act["action"], "dispatch")
        self.assertEqual({b["id"] for b in act["batch"]}, {"impl:alpha", "impl:beta"})

        # 双分区各自 pin 各自的 contract_hash
        disp = json.loads((self.state.parent / "dispatch.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(disp["waves"]), ["domains", "infra"])
        self.assertNotEqual(disp["waves"]["infra"]["contract_hash"],
                            disp["waves"]["domains"]["contract_hash"])

    def test_legacy_flat_dispatch_rejected(self) -> None:
        # 旧扁平结构（跨 wave 串账）→ 双侧 exit 1，提示删除重跑（试点期无存量，不迁移）
        self.write_plan(self.base_plan())
        self._write(self.state.parent / "dispatch.json", json.dumps(
            {"version": 1, "wave": "domains", "contract_hash": "sha256:" + "0" * 64,
             "dispatched": {"impl:alpha": {"attempts": 1}}}))
        for script in (NEXT_BATCH, LAND_RESULTS):
            proc = self._run(script, "--plan", str(self.plan_path),
                             "--state", str(self.state), "--json")
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertIn("旧版", proc.stderr)


class TestApprovalMaterialFailure(KernelFixture):
    """F4：审批节点材料生成失败（run rc!=0 / suspend_payload 未实存）→ 不进挂起态，走常规 REDUCE_FAIL。"""

    def approval_plan(self, run: str) -> dict:
        plan = self.base_plan()
        plan["tasks"][2] = {"id": "gate:compile", "kind": "reduce", "run": run,
                            "parents": ["@domains-impl"],
                            "approval": {"suspend_payload": "spec/state/approvals/gate.json"}}
        return plan

    def _dispatch_and_land_agents(self) -> dict:
        self.next_batch()
        self.write_result("alpha", VALID_ALPHA)
        self.write_result("beta", VALID_BETA)
        return self.land(expect=0)              # 不 exit 2：无挂起、无升级

    def _assert_not_pending(self, out: dict) -> None:
        self.assertIsNone(out["approval"])
        self.assertEqual(out["reduces"][0]["status"], "REDUCE_FAIL")
        journal = json.loads((self.state.parent / "journal.json").read_text(encoding="utf-8"))
        self.assertNotIn("APPROVAL_PENDING",
                         [r["status"] for r in journal["operation_outputs"]])
        self.assertNotEqual(self.next_batch()["action"], "approval")

    def test_run_fail_goes_reduce_fail(self) -> None:
        self.write_plan(self.approval_plan(self.gate_run))
        self._write(self.gate_rc, "1")           # run rc!=0
        self._assert_not_pending(self._dispatch_and_land_agents())

    def test_payload_missing_goes_reduce_fail(self) -> None:
        self.write_plan(self.approval_plan(self.gate_run))  # fake gate rc==0 但不产 payload
        out = self._dispatch_and_land_agents()
        self.assertIn("suspend_payload", out["reduces"][0]["error"])
        self._assert_not_pending(out)


class TestReduceOnFail(KernelFixture):

    def test_gate_fail_skips_downstream_and_escalates(self) -> None:
        self.write_plan(self.base_plan())
        self._write(self.gate_rc, "1")                           # 门禁判红
        self.next_batch()
        self.write_result("alpha", VALID_ALPHA)
        self.write_result("beta", VALID_BETA)
        out = self.land(expect=2)                                # 呈升级材料
        self.assertEqual(out["reduces"][0]["status"], "REDUCE_FAIL")
        self.assertEqual(out["skipped"], ["impl:final"])
        self.assertEqual(out["escalations"][0]["task"], "gate:compile")
        folded = self.state_task("impl:final")
        self.assertEqual(folded["status"], "folded")
        self.assertIn("SKIPPED", folded["reason"])

        act = self.next_batch()                                  # 升级门禁需人工
        self.assertEqual((act["action"], act.get("settled")), ("done", True))  # E266：不再停机，改记欠账放行
        self.assertEqual(act["failed_gates"], ["gate:compile"])


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
