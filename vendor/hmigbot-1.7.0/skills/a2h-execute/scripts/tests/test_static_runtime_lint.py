# -*- coding: utf-8 -*-
"""static_runtime_lint（AIPPT_930_token2 实装实证）：模块加载期触碰运行期单例（冷启 ReferenceError）、avoid-area px 当 vp
（首页顶部空白带）、float.json 与安卓 dimens 同名异值。固定判据：该响的响（顶层 const / static 字段 / 一跳链 / entryability
初始化符号 / 直接尺寸参数 / 赋值后作尺寸 / AppStorage 键跨文件），不该响的不响（惰性 getter / 函数内条件构造 / 延迟箭头 /
struct 实例字段 / px2vp 已包 / 从未作尺寸 / 无漂移）；--fix 只做安全变换且幂等，被别处赋值的 static 字段不改写，
顶层 export const 不改写。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import _static_runtime as SR  # noqa: E402

CLI = SCRIPTS / "static_runtime_lint.py"

FILES = {
    "entry/src/main/ets/services/ApiService.ets": """// comment with AppStorage in it
import { preferences } from '@kit.ArkData';
export class ApiService {
  private token: string = '';
  constructor() {
    this.token = AppStorage.get<string>('token') ?? '';
  }
  fetch(): string { return 'AppStorage' }
}
export const api = new ApiService();
export const lazyApi = () => new ApiService();
export class Holder {
  private static _l: ApiService | undefined = undefined;
  static get lazy(): ApiService {
    if (!Holder._l) { Holder._l = new ApiService(); }
    return Holder._l;
  }
}
""",
    "entry/src/main/ets/services/Repo.ets": """import { ApiService as Svc } from './ApiService';
export class Repo {
  private static readonly TAG = 'Repo';
  private static readonly instance: Svc = new Svc();
  private svc: Svc | undefined = undefined;
  init(): void {
    if (!this.svc) { this.svc = new Svc(); }
  }
}
""",
    "entry/src/main/ets/services/Plain.ets": """export class Plain {
  x: number = 0;
  constructor() { this.x = 1; }
}
export const plain = new Plain();
const m = new Map<string, number>();
""",
    "entry/src/main/ets/services/Chain.ets": """import { ApiService } from './ApiService';
export class Chain {
  api: ApiService;
  constructor() { this.api = new ApiService(); }
  static inst = new Chain();
}
""",
    "entry/src/main/ets/services/Direct.ets": """export class Ctx {
  static ctx = getContext();
}
""",
    "entry/src/main/ets/entryability/EntryAbility.ets": """import { BoxApplication } from '../services/Box';
export default class EntryAbility extends UIAbility {
  onCreate(): void {
    BoxApplication.context = this.context;
    RetrofitFactory.init(this.context);
  }
}
""",
    "entry/src/main/ets/services/Box.ets": """export class BoxApplication { static context: Context | undefined = undefined; }
class Box {
  c: Context | undefined;
  constructor() { this.c = BoxApplication.context; }
}
export const box = new Box();
class Rf { constructor() { const r = RetrofitFactory.instance; } }
export default new Rf();
""",
    "entry/src/main/ets/pages/HomePage.ets": """import { window } from '@kit.ArkUI';
