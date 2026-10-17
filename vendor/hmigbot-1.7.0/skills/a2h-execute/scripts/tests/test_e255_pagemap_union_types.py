"""E255：页面 Builder 首参是联合 / 泛型 / 数组类型时，PageMapGen 把其中每个具名类型都 import（ds 主会话报：
`param: LoginRouteParam | undefined` 一个都不 import，PageMapGen 编译报找不到 LoginRouteParam）。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SYNC = Path(__file__).resolve().parent.parent / "sync_pagemap.py"


class TestUnionParamImports(unittest.TestCase):
    def test_union_generic_and_unresolved(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "proj"; pages = proj / "entry/src/main/ets/pages"
            feats = proj / "entry/src/main/ets/features/app-home"
            feats.mkdir(parents=True); pages.mkdir(parents=True)
            (feats / "Params.ets").write_text("export class LoginRouteParam { from: string = '' }\n"
                                              "export interface Row { id: string }\n", encoding="utf-8")
            (pages / "LoginPage.ets").write_text("@ComponentV2 struct LoginPage { build() {} }\n"
                                                 "export @Builder function LoginPageBuilder(param: LoginRouteParam | undefined) { LoginPage() }\n",
                                                 encoding="utf-8")
            (pages / "ListPage.ets").write_text("@ComponentV2 struct ListPage { build() {} }\n"
                                                "export @Builder function ListPageBuilder(rows: Array<Row> | Ghost) { ListPage() }\n",
                                                encoding="utf-8")
            r = subprocess.run([sys.executable, str(SYNC), "--project", str(proj), "--json"], capture_output=True, text=True, timeout=120)
            gen = (pages / "PageMapGen.ets").read_text(encoding="utf-8")
            self.assertIn("import { LoginRouteParam } from '../features/app-home/Params';", gen)
            self.assertIn("import { Row } from '../features/app-home/Params';", gen)
            self.assertIn("LoginPageBuilder(param as LoginRouteParam | undefined)", gen)
            out = json.loads(r.stdout)
            self.assertTrue(any("Ghost" in v.get("issue", "") for v in out.get("violations") or []), out)   # 找不到的类型照旧报违例


if __name__ == "__main__":
    unittest.main()
