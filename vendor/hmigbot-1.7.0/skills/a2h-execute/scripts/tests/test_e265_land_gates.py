#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E265 ③④：堵掉落账链里「质量不达标也放行」的两处缺口。

③ 落账期自检链第二次仍不合格，不再「落 OK 留痕」交波尾兜底——照常判 RETRY_EXHAUSTED，
  由 next_batch 走 escalate 停机呈报；journal 行记 selfcheck_left（剩余违规数，下一轮进展基线）
  与 quality_rework（返工材料）。补漏任务书按「配额未尽 或 本轮有进展」保留，两轮零进展则删掉。
  配额口径仍是「有效派发 = attempts − INFRA_FAIL 豁免」——平台事故不占质量配额（K7）。
④ 五个 gates 开关不得静默关闭：质量底线四项（depth_selfcheck / static_runtime_check /
  ui_form_check / theme_selfcheck）必须配 gates.<X>_off_reason 才关得掉，裸 false 按未关处理；
  关 / 拒关都在 journal 行、落账输出 JSON、wave-<w>.result.json 与收尾摘要里显形。

用法示例:
    python3 -m unittest test_e265_land_gates -v

输入:  复用 test_scheduler_kernel.KernelFixture 的合成工程（subprocess 黑盒跑真脚本）。
输出:  unittest 标准输出。无副作用（tempfile 目录用后即删）。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import land_results  # noqa: E402
from test_scheduler_kernel import KernelFixture, VALID_BETA, LAND_RESULTS  # noqa: E402

# 模块加载期触碰运行期单例 → static_runtime_lint 的 P0（module-init-runtime-dependency）。
# `export const x = new Y()` 是 --fix **不自动改**的那一档（E226），所以能稳定留在报告里当判退素材。
SVC_HEAD = """export class ApiService {
  constructor() { this.t = AppStorage.get<string>('token') ?? ''; }
}
"""
BAD_ONE = SVC_HEAD + "export const api = new ApiService();\n"
BAD_TWO = BAD_ONE + "export const api2 = new ApiService();\n"
CLEAN = SVC_HEAD + "export function makeApi(): ApiService { return new ApiService(); }\n"

ALPHA_FILE = "features/alpha/A.ets"
ALPHA_RESULT = {"task": "domain:alpha", "final_state": "PASS", "files": [ALPHA_FILE]}
ALPHA_PROMPT = """# _redlines — 全 wave 公共红线

## 防污染（HARD CONSTRAINT）
安卓源码根：`/tmp/android`——只读这一份源码。

## 你的任务（wave=domains，域=alpha）
（整份 spec 分节）

## 界面形态（本块页面的形态判定）
弹窗页用 DIALOG 模式。
"""


class LandGateFixture(KernelFixture):
    """alpha 写一个带 P0 的产物、beta 干净；每轮可换 alpha 的源码内容来调剩余违规条数。"""

    def setUp(self) -> None:
        super().setUp()
        self._write(self.proj / "spec/waves/prompts/domains/alpha.txt", ALPHA_PROMPT)

    def gates(self, **kw) -> None:
        self._write(self.blueprint / "workflow-params.json", json.dumps({"gates": kw}, ensure_ascii=False))

    def alpha_round(self, body: str) -> None:
        """一轮：写 alpha 源码（决定剩余 P0 条数）+ 交回执。"""
        self._write(self.proj / ALPHA_FILE, body)
        self.write_result("alpha", ALPHA_RESULT)

    def rows(self, tid: str) -> list:
        journal = json.loads((self.state.parent / "journal.json").read_text(encoding="utf-8"))
        return [r for r in journal["operation_outputs"] if r.get("task_id") == tid]

    def repair_book(self) -> Path:
        return self.proj / "spec/waves/prompts/domains/alpha.txt.repair.txt"

    def first_round(self, body: str = BAD_TWO) -> dict:
        """首派 → alpha 带 P0 回执 → 落账（应判 RETRY_NEEDED 并写补漏任务书）。"""
        self.write_plan(self.base_plan())
        self.next_batch()
        self.alpha_round(body)
        self.write_result("beta", VALID_BETA)
        return self.land()

    def second_round(self, body: str) -> dict:
        """重派 → 再交一份仍不合格的回执 → 落账。"""
        act = self.next_batch()
        self.assertEqual(act["action"], "dispatch", act)
        self.assertEqual([b["id"] for b in act["batch"]], ["impl:alpha"], act)
        self.alpha_round(body)
        return self.land()


