#!/usr/bin/env python3
"""hit_test_gate / resource_name_gate 判据回归（2026-08-26 装机事故驱动）。

固定两组事实：
  hit_test —— AIPPT 弹窗全按钮失灵原型必 FAIL；ant_arkts_0806 的条件式
  Block（视频控制条隐藏态）、纯 loading 遮罩、叶子组件必不报。
  resname —— AIPPT aiPptAppId「包装函数一跳 + 资源不存在 + 无登记」原型
  必 FAIL；存在的资源必 PASS；FWD-REF 登记的缺席必 WARN 不 FAIL。
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


def run_gate(script: str, project: Path) -> dict:
    out = project / "_det.json"
    subprocess.run([PY, str(SCRIPTS / script), "--project", str(project),
                    "--output-json", str(out)], capture_output=True)
    return json.loads(out.read_text(encoding="utf-8"))


def make_project(tmp: Path, ets: dict[str, str], strings: list[dict] | None = None,
                 rawfiles: list[str] = ()) -> Path:
    root = tmp / "proj"
    etsdir = root / "entry" / "src" / "main" / "ets" / "components"
    etsdir.mkdir(parents=True)
    for name, body in ets.items():
        (etsdir / name).write_text(body, encoding="utf-8")
    resdir = root / "entry" / "src" / "main" / "resources" / "base" / "element"
    resdir.mkdir(parents=True)
    (resdir / "string.json").write_text(
        json.dumps({"string": strings or []}), encoding="utf-8")
    rawdir = root / "entry" / "src" / "main" / "resources" / "rawfile"
    rawdir.mkdir(parents=True)
    for rf in rawfiles:
        (rawdir / rf).write_text("x", encoding="utf-8")
    return root


DIALOG_BLOCK = """
@Component
struct AgreementDialog {
  build() {
    Column() {
      Button('同意').onClick(() => {})
    }
    .hitTestBehavior(HitTestMode.Block)
  }
}
"""

LOADING_MASK = """
@Component
struct LoadingMask {
  build() {
    Column() { LoadingProgress(); Text('加载中') }
      .width('100%').height('100%')
      .hitTestBehavior(HitTestMode.Block)
  }
}
"""

CONDITIONAL_BLOCK = """
@Component
struct VideoControls {
  @Local showing: boolean = false
  build() {
    Column() { Button('play').onClick(() => {}) }
      .hitTestBehavior(this.showing ? HitTestMode.Transparent : HitTestMode.Block)
  }
}
"""

LEAF_BLOCK = """
@Component
struct Badge {
  build() {
    Image($r('app.media.dot')).hitTestBehavior(HitTestMode.Block)
  }
}
"""


VISIBLE_BLOCK = """
@ComponentV2
export struct ConfirmDialog {
  @Param isDialogVisible: boolean = false
  @Local dialogVisible: boolean = true
  build(): void {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        Button('取消').onClick((): void => { this.dialogVisible = false })
      }
      .hitTestBehavior(HitTestMode.Default)
    }
    .visibility(this.isDialogVisible && this.dialogVisible ? Visibility.Visible : Visibility.None)
    .hitTestBehavior(this.isDialogVisible && this.dialogVisible ? HitTestMode.Block : HitTestMode.None)
  }
}
"""

class HitTestGate(unittest.TestCase):
    def test_block_on_interactive_subtree_fails(self):
        with tempfile.TemporaryDirectory() as t:
            det = run_gate("hit_test_gate.py",
                           make_project(Path(t), {"A.ets": DIALOG_BLOCK}))
            self.assertFalse(det["passed"])
            self.assertEqual(det["findings"][0]["code"], "block-on-interactive-subtree")

    def test_legal_forms_do_not_fire(self):
        with tempfile.TemporaryDirectory() as t:
            det = run_gate("hit_test_gate.py", make_project(Path(t), {
                "Mask.ets": LOADING_MASK,
                "Video.ets": CONDITIONAL_BLOCK,
                "Badge.ets": LEAF_BLOCK,
            }))
            self.assertTrue(det["passed"])
            self.assertEqual(det["findings"], [])

    def test_visible_block_fails(self):
        """★2026-08-29 AIPPT 实锤：`visible ? Block : None`（**显示**时 Block）。
        与合法形态②（**隐藏**时 Block）只差分支位置，语义完全相反——
        旧闸把所有条件表达式一律豁免，于是 6 个弹窗按钮全死而闸全绿。"""
        with tempfile.TemporaryDirectory() as t:
            det = run_gate("hit_test_gate.py",
                           make_project(Path(t), {"ConfirmDialog.ets": VISIBLE_BLOCK}))
            self.assertFalse(det["passed"], "显示时 Block 必须 FAIL")
            f = det["findings"][0]
            self.assertEqual(f["code"], "block-on-interactive-subtree")
            self.assertIn("显示时", f["message"])

    def test_hidden_block_still_passes(self):
        """反向锁死：**隐藏**时 Block 是文档形态②，补判据后仍必须放行（防过度收紧）。"""
        with tempfile.TemporaryDirectory() as t:
            det = run_gate("hit_test_gate.py",
                           make_project(Path(t), {"Video.ets": CONDITIONAL_BLOCK}))
            self.assertTrue(det["passed"], "隐藏时 Block 被误伤了")

    def test_gate_and_probe_classify_identically(self):
        """★双件同判：闸的 block_verdict 与探针的 classify 必须对同一批形态给同一结论。

        两件分处 a2h-execute / arkts-visual-verify 两个 skill，语义各写了一份；
        本用例是它们唯一的单一事实源——判据分叉时这里先红。"""
        import importlib.util

        def load(path, name):
            spec = importlib.util.spec_from_file_location(name, path)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m

        gate = load(Path(__file__).resolve().parent.parent / "hit_test_gate.py", "_g")
        probe_p = (Path(__file__).resolve().parents[3]
                   / "arkts-visual-verify/scripts/hit_chain_probe.py")
        if not probe_p.is_file():
            self.skipTest(f"探针不在预期路径: {probe_p}")
        probe = load(probe_p, "_p")

        forms = [
            "HitTestMode.Block",
            "HitTestMode.Default",
            "HitTestMode.None",
            "HitTestMode.Transparent",
            "this.visible ? HitTestMode.Block : HitTestMode.None",
            "this.visible ? HitTestMode.None : HitTestMode.Block",
            "this.a && this.b ? HitTestMode.Block : HitTestMode.None",
            "this.f(x) ? HitTestMode.Block : HitTestMode.Default",
            "this.mode",
        ]
        for f in forms:
            with self.subTest(form=f):
                self.assertEqual(gate.block_verdict(f)[0], probe.classify(f)[0],
                                 f"判据分叉: {f}")


WRAPPER_SILENT = """
class AsmRes {
  static getBuildValue(context: Object, resourceName: string): string {
    try {
      return (context as R).resourceManager.getStringByNameSync(resourceName)
    } catch (error) { return '' }
  }
}
export function install(ctx: Object): void {
  const bad = AsmRes.getBuildValue(ctx, 'aiPptAppId')
  const ok = AsmRes.getBuildValue(ctx, 'app_name')
}
"""

REGISTERED_MISSING = """
// FWD-REF: resources/rawfile/special_thanks.csv 资产未随资源转换落盘，按 onError 分支降级
export async function load(ctx: Object): Promise<string> {
  const bytes = await (ctx as R).resourceManager.getRawFileContent('special_thanks.csv')
  return ''
}
"""


class ResourceNameGate(unittest.TestCase):
    def test_wrapper_one_hop_silent_missing_fails(self):
        with tempfile.TemporaryDirectory() as t:
            det = run_gate("resource_name_gate.py", make_project(
                Path(t), {"Asm.ets": WRAPPER_SILENT},
                strings=[{"name": "app_name", "value": "x"}]))
            fails = [f for f in det["findings"] if f["severity"] == "FAIL"]
            self.assertEqual(len(fails), 1)
            self.assertIn("aiPptAppId", fails[0]["message"])
            self.assertEqual(fails[0]["code"], "silent-missing-resource")

    def test_registered_missing_warns_not_fails(self):
        with tempfile.TemporaryDirectory() as t:
            det = run_gate("resource_name_gate.py", make_project(
                Path(t), {"Contrib.ets": REGISTERED_MISSING}))
            self.assertTrue(det["passed"])
            warns = [f for f in det["findings"] if f["severity"] == "WARN"]
            self.assertEqual(len(warns), 1)
            self.assertEqual(warns[0]["code"], "registered-missing-resource")

    def test_mention_in_plain_spec_md_is_not_registration(self):
        """全文 mention ≠ 登记：名字只出现在普通 spec md（如 slice worker 的
        待办指令）不豁免——webBridgeEncodeKey 实证形态，必须 FAIL。"""
        with tempfile.TemporaryDirectory() as t:
            root = make_project(Path(t), {"Asm.ets": WRAPPER_SILENT},
                                strings=[{"name": "app_name", "value": "x"}])
            worker = root / "spec" / "execution" / "slice-work"
            worker.mkdir(parents=True)
            (worker / "slice_08_worker.md").write_text(
                "closer must provide the local build resource aiPptAppId", encoding="utf-8")
            det = run_gate("resource_name_gate.py", root)
            fails = [f for f in det["findings"] if f["severity"] == "FAIL"]
            self.assertEqual(len(fails), 1)

    def test_structured_registry_is_registration(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_project(Path(t), {"Asm.ets": WRAPPER_SILENT},
                                strings=[{"name": "app_name", "value": "x"}])
            reg = root / "spec"
            reg.mkdir(parents=True, exist_ok=True)
            (reg / "placeholder-registry.md").write_text(
                "| P-S8-090 | aiPptAppId | 待供值 |", encoding="utf-8")
            det = run_gate("resource_name_gate.py", root)
            self.assertTrue(det["passed"])
            self.assertEqual([f["code"] for f in det["findings"]],
                             ["registered-missing-resource"])

    def test_empty_value_resource_warns(self):
        with tempfile.TemporaryDirectory() as t:
            det = run_gate("resource_name_gate.py", make_project(
                Path(t), {"Asm.ets": WRAPPER_SILENT},
                strings=[{"name": "app_name", "value": "x"},
                         {"name": "aiPptAppId", "value": ""}]))
            self.assertTrue(det["passed"])  # WARN-only，永不阻断
            self.assertIn("empty-value-resource",
                          [f["code"] for f in det["findings"]])

    def test_existing_resource_passes(self):
        with tempfile.TemporaryDirectory() as t:
            det = run_gate("resource_name_gate.py", make_project(
                Path(t),
                {"Ok.ets": "const s = ctx.resourceManager.getStringByNameSync('todo')\n"},
                strings=[{"name": "todo", "value": "To do"}]))
            self.assertTrue(det["passed"])
            self.assertEqual(det["findings"], [])


if __name__ == "__main__":
    unittest.main()
