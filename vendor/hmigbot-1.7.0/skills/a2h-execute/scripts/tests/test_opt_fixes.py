#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OPT-PLAN 第一批内核修复（K 系列）单测：机械规范化 / REDUCE_FAIL 复位 / INFRA_FAIL 分账 /
编译图对账 / 路由收束脚本 / 字段契约表 / --raw-json / lint 兜底 / mainloop 审计对 / 契约段兜底。

用法示例:
    python3 -m unittest discover -s arkts-skills/skills/a2h-execute/scripts/tests -v

输入:  复用 test_scheduler_kernel.KernelFixture 与 test_generate_plan.PlanFixture 的合成工程；
       全部 subprocess 黑盒调用（与既有测试同纪律）。
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

from test_scheduler_kernel import (KernelFixture, VALID_ALPHA, VALID_BETA,
                                   NEXT_BATCH, LAND_RESULTS, LINT_PLAN, SCRIPTS)
from test_generate_plan import PlanFixture

GATE_CHECK = SCRIPTS / "gate_check.py"
SYNC_PAGEMAP = SCRIPTS / "sync_pagemap.py"
PARSE_AGENT = SCRIPTS / "parse_agent_output.py"


class TestMechanicalNormalize(KernelFixture):
    """K2：白名单内 schema 偏差自动规范化入账；白名单外照旧 RETRY。"""

    def _journal_rows(self) -> list[dict]:
        journal = json.loads((self.state.parent / "journal.json").read_text(encoding="utf-8"))
        return [r for r in journal["operation_outputs"] if r["kind"] == "agent"]

    def test_object_exports_and_scalar_files_normalized(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        # alpha：exports 对象数组（试点 infra 波实锤形态）；beta：files 标量
        self.write_result("alpha", {"task": "domain:alpha", "final_state": "PASS",
                                    "files": ["features/alpha/A.ets"],
                                    "exports": [{"symbol": "push",
                                                 "signature": "push(name: string): void"}]})
        self.write_result("beta", {"task": "domain:beta", "final_state": "PASS",
                                   "files": "features/beta/B.ets"}, fenced=False)
        out = self.land()
        self.assertEqual({r["id"]: r["status"] for r in out["landed"]},
                         {"impl:alpha": "OK", "impl:beta": "OK"})
        notes = {r["task_id"]: r.get("normalized") for r in self._journal_rows()}
        self.assertIn("exports:元素→字符串表示", notes["impl:alpha"] or [])
        self.assertIn("files:标量→单元素数组", notes["impl:beta"] or [])
        self.assertEqual(self.state_task("impl:beta")["files_touched"], ["features/beta/B.ets"])

    def test_fix_schema_domain_derived_and_fixed_wrapped(self) -> None:
        plan = self.base_plan()
        plan["tasks"] = [{
            "id": "fix:alpha", "kind": "agent", "agent": "a2h-domain-worker@2.1.0",
            "prompt_file": "spec/waves/prompts/domains/fix-alpha.txt", "model": "flagship",
            "schema": "fixResult", "parents": [], "map_group": "auditfix-fix",
            "ownership": ["features/alpha/**"],
            "result_path": "spec/waves/results/domains/alpha.json",
            "resume_key": "domains:fix:alpha"}]
        self.write_plan(plan)
        self.next_batch()
        # 缺顶层 domain（从任务 id 推导）+ fixed 为标量（包裹为数组）——试点 audit/fix 两连踩形态
        self.write_result("alpha", {"fixed": "#1 空指针已修", "skipped": []}, fenced=False)
        out = self.land()
        self.assertEqual(out["landed"][0]["status"], "OK")
        notes = self._journal_rows()[0].get("normalized") or []
        self.assertIn("domain:从任务 id 推导补全", notes)
        self.assertIn("fixed:标量→单元素数组", notes)

    def test_out_of_whitelist_defect_still_retries(self) -> None:
        # 缺必填 files（非机械可修——不做无中生有的补全）→ 照旧 RETRY_NEEDED
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("alpha", {"task": "domain:alpha", "final_state": "PASS"})
        self.write_result("beta", VALID_BETA)
        out = self.land()
        self.assertEqual({r["id"]: r["status"] for r in out["landed"]},
                         {"impl:alpha": "RETRY_NEEDED", "impl:beta": "OK"})
        self.assertIsNone(self._journal_rows()[0].get("normalized")
                          if self._journal_rows()[0]["task_id"] == "impl:alpha" else None)


class TestRerunReduce(KernelFixture):
    """K3：--rerun-reduce 复位重跑终态 REDUCE_FAIL 的门禁（R7 剧本的机器承载）。"""

    def _fail_gate_once(self) -> None:
        self.write_plan(self.base_plan())
        self._write(self.gate_rc, "1")
        self.next_batch()
        self.write_result("alpha", VALID_ALPHA)
        self.write_result("beta", VALID_BETA)
        self.land(expect=2)   # REDUCE_FAIL + skip impl:final + escalate

    def test_rerun_after_root_cause_fixed(self) -> None:
        self._fail_gate_once()
        act = self.next_batch()
        self.assertEqual((act["action"], act.get("settled")), ("done", True))  # E266：不再停机，改记欠账放行
        self.assertIn("rerun-reduce", act.get("hint", ""))
        self._write(self.gate_rc, "0")             # 人工裁决修复根因
        proc = self._run(LAND_RESULTS, "--plan", str(self.plan_path),
                         "--state", str(self.state), "--rerun-reduce", "gate:compile", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        out = json.loads(proc.stdout)
        self.assertEqual(out["reduces"], [{"id": "gate:compile", "status": "REDUCE_PASS"}])
        journal = json.loads((self.state.parent / "journal.json").read_text(encoding="utf-8"))
        gate_rows = [r["status"] for r in journal["operation_outputs"]
                     if r["task_id"] == "gate:compile"]
        self.assertEqual(gate_rows, ["REDUCE_FAIL", "REDUCE_PASS"])   # append-only 不改历史
        self.assertNotEqual(self.next_batch()["action"], "escalate")  # escalate 解除

    def test_rerun_rejects_non_reduce_fail_target(self) -> None:
        self._fail_gate_once()
        for target in ("impl:alpha", "no-such-node"):
            proc = self._run(LAND_RESULTS, "--plan", str(self.plan_path),
                             "--state", str(self.state), "--rerun-reduce", target, "--json")
            self.assertEqual(proc.returncode, 1, target)
            self.assertIn("rerun-reduce", proc.stderr)


class TestInfraFail(KernelFixture):
    """K7：基础设施失败分账——INFRA_FAIL 不耗 attempts、state 回 pending、健康探测门。"""

    def three_plan(self) -> dict:
        plan = self.base_plan()
        gamma = dict(plan["tasks"][0])
        gamma.update({"id": "impl:gamma", "ownership": ["features/gamma/**"],
                      "prompt_file": "spec/waves/prompts/domains/gamma.txt",
                      "result_path": "spec/waves/results/domains/gamma.json",
                      "resume_key": "domains:impl:gamma"})
        plan["tasks"].insert(2, gamma)
        return plan

    def _receipt(self, key: str) -> None:
        """主会话代写的一行 FAIL 回执（R8 动作序列第 1 步）。"""
        self._write(self.proj / "spec" / "waves" / "results" / "domains" / f"{key}.json",
                    f"FAIL spec/waves/results/domains/{key}.json API Error 529 overloaded\n")

    def test_infra_fail_waives_attempts_and_returns_pending(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        self._receipt("alpha")
        self.write_result("beta", VALID_BETA)
        out = self.land()
        self.assertEqual({r["id"]: r["status"] for r in out["landed"]},
                         {"impl:alpha": "INFRA_FAIL", "impl:beta": "OK"})
        self.assertEqual(self.state_task("impl:alpha")["status"], "pending")

        act = self.next_batch()                    # 尾部 INFRA_FAIL=1 < 3，按新任务重吐
        self.assertEqual(act["action"], "dispatch")
        self.assertEqual([b["id"] for b in act["batch"]], ["impl:alpha"])
        self.write_result("alpha", None, garbage=True)   # 这次是真失败
        out = self.land()
        self.assertEqual(out["landed"][0]["status"], "RETRY_NEEDED")  # 豁免后仍有完整重派额度

    def test_health_probe_gate_and_assume_healthy(self) -> None:
        self.write_plan(self.three_plan())
        self.next_batch()
        for key in ("alpha", "beta", "gamma"):
            self._receipt(key)
        self.land()
        act = self.next_batch()                    # 尾部连续 3 个 INFRA_FAIL → 健康门拦下
        self.assertEqual(act["action"], "wait")
        self.assertTrue(act.get("health_probe"))
        proc = self._run(NEXT_BATCH, "--plan", str(self.plan_path),
                         "--state", str(self.state), "--assume-healthy", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        act = json.loads(proc.stdout)
        self.assertEqual(act["action"], "dispatch")
        self.assertEqual({b["id"] for b in act["batch"]},
                         {"impl:alpha", "impl:beta", "impl:gamma"})
        import time as _t; _t.sleep(1.1)
        act = self.next_batch()                    # E83：已按健康断言派过新批 → 不再每拍①都要求探测
        self.assertFalse(act.get("health_probe"), act); self.assertEqual(act["action"], "wait")

    def test_structured_invalid_result_never_classified_infra(self) -> None:
        # 结构化结果里含 rate limit 字样但 schema 不合格 → 走 RETRY，防误分类无限重派
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("alpha", {"task": "domain:alpha",
                                    "notes": "hit rate limit in doc"}, fenced=False)
        self.write_result("beta", VALID_BETA)
        out = self.land()
        self.assertEqual(out["landed"][0]["status"], "RETRY_NEEDED")


class TestGateCheckBuildGraph(unittest.TestCase):
    """K4：编译图对账杀「假 PASS」——sourceMaps 条目 vs ownership 实盘 .ets。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-graph-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.bp = self.proj / "spec" / "blueprint"
        self._write(self.bp / "ownership.json", json.dumps(
            {"version": 1, "owners": {"domain:alpha": ["entry/src/main/ets/pages/**"]},
             "mainloop_owned": []}))
        self._write(self.proj / "build.log", "BUILD SUCCESSFUL in 3 s 300 ms\n")
        for name in ("A", "B", "C"):
            self._write(self.proj / "entry/src/main/ets/pages" / f"{name}.ets", "// ets\n")

    def _write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _sourcemaps(self, names: list[str]) -> None:
        data = {"entry|entry|1.0.0|src/main/ets/pages/%s.ts" % n: {"version": 3} for n in names}
        self._write(self.proj / "entry/build/default/cache/default/default@CompileArkTS"
                    / "esmodule/debug/sourceMaps.map", json.dumps(data))

    def _run_gate(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(GATE_CHECK), "--state", "spec/state/state.json",
             "--gate", "compile#2", "--build-log", "build.log",
             "--blueprint", "spec/blueprint", "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj), timeout=120)

    def test_full_coverage_green(self) -> None:
        self._sourcemaps(["A", "B", "C"])
        proc = self._run_gate()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["verdict"], "green")
        self.assertTrue(out["build_graph"]["passed"])

    def test_partial_coverage_graph_mismatch(self) -> None:
        self._sourcemaps(["A"])                    # 1/3 入图（试点 4/49 同型）
        proc = self._run_gate()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        out = json.loads(proc.stdout)
        self.assertEqual(out["verdict"], "graph-mismatch")
        self.assertIn("探针", out["probe_hint"])

    def test_missing_sourcemaps_is_graph_nodata_fail(self) -> None:
        """E265⑧：编译图取不到 = 证明不了达标 → graph-nodata（FAIL），并给出可执行补救。

        原判据是「stderr WARN 降级跳过」——构建没产出 sourceMaps 反而自动拿绿灯，是典型的条件跳过。"""
        proc = self._run_gate()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        out = json.loads(proc.stdout)
        self.assertEqual(out["verdict"], "graph-nodata")
        self.assertEqual(out["verdict_label"], "graph-nodata(no-sourcemaps)")
        self.assertFalse(out["build_graph"]["available"]); self.assertFalse(out["build_graph"]["passed"])
        self.assertIn("sourceMaps", out["probe_hint"]); self.assertIn("hvigorw", out["probe_hint"])
        self.assertIn("compile_graph_nodata_waiver", out["probe_hint"])   # 补救里写明署名豁免怎么走

    def test_nodata_waiver_must_be_signed(self) -> None:
        """豁免必须署名+给理由：占位责任人/敷衍理由关不掉；署名合格才放行且在 verdict 与 stderr 双处显形。"""
        wp = self.bp / "workflow-params.json"
        self._write(wp, json.dumps({"gates": {"compile_graph_nodata_waiver": {"by": "auto", "reason": "夹具没有真实构建产物"}}}))
        self.assertEqual(self._run_gate().returncode, 1)                   # by 是占位词 → 关不掉
        self._write(wp, json.dumps({"gates": {"compile_graph_nodata_waiver": {"by": "ventiu", "reason": "短"}}}))
        self.assertEqual(self._run_gate().returncode, 1)                   # 理由不足 8 字 → 关不掉
        self._write(wp, json.dumps({"gates": {"compile_graph_nodata_waiver":
                                              {"by": "ventiu", "reason": "单测夹具不跑真实 hvigor 构建"}}}))
        proc = self._run_gate()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        out = json.loads(proc.stdout)
        self.assertEqual(out["verdict"], "green")
        self.assertEqual(out["build_graph"]["waived_by"], "ventiu")
        self.assertFalse(out["build_graph"]["available"])                  # 放行 ≠ 证明过
        self.assertIn("ventiu", proc.stderr); self.assertIn("未经证明", proc.stderr)

    def test_unowned_ets_is_graph_nodata(self) -> None:
        """有编译图但没有一个实盘 .ets 落在归属面内：同样是数据不可得，补救指向 ownership。"""
        self._sourcemaps(["A", "B", "C"])
        self._write(self.bp / "ownership.json", json.dumps(
            {"version": 1, "owners": {"domain:alpha": ["features/alpha/**"]}, "mainloop_owned": []}))
        proc = self._run_gate()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        out = json.loads(proc.stdout)
        self.assertEqual(out["build_graph"]["nodata"], "no-owned-ets")
        self.assertEqual(out["build_graph"]["all_ets"], 3)
        self.assertIn("ownership.json", out["probe_hint"])


class TestSyncPagemap(unittest.TestCase):
    """K9：波尾路由收束脚本——发现/生成/断言三段（试点 P1-7 的 83 编译错固化）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-pagemap-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.pages = self.proj / "entry/src/main/ets/pages"

    def _write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _run(self, *extra: str) -> subprocess.CompletedProcess:
        self.proj.mkdir(parents=True, exist_ok=True)
        return subprocess.run(
            [sys.executable, str(SYNC_PAGEMAP), "--project", str(self.proj), "--json", *extra],
            capture_output=True, text=True, encoding="utf-8", timeout=120)

    def test_no_pages_dir_is_noop_pass(self) -> None:
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["builders"], 0)

    def test_generation_param_vs_zero_arg_and_idempotent(self) -> None:
        self._write(self.pages / "alpha/AlphaPage.ets",
                    "@Component struct AlphaPage {}\n"
                    "export @Builder function AlphaPageBuilder() { AlphaPage() }\n")
        self._write(self.pages / "beta/BetaPage.ets",
                    "export class BetaParam { id: number = 0 }\n"
                    "export @Builder function BetaPageBuilder(p: BetaParam) { Text('b') }\n")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        gen = (self.pages / "PageMapGen.ets").read_text(encoding="utf-8")
        self.assertIn("AlphaPageBuilder()", gen)                       # 零参不传参
        self.assertIn("BetaPageBuilder(param as BetaParam)", gen)      # 带参按声明类型转型
        self.assertIn("import { BetaParam } from './beta/BetaPage';", gen)   # E136：首参类型也 import
        self.assertIn("import { AlphaPageBuilder } from './alpha/AlphaPage';", gen)
        proc2 = self._run()                                            # 幂等重跑
        self.assertEqual(proc2.returncode, 0)
        self.assertEqual(gen, (self.pages / "PageMapGen.ets").read_text(encoding="utf-8"))

    def test_builder_with_return_fails(self) -> None:
        self._write(self.pages / "Bad.ets",
                    "export @Builder function BadPageBuilder() {\n"
                    "  if (true) { return }\n  Text('x')\n}\n")
        proc = self._run()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        out = json.loads(proc.stdout)
        self.assertTrue(any("return" in v["issue"] for v in out["violations"]))

    def test_unregistered_push_fails(self) -> None:
        self._write(self.pages / "A.ets",
                    "export @Builder function APageBuilder() { Text('a') }\n")
        self._write(self.proj / "entry/src/main/ets/common/Nav.ets",
                    "stack.pushPathByName('Nope', undefined)\n")
        proc = self._run()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("Nope", json.loads(proc.stdout)["unregistered_pushes"])


class TestParseAgentOutputFlags(unittest.TestCase):
    """K10 --raw-json + K1 FIELD_TABLE 单源（与校验器同文件互证）。"""

    def _run_parse(self, text: str, *extra: str) -> subprocess.CompletedProcess:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        tmp.write(text)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        return subprocess.run(
            [sys.executable, str(PARSE_AGENT), "--file", tmp.name, "--schema", "impl", *extra],
            capture_output=True, text=True, encoding="utf-8", timeout=60)

    def test_raw_json_mode(self) -> None:
        ok = self._run_parse(json.dumps(VALID_ALPHA), "--raw-json")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        bad = self._run_parse("[1, 2]", "--raw-json")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("顶层必须是对象", bad.stderr)

    def test_field_table_covers_all_schemas(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import parse_agent_output as pao
        for schema in pao.SCHEMAS:
            self.assertIn(schema, pao.FIELD_TABLE, schema)
        table = pao.render_field_table("fix")
        self.assertIn("纯字符串数组", table)          # 试点 fixed[] 类型未言明的根因治理
        self.assertIn("| domain |", table)
        tightened = pao.render_field_table("impl", extras=["source_summary_roles"])
        self.assertIn("必填（本任务收紧）", tightened)


class TestLintPlanRegistryFallback(KernelFixture):
    """K10：无 --registry 且无 $ARKTS_SKILL_DIR 时按 bundle 布局相对上探。"""

    def test_fallback_resolves_bundle_registry(self) -> None:
        self.write_plan(self.base_plan())
        env = dict(os.environ)
        env.pop("ARKTS_SKILL_DIR", None)
        proc = subprocess.run(
            [sys.executable, str(LINT_PLAN), "--plan", str(self.plan_path),
             "--blueprint", str(self.blueprint), "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj),
            env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)  # bundle 真身 registry 兜底


class TestPlanShapeAdditions(PlanFixture):
    """K5 audit:mainloop 对 + K6 契约段兜底（generate_waves/assemble_prompt 侧形状断言）。"""

    def test_mainloop_pair_generated_when_ownership_present(self) -> None:
        self._write(self.blueprint / "ownership.json", json.dumps({
            "version": 1, "owners": {
                "domain:alpha": ["features/alpha/**"],
                "domain:beta": ["features/beta/**"],
                "infra:core": ["common/**"],
                "seed:shell": ["entry/src/main/ets/app/**"],
            }, "mainloop_owned": ["entry/src/main/ets/pages/Index.ets"]}))
        self.gen("auditfix")
        plan = self.plan("auditfix")
        by_id = {t["id"]: t for t in plan["tasks"]}
        self.assertIn("audit:mainloop", by_id)
        self.assertEqual(by_id["fix:mainloop"]["parents"], ["audit:mainloop"])
        self.assertEqual(by_id["audit:mainloop"]["map_group"], "auditfix-audit")
        self.assertIn("entry/src/main/module.json5", by_id["audit:mainloop"]["ownership"])
        prompt = (self.proj / "spec/waves/prompts/auditfix/audit-mainloop.txt") \
            .read_text(encoding="utf-8")
        self.assertIn("Navigation 根内容非占位", prompt)
        self.assertIn('domain 字段固定填 "mainloop"', prompt)
        self.assertTrue(self.lint("auditfix")["ok"])

    def test_no_mainloop_ownership_skips_pair(self) -> None:
        proc = self.gen("auditfix")
        self.assertNotIn("audit:mainloop", [t["id"] for t in self.plan("auditfix")["tasks"]])
        self.assertIn("audit:mainloop", proc.stderr)   # 盲区未覆盖的显式告警

    def test_cheatsheet_fallback_when_no_depends_on_infra(self) -> None:
        # fixture 域全部无 depends_on_infra → 按 seed+infra 模块全集兜底注入（K6，防 ADJ-05 复发）
        proc = self.gen("domains")
        prompt = (self.proj / "spec/waves/prompts/domains/alpha.txt").read_text(encoding="utf-8")
        self.assertIn("INFRA CHEAT SHEET", prompt)
        self.assertIn("common/Seed.ets", prompt)
        self.assertIn("兜底注入", proc.stderr)


class TestPageSpecsTier(PlanFixture):
    """R2：spec.page_specs 档位——目录式域 spec + 页级生产要求 + pages 收紧（修订 R2）。"""

    def _enable(self, dir_form: bool = True) -> None:
        sf = "spec/domains/alpha/spec.md" if dir_form else "spec/domains/alpha.md"
        self._write(self.blueprint / "domain-map.json", json.dumps({
            "version": 1, "app": "demo", "domains": [
                {"key": "alpha", "title": "Alpha", "spec_file": sf,
                 "pages": ["page_0001_Main"]},
                {"key": "beta", "title": "Beta", "spec_file": "spec/domains/beta.md", "pages": []},
            ]}))
        wp = json.loads((self.blueprint / "workflow-params.json").read_text(encoding="utf-8"))
        wp["spec"] = {"page_specs": True}
        self._write(self.blueprint / "workflow-params.json", json.dumps(wp))

    def test_dir_form_produces_page_instructions_and_extras(self) -> None:
        self._enable(dir_form=True)
        self.gen("understand")
        plan = self.plan("understand")
        by_id = {t["id"]: t for t in plan["tasks"]}
        self.assertEqual(by_id["read:alpha"]["ownership"], ["spec/domains/alpha/**"])  # 整域目录单 glob
        self.assertEqual(by_id["read:alpha"].get("schema_required_extra"), ["pages"])  # pages 收紧
        self.assertNotIn("schema_required_extra", by_id["read:beta"])                  # 平铺域不收紧
        prompt = (self.proj / "spec/waves/prompts/understand/alpha.txt").read_text(encoding="utf-8")
        self.assertIn("spec/domains/alpha/pages", prompt)
        self.assertIn("page-spec-template.md", prompt)
        self.assertIn("摘要 pages 字段", prompt)

    def test_flat_form_skips_with_warning(self) -> None:
        self._enable(dir_form=False)
        proc = self.gen("understand")
        self.assertIn("非目录式", proc.stderr)
        plan = self.plan("understand")
        by_id = {t["id"]: t for t in plan["tasks"]}
        self.assertNotIn("schema_required_extra", by_id["read:alpha"])
        prompt = (self.proj / "spec/waves/prompts/understand/alpha.txt").read_text(encoding="utf-8")
        self.assertNotIn("page-spec-template.md", prompt)

    def test_domains_brief_includes_pages_when_present(self) -> None:
        self._enable(dir_form=True)
        self._write(self.proj / "spec/domains/alpha/pages/page_0001_Main.md", "# page spec\n")
        self.gen("domains")
        prompt = (self.proj / "spec/waves/prompts/domains/alpha.txt").read_text(encoding="utf-8")
        self.assertIn("本域页级 spec", prompt)
        self.assertIn("spec/domains/alpha/pages", prompt)


BUILD_DIGEST = SCRIPTS.parent.parent / "a2h-spec" / "scripts" / "build_common_digest.py"
LINT_BLUEPRINT = SCRIPTS.parent.parent / "a2h-plan" / "scripts" / "lint_blueprint.py"


class TestCommonDigest(unittest.TestCase):
    """消费信任协议 §2：名单机器规则 / 签名抽取 / 幂等（语义节保留）/ --apply 登记。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-digest-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.android = self.root / "android"
        self.bp = self.root / "proj" / "spec" / "blueprint"
        base = ("open class BaseAct : AppCompatActivity() {\n"
                "  fun showLoading(msg: String) {\n  }\n"
                "  private fun hidden() {\n  }\n"
                "}\n")
        self._write(self.android / "common/src/main/java/com/x/base/BaseAct.kt", base)
        self._write(self.android / "app/src/other/Rare.kt", "class Rare {\n}\n")
        files = {}
        for i, dom in enumerate(("alpha", "beta", "gamma")):
            p = f"app/src/main/java/com/x/{dom}/A{i}.kt"
            self._write(self.android / p,
                        "import com.x.base.BaseAct\nclass A%d : BaseAct() {\n}\n" % i)
            files[dom] = [p]
        files["beta"].append("app/src/beta2/B2.kt")
        self._write(self.android / "app/src/beta2/B2.kt",
                    "import com.x.other.Rare\nclass B2 {\n}\n")  # Rare 仅 1 域引用且非启发路径
        # Helper：非启发路径（shared 不在 base|common|util 词表），被 alpha/beta 两域引用——
        # 用于阈值边界测试（K=3 落选 / K=2 入选，不受启发并集干扰）
        self._write(self.android / "app/src/main/java/com/x/shared/Helper.kt",
                    "class Helper {\n  fun help(): String {\n  }\n}\n")
        for dom, i in (("alpha", 0), ("beta", 1)):
            p = self.android / f"app/src/main/java/com/x/{dom}/A{i}.kt"
            p.write_text(p.read_text(encoding="utf-8")
                         + "import com.x.shared.Helper\n", encoding="utf-8")
        self._write(self.android / "com/x/other/Rare2.kt", "class Rare2 {\n}\n")
        self._write(self.bp / "domain-map.json", json.dumps({
            "version": 1, "domains": [
                {"key": k, "spec_file": f"spec/domains/{k}.md", "android_files": v}
                for k, v in files.items()]}))
        self._write(self.bp / "contracts.json", json.dumps(
            {"version": 1, "modules": [], "wires": [], "deferred": [],
             "chains": [], "acceptance": []}))

    def _write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _run(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(BUILD_DIGEST), "--blueprint", str(self.bp),
             "--android-root", str(self.android), "--json", *extra],
            capture_output=True, text=True, encoding="utf-8", timeout=120)

    def test_list_rule_extraction_apply_and_idempotency(self) -> None:
        proc = self._run("--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["files"], ["common/src/main/java/com/x/base/BaseAct.kt"])  # K=3 命中；Rare 落选
        digest = (self.bp / "common-digest.md").read_text(encoding="utf-8")
        self.assertIn("class BaseAct : AppCompatActivity()", digest)
        self.assertIn("fun showLoading(msg: String)", digest)
        self.assertNotIn("hidden", digest)                       # private 不入 T1 节
        self.assertIn("## 语义注记", digest)
        contracts = json.loads((self.bp / "contracts.json").read_text(encoding="utf-8"))
        self.assertEqual(contracts["common_digest"]["files"], out["files"])  # --apply 登记

        # 幂等 + 语义节保留：A1 代理追加注记后重生成，机器节覆写、注记原样保留
        note = "- BaseAct.onCreate 会触发埋点上报（common/src/main/java/com/x/base/BaseAct.kt:2）\n"
        p = self.bp / "common-digest.md"
        p.write_text(digest.rstrip() + "\n" + note, encoding="utf-8")
        proc2 = self._run()
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        regen = p.read_text(encoding="utf-8")
        self.assertIn("BaseAct.onCreate 会触发埋点上报", regen)   # 语义注记保留
        self.assertIn("fun showLoading(msg: String)", regen)     # 机器节仍在

    def test_min_referrers_threshold(self) -> None:
        # K=3（缺省）：Helper 仅 2 域引用且非启发路径 → 落选（BaseAct 走启发并集仍在）
        out3 = json.loads(self._run().stdout)
        self.assertNotIn("app/src/main/java/com/x/shared/Helper.kt", out3["files"])
        # K=2：Helper 达阈入选
        out2 = json.loads(self._run("--min-referrers", "2").stdout)
        self.assertIn("app/src/main/java/com/x/shared/Helper.kt", out2["files"])


class TestTrustProtocolConsumption(PlanFixture):
    """消费信任协议 §3.1：摘要注入面 + 分级纪律句 + 「真值单源」废除。"""

    def _register_digest(self) -> None:
        self._write(self.proj / "spec/blueprint/common-digest.md",
                    "# 公共基座摘要（common-digest）\n\n## 机器抽取（T1）\n\n"
                    "### base/B.kt（被 3 个域依赖：alpha, beta, gamma）\n- `class B`\n\n"
                    "## 语义注记（T2）\n\n<!-- A1 -->\n")
        contracts = json.loads((self.blueprint / "contracts.json").read_text(encoding="utf-8"))
        contracts["common_digest"] = {"path": "spec/blueprint/common-digest.md",
                                      "files": ["base/B.kt"], "min_referrers": 3}
        self._write(self.blueprint / "contracts.json", json.dumps(contracts))

    def test_digest_injected_for_domains_not_understand(self) -> None:
        self._register_digest()
        self.gen("domains")
        prompt = (self.proj / "spec/waves/prompts/domains/alpha.txt").read_text(encoding="utf-8")
        self.assertIn("公共基座摘要（消费信任分级）", prompt)
        self.assertIn("class B", prompt)
        self.assertIn("禁回读其源文件", prompt)                  # T1（契约段头）
        self.assertIn("rereads[]", prompt)                       # T2/T3 申报通道
        self.assertNotIn("真值单源", prompt)                     # 过强声明已废除
        self.gen("understand")
        up = (self.proj / "spec/waves/prompts/understand/alpha.txt").read_text(encoding="utf-8")
        self.assertNotIn("公共基座摘要", up)                     # 裁决点 7：understand 不注入

    def test_registered_but_missing_digest_fails_assembly(self) -> None:
        contracts = json.loads((self.blueprint / "contracts.json").read_text(encoding="utf-8"))
        contracts["common_digest"] = {"path": "spec/blueprint/common-digest.md",
                                      "files": ["base/B.kt"]}
        self._write(self.blueprint / "contracts.json", json.dumps(contracts))
        proc = self.gen("domains", expect=1)                     # 登记悬空 → 组装硬 FAIL
        self.assertIn("common_digest", proc.stderr + proc.stdout)


class TestRereadsAccounting(KernelFixture):
    """消费信任协议 §3.2：rereads 申报校验 + journal 计数留痕 + 机械规范化兼容。"""

    def test_rereads_landed_and_counted(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("alpha", {**VALID_ALPHA, "rereads": ["app/src/a.kt", "app/src/b.kt"]})
        self.write_result("beta", {**VALID_BETA, "rereads": "app/src/c.kt"})  # 标量→K2 包裹
        out = self.land()
        self.assertEqual({r["id"]: r["status"] for r in out["landed"]},
                         {"impl:alpha": "OK", "impl:beta": "OK"})
        journal = json.loads((self.state.parent / "journal.json").read_text(encoding="utf-8"))
        counts = {r["task_id"]: r.get("rereads") for r in journal["operation_outputs"]
                  if r["kind"] == "agent"}
        self.assertEqual(counts["impl:alpha"], 2)
        self.assertEqual(counts["impl:beta"], 1)


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
