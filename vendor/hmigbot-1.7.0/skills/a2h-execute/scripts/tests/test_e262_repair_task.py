# -*- coding: utf-8 -*-
"""E262 / E263 补漏小任务替代整任务重派：落账因机械可判的两类（static_runtime P0 / ui_form P1）判退时写
`<原任务书>.repair.txt`，重派由 next_batch 优先取它；深度浅页 / 主题回执仍走整任务重派。E263 把接线退回（WIRES_TODO_UNMET，ds 重派里占 32%）也接进这条路径，
处方直接用落账错误串同一份 `_how()`；并收紧成「只读本次判退那条检查的报告」，防上一轮旧 finding 混入。

依据 X-XXXII 真实代理对照：同一批 3 条 immersive-l3-top P1，整任务重派 1054 万 token / 92 请求，
补漏小任务 315 万 / 35 请求，两者都修到 0；且现行重派的派发行与首派逐字相同，退回原因根本没给代理。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import land_results  # noqa: E402
import next_batch  # noqa: E402
import repair_prompt  # noqa: E402
from test_land_static_theme_checks import make_project  # noqa: E402

CLI = SCRIPTS / "repair_prompt.py"
BRIEF = """# _redlines — 全 wave 公共红线

## 防污染（HARD CONSTRAINT）
安卓源码根：`/tmp/android`——只读这一份源码。

## 输出纪律
回执写到 result_path，最终消息只回一行 OK。

## 你的任务（wave=domains，域=d，页面块 p1/2）
（此处是整份 spec 分节，几千行，补漏任务书不应该带上）
%s
**本任务的沉浸式页**——每页都必须做 L3 前景避让：`.padding({ top: this.windowModel.windowTopPadding })`。

