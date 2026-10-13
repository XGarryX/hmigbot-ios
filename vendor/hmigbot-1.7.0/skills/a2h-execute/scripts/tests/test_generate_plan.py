#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""计划生成器（generate_waves 单形态收敛）单测：blueprint fixture → 计划 IR → 四拍循环端到端。

用法示例:
    python3 -m unittest discover -s arkts-skills/skills/a2h-execute/scripts/tests -v
    python3 arkts-skills/skills/a2h-execute/scripts/tests/test_generate_plan.py

输入:  被测脚本按仓库相对位置寻址（../generate_waves.py、../../a2h-plan/scripts/lint_plan.py 等）；
       每用例在临时目录合成最小 blueprint 六件（契约合法内容 + 2 个域 + 1 个 infra 模块组），
       registry 用 bundle 真身（registry/agents/a2h-domain-worker.json），全 subprocess 黑盒调用。
输出:  unittest 标准输出。无副作用（tempfile 目录用后即删）。

覆盖（阶段 A→B 真实衔接，IMPLEMENTATION.md §6 缺口 1 的回归面）:
    infra 波   generate → lint exit 0 → next_batch 派发 → 伪造回执/实盘 .ets/构建日志 → land 落账
               （真跑 contract_sync --apply-class1 对账回写 + gate_check compile#1）→ done
    domains 波 generate → lint exit 0 → 派发 2 域 → 伪造回执 → land（gate_check compile#2）→ done
    auditfix   计划形状：audit→fix 静态接力（fix.parents=[audit]）、gate:round0/compile-3/
               escalated-ratio/report/compat-views 门禁链、fix prompt 含接力段、prompt 含回执纪律段
    understand 最小输入集模式（仅 domain-map+workflow-params）→ 出计划且 lint PASS（缺席件按空字节计）
    --retry-failed  按 state.json 任务 id 裁剪；auditfix 只留 fix 时 parents 剪空、gate:round0 随裁
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
GENERATE = SCRIPTS / "generate_waves.py"
NEXT_BATCH = SCRIPTS / "next_batch.py"
LAND_RESULTS = SCRIPTS / "land_results.py"
LINT_PLAN = SCRIPTS.parent.parent / "a2h-plan" / "scripts" / "lint_plan.py"
REGISTRY = SCRIPTS.parent.parent.parent / "registry" / "agents"   # bundle 真身 registry


