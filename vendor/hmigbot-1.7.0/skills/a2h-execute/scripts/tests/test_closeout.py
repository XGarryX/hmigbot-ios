#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V1/V2/K0 第一批单测：closeout/wiring 波形状、@start 保留组、done.next 指引、
build_wave 探针摘除、verify_handoffs 三型断言、fix_backlog 汇账、handoff_check 交棒门。

用法示例:
    python3 -m unittest discover -s arkts-skills/skills/a2h-execute/scripts/tests -v
    python3 arkts-skills/skills/a2h-execute/scripts/tests/test_closeout.py

输入:  复用 test_generate_plan.PlanFixture / test_scheduler_kernel.KernelFixture 的合成工程；
       全部 subprocess 黑盒调用。
输出:  unittest 标准输出。无副作用。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_scheduler_kernel import KernelFixture, VALID_ALPHA, VALID_BETA, SCRIPTS
from test_generate_plan import PlanFixture, GENERATE

BUILD_WAVE = SCRIPTS / "build_wave.py"
VERIFY_HANDOFFS = SCRIPTS / "verify_handoffs.py"
FIX_BACKLOG = SCRIPTS / "fix_backlog.py"
HANDOFF_CHECK = SCRIPTS / "handoff_check.py"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestCloseoutPlanShape(PlanFixture):
    """closeout 波：device_smoke=off 零 agent（@start 挂链）；hmos/dual 档带 b4:factchain。"""

    def _set_smoke(self, tier) -> None:
        wp = json.loads((self.blueprint / "workflow-params.json").read_text(encoding="utf-8"))
        wp.setdefault("gates", {})["device_smoke"] = tier
        self._write(self.blueprint / "workflow-params.json", json.dumps(wp))

    def test_smoke_off_zero_agent_reduce_chain_on_start(self) -> None:
        self._set_smoke("off")      # 缺省档已是 hmos（V6：未配置≠关闭），off 需显式声明
        self.gen("closeout")
        plan = self.plan("closeout")
        agents = [t for t in plan["tasks"] if t["kind"] == "agent"]
        self.assertEqual(agents, [])                                # 零 agent 仍出计划（K0.1）
        by_id = {t["id"]: t for t in plan["tasks"]}
        self.assertEqual(by_id["reduce:build-closeout"]["parents"], ["@start"])
        self.assertIn("--detach-probe", by_id["reduce:build-closeout"]["run"])
        self.assertEqual(by_id["gate:compile-4"]["parents"], ["reduce:build-closeout"])
        self.assertIn("verify_handoffs.py", by_id["gate:handoffs"]["run"])
        self.assertNotIn("gate:smoke-1page", by_id)                 # off 档无冒烟
        self.assertNotIn("gate:cold-start", by_id)                  # off 档无冷启探针
        # F4：off 档渲染期门禁走静态回退（render_static_gate），挂 compile-4 之后、进 report 父集
        self.assertIn("render_static_gate.py", by_id["gate:render-static"]["run"])
        self.assertEqual(by_id["gate:render-static"]["parents"], ["gate:compile-4"])
        # FV-1 结构闭包及其修复循环在上游 closure 波——closeout 不得重复跑 structural_loop
        self.assertNotIn("gate:structural-closure", by_id)
        for gid in ("theme", "literal", "dead-shell", "carrier", "hit-test", "resname"):
            self.assertNotIn("gate:%s" % gid, by_id, gid)
        # FV-2 终态全量编译 = build-closeout(--detach-probe) + gate:compile-4
        self.assertEqual(by_id["gate:handoffs"]["parents"], ["gate:compile-4"])
        self.assertEqual(by_id["reduce:report"]["parents"], ["gate:handoffs", "gate:render-static"])
        self.assertIn("--strict", by_id["reduce:report"]["run"])
        self.assertEqual(by_id["gate:handoff-check"]["parents"], ["reduce:report"])
        self.assertTrue(self.lint("closeout")["ok"])                # @start 过 lint（K0.1）

    def test_smoke_hmos_adds_factchain_and_smoke_gate(self) -> None:
        self._set_smoke("hmos")
        self.gen("closeout")
        plan = self.plan("closeout")
        by_id = {t["id"]: t for t in plan["tasks"]}
        b4 = by_id["b4:factchain"]
        self.assertEqual(b4["agent"], "a2h-factchain-runner@1.0.0")
        self.assertEqual(b4["schema"], "factchainResult")
        self.assertEqual(b4["map_group"], "closeout-b4")
        self.assertEqual(b4["ownership"], ["spec/a2h/**", "spec/visual-verify/**"])
        self.assertIn("gate:smoke-1page", by_id)
        self.assertIn("smoke_one_page.py", by_id["gate:smoke-1page"]["run"])
        # 830 回填：冷启探针（二值机械判据）排在首屏点击之前——冷启不过就不必点
        self.assertIn("gate:cold-start", by_id)
        self.assertIn("cold_start_gate.py", by_id["gate:cold-start"]["run"])
        self.assertEqual(by_id["gate:cold-start"]["parents"], ["gate:compile-4"])
        self.assertEqual(by_id["gate:smoke-1page"]["parents"], ["gate:cold-start"])
        self.assertEqual(
            sorted(by_id["reduce:report"]["parents"]),
            ["@closeout-b4", "gate:cold-start", "gate:handoffs", "gate:smoke-1page"])
        self.assertNotIn("gate:render-static", by_id)               # F4：有设备档不走静态回退
        prompt = (self.proj / b4["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("B4 产物补齐", prompt)
        self.assertIn("device_smoke=hmos", prompt)
        self.assertIn("## 回执纪律", prompt)
        self.assertTrue(self.lint("closeout")["ok"])                # runner 在 registry 实存

    def test_unset_defaults_to_hmos(self) -> None:
        # V6 缺省口径：workflow-params 未配置 device_smoke → hmos（不是 off）——
        # 与 schema default / lint 文案 / smoke_tier() 四处实现同口径
        wp = json.loads((self.blueprint / "workflow-params.json").read_text(encoding="utf-8"))
        wp.pop("gates", None)
        self._write(self.blueprint / "workflow-params.json", json.dumps(wp))
        self.gen("closeout")
        by_id = {t["id"]: t for t in self.plan("closeout")["tasks"]}
        self.assertIn("b4:factchain", by_id)          # 缺省进 hmos 档 → 有 B4
        self.assertIn("gate:smoke-1page", by_id)      # 且有一页冒烟

    def test_boolean_true_maps_to_dual(self) -> None:
        self._set_smoke(True)
        self.gen("closeout")
        prompt_file = next(t["prompt_file"] for t in self.plan("closeout")["tasks"]
                           if t["kind"] == "agent")
        self.assertIn("device_smoke=dual",
                      (self.proj / prompt_file).read_text(encoding="utf-8"))


class TestWiringPlanShape(PlanFixture):
    """wiring 条件波：backlog 驱动生成；无 backlog 即 skip。"""

    BACKLOG = {"version": 1, "open": 2, "by_owner": {"alpha": ["BK-1", "BK-2"]}, "items": [
        {"id": "BK-1", "from": "beta", "required_owner": "alpha", "severity": "P0",
         "file": "features/alpha/A.ets", "summary": "启动装配链断", "fix": "SplashPage 改调 AppInitializer",
         "finding_ref": 1, "source": "fix-skipped"},
        {"id": "BK-2", "from": "beta", "required_owner": "alpha", "severity": "P1",
         "file": "features/alpha/B.ets", "summary": "事件桥空桩", "fix": "接 EventHub",
         "finding_ref": 2, "source": "fix-skipped"}]}

    def test_backlog_drives_tasks_and_reduces(self) -> None:
        self._write(self.blueprint / "wiring-backlog.json", json.dumps(self.BACKLOG))
        self.gen("wiring")
        plan = self.plan("wiring")
        by_id = {t["id"]: t for t in plan["tasks"]}
        task = by_id["wiring:alpha"]
        self.assertEqual(task["schema"], "domainImpl")
        self.assertEqual(task["map_group"], "wiring-impl")
        self.assertEqual(task["ownership"], ["features/alpha/**"])
        prompt = (self.proj / task["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("跨域接线修复", prompt)
        self.assertIn("BK-1", prompt)
        self.assertIn("SplashPage 改调 AppInitializer", prompt)
        self.assertEqual(by_id["reduce:pagemap"]["parents"], ["@wiring-impl"])
        self.assertIn("--merge-deferred-dir spec/waves/results/wiring",
                      by_id["reduce:merge-deferred"]["run"])
        self.assertEqual(by_id["gate:compile-w"]["parents"], ["reduce:build-wiring"])
        self.assertTrue(self.lint("wiring")["ok"])

    def test_second_wiring_pass_gets_round_suffix(self) -> None:
        """E66：journal 已有第一轮 wiring 回执 → 再生成的 wiring 任务 id 带 r2，与 closure 同形。"""
        self._write(self.blueprint / "wiring-backlog.json", json.dumps(self.BACKLOG))
        jp = self.proj / "spec/state/journal.json"
        self._write(jp, json.dumps({"version": 1, "workflow_status": [], "operation_outputs": [
            {"workflow_id": "wiring", "task_id": "wiring:alpha", "kind": "agent", "attempt": 1, "status": "OK"}]}))
        self.gen("wiring")
        ids = [t["id"] for t in self.plan("wiring")["tasks"] if t.get("kind") == "agent"]
        self.assertIn("wiring:r2:alpha", ids); self.assertNotIn("wiring:alpha", ids)
        import _wavelib as W
        self.assertEqual(W.plan_run_tag(self.plan("wiring")), "r2")

    def test_tag_id_and_wave_round_helpers(self) -> None:
        """E68：specfix/depthfix/orphanwire 重入同样带 rN；首轮不带；domain_key_of 剥掉 rN 后仍归域。"""
        import generate_waves as G, _wavelib as W
        self.assertEqual(G._tag_id("read:app-load", 1), "read:app-load"); self.assertEqual(G._tag_id("read:app-load", 2), "read:r2:app-load")
        self.assertEqual(G._tag_id("impl:app-load:p1", 3), "impl:r3:app-load:p1")
        self.assertEqual(W.domain_key_of("read:r2:app-load"), "app-load"); self.assertEqual(W.domain_key_of("impl:r3:app-load:p1"), "app-load")
        self.assertEqual(W.plan_run_tag({"tasks": [{"id": "read:r2:app-load", "kind": "agent"}]}), "r2")
        jp = self.proj / "spec/state/journal.json"; jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps({"version": 1, "workflow_status": [], "operation_outputs": [
            {"workflow_id": "specfix", "task_id": "read:app-tips", "kind": "agent", "attempt": 1, "status": "OK"}]}), encoding="utf-8")
        self.assertEqual(G._wave_round(self.proj / "spec/waves", "specfix"), 2); self.assertEqual(G._wave_round(self.proj / "spec/waves", "depthfix"), 1)

    def test_no_backlog_skips_wave(self) -> None:
        proc = self.gen("wiring")
        self.assertIn("wiring-backlog", proc.stderr)
        self.assertFalse((self.proj / "spec/waves/plan-wiring.json").exists())


class TestNextHint(KernelFixture):
    """K0.2：done 携带 next——domains→auditfix；auditfix→wiring（有 backlog）/closeout；closeout→skill。"""

    def _run_wave_to_done(self, wave: str) -> dict:
        plan = self.base_plan()
        plan["wave"] = wave
        path = self.proj / "spec" / "waves" / ("plan-%s.json" % wave)
        self.write_plan(plan, path=path)
        self.next_batch(path=path)
        self.write_result("alpha", VALID_ALPHA)
        self.write_result("beta", VALID_BETA)
        self.land(path=path)
        act = self.next_batch(path=path)
        self.assertEqual(act["action"], "dispatch")     # impl:final
        self.write_result("final", {"task": "domain:final", "final_state": "PASS",
                                    "files": ["reports/final.md"]})
        self.land(path=path)
        act = self.next_batch(path=path)
        self.assertEqual(act["action"], "done", act)
        return act

    def test_domains_done_points_to_auditfix(self) -> None:
        act = self._run_wave_to_done("domains")
        self.assertEqual(act["next"]["kind"], "wave")
        self.assertEqual(act["next"]["wave"], "auditfix")
        self.assertFalse(act["next"]["exists"])
        self.assertIn("--wave auditfix", act["next"]["generate"])

    def test_auditfix_done_skips_wiring_without_backlog(self) -> None:
        act = self._run_wave_to_done("auditfix")
        self.assertEqual(act["next"]["wave"], "closeout")

    def test_auditfix_done_points_to_wiring_with_backlog(self) -> None:
        self._write(self.proj / "spec/blueprint/wiring-backlog.json",
                    json.dumps({"open": 2, "items": []}))
        act = self._run_wave_to_done("auditfix")
        self.assertEqual(act["next"]["wave"], "wiring")

    def test_deferred_backlog_skips_wiring(self) -> None:
        self._write(self.proj / "spec/blueprint/wiring-backlog.json",
                    json.dumps({"open": 2, "resolution": {"defer": True}, "items": []}))
        act = self._run_wave_to_done("auditfix")
        self.assertEqual(act["next"]["wave"], "closeout")

    def test_closeout_done_hands_off_to_verify(self) -> None:
        act = self._run_wave_to_done("closeout")
        self.assertEqual(act["next"]["kind"], "skill")
        self.assertEqual(act["next"]["skill"], "a2h-verify")
        self.assertEqual(act["next"]["message"], "spec/reports/handoff-message.md")


class TestBuildWaveDetach(unittest.TestCase):
    """V1/V15：build_wave 产日志；--detach-probe 按 A2H-PROBE 标记机械摘除，残留即失败。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-buildwave-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.ets = self.proj / "entry/src/main/ets"
        _write(self.proj / "spec/blueprint/workflow-params.json", json.dumps(
            {"project": {"root": str(self.proj), "android_src": "/dev/null",
                         "build_cmd": "echo BUILD SUCCESSFUL", "encoding": "utf-8"}}))

    def _run(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(BUILD_WAVE), "--wave", "closeout",
             "--params", "spec/blueprint/workflow-params.json", "--json", *extra],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj), timeout=120)

    def test_build_log_landed(self) -> None:
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        log = self.proj / "spec/reports/build-closeout.log"
        self.assertIn("BUILD SUCCESSFUL", log.read_text(encoding="utf-8"))

    def test_detach_removes_probe_dir_and_marked_lines(self) -> None:
        _write(self.ets / "__probe/Probe.ets", "export function __probeKeepAlive() {}\n")
        _write(self.ets / "entryability/EntryAbility.ets",
               "import { __probeKeepAlive } from '../__probe/Probe'; // A2H-PROBE\n"
               "export default class EntryAbility {\n"
               "  onCreate(): void {\n"
               "    __probeKeepAlive(); // A2H-PROBE\n"
               "  }\n}\n")
        proc = self._run("--detach-probe")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse((self.ets / "__probe").exists())
        text = (self.ets / "entryability/EntryAbility.ets").read_text(encoding="utf-8")
        self.assertNotIn("__probe", text)
        self.assertEqual(json.loads(proc.stdout)["removed_lines"], 2)

    def test_unmarked_probe_reference_fails(self) -> None:
        _write(self.ets / "__probe/Probe.ets", "export function __probeKeepAlive() {}\n")
        _write(self.ets / "entryability/EntryAbility.ets",
               "import { __probeKeepAlive } from '../__probe/Probe';\n")   # 无标记
        proc = self._run("--detach-probe")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("A2H-PROBE", proc.stderr)


class TestVerifyHandoffs(unittest.TestCase):
    """V2：HANDOFF 三型断言对账 + handoff 台账 resolved 回写 + forward-ref 到期欠账。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-handoffs-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.ets = self.proj / "entry/src/main/ets"

    def _run(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(VERIFY_HANDOFFS), "--project", str(self.proj),
             "--blueprint", "spec/blueprint", "--json", *extra],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj), timeout=120)

    def test_grep_assertion_met_and_unmet(self) -> None:
        _write(self.ets / "bridge/PushBridge.ets",
               "// HANDOFF: owner=infra-platform what=接推送初始化 verify=grep:PushBridge\\.init\n")
        _write(self.ets / "entry/App.ets", "PushBridge.init(ctx)\n")
        proc = self._run("--strict")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual((out["total"], out["met"], out["unmet"]), (1, 1, []))
        # 调用点移除 → unmet（marker 行自身不计——防自证）
        _write(self.ets / "entry/App.ets", "// PushBridge 已删\n")
        proc = self._run("--strict")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        out = json.loads(proc.stdout)
        self.assertEqual(len(out["unmet"]), 1)
        self.assertTrue((self.proj / "spec/reports/handoff-ledger.json").is_file())

    def test_artifact_assertion_and_resolved_writeback(self) -> None:
        _write(self.ets / "a/Dialog.ets",
               "// HANDOFF: owner=mainloop what=DialogHost 挂载 verify=artifact:spec/a2h/dialog.json#host\n")
        _write(self.proj / "spec/blueprint/contracts.json", json.dumps(
            {"version": 1, "modules": [], "wires": [], "chains": [], "acceptance": [],
             "deferred": [{"id": "P-9", "kind": "handoff", "status": "registered",
                           "location": {"file": "entry/src/main/ets/a/Dialog.ets",
                                        "anchor": "dialog-host"}}]}))
        proc = self._run("--strict")
        self.assertEqual(proc.returncode, 1)                     # 产物缺 → unmet
        _write(self.proj / "spec/a2h/dialog.json", json.dumps({"host": "AppDialogHost"}))
        proc = self._run("--strict")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        contracts = json.loads((self.proj / "spec/blueprint/contracts.json")
                               .read_text(encoding="utf-8"))
        self.assertEqual(contracts["deferred"][0]["status"], "resolved")   # 唯一机器推进路径

    def test_dangling_forward_ref_due(self) -> None:
        _write(self.proj / "spec/blueprint/contracts.json", json.dumps(
            {"version": 1, "modules": [], "wires": [], "chains": [], "acceptance": [],
             "deferred": [{"id": "P-1", "kind": "forward-ref", "status": "registered",
                           "resolve_by": "round-1 审计修复",
                           "location": {"file": "x.ets", "anchor": "a"}}]}))
        _write(self.proj / "spec/state/state.json", json.dumps(
            {"version": 1, "waves": {"auditfix": {"tasks": []}}, "domains": {}, "pages": {},
             "gates": {}}))
        proc = self._run("--strict")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        out = json.loads(proc.stdout)
        self.assertEqual(out["dangling_fwd_ref"][0]["id"], "P-1")


class TestFixBacklog(unittest.TestCase):
    """V2：skipped[required_owner] 汇账、owner 合法性、payload 自动放行/挂起、幂等。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-backlog-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.bp = self.proj / "spec" / "blueprint"
        _write(self.bp / "domain-map.json", json.dumps(
            {"version": 1, "domains": [{"key": "alpha"}, {"key": "beta"}]}))
        _write(self.bp / "ownership.json", json.dumps(
            {"version": 1, "owners": {"domain:alpha": ["a/**"], "domain:beta": ["b/**"],
                                      "infra:core": ["common/**"]}, "mainloop_owned": []}))

    def _results(self) -> None:
        _write(self.proj / "spec/waves/results/auditfix/audit-alpha.json", json.dumps(
            {"domain": "alpha", "findings": [
                {"file": "a/A.ets", "severity": "P0", "kind": "functional",
                 "summary": "初始化链断", "fix": "SplashPage 改调 AppInitializer"},
                {"file": "a/B.ets", "severity": "P1", "kind": "visual",
                 "summary": "圆角", "fix": "8vp"}]}))
        _write(self.proj / "spec/waves/results/auditfix/fix-alpha.json", json.dumps(
            {"domain": "alpha", "fixed": [], "files_touched": [], "skipped": [
                {"finding_ref": 1, "reason": "跨白名单", "required_owner": "beta"},
                {"finding_ref": 2, "reason": "越界", "required_owner": "nosuch-owner"},
                {"finding_ref": 2, "reason": "否决：不实"}]}))     # 无 owner 不入账

    def _run(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(FIX_BACKLOG), "--project", str(self.proj),
             "--blueprint", "spec/blueprint", "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj), timeout=120)

    def test_collects_and_suspends(self) -> None:
        self._results()
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["open"], 2)
        by_id = {it["id"]: it for it in out["items"]}
        self.assertEqual(by_id["BK-1"]["severity"], "P0")
        self.assertEqual(by_id["BK-1"]["fix"], "SplashPage 改调 AppInitializer")
        self.assertFalse(by_id["BK-1"]["owner_invalid"])
        self.assertTrue(by_id["BK-2"]["owner_invalid"])          # nosuch-owner 非法
        payload = json.loads((self.proj / "spec/state/approvals/fix-backlog.json")
                             .read_text(encoding="utf-8"))
        self.assertFalse(payload["approved"])                    # 非空挂起（裁决点 2）
        self.assertEqual(payload["p0"], 1)
        self.assertTrue((self.bp / "wiring-backlog.json").is_file())

    def test_empty_auto_approves(self) -> None:
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads((self.proj / "spec/state/approvals/fix-backlog.json")
                             .read_text(encoding="utf-8"))
        self.assertTrue(payload["approved"])
        self.assertTrue(payload["auto"])

    def test_human_approval_not_overwritten(self) -> None:
        self._results()
        _write(self.proj / "spec/state/approvals/fix-backlog.json",
               json.dumps({"approved": True, "by": "mj-cjm",
                           "resolution": {"defer": True}}))
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads((self.proj / "spec/state/approvals/fix-backlog.json")
                             .read_text(encoding="utf-8"))
        self.assertTrue(payload["approved"])                     # 人批不被覆盖
        out = json.loads(proc.stdout)
        self.assertTrue(out["resolution"]["defer"])              # defer 透传进 backlog


class TestHandoffCheck(unittest.TestCase):
    """V1：交棒硬门——空账全 blocked；产物齐则 PASS，消息首行不含「完成」。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-handoffcheck-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.bp = self.proj / "spec" / "blueprint"
        _write(self.bp / "domain-map.json", json.dumps(
            {"version": 1, "domains": [{"key": "alpha"}]}))
        _write(self.bp / "workflow-params.json", json.dumps(
            {"profile": "flagship", "gates": {"device_smoke": "off"}}))

    def _run(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HANDOFF_CHECK), "--project", str(self.proj),
             "--blueprint", "spec/blueprint", "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj), timeout=120)

    def test_empty_project_is_blocked(self) -> None:
        proc = self._run()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        out = json.loads(proc.stdout)
        for cid in ("build-graph", "handoffs", "fix-backlog", "decision-gaps",
                    "report", "state-accounts",
                    "findings"):   # E265⑦：findings-gate.json 缺席也是空账，与其余各门同判 blocked（原为 skip）
            self.assertIn(cid, out["blocked"], out["blocked"])
        msg = (self.proj / "spec/reports/handoff-message.md").read_text(encoding="utf-8")
        self.assertTrue(msg.startswith("阶段 B 收尾：BLOCKED"))
        self.assertNotIn("完成", msg)
        self.assertNotIn("failed=0", msg)

    def test_all_green_passes_and_hands_off(self) -> None:
        _write(self.proj / "build-profile.json5", '{\n  "signingConfig": "default",\n}\n')
        _write(self.proj / "spec/state/state.json", json.dumps(
            {"version": 1, "pages": {}, "waves": {},
             "domains": {"alpha": {"final_state": "PASS"}},
             "gates": {"compile#4": {"status": "green", "passed": True, "attempts": 1,
                                     "build_graph": {"business_ratio": 0.95, "passed": True}}}}))
        _write(self.proj / "spec/reports/handoff-ledger.json", json.dumps(
            {"total": 0, "met": 0, "unmet": [], "dangling_fwd_ref": []}))
        _write(self.proj / "spec/reports/fix-backlog.json", json.dumps(
            {"open": 0, "items": [], "by_owner": {}}))
        _write(self.proj / "spec/reports/decision-gaps.json", json.dumps(
            {"total": 0, "blocking": 0, "gaps": []}))
        _write(self.proj / "spec/reports/migration-report.meta.json", json.dumps(
            {"nodata_sections": [], "sources_degraded": [], "unverified_device_ac": []}))
        _write(self.proj / "spec/reports/smoke/render-static.json", json.dumps(   # F4：off 档 cold-start/smoke-1page 读静态回退报告
            {"ok": True, "mode": "static", "checks": {}, "findings": []}))
        _write(self.proj / "spec/reports/findings-gate.json", json.dumps(         # E265⑦：findings 销账门必须跑过且清零
            {"detector": "findings-gate", "mode": "blocking", "passed": True,
             "counts": {"P0": 0, "P1": 0, "P2": 0, "other": 0}, "open": [], "waived": [], "backlog": []}))
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(next(c["status"] for c in out["checks"] if c["id"] == "findings"), "ok")
        msg = (self.proj / "spec/reports/handoff-message.md").read_text(encoding="utf-8")
        self.assertTrue(msg.startswith("阶段 B 收尾：PASS"))
        self.assertIn("- findings 销账：round0 未销账 P0/P1 0 条", msg)
        self.assertIn("$a2h-verify", msg)


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()


class TestClosureWave(PlanFixture):
    """closure 波（V-830 Final Structural Closure 自动修复波）：条件波形状 + 再入判定。"""

    def _backlog(self, **over) -> None:
        payload = {"version": 1, "round": 1, "max_iter": 8, "verdict": "CONTINUE",
                   "open": 2, "converged": False, "exhausted": False,
                   "items": [
                       {"id": "CL-001", "file": "features/alpha/A.ets", "owner": "domain:alpha",
                        "layer": "ui", "severity": "FAIL", "detector": "audit",
                        "code": "skeleton-L2", "summary": "空实现",
                        "suggested_action": "补齐 onClick"},
                       {"id": "CL-002", "file": "features/beta/B.ets", "owner": "domain:beta",
                        "layer": "feat", "severity": "FAIL", "detector": "orphans",
                        "code": "orphan-vm", "summary": "VM 未被引用",
                        "suggested_action": "接线到页面"}],
                   "unowned": [], "brief_ref": "spec/execution/autofix-log/round-latest/x.json",
                   "resolution": {}}
        payload.update(over)
        self._write(self.blueprint / "closure-backlog.json", json.dumps(payload))

    def test_closure_fans_out_by_owner_with_round_suffix(self) -> None:
        self._backlog()
        self.gen("closure")
        by_id = {t["id"]: t for t in self.plan("closure")["tasks"]}
        # 按 owner 扇出，round 后缀防跨轮撞 dispatch 账
        self.assertIn("closure:r1:domain:alpha", by_id)
        self.assertIn("closure:r1:domain:beta", by_id)
        a = by_id["closure:r1:domain:alpha"]
        self.assertEqual(a["kind"], "agent")
        self.assertEqual(a["schema"], "domainImpl")
        self.assertEqual(a["map_group"], "closure-impl")
        self.assertEqual(a["ownership"], ["features/alpha/**"])   # 白名单按 owner 收窄
        # 830 §3.5 分轨：全 ui → UI 转换专家；含 feat → 通用迁移工人（粒度是 owner 不是 finding）
        self.assertEqual(a["agent"], "a2h-activity-converter@1.0.0")
        self.assertEqual(by_id["closure:r1:domain:beta"]["agent"], "a2h-migration-worker@1.0.0")
        # 波尾：重编 + 编译门 + 重扫（重扫是收敛判定的唯一来源）
        self.assertEqual(by_id["gate:compile-closure"]["parents"], ["reduce:build-closure"])
        # 重扫由 closure_backlog --run-iterate 内部发起（单条命令）——reduce.run 不经 shell，
        # 旧版用 `;` 串 structural_loop + closure_backlog，分号连同后半条被当成前一条的参数，
        # 汇账从未执行（AIPPT_915_test3 实证）。断言随契约更新。
        rescan = by_id["gate:closure-rescan"]["run"]
        self.assertIn("closure_backlog.py", rescan)
        self.assertIn("--run-iterate", rescan)
        self.assertNotIn(";", rescan)
        self.assertIn("closure_backlog.py", by_id["gate:closure-rescan"]["run"])
        self.assertEqual(by_id["gate:closure-rescan"]["parents"], ["gate:compile-closure"])
        self.assertTrue(self.lint("closure")["ok"])

    def test_closure_task_book_carries_only_own_items(self) -> None:
        self._backlog()
        self.gen("closure")
        t = {x["id"]: x for x in self.plan("closure")["tasks"]}["closure:r1:domain:alpha"]
        prompt = (self.proj / t["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("CL-001", prompt)
        self.assertNotIn("CL-002", prompt)              # 别人的条目不进本任务书
        self.assertIn("suggested_action", prompt)
        self.assertIn("gate:closure-rescan", prompt)    # 明示「不自证，由重扫验证」

    def test_closure_stalled_needs_human_before_another_round(self) -> None:
        """E52：verdict=STALLED 未经 resolution.allow_stalled → generate 拒绝扇出；裁决后放行。"""
        self._backlog(round=3, verdict="STALLED", open=2)
        proc = self._run(GENERATE, "--blueprint", "spec/blueprint", "--out", "spec/waves", "--wave", "closure", "--json")
        self.assertNotEqual(proc.returncode, 0); self.assertIn("STALLED", proc.stderr + proc.stdout)
        self.assertFalse((self.proj / "spec/waves/plan-closure.json").is_file())
        import next_batch as NB
        hint = NB._next_hint({"wave": "closure"}, self.proj / "spec/waves/plan-closure.json", self.proj)
        self.assertEqual(hint["kind"], "escalate"); self.assertIn("STALLED", hint["reason"])
        self._backlog(round=3, verdict="STALLED", open=2, resolution={"allow_stalled": True})
        proc = self._run(GENERATE, "--blueprint", "spec/blueprint", "--out", "spec/waves", "--wave", "closure", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertTrue((self.proj / "spec/waves/plan-closure.json").is_file())
        self.assertEqual(NB._next_hint({"wave": "closure"}, self.proj / "spec/waves/plan-closure.json", self.proj)["kind"], "wave")

    def test_closure_skipped_when_converged(self) -> None:
        """收敛即零任务——条件波不出计划（实际流程里 next_batch 见 open=0 根本不会来 generate）。"""
        self._backlog(open=0, converged=True, verdict="CONVERGED", items=[])
        proc = self._run(GENERATE, "--blueprint", "spec/blueprint", "--out", "spec/waves",
                         "--wave", "closure")
        # 与 wiring 条件波同约定：exit 0 但不落计划（next_batch 见 open=0 根本不会来 generate）
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertFalse((self.proj / "spec/waves/plan-closure.json").is_file(),
                         "收敛的 closure 不应产出计划")
        self.assertIn("closure-backlog", proc.stderr + proc.stdout)

    def test_closure_mixed_layer_owner_routes_to_generalist(self) -> None:
        """同一 owner 同时有 ui 与 feat 条目 → 走通用迁移工人（不拆两个任务：
        lint R3 禁同组 ownership 相交，单写者纪律也禁两个 agent 并发改同一 owner）。"""
        self._backlog(items=[
            {"id": "CL-001", "file": "features/alpha/A.ets", "owner": "domain:alpha",
             "layer": "ui", "severity": "FAIL", "detector": "audit", "code": "skeleton-L2",
             "summary": "空实现", "suggested_action": "补齐 onClick"},
            {"id": "CL-002", "file": "features/alpha/S.ets", "owner": "domain:alpha",
             "layer": "feat", "severity": "FAIL", "detector": "orphans", "code": "orphan-vm",
             "summary": "VM 未引用", "suggested_action": "接线"}])
        self.gen("closure")
        tasks = [t for t in self.plan("closure")["tasks"] if t["kind"] == "agent"]
        self.assertEqual(len(tasks), 1, "同一 owner 只出一个修复任务")
        self.assertEqual(tasks[0]["agent"], "a2h-migration-worker@1.0.0")
        prompt = (self.proj / tasks[0]["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("layer=feat+ui", prompt)      # 任务书如实标混合
        self.assertIn("CL-001", prompt)
        self.assertIn("CL-002", prompt)             # 混合时两条一并处理