@Entry @ComponentV2 struct HomePage {
  @Local topH: number = 0;
  private svc = new ApiService();
  aboutToAppear(): void {
    const win = window.getLastWindow(getContext(this));
    const area = win.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM);
    this.topH = area.topRect.height;
  }
  build() {
    Column() { Text('hi') }
      .padding({ top: this.topH })
  }
}
""",
    "entry/src/main/ets/pages/GoodPage.ets": """@Entry @ComponentV2 struct GoodPage {
  @Local topH: number = 0;
  aboutToAppear(): void {
    const area = win.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM);
    this.topH = px2vp(area.topRect.height);
    this.rawPx = area.bottomRect.height;
  }
  build() { Column().padding({ top: this.topH }).height(px2vp(this.rawPx)) }
}
""",
    "entry/src/main/ets/pages/DirectPage.ets": """@Entry @ComponentV2 struct DirectPage {
  build() {
    Column()
      .padding({ top: this.area.topRect.height, bottom: 0 })
      .width(win.getWindowProperties().windowRect.width)
  }
}
""",
    "entry/src/main/ets/pages/StorePage.ets": """struct StorePage {
  aboutToAppear(): void {
    const area = win.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM);
    AppStorage.setOrCreate('statusH', area.topRect.height);
    Text($r('app.float.margin_big')).height($r('app.float.margin_small'))
  }
}
""",
    "entry/src/main/ets/pages/StoreUse.ets": """struct StoreUse {
  @StorageProp('statusH') sh: number = 0;
  build() { Column().margin({ top: this.sh }) }
}
""",
    "spec/baseline/android-literals.json": json.dumps(
        {"values_map": {"dimens": {"margin_big": "24dp", "margin_small": "8dp", "unused": "3dp"}}}),
    "entry/src/main/resources/base/element/float.json": json.dumps(
        {"float": [{"name": "margin_big", "value": "16vp"}, {"name": "margin_small", "value": "8vp"}]}, indent=2),
}


def make_project(td: Path, extra=None) -> Path:
    for rel, text in dict(FILES, **(extra or {})).items():
        p = td / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    # 跳过目录
    (td / "entry/src/main/ets/__probe").mkdir(parents=True, exist_ok=True)
    (td / "entry/src/main/ets/__probe/P.ets").write_text("export const p = new Bad();\nclass Bad { constructor() { AppStorage.get('x') } }\n", encoding="utf-8")
    return td


def cli(td: Path, *args):
    proc = subprocess.run([sys.executable, str(CLI), "--project", str(td), "--json"] + list(args),
                          capture_output=True, text=True)
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else None), proc.stderr


def by_code(rep: dict) -> dict:
    out = {}
    for f in rep["findings"]:
        out.setdefault(f["code"], []).append((f["file"].rsplit("/", 1)[-1], f["line"]))
    return out


class TestStrip(unittest.TestCase):
    def test_strip_keeps_length_and_lines(self):
        src = "a = 'AppStorage'; // AppStorage\n/* x\n y */ b = `t ${c}`\n"
        out = SR.strip_code(src)
        self.assertEqual(len(out), len(src))
        self.assertEqual(out.count("\n"), src.count("\n"))
        self.assertNotIn("AppStorage", out)
        self.assertIn("a = '", out)


class TestLint(unittest.TestCase):
    def test_true_positives_and_negatives(self):
        with tempfile.TemporaryDirectory() as td:
            td = make_project(Path(td))
            rc, rep, err = cli(td)
            self.assertEqual(rc, 1, err)
            self.assertFalse(rep["ok"])
            self.assertEqual(rep["scanned"], 12)   # __probe 跳过
            self.assertEqual(rep["counts"], {"module-init-runtime-dependency": 6, "avoid-area-px-as-vp": 3,
                                             "dimen-binding-literal-drift": 1}, rep["findings"])
            got = by_code(rep)
            self.assertEqual(sorted(got["module-init-runtime-dependency"]), sorted([
                ("ApiService.ets", 10),   # 顶层 export const = new（构造函数触碰 AppStorage）
                ("Box.ets", 6),           # 构造函数读 entryability 赋值的 BoxApplication.context
                ("Box.ets", 8),           # export default new Rf()：RetrofitFactory.instance（entryability init）
                ("Chain.ets", 5),         # static 字段，一跳链 Chain → ApiService
                ("Repo.ets", 4),          # static 字段，别名 import
                ("Direct.ets", 2),        # static 右值直接 getContext()
            ]))
            self.assertEqual(sorted(got["avoid-area-px-as-vp"]),
                             sorted([("DirectPage.ets", 3), ("HomePage.ets", 8), ("StorePage.ets", 4)]))
            self.assertEqual(got["dimen-binding-literal-drift"], [("float.json", 4)])   # indent=2 的 "name" 行
            files = {f["file"].rsplit("/", 1)[-1] for f in rep["findings"]}
            for neg in ("Plain.ets", "GoodPage.ets", "StoreUse.ets", "EntryAbility.ets", "P.ets"):
                self.assertNotIn(neg, files)
            home = [f for f in rep["findings"] if f["file"].endswith("HomePage.ets")]
            self.assertEqual(len(home), 1)   # struct 实例字段 `private svc = new ApiService()` 不判
            self.assertIn("HomePage.ets:11", home[0]["message"])   # 使用处（语句起始行 = Column() 链首行）
            store = [f for f in rep["findings"] if f["file"].endswith("StorePage.ets")][0]
            self.assertIn("StoreUse.ets:3", store["message"])
            shape = rep["findings"][0]
            self.assertEqual(sorted(shape), ["code", "file", "fix", "kind", "line", "message", "severity"])
            sev = {f["code"]: (f["severity"], f["kind"]) for f in rep["findings"]}
            self.assertEqual(sev, {"module-init-runtime-dependency": ("P0", "runtime"),
                                   "avoid-area-px-as-vp": ("P1", "visual"),
                                   "dimen-binding-literal-drift": ("P2", "visual")})

    def test_files_filter_out_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            td = make_project(Path(td))
            rc, rep, _ = cli(td, "--files", "entry/src/main/ets/pages/HomePage.ets,entry/src/main/ets/pages/Nope.ets",
                             "--out", "spec/reports/srl.json")
            self.assertEqual(rc, 1)
            self.assertEqual(rep["scanned"], 1)
            self.assertEqual(rep["counts"], {"avoid-area-px-as-vp": 1})
            self.assertTrue((td / "spec/reports/srl.json").is_file())
            rc, rep, _ = cli(td, "--files", "entry/src/main/ets/pages/GoodPage.ets")
            self.assertEqual((rc, rep["ok"], rep["findings"]), (0, True, []))
            proc = subprocess.run([sys.executable, str(CLI), "--project", str(td / "nonexistent")], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2)
            # 无 android-literals → 不判漂移
            (td / "spec/baseline/android-literals.json").unlink()
            rc, rep, _ = cli(td, "--files", "entry/src/main/ets/pages/StorePage.ets")
            self.assertNotIn("dimen-binding-literal-drift", rep["counts"])

    def test_fix_transforms_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            td = make_project(Path(td))
            rc, rep, err = cli(td, "--fix")
            self.assertEqual(rc, 1, err)
            fixed = {(x["code"], x["file"].rsplit("/", 1)[-1], x["line"]) for x in rep["fixed"]}
            self.assertEqual(fixed, {
                ("module-init-runtime-dependency", "Chain.ets", 5),
                ("module-init-runtime-dependency", "Repo.ets", 4),
                ("avoid-area-px-as-vp", "DirectPage.ets", 3),
                ("avoid-area-px-as-vp", "HomePage.ets", 8),
                ("avoid-area-px-as-vp", "StorePage.ets", 4),
            })
            # 剩余：顶层 export const / export default（不自动改）+ static 右值直接标记 + 漂移
            self.assertEqual(rep["counts"], {"module-init-runtime-dependency": 4, "dimen-binding-literal-drift": 1})
            repo = (td / "entry/src/main/ets/services/Repo.ets").read_text(encoding="utf-8")
            self.assertIn("private static _instance: Svc | undefined = undefined;", repo)
            self.assertIn("private static get instance(): Svc {", repo)
            self.assertIn("Repo._instance = new Svc();", repo)
            self.assertNotIn("static readonly instance", repo)
            chain = (td / "entry/src/main/ets/services/Chain.ets").read_text(encoding="utf-8")
            self.assertIn("static get inst(): Chain {", chain)
            self.assertIn("if (!Chain._inst) {", chain)
            home = (td / "entry/src/main/ets/pages/HomePage.ets").read_text(encoding="utf-8")
            self.assertIn("this.topH = px2vp(area.topRect.height);", home)
            direct = (td / "entry/src/main/ets/pages/DirectPage.ets").read_text(encoding="utf-8")
            self.assertIn(".padding({ top: px2vp(this.area.topRect.height), bottom: 0 })", direct)
            self.assertIn(".width(px2vp(win.getWindowProperties().windowRect.width))", direct)
            store = (td / "entry/src/main/ets/pages/StorePage.ets").read_text(encoding="utf-8")
            self.assertIn("AppStorage.setOrCreate('statusH', px2vp(area.topRect.height));", store)
            api = (td / "entry/src/main/ets/services/ApiService.ets").read_text(encoding="utf-8")
            self.assertIn("export const api = new ApiService();", api)   # 顶层不改
            # 幂等：第二次 --fix 零改动、结果相同
            rc2, rep2, _ = cli(td, "--fix")
            self.assertEqual((rc2, rep2["fixed"], rep2["counts"]), (1, [], rep["counts"]))

    def test_fix_guard_field_assigned_elsewhere(self):
        with tempfile.TemporaryDirectory() as td:
            td = make_project(Path(td), extra={
                "entry/src/main/ets/services/Reset.ets": "import { Chain } from './Chain';\nexport function reset(): void {\n  Chain.inst = new Chain();\n}\n"})
            rc, rep, _ = cli(td, "--fix")
            fixed_files = {x["file"].rsplit("/", 1)[-1] for x in rep["fixed"]}
            self.assertNotIn("Chain.ets", fixed_files)
            self.assertIn("Repo.ets", fixed_files)
            self.assertIn("  static inst = new Chain();", (td / "entry/src/main/ets/services/Chain.ets").read_text(encoding="utf-8"))
            self.assertIn(("Chain.ets", 5), by_code(rep)["module-init-runtime-dependency"])   # 仍是 finding

    def test_no_fix_flag_leaves_files_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            td = make_project(Path(td))
            before = {p: p.read_text(encoding="utf-8") for p in (td / "entry").rglob("*.ets")}
            rc, rep, _ = cli(td)
            self.assertNotIn("fixed", rep)
            self.assertEqual(before, {p: p.read_text(encoding="utf-8") for p in (td / "entry").rglob("*.ets")})


if __name__ == "__main__":
    unittest.main()