class PlanFixture(unittest.TestCase):
    """公共 fixture：临时工程 + 契约六件最小合法内容（2 域 + 1 infra 模块组）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-genplan-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.blueprint = self.proj / "spec" / "blueprint"
        self.state = self.proj / "spec" / "state" / "state.json"
        self._write(self.blueprint / "domain-map.json", json.dumps({
            "version": 1, "app": "demo", "domains": [
                {"key": "alpha", "title": "Alpha", "spec_file": "spec/domains/alpha.md", "pages": []},
                {"key": "beta", "title": "Beta", "spec_file": "spec/domains/beta.md", "pages": []},
            ]}))
        self._write(self.blueprint / "ownership.json", json.dumps({
            "version": 1, "owners": {
                "domain:alpha": ["features/alpha/**"],
                "domain:beta": ["features/beta/**"],
                "infra:core": ["common/**"],
            }, "mainloop_owned": []}))
        self._write(self.blueprint / "contracts.json", json.dumps({
            "version": 1,
            "modules": [{"file": "common/Seed.ets", "owner": "infra:core",
                         "status": "planned", "exports": []}],
            "wires": [], "deferred": [], "chains": [], "acceptance": []}))
        self._write(self.blueprint / "decisions.json", json.dumps({"version": 1, "decisions": []}))
        self._write(self.blueprint / "workflow-params.json", json.dumps({
            "profile": "flagship",
            "project": {"root": str(self.proj), "android_src": str(self.proj / "android"),
                        "build_cmd": "true", "encoding": "utf-8"},
            # E265⑧：编译图对账「数据不可得」已改判 graph-nodata（FAIL）。本夹具的 build_cmd=true 从不产
            # sourceMaps.map，属于真取不到——按新规矩显式署名豁免（而不是像从前那样靠脚本自己 WARN 跳过）。
            # 真跑的工程套不上这把钥匙：那里 hvigor 必产编译图，取不到就是构建没跑对。
            "gates": {"compile_graph_nodata_waiver":
                      {"by": "fixture", "reason": "单测夹具 build_cmd=true，不产 hvigor 编译图"}},
            "waves": {"domains": {"model": "flagship", "fragments_default": []}}}))
        self._write(self.blueprint / "decision-ledger.md", "# ledger\n")

    # ── fixture 工具 ──────────────────────────────────────────────────────

    def _write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _run(self, script: Path, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["ARKTS_SKILL_DIR"] = str(SCRIPTS.parent)  # a2h-execute skill 目录（片段库/兄弟脚本寻址）
        return subprocess.run([sys.executable, str(script), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              cwd=str(self.proj), env=env, timeout=180)

    def gen(self, wave: str, *flags: str, expect: int = 0) -> subprocess.CompletedProcess:
        proc = self._run(GENERATE, "--blueprint", "spec/blueprint", "--out", "spec/waves",
                         "--wave", wave, *flags)
        self.assertEqual(proc.returncode, expect, proc.stderr + proc.stdout)
        return proc

    def plan(self, wave: str) -> dict:
        return json.loads((self.proj / "spec" / "waves" / ("plan-%s.json" % wave))
                          .read_text(encoding="utf-8"))

    def lint(self, wave: str, expect: int = 0) -> dict:
        proc = self._run(LINT_PLAN, "--plan", "spec/waves/plan-%s.json" % wave,
                         "--blueprint", "spec/blueprint", "--registry", str(REGISTRY), "--json")
        self.assertEqual(proc.returncode, expect, proc.stderr + proc.stdout)
        return json.loads(proc.stdout)

    def next_batch(self, wave: str, expect: int = 0) -> dict:
        proc = self._run(NEXT_BATCH, "--plan", "spec/waves/plan-%s.json" % wave,
                         "--state", str(self.state), "--json")
        self.assertEqual(proc.returncode, expect, proc.stderr + proc.stdout)
        return json.loads(proc.stdout)

    def land(self, wave: str, expect: int = 0) -> dict:
        proc = self._run(LAND_RESULTS, "--plan", "spec/waves/plan-%s.json" % wave,
                         "--state", str(self.state), "--json")
        self.assertEqual(proc.returncode, expect, proc.stderr + proc.stdout)
        return json.loads(proc.stdout)

    def write_result(self, rel: str, obj: dict) -> None:
        for key in ("files", "files_touched"):   # A8：声明的文件必须实存，夹具代表真写了文件的 worker
            for f in (obj or {}).get(key) or []:
                if isinstance(f, str) and f and not any(ch in f for ch in "*?[") and not (self.proj / f).exists():
                    self._write(self.proj / f, "// fixture\n")
        self._write(self.proj / rel, json.dumps(obj, ensure_ascii=False))

    def write_build_log(self, wave: str) -> None:
        self._write(self.proj / "spec" / "reports" / ("build-%s.log" % wave),
                    "BUILD SUCCESSFUL in 2 s\n")

    def run_to_done(self, wave: str, on_dispatch, max_beats: int = 6) -> None:
        """四拍循环驱动到 done：dispatch → on_dispatch(batch) 伪造回执 → land → 回拍①。"""
        for _ in range(max_beats):
            act = self.next_batch(wave)
            if act["action"] == "done":
                return
            self.assertEqual(act["action"], "dispatch", act)
            on_dispatch(act["batch"])
            self.land(wave)
        self.fail("四拍循环 %d 拍内未收敛到 done" % max_beats)


class TestInfraWaveEndToEnd(PlanFixture):
    """infra 波：generate → lint → 派发 → 落账（真跑 contract_sync/gate_check reduce）→ done。"""

    def _seed_infra_tail_inputs(self) -> None:
        """F1/资源闸：infra 波尾 reduce:host-page 要启动路由可解析，gate:resource-coverage 要非空期望集且全覆盖。"""
        self._write(self.proj / "spec" / "journeys.json", json.dumps({"start": ["SplashActivity"]}))
        self._write(self.blueprint / "page-names.json", json.dumps({"domains": {"alpha": {"SplashActivity": "SplashPage"}}}))
        self._write(self.proj / "android" / "app" / "src" / "main" / "res" / "values" / "strings.xml",
                    '<resources><string name="app_name">Demo</string></resources>\n')
        self._write(self.proj / "android" / "app" / "src" / "main" / "java" / "demo" / "A.java", "class A { int x = R.string.app_name; }\n")
        self._write(self.proj / "entry" / "src" / "main" / "resources" / "base" / "element" / "string.json",
                    json.dumps({"string": [{"name": "app_name", "value": "Demo"}]}))

    def test_generate_lint_dispatch_land_done(self) -> None:
        self._seed_infra_tail_inputs()
        self.gen("infra")
        out = self.lint("infra")
        self.assertTrue(out["ok"], out)
        plan = self.plan("infra")
        self.assertEqual(plan["plan_version"], "a2h-2.1.0")
        self.assertEqual(plan["contract_hash"], out["computed_contract_hash"])
        by_id = {t["id"]: t for t in plan["tasks"]}
        self.assertEqual(by_id["impl:core"]["agent"], "a2h-domain-worker@2.1.0")
        self.assertEqual(by_id["impl:core"]["schema"], "infraImpl")
        self.assertEqual(by_id["impl:core"]["resume_key"], "infra:impl:core")
        self.assertEqual(by_id["gate:contract-sync"]["parents"], ["@infra-impl"])
        # V15：contract-sync → build-infra（build_wave 产日志）→ compile-1（消灭带外前置 E-10）
        self.assertEqual(by_id["reduce:build-infra"]["parents"], ["reduce:probe"]); self.assertEqual(by_id["reduce:probe"]["parents"],
                         ["gate:contract-sync", "reduce:resource-sweep", "gate:fence-audit", "reduce:host-page", "gate:resource-coverage"])   # F1：宿主单写 + 资源覆盖闸进编译前
        self.assertEqual(by_id["gate:compile-1"]["parents"], ["reduce:build-infra"])
        self.assertIn("host_page.py", by_id["reduce:host-page"]["run"]); self.assertEqual(by_id["reduce:host-page"]["parents"], ["@infra-impl"])
        self.assertIn("resource_coverage_gate.py", by_id["gate:resource-coverage"]["run"])

        def on_dispatch(batch):
            self.assertEqual([b["id"] for b in batch], ["impl:core"])
            # 伪造 worker 效果：实盘落 .ets（契约对账面）+ 回执结果 + 构建日志（编译门输入）
            self._write(self.proj / "entry" / "src" / "main" / "ets" / "common" / "Seed.ets",
                        "export class Seed {\n  boot(): void {}\n}\n")
            self.write_result(batch[0]["result_path"],
                              {"task": "infra:core", "final_state": "PASS",
                               "files": ["common/Seed.ets"],
                               "exports": ["Seed: class Seed { boot(): void }"]})
            self.write_build_log("infra")

        self.run_to_done("infra", on_dispatch)
        # contract_sync --apply-class1 真跑过：①类导出收编 + status planned→implemented 回写
        module = json.loads((self.blueprint / "contracts.json").read_text(encoding="utf-8"))["modules"][0]
        self.assertEqual(module["status"], "implemented")
        self.assertTrue(any(e.get("symbol") == "Seed" for e in module.get("exports", [])), module)
        journal = json.loads((self.state.parent / "journal.json").read_text(encoding="utf-8"))
        reduce_rows = {r["task_id"]: r["status"] for r in journal["operation_outputs"]
                       if r["kind"] == "reduce"}
        self.assertEqual(reduce_rows, {"gate:contract-sync": "REDUCE_PASS", "reduce:contract-fill": "REDUCE_PASS",
                                       "reduce:build-infra": "REDUCE_PASS", "reduce:resource-sweep": "REDUCE_PASS", "gate:fence-audit": "REDUCE_PASS",
                                       "gate:compile-1": "REDUCE_PASS", "reduce:product-write-audit": "REDUCE_PASS", "reduce:probe": "REDUCE_PASS",
                                       "reduce:wires-check": "REDUCE_PASS",
                                       "reduce:host-page": "REDUCE_PASS", "gate:resource-coverage": "REDUCE_PASS",
                                       "reduce:refresh-domain-briefs": "REDUCE_PASS"})   # E281：本夹具没生成 domains 计划 → 脚本按规则跳过；I5：契约无 nav-edge 时 verify_wires 空跑 PASS；F1 宿主单写真跑
        host = self.proj / "entry/src/main/ets/pages/Index.ets"     # F1：宿主由 reduce:host-page 写出（Provider + 启动入栈）
        self.assertTrue(host.is_file()); self.assertIn("@Provider('navPathStack')", host.read_text(encoding="utf-8"))
        self.assertIn("pushPathByName('SplashPage', undefined)", host.read_text(encoding="utf-8"))


class TestDomainsWaveEndToEnd(PlanFixture):
    """domains 波：2 域并行派发 → 伪造回执 → land（gate_check compile#2）→ done。"""

    def test_generate_lint_dispatch_land_done(self) -> None:
        self.gen("domains")
        self.assertTrue(self.lint("domains")["ok"])
        plan = self.plan("domains")
        agents = [t for t in plan["tasks"] if t["kind"] == "agent"]
        self.assertEqual([t["id"] for t in agents], ["impl:alpha", "impl:beta"])
        self.assertTrue(all(t["map_group"] == "domains-impl" for t in agents))
        self.assertEqual(plan["products"]["#Eimpl-alpha"], "spec/waves/results/domains/alpha.json")
        # 回执纪律段已追加到 prompt 尾部（D3）
        prompt = (self.proj / "spec/waves/prompts/domains/alpha.txt").read_text(encoding="utf-8")
        self.assertIn("## 回执纪律", prompt)
        self.assertIn("OK spec/waves/results/domains/alpha.json", prompt)

        def on_dispatch(batch):
            self.assertEqual({b["id"] for b in batch}, {"impl:alpha", "impl:beta"})
            for b in batch:
                key = b["id"].split(":", 1)[1]
                self.write_result(b["result_path"],
                                  {"task": "domain:%s" % key, "final_state": "PASS",
                                   "files": ["features/%s/A.ets" % key]})
            self.write_build_log("domains")

        self.run_to_done("domains", on_dispatch)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        statuses = {t["id"]: t["status"] for t in state["waves"]["domains"]["tasks"]}
        self.assertEqual(statuses, {"impl:alpha": "done", "impl:beta": "done"})
        journal = json.loads((self.state.parent / "journal.json").read_text(encoding="utf-8"))
        self.assertEqual([r["status"] for r in journal["workflow_status"]], ["SUCCESS"])