class TestSecondFailureNoLongerLandsOk(LandGateFixture):
    """③ 第二次仍不合格 → 不再落 OK 留痕，判 RETRY_EXHAUSTED 并呈报返工。"""

    def test_first_retry_then_exhausted_not_ok(self) -> None:
        out1 = self.first_round(BAD_TWO)
        a1 = next(r for r in out1["landed"] if r["id"] == "impl:alpha")
        self.assertEqual(a1["status"], "RETRY_NEEDED")
        self.assertIn("STATIC_RUNTIME", a1["error"])
        self.assertTrue(self.repair_book().is_file())                 # E262 补漏任务书已写
        self.assertEqual(self.rows("impl:alpha")[-1]["selfcheck_left"], {"static_runtime": 2})

        out2 = self.second_round(BAD_TWO)                              # 一条没修
        a2 = next(r for r in out2["landed"] if r["id"] == "impl:alpha")
        self.assertEqual(a2["status"], "FAIL")                         # ← 旧行为是 "OK"（留痕放行）
        self.assertIn("不再落 OK 放行", a2["error"])
        self.assertEqual(self.state_task("impl:alpha")["status"], "failed")
        self.assertTrue(self.state_task("impl:alpha")["reason"].startswith("RETRY_EXHAUSTED"))

        row = self.rows("impl:alpha")[-1]
        self.assertEqual(row["status"], "FAIL")
        self.assertNotIn("static_runtime", row)      # 旧的「落 OK 留痕」字段已无（那条出口被删）
        rw = row["quality_rework"]
        self.assertEqual((rw["check"], rw["left"], rw["prev_left"], rw["progressed"]),
                         ("static_runtime", 2, 2, False))
        self.assertEqual([r["task"] for r in out2["quality_rework"]], ["impl:alpha"])
        self.assertIn("RETRY_EXHAUSTED", out2["quality_rework_hint"])

        # 拍①据此处置（不是默默往下跑）。E265③ 的 next_batch 侧接口已接上：判据换成「有没有进展」而不是
        # 「有没有配额」——本轮零进展但这是第一条 quality_rework 行，按「连续 2 轮零进展才升级」再放一轮；
        # 且 land 这一轮已把补漏任务书删掉（同一份清单代理看过一轮没动，再投没意义），这一轮走整份任务书。
        # 再来一轮零进展即 escalate，见 test_e265_quality_gate_repair.TestQualityReworkQuota。
        act = self.next_batch()
        self.assertEqual(act["action"], "dispatch", act)
        self.assertEqual([b["id"] for b in act["batch"]], ["impl:alpha"])
        self.assertFalse(self.repair_book().is_file())
        self.assertIs(act["quality_rework"]["impl:alpha"][-1]["progressed"], False)

    def test_clean_receipt_still_lands_ok(self) -> None:
        """护栏：改干净了照常落 OK，并清掉残留补漏任务书（不因本次收紧而误伤正常路径）。"""
        self.first_round(BAD_TWO)
        self.assertTrue(self.repair_book().is_file())
        out2 = self.second_round(CLEAN)
        self.assertEqual(next(r for r in out2["landed"] if r["id"] == "impl:alpha")["status"], "OK")
        self.assertFalse(self.repair_book().is_file())
        self.assertNotIn("quality_rework", out2)


class TestRepairProgressCriterion(LandGateFixture):
    """③ 进展判据：违规条数严格下降才算补漏有效果——有进展留补漏任务书，零进展删掉改整任务重派。"""

    def test_progress_keeps_repair_book(self) -> None:
        self.first_round(BAD_TWO)                 # 剩 2 条
        out2 = self.second_round(BAD_ONE)         # 修掉 1 条 → 仍不合格但在收敛
        a2 = next(r for r in out2["landed"] if r["id"] == "impl:alpha")
        self.assertEqual(a2["status"], "FAIL")
        rw = self.rows("impl:alpha")[-1]["quality_rework"]
        self.assertEqual((rw["left"], rw["prev_left"], rw["progressed"]), (1, 2, True))
        self.assertTrue(self.repair_book().is_file())          # 裁决放行后那一次重派照样走便宜路线
        self.assertTrue(rw["repair_prompt"])
        self.assertIn("补漏在收敛", a2["error"])

    def test_no_progress_drops_repair_book(self) -> None:
        self.first_round(BAD_TWO)
        out2 = self.second_round(BAD_TWO)         # 一条没修
        rw = self.rows("impl:alpha")[-1]["quality_rework"]
        self.assertFalse(rw["progressed"])
        self.assertIsNone(rw["repair_prompt"])
        self.assertFalse(self.repair_book().is_file())         # 同一份清单代理看过一轮没动，再投无意义
        self.assertIn("两轮无进展", next(r for r in out2["landed"] if r["id"] == "impl:alpha")["error"])

    def test_history_baseline_ignores_rows_without_left(self) -> None:
        """基线只认带 selfcheck_left 的行——INFRA_FAIL 等行不覆盖（那一轮没有质量信号）。"""
        journal = {"operation_outputs": [
            {"workflow_id": "domains", "kind": "agent", "task_id": "impl:alpha",
             "selfcheck_left": {"static_runtime": 5}},
            {"workflow_id": "domains", "kind": "agent", "task_id": "impl:alpha", "status": "INFRA_FAIL"},
            {"workflow_id": "other", "kind": "agent", "task_id": "impl:alpha",
             "selfcheck_left": {"static_runtime": 1}},          # 别的 wave 不串账
            {"workflow_id": "domains", "kind": "reduce", "task_id": "impl:alpha",
             "selfcheck_left": {"static_runtime": 9}},          # reduce 行不算
        ]}
        self.assertEqual(land_results.selfcheck_left_history(journal, "domains"),
                         {"impl:alpha": {"static_runtime": 5}})