## 契约段（INFRA CHEAT SHEET）
（几万字节的契约表）
""" % ("填充行（整份 spec 分节）\n" * 900)


def _brief(root: Path, rel="spec/waves/prompts/domains/d-p1.txt") -> str:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(BRIEF, encoding="utf-8")
    return rel


def _node(rel, extra=None):
    n = {"id": "impl:d:p1", "schema": "domainImpl", "_variant": "p1", "prompt_file": rel,
         "result_path": "spec/waves/results/domains/d-p1.json",
         "ownership": ["entry/src/main/ets/pages/HomePage.ets", "entry/src/main/ets/services/**"]}
    n.update(extra or {})
    return n


class TestRepairPrompt(unittest.TestCase):
    def test_build_slices_head_and_form_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rel = _brief(root)
            rep_rel = "spec/reports/x.json"
            (root / rep_rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rep_rel).write_text(json.dumps({"findings": [
                {"code": "immersive-l3-top", "file": "entry/src/main/ets/pages/HomePage.ets", "line": 0,
                 "severity": "P1", "message": "沉浸式页 HomePage 没有顶部前景避让", "fix": "用 windowTopPadding"},
                {"code": "dialog-inline", "file": "entry/src/main/ets/pages/HomePage.ets", "line": 9,
                 "severity": "P2", "message": "条件内联", "fix": "—"}]}), encoding="utf-8")
            out = repair_prompt.build(root, rel, [rep_rel], "impl:d:p1", "spec/waves/results/domains/d-p1.json")
            self.assertTrue(out["ok"], out)
            self.assertEqual((out["findings"], out["codes"]), (1, ["immersive-l3-top"]))   # P2 不进
            self.assertEqual(out["out"], rel + ".repair.txt")
            txt = (root / out["out"]).read_text(encoding="utf-8")
            self.assertIn("防污染（HARD CONSTRAINT）", txt)                    # 红线头保留
            self.assertIn("本次是「补漏任务」（不是重做）", txt)
            self.assertIn("immersive-l3-top", txt)
            self.assertIn("用 windowTopPadding", txt)
            self.assertIn("windowTopPadding })", txt)                        # 标准写法段切进来了
            self.assertIn("spec/waves/results/domains/d-p1.json", txt)       # 回执写回原路径
            self.assertNotIn("填充行", txt)                                   # 整份 spec 分节不带
            self.assertLess(out["bytes"] * 3, len(BRIEF.encode("utf-8")))     # 显著小于原任务书

    def test_no_findings_exit_1(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rel = _brief(root)
            (root / "r.json").write_text(json.dumps({"findings": [{"severity": "P2", "code": "x"}]}), encoding="utf-8")
            r = subprocess.run([sys.executable, str(CLI), "--project", str(root), "--prompt", rel,
                                "--reports", "r.json", "--json"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertFalse(json.loads(r.stdout)["ok"])
            self.assertFalse((root / (rel + ".repair.txt")).is_file())


class TestLandResultsHook(unittest.TestCase):
    def _prep(self, td, gates=None):
        root = make_project(Path(td), gates=gates)
        rel = _brief(root)
        node = _node(rel)
        land_results._static_runtime_check(root, node, "impl:d:p1", ["entry/src/main/ets/pages/HomePage.ets"])
        return root, rel, node

    def test_static_runtime_retry_writes_repair(self):
        with tempfile.TemporaryDirectory() as td:
            root, rel, node = self._prep(td)
            out = land_results._write_repair(root, node, "impl:d:p1", None, "static_runtime")
            self.assertEqual(out, rel + ".repair.txt")
            txt = (root / out).read_text(encoding="utf-8")
            self.assertIn("module-init-runtime-dependency", txt)
            self.assertIn("static_runtime_lint.py", txt)                     # 自检命令
            # 深度 / 主题不走补漏；且会清掉残留
            self.assertEqual(land_results._write_repair(root, node, "impl:d:p1", None, "depth_shallow"), "")
            land_results._drop_repair(root, node)
            self.assertFalse((root / (rel + ".repair.txt")).is_file())

    def test_gate_off(self):
        with tempfile.TemporaryDirectory() as td:
            root, rel, node = self._prep(td, gates={"repair_task": False})
            self.assertEqual(land_results._write_repair(root, node, "impl:d:p1", None, "static_runtime"), "")
            self.assertFalse((root / (rel + ".repair.txt")).is_file())


class TestWireTodoRepair(unittest.TestCase):
    """E263：接线退回也走补漏路径。"""

    def _how(self, u):
        fp, tp, mod, cls = (list(u) + [None, None])[:4]
        return ("%s→%s（inline：在 %s 里 import 并按状态位渲染 `%s(...)` 组件）" % (fp, tp, fp, cls or tp)
                if mod == "inline" else "%s→%s（route：`this.navPathStack.pushPathByName('%s', 参数)`）" % (fp, tp, tp))

    def test_wire_report_then_repair_brief(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_project(Path(td))
            rel = _brief(root)
            node = _node(rel)
            unmet = [("HomePage", "MineFragmentPage", "route", None),
                     ("HomePage", "AppLoadDialogPage", "inline", "AppLoadDialog")]
            land_results._write_wire_report(root, "impl:d:p1", unmet, self._how)
            rep = json.loads((root / "spec/reports/wire-todo/land-impl_d_p1.json").read_text(encoding="utf-8"))
            self.assertEqual([f["code"] for f in rep["findings"]], ["wire-todo-unmet"] * 2)
            self.assertEqual(rep["findings"][0]["file"], "entry/src/main/ets/pages/HomePage.ets")
            out = land_results._write_repair(root, node, "impl:d:p1", None, "wire_todo")
            self.assertEqual(out, rel + ".repair.txt")
            txt = (root / out).read_text(encoding="utf-8")
            self.assertIn("MineFragmentPage", txt)
            self.assertIn("pushPathByName('MineFragmentPage', 参数)", txt)      # route 处方原文
            self.assertIn("import 并按状态位渲染", txt)                          # inline 处方原文
            self.assertIn("逐条回读被点名的 from 页", txt)                        # 接线专属自检段
            self.assertNotIn("ui_form_lint.py", txt)                          # 接线退回不给界面形态自检
            self.assertIn("static_runtime_lint.py", txt)

    def test_same_page_multiple_edges_all_kept(self):
        """ds 真数据回放抓到的缺陷：同一页上的多条边 code/file/line 全一样（line=0），
        按三元组去重会把第 2 条悄悄丢掉（5 条边只剩 2 条）；重复边本身要去重。"""
        with tempfile.TemporaryDirectory() as td:
            root = make_project(Path(td))
            rel = _brief(root)
            node = _node(rel)
            unmet = [("HomePage", "AppLoadDialogPage", "route", None),
                     ("HomePage", "PPTCreatingDialogPage", "route", None),
                     ("HomePage", "AppLoadDialogPage", "route", None),      # 完全重复 → 去掉
                     ("OtherPage", "FillPPTQueryDialogPage", "route", None)]
            land_results._write_wire_report(root, "impl:d:p1", unmet, self._how)
            rep = json.loads((root / "spec/reports/wire-todo/land-impl_d_p1.json").read_text(encoding="utf-8"))
            self.assertEqual(len(rep["findings"]), 3)                        # 重复边去掉一条
            out = land_results._write_repair(root, node, "impl:d:p1", None, "wire_todo")
            txt = (root / out).read_text(encoding="utf-8")
            self.assertEqual(txt.count("wire-todo-unmet"), 3)                # 同页两条边都在
            for tp in ("AppLoadDialogPage", "PPTCreatingDialogPage", "FillPPTQueryDialogPage"):
                self.assertIn(tp, txt)

    def test_only_own_report_is_read(self):
        """上一轮 ui_form 的旧报告不得混进本轮接线补漏清单。"""
        with tempfile.TemporaryDirectory() as td:
            root = make_project(Path(td))
            rel = _brief(root)
            node = _node(rel)
            stale = root / "spec/reports/ui-form/land-impl_d_p1.json"
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_text(json.dumps({"findings": [{"code": "dialog-page-mode", "severity": "P1", "line": 5,
                                                       "file": "entry/src/main/ets/pages/HomePage.ets",
                                                       "message": "上一轮的旧违规", "fix": "旧处方"}]}), encoding="utf-8")
            land_results._write_wire_report(root, "impl:d:p1", [("HomePage", "MineFragmentPage", "route", None)], self._how)
            out = land_results._write_repair(root, node, "impl:d:p1", None, "wire_todo")
            txt = (root / out).read_text(encoding="utf-8")
            self.assertIn("MineFragmentPage", txt)
            self.assertNotIn("上一轮的旧违规", txt)
            self.assertNotIn("dialog-page-mode", txt)


class TestDispatchPrefersRepair(unittest.TestCase):
    def test_batch_entry_order(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rel = _brief(root)
            t = {"id": "impl:d:p1", "agent": "a2h-domain-worker@2.1.0", "prompt_file": rel,
                 "result_path": "spec/waves/results/domains/d-p1.json"}
            e = next_batch.batch_entry(t, root)
            self.assertEqual(e["prompt_file"], rel)
            self.assertNotIn("mode", e)
            self.assertIn("任务书：", e["dispatch_prompt"])
            (root / (rel + ".repair.txt")).write_text("repair\n", encoding="utf-8")
            e = next_batch.batch_entry(t, root)
            self.assertEqual((e["prompt_file"], e["mode"]), (rel + ".repair.txt", "repair"))
            self.assertIn("补漏任务书：", e["dispatch_prompt"])
            self.assertIn("只改被点名的问题", e["dispatch_prompt"])
            # resume 仍优先于 repair（半成品要接着做，不是补漏）
            (root / (rel + ".resume.txt")).write_text("resume\n", encoding="utf-8")
            e = next_batch.batch_entry(t, root)
            self.assertEqual(e["prompt_file"], rel + ".resume.txt")
            self.assertNotIn("mode", e)


if __name__ == "__main__":
    unittest.main()