class TestAuditfixPlanShape(PlanFixture):
    """auditfix 计划形状：audit→fix 静态接力 + 门禁 reduce 链（D1/D2 的机器断言）。"""

    def test_relay_and_gate_chain(self) -> None:
        self.gen("auditfix")
        self.assertTrue(self.lint("auditfix")["ok"])
        plan = self.plan("auditfix")
        by_id = {t["id"]: t for t in plan["tasks"]}
        self.assertEqual(by_id["fix:alpha"]["parents"], ["audit:alpha"])
        self.assertEqual(by_id["audit:alpha"]["schema"], "auditFindings")
        self.assertEqual(by_id["fix:alpha"]["schema"], "fixResult")
        self.assertEqual(by_id["gate:round0"]["parents"], ["@auditfix-audit"])
        # E265①：D2 的 best-effort（无 on_fail → failed_handled 静默）改为 escalate——round0_precheck 的非 0
        # 只代表机械预检整个没产出（有 findings 也是 exit 0），fix 代理因此拿不到 round-0 清单，无人看得见
        self.assertIs(by_id["gate:round0"]["on_fail"]["escalate"], True)
        # K9：fix 后编译门前幂等重收束路由（sync_pagemap），编译门改挂其后
        self.assertEqual(by_id["reduce:pagemap"]["parents"], ["@auditfix-fix"])
        self.assertIn("sync_pagemap.py", by_id["reduce:pagemap"]["run"])
        # V15/V2 新链：pagemap → build-auditfix → compile-3 → fix-backlog（审批）
        #             → escalated-ratio（并等 merge-gaps）→ report → compat-views
        self.assertEqual(by_id["reduce:build-auditfix"]["parents"], ["reduce:probe"]); self.assertEqual(by_id["reduce:probe"]["parents"],
                         ["reduce:pagemap", "reduce:resource-sweep", "gate:fence-audit"])
        self.assertEqual(by_id["gate:compile-3"]["parents"], ["reduce:build-auditfix"])
        self.assertEqual(by_id["gate:fix-backlog"]["parents"], ["gate:compile-3", "gate:round0-clear"])
        self.assertEqual(by_id["gate:fix-backlog"]["approval"]["suspend_payload"],
                         "spec/state/approvals/fix-backlog.json")
        self.assertIn("fix_backlog.py", by_id["gate:fix-backlog"]["run"])
        self.assertEqual(by_id["reduce:merge-gaps"]["parents"], ["@auditfix-audit"])
        self.assertIn("merge_gaps.py", by_id["reduce:merge-gaps"]["run"])
        self.assertEqual(by_id["gate:escalated-ratio"]["parents"],
                         ["gate:fix-backlog", "reduce:merge-gaps"])
        self.assertEqual(by_id["reduce:report"]["parents"], ["gate:escalated-ratio"])
        self.assertEqual(by_id["reduce:compat-views"]["parents"], ["reduce:report"])
        # fix prompt 含静态接力段：读 audit 回执文件；findings 为空直接回 OK（D1）
        prompt = (self.proj / "spec/waves/prompts/auditfix/fix-alpha.txt").read_text(encoding="utf-8")
        self.assertIn("audit→fix 静态接力", prompt)
        self.assertIn("spec/waves/results/auditfix/audit-alpha.json", prompt)
        self.assertIn("spec/reports/round0/alpha.json", prompt)