class TestInfraFailNotCountedAsQualityQuota(LandGateFixture):
    """③ 配额口径：INFRA_FAIL 豁免的那次派发不算进质量配额（K7），别把平台事故当成「第二次不合格」。"""

    def test_infra_fail_round_does_not_exhaust_quota(self) -> None:
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("beta", VALID_BETA)
        proc = self._run(LAND_RESULTS, "--plan", str(self.plan_path), "--state", str(self.state),
                         "--infra-fail", "impl:alpha", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(json.loads(proc.stdout)["landed"][0]["status"], "INFRA_FAIL")

        act = self.next_batch()                                 # 豁免后配额未耗尽 → 续派
        self.assertEqual([b["id"] for b in act["batch"]], ["impl:alpha"], act)
        self.alpha_round(BAD_TWO)
        out = self.land()                                       # attempts=2 但 waived=1 → 有效 1/2
        a = next(r for r in out["landed"] if r["id"] == "impl:alpha")
        self.assertEqual(a["status"], "RETRY_NEEDED")           # 不是 FAIL：这才是质量上的第一次
        self.assertNotIn("quality_rework", out)

        out2 = self.second_round(BAD_TWO)                       # 质量上的第二次才判 exhausted
        a2 = next(r for r in out2["landed"] if r["id"] == "impl:alpha")
        self.assertEqual(a2["status"], "FAIL")
        self.assertEqual(self.rows("impl:alpha")[-1]["quality_rework"]["infra_waived"], 1)


class TestGateOffVisibility(LandGateFixture):
    """④ 开关关闭必须显形；质量底线四项无理由不得关。"""

    def test_quality_gate_off_without_reason_is_refused(self) -> None:
        self.gates(static_runtime_check=False)                  # 裸 false：想静默关掉
        out = self.first_round(BAD_TWO)
        a = next(r for r in out["landed"] if r["id"] == "impl:alpha")
        self.assertEqual(a["status"], "RETRY_NEEDED")           # 照常检查、照常判退
        row = self.rows("impl:alpha")[-1]
        self.assertTrue(any("不予关闭" in n for n in row["gates_off_refused"]), row)
        self.assertEqual([g["gate"] for g in out["gates_disabled"]["refused"]], ["static_runtime_check"])
        self.assertEqual(out["gates_disabled"]["off"], [])

    def test_quality_gate_off_with_reason_is_honored_and_recorded(self) -> None:
        self.gates(static_runtime_check=False,
                   static_runtime_check_off_reason="E0 基线臂：本轮只测 token，不跑静态核")
        out = self.first_round(BAD_TWO)
        a = next(r for r in out["landed"] if r["id"] == "impl:alpha")
        self.assertEqual(a["status"], "OK")                     # 带理由关掉 → 这条不再判退
        row = self.rows("impl:alpha")[-1]
        self.assertTrue(any("static_runtime_check=false 关闭" in n for n in row["gates_disabled"]), row)
        self.assertNotIn("gates_off_refused", row)
        off = out["gates_disabled"]["off"]
        self.assertEqual([g["gate"] for g in off], ["static_runtime_check"])
        self.assertIn("E0 基线臂", off[0]["reason"])
        # 波级汇总同样留痕（report_aggregate 的数据源；复盘时「零问题」与「没跑」可分）
        summary = json.loads((self.plan_path.parent / "wave-domains.result.json").read_text(encoding="utf-8"))
        self.assertIn("static_runtime_check", summary["gates_disabled"])

    def test_non_quality_repair_task_gate_off_is_honored_and_recorded(self) -> None:
        """repair_task 不是质量底线（关掉只是退回整任务重派，质量不降）——允许裸 false 关，但同样显形。"""
        self.gates(repair_task=False)
        out = self.first_round(BAD_TWO)
        a = next(r for r in out["landed"] if r["id"] == "impl:alpha")
        self.assertEqual(a["status"], "RETRY_NEEDED")
        self.assertFalse(self.repair_book().is_file())          # 不写补漏任务书 → 整任务重派
        row = self.rows("impl:alpha")[-1]
        self.assertTrue(any("补漏小任务改派" in n for n in row["gates_disabled"]), row)
        self.assertEqual([g["gate"] for g in out["gates_disabled"]["off"]], ["repair_task"])

    def test_summary_line_reports_disabled_and_rework(self) -> None:
        """收尾摘要（人读那行）里必须汇总本次被关掉的检查与须返工的任务，不能只躺在 JSON 里。"""
        self.gates(ui_form_check=False, ui_form_check_off_reason="本工程无 ui-forms.json",
                   static_runtime_check=False)                # 裸 false → 被拒、照常检查
        self.first_round(BAD_TWO)
        self.next_batch()
        self.alpha_round(BAD_TWO)
        proc = self._run(LAND_RESULTS, "--plan", str(self.plan_path), "--state", str(self.state), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        line = proc.stderr
        self.assertIn("质量不达标须返工 1 个", line)
        self.assertIn("gates.ui_form_check=false", line)
        self.assertIn("无理由关闭", line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
