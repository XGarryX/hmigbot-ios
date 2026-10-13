"""E253：编译图孤儿清单保留原大小写路径 + 分类（纯类型模块 / 只作类型引用 / 只被孤儿引用 / 完全无引用）；
纯类型模块不计覆盖率分母；派修单只收完全无引用的真孤儿。ds closeout：孤儿清单全是小写路径，主会话与修复代理去查了一轮
「大小写误判」；54 个孤儿里 21 个其实有人 import。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GATE_CHECK = Path(__file__).resolve().parent.parent / "gate_check.py"
ETS = "entry/src/main/ets"


def _w(p: Path, t: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(t, encoding="utf-8")


class TestOrphanKinds(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.proj = Path(tmp.name) / "proj"
        _w(self.proj / "spec/blueprint/ownership.json", json.dumps({"version": 1, "owners": {"domain:alpha": [ETS + "/**"]}, "mainloop_owned": []}))
        _w(self.proj / "build.log", "BUILD SUCCESSFUL in 3 s\n")
        files = {
            "pages/HomePage.ets": "import { Api } from '../features/Home/Api';\nimport { Cb } from '../features/Home/Callback';\n"
                                  "@ComponentV2 struct HomePage { cb?: Cb; build() { Text(Api.name()) } }\n",
            "features/Home/Api.ets": "export class Api { static name(): string { return 'x'; } }\n",
            "features/Home/Types.ets": "/** 纯类型 */\nexport interface Row { id: string }\nexport type Rows = Row[];\n",
            "features/Home/Callback.ets": "export interface Cb { on(): void }\nexport class CbImpl implements Cb { on(): void {} }\n",
            "features/Home/DeadRoot.ets": "import { DeadLeaf } from './DeadLeaf';\nexport class DeadRoot { f(): void { DeadLeaf.g(); } }\n",
            "features/Home/DeadLeaf.ets": "export class DeadLeaf { static g(): void {} }\n",
        }
        for rel, text in files.items():
            _w(self.proj / ETS / rel, text)
        compiled = ["pages/HomePage", "features/Home/Api"]
        _w(self.proj / "entry/build/default/cache/default/default@CompileArkTS/esmodule/debug/sourceMaps.map",
           json.dumps({"entry|entry|1.0.0|src/main/ets/%s.ts" % n: {"version": 3} for n in compiled}))

    def test_kinds_paths_denominator_and_tasks(self):
        r = subprocess.run([sys.executable, str(GATE_CHECK), "--state", "spec/state/state.json", "--gate", "compile#2",
                            "--build-log", "build.log", "--blueprint", "spec/blueprint", "--json"],
                           capture_output=True, text=True, cwd=str(self.proj), timeout=120)
        out = json.loads(r.stdout)
        g = out["build_graph"]
        kinds = {o["file"].rsplit("/", 1)[-1]: o["kind"] for o in g["orphans"]}
        self.assertEqual(kinds, {"Types.ets": "type-only", "Callback.ets": "type-ref-only",
                                 "DeadRoot.ets": "unreferenced", "DeadLeaf.ets": "orphan-referenced"})
        self.assertIn(ETS + "/features/Home/DeadRoot.ets", [o["file"] for o in g["orphans"]])      # 原大小写、工程相对
        self.assertEqual((g["owned"], g["type_only_excluded"]), (6, 1))
        self.assertAlmostEqual(g["ratio"], round(2 / 5, 4))                                          # 分母去掉纯类型模块
        tasks = json.loads((self.proj / "spec/reports/orphan-tasks.compile-2.json").read_text(encoding="utf-8"))["tasks"]
        self.assertEqual([t["files"] for t in tasks], [[ETS + "/features/Home/DeadRoot.ets"]])       # 只派真孤儿
        txt = (self.proj / "spec/reports/orphan-ets.compile-2.txt").read_text(encoding="utf-8")
        self.assertIn("features/Home/Types.ets\tdomain:alpha\ttype-only", txt)


if __name__ == "__main__":
    unittest.main()