class TestUnderstandMinimalInputs(PlanFixture):
    """understand 最小输入集模式：仅 domain-map + workflow-params（a2h-spec A1 依赖）。"""

    def test_minimal_blueprint_generates_lintable_plan(self) -> None:
        for name in ("ownership.json", "contracts.json", "decisions.json", "decision-ledger.md"):
            (self.blueprint / name).unlink()
        proc = self.gen("understand")
        self.assertIn("最小输入集", proc.stderr)
        plan = self.plan("understand")
        agents = [t for t in plan["tasks"] if t["kind"] == "agent"]
        self.assertEqual([t["id"] for t in agents], ["read:alpha", "read:beta"])
        self.assertEqual([t["schema"] for t in agents], ["understandSummary"] * 2)
        # 波尾机械收割节点（830 资源管线回填：直扫安卓 res/layout 收割字面量入台账）。
        # E265①：收割/播种改为升级——「无事可对账」的 literal 闸是判绿而不是显红，整条资源管线的头崩了主线不该继续；
        # 两个 spec 闸（一轮）维持不升级，它们的失败本身就是 specfix 条件波的派发扳机。
        reduces = [t for t in plan["tasks"] if t["kind"] == "reduce"]
        self.assertEqual([r["id"] for r in reduces], ["reduce:harvest-literals", "reduce:annotate-attrs", "reduce:seed-resources", "gate:spec-depth", "gate:interface"])   # I6（E280 加 annotate-attrs）
        self.assertEqual(reduces[0]["parents"], ["@understand-read"])
        self.assertEqual([r["on_fail"]["escalate"] for r in reduces], [True, False, True, False, False])   # annotate-attrs 纯文本变换，失败不阻断主线
        for t in agents:
            self.assertTrue((self.proj / t["prompt_file"]).is_file(), t["prompt_file"])
        out = self.lint("understand")   # 缺席件按空字节计入 hash → PASS + warnings
        self.assertTrue(out["ok"], out)
        self.assertTrue(any("缺席" in w for w in out["warnings"]), out["warnings"])


