# -*- coding: utf-8 -*-
"""E261 module-init-cycle-tdz：import 环 + 模块加载期求值 = 冷启 `ReferenceError: X is not initialized`。

固定判据——该响的响：环内 static 字段初始化读同环绑定（ds `CheckAppUtil.service = userApiService` 形；
AIPPT_0907 `new HarmonyWechatProviderAdapter()` 形）、顶层 const 读同环绑定、`class X extends Y` 的 Y 在环内；
不该响的不响：只在函数体/方法体里用（安全）、纯类型导入（编译期擦除不成环）、只作泛型实参（AIPPT_930 PreviewReuse 形）、
箭头体里构造（闭包不在加载期执行）、不在同一个环里的普通依赖。
--fix：单行 static 字段 → 私有后备字段 + 惰性 getter（类型取显式标注或 `new Y(...)` 的 Y）；被别处赋值 / 类型定不了 /
顶层 const 一律不改，留 finding。"""
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
ETS = "entry/src/main/ets/"

# 环①：Ext ↔ RetrofitFactory —— 复刻真崩溃（静态字段在加载期 new 同环模块的类）
FILES = {
    ETS + "net/Ext.ets": """import { RetrofitFactory } from './RetrofitFactory';
export class GsonCompat {
  parse(s: string): string { return s; }
}
export function ext(): string { return RetrofitFactory.gson.parse('x'); }
""",
    ETS + "net/RetrofitFactory.ets": """import { GsonCompat } from './Ext';
export class RetrofitFactory {
  static gson: GsonCompat = new GsonCompat();
}
""",
    # 环②：UserApiService ↔ CheckAppUtil —— 读的是同环模块导出的 const（ds 真隐患形）
    ETS + "net/UserApiService.ets": """import { CheckAppUtil } from './CheckAppUtil';
export class UserApiService {
  list(): string { return CheckAppUtil.tag(); }
}
export const userApiService: UserApiService = new UserApiService();
""",
    ETS + "net/CheckAppUtil.ets": """import { UserApiService, userApiService } from './UserApiService';
export class CheckAppUtil {
  private static readonly service: UserApiService = userApiService;
  static tag(): string { return 'x'; }
  static check(): string { return CheckAppUtil.service.list(); }
}
""",
    # 负例①：同环但只在方法体里用 —— 安全
    ETS + "safe/A.ets": """import { B } from './B';
export class A {
  go(): string { return B.name(); }
}
""",
    ETS + "safe/B.ets": """import { A } from './A';
export class B {
  static name(): string { return new A().go(); }
}
""",
    # 负例②：纯类型导入 —— 编译期擦除，不成环
    ETS + "typeonly/Impl.ets": """import type { Spec } from './Spec';
export class Impl {
  static seed: string = 'x';
  run(s: Spec): string { return 'y'; }
}
""",
    ETS + "typeonly/Spec.ets": """import { Impl } from './Impl';
export interface Spec { id: string }
export const seed: string = Impl.seed;
""",
    # 负例③：只作泛型实参（AIPPT_930 PreviewReuse 形）
    ETS + "generic/Reuse.ets": """import { PageParams } from './Page';
export class Reuse {
  private static listeners: Map<PageParams, (p: PageParams) => void> =
    new Map<PageParams, (p: PageParams) => void>();
  static add(p: PageParams): void { Reuse.listeners.set(p, (q: PageParams) => {}); }
}
""",
    ETS + "generic/Page.ets": """import { Reuse } from './Reuse';
export class PageParams { id: string = ''; }
export function open(p: PageParams): void { Reuse.add(p); }
""",
    # 负例④：箭头体里构造 —— 闭包不在加载期执行
    ETS + "lazy/Maker.ets": """import { Thing } from './Thing';
export const makeThing: () => Thing = () => new Thing();
export class Maker { static tag: string = 'm'; }
""",
    ETS + "lazy/Thing.ets": """import { Maker } from './Maker';
export class Thing { id: string = Maker.tag; }
""",
    # 正例③：顶层 const 读同环绑定（不自动改）+ class extends 同环基类
    ETS + "top/Base.ets": """import { REG } from './Reg';
export class Base { tag(): string { return REG; } }
export const BASE_NAME: string = 'base';
""",
    ETS + "top/Reg.ets": """import { Base, BASE_NAME } from './Base';
export const REG: string = BASE_NAME;
export class Sub extends Base { }
""",
}


def make_project(td: Path) -> Path:
    for rel, text in FILES.items():
        p = td / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return td


def _tdz(rep) -> dict:
    return {x["file"].split("/")[-1] + ":" + str(x["line"]): x
            for x in rep["findings"] if x["code"] == "module-init-cycle-tdz"}


class TestCycleTdz(unittest.TestCase):
    def test_hits_and_misses(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_project(Path(td))
            rep = SR.run_lint(root, module="entry")
            hits = _tdz(rep)
            self.assertEqual(sorted(hits), ["CheckAppUtil.ets:3", "Reg.ets:2", "Reg.ets:3", "RetrofitFactory.ets:3"])
            self.assertEqual(hits["RetrofitFactory.ets:3"]["severity"], "P0")
            self.assertEqual(hits["RetrofitFactory.ets:3"]["kind"], "runtime")
            self.assertIn("GsonCompat", hits["RetrofitFactory.ets:3"]["message"])
            self.assertIn("ReferenceError", hits["RetrofitFactory.ets:3"]["message"])
            self.assertIn("userApiService", hits["CheckAppUtil.ets:3"]["message"])
            self.assertIn("BASE_NAME", hits["Reg.ets:2"]["message"])         # 顶层 const 读同环绑定
            self.assertIn("Base", hits["Reg.ets:3"]["message"])              # extends 同环基类

    def test_cycles_exclude_type_only_and_generic_edges(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_project(Path(td))
            ctx = SR.ModuleContext(root, SR.collect_module_files(root, "entry"))
            cyc = {tuple(sorted(ctx.rel(x).split("/")[-1] for x in c)) for c in ctx.cycles()}
            self.assertIn(("Ext.ets", "RetrofitFactory.ets"), cyc)
            self.assertIn(("A.ets", "B.ets"), cyc)                            # 成环但加载期不读 → 无 finding
            self.assertNotIn(("Impl.ets", "Spec.ets"), cyc)                   # import type 不成运行期边
            self.assertNotIn(("Page.ets", "Reuse.ets"), cyc)                  # 只作泛型实参 → 不是按值使用

    def test_fix_static_field_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_project(Path(td))
            r = subprocess.run([sys.executable, str(CLI), "--project", str(root), "--module", "entry", "--fix", "--json"],
                               capture_output=True, text=True)
            rep = json.loads(r.stdout)
            fixed = {x["file"].split("/")[-1]: x for x in rep["fixed"] if x["code"] == "module-init-cycle-tdz"}
            self.assertEqual(sorted(fixed), ["CheckAppUtil.ets", "RetrofitFactory.ets"])
            src = (root / (ETS + "net/RetrofitFactory.ets")).read_text(encoding="utf-8")
            self.assertIn("private static _gson: GsonCompat | undefined = undefined;", src)
            self.assertIn("static get gson(): GsonCompat {", src)
            self.assertIn("RetrofitFactory._gson = new GsonCompat();", src)
            src2 = (root / (ETS + "net/CheckAppUtil.ets")).read_text(encoding="utf-8")
            self.assertIn("private static get service(): UserApiService {", src2)
            self.assertIn("CheckAppUtil._service = userApiService;", src2)
            left = _tdz(rep)
            self.assertEqual(sorted(left), ["Reg.ets:2", "Reg.ets:3"])        # 顶层 const / extends 不自动改
            # 幂等：再跑一次不再改
            r2 = subprocess.run([sys.executable, str(CLI), "--project", str(root), "--module", "entry", "--fix", "--json"],
                                capture_output=True, text=True)
            self.assertEqual([x for x in json.loads(r2.stdout)["fixed"] if x["code"] == "module-init-cycle-tdz"], [])

    def test_no_fix_when_assigned_elsewhere(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_project(Path(td))
            # AIPPT_0907 形：静态字段有 setter（别处赋值）→ 只报不改
            (root / (ETS + "net/RetrofitFactory.ets")).write_text(
                "import { GsonCompat } from './Ext';\n"
                "export class RetrofitFactory {\n"
                "  static gson: GsonCompat = new GsonCompat();\n"
                "  static register(g: GsonCompat): void { RetrofitFactory.gson = g; }\n}\n", encoding="utf-8")
            r = subprocess.run([sys.executable, str(CLI), "--project", str(root), "--module", "entry", "--fix", "--json"],
                               capture_output=True, text=True)
            rep = json.loads(r.stdout)
            self.assertNotIn("RetrofitFactory.ets", {x["file"].split("/")[-1] for x in rep["fixed"]})
            self.assertIn("RetrofitFactory.ets:3", _tdz(rep))


if __name__ == "__main__":
    unittest.main()