class TestRetryFailedTrim(PlanFixture):
    """--retry-failed：按 state.json 任务 id 只留 failed；被裁上游的 parents/门禁随剪。"""

    def _state(self, wave: str, statuses: dict) -> None:
        self._write(self.state, json.dumps({
            "version": 1, "waves": {wave: {"tasks": [
                {"id": tid, "status": st} for tid, st in statuses.items()]}}}))

    def test_domains_keeps_only_failed(self) -> None:
        self._state("domains", {"impl:alpha": "failed", "impl:beta": "done"})
        self.gen("domains", "--retry-failed")
        plan = self.plan("domains")
        ids = [t["id"] for t in plan["tasks"]]
        # K9+V2+V15：pagemap / merge-deferred / merge-gaps 并行（@domains-impl）
        #            → build-domains → compile-2
        # …→ compile-2 → gate:depth（还原深度闸：既有门禁全守结构健康，无一守深度）
        # merge-gaps 之后：资源 sweep（资源 JSON 单写者）→ 围栏审计门 → 编译
        self.assertEqual(ids, ["impl:alpha", "reduce:pagemap", "reduce:merge-deferred",
                               "reduce:merge-gaps", "reduce:resource-sweep", "gate:fence-audit",
                               "reduce:probe", "reduce:build-domains", "gate:compile-2", "gate:depth", "reduce:wires-check", "reduce:product-write-audit"])
        self.assertTrue(self.lint("domains")["ok"])

    def test_auditfix_fix_only_prunes_parents_and_round0(self) -> None:
        self._state("auditfix", {"audit:alpha": "done", "fix:alpha": "failed",
                                 "audit:beta": "done", "fix:beta": "done"})
        self.gen("auditfix", "--retry-failed")
        plan = self.plan("auditfix")
        by_id = {t["id"]: t for t in plan["tasks"]}
        self.assertEqual(sorted(by_id), ["fix:alpha", "gate:closure-scan", "gate:compile-3",
                                         "gate:escalated-ratio", "gate:fence-audit", "gate:fix-backlog", "gate:round0-clear",
                                         "reduce:build-auditfix", "reduce:compat-views",
                                         "reduce:pagemap", "reduce:probe", "reduce:product-write-audit", "reduce:report", "reduce:resource-sweep",
                                         "reduce:wires-check"])
        self.assertEqual(by_id["fix:alpha"]["parents"], [])   # audit 已 done 被裁 → 按已满足剔除
        self.assertNotIn("gate:round0", by_id)                # 审计组清空 → 前置 reduce 随裁
        self.assertNotIn("reduce:merge-gaps", by_id)          # 同理：@auditfix-audit 上游全裁
        # merge-gaps 被裁 → escalated-ratio 的 parents 相应剪除
        self.assertEqual(by_id["gate:escalated-ratio"]["parents"], ["gate:fix-backlog"])
        self.assertTrue(self.lint("auditfix")["ok"])

    def test_retry_without_state_fails(self) -> None:
        proc = self._run(GENERATE, "--blueprint", "spec/blueprint", "--out", "spec/waves",
                         "--wave", "domains", "--retry-failed")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("state.json", proc.stderr)


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
