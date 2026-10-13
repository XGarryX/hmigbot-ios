#!/usr/bin/env python3
"""E163 回归：contract_sync 回写的 exports 签名口径与 --emit-exports 同源。

AIPPT_930 2026-09-17 15:14 实证：A3 `--apply-class1` 把 seed 文件登记为新模块时，class/interface/enum 这类
符号级条目写成 signature=null，出口 lint B7b 判「缺 symbol/signature」阻断审批；而 --emit-exports 对同一文件
输出 signature=符号名。三处对齐：纯增量补录、新模块自动登记、既有 null 签名的符号级条目机械补齐（幂等）。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import contract_sync as CS  # noqa: E402

ROUTER = """
export class AppRouter {
  static stack: NavPathStack = new NavPathStack()
  static push(name: string): void {}
  static back(): void {}
}
export class NoRouteParams {}
export class Routes {
  static Home: string = 'Home'
}
"""
HTTP = """
export class HttpCore {
  static request(url: string): Promise<string> { return Promise.resolve('') }
}
"""


def _w(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


def _b7b_ok(contracts):
    for m in contracts.get("modules") or []:
        for e in m.get("exports") or []:
            if not isinstance(e, dict) or not e.get("symbol") or not e.get("signature"):
                return False, (m.get("file"), e)
    return True, None


class ContractSyncSignatureParity(unittest.TestCase):
    def _ets(self, d: Path) -> Path:
        ets = d / "entry" / "src" / "main" / "ets"
        _w(ets / "common" / "Router.ets", ROUTER)
        _w(ets / "common" / "HttpCore.ets", HTTP)
        return ets

    def test_new_module_registration_has_symbol_level_signature(self):
        with tempfile.TemporaryDirectory() as d:
            ets = self._ets(Path(d))
            disk = CS.scan_ets_root(ets)
            contracts = {"modules": []}
            ownership = {"owners": {"seed": ["entry/src/main/ets/common/**"]}}
            rep = CS.reconcile(contracts, disk, ownership, apply_class1=True)
        ok, bad = _b7b_ok(contracts)
        self.assertTrue(ok, bad)
        router = next(m for m in contracts["modules"] if m["file"].endswith("Router.ets"))
        sigs = {e["symbol"]: e["signature"] for e in router["exports"]}
        self.assertEqual(sigs["AppRouter"], "AppRouter")
        self.assertEqual(sigs["Routes"], "Routes")
        self.assertEqual(sigs["AppRouter.back"], "static back(): void")
        self.assertEqual(rep["summary"]["class2"], 0)
        self.assertEqual(rep["summary"]["class3"], 0)

    def test_additive_export_has_symbol_level_signature(self):
        with tempfile.TemporaryDirectory() as d:
            ets = self._ets(Path(d))
            disk = CS.scan_ets_root(ets)
            contracts = {"modules": [{"file": "common/Router.ets", "owner": "seed", "status": "implemented",
                                      "exports": [{"symbol": "AppRouter.push",
                                                   "signature": "static push(name: string): void"}]}]}
            CS.reconcile(contracts, disk, {"owners": {}}, apply_class1=True)
        ok, bad = _b7b_ok(contracts)
        self.assertTrue(ok, bad)
        sigs = {e["symbol"]: e["signature"] for e in contracts["modules"][0]["exports"]}
        self.assertEqual(sigs["NoRouteParams"], "NoRouteParams")

    def test_legacy_null_signature_is_normalized_idempotently(self):
        with tempfile.TemporaryDirectory() as d:
            ets = self._ets(Path(d))
            disk = CS.scan_ets_root(ets)
            contracts = {"modules": [{"file": "common/HttpCore.ets", "owner": "seed", "status": "implemented",
                                      "exports": [{"symbol": "HttpCore", "signature": None, "notes": "old"},
                                                  {"symbol": "HttpCore.request",
                                                   "signature": "static request(url: string): Promise<string>"}]}]}
            rep1 = CS.reconcile(contracts, disk, {"owners": {}}, apply_class1=True)
            self.assertTrue(_b7b_ok(contracts)[0])
            e0 = contracts["modules"][0]["exports"][0]
            self.assertEqual(e0["signature"], "HttpCore")
            self.assertIn("符号级签名补齐", e0["notes"])
            kinds1 = [x.get("kind") for x in rep1["class1_additive"]]
            self.assertIn("sig_symbol_level", kinds1)
            # 第二次：已补齐，不再产 class1 条目、内容不变
            snap = [dict(e) for e in contracts["modules"][0]["exports"]]
            rep2 = CS.reconcile(contracts, disk, {"owners": {}}, apply_class1=True)
            self.assertEqual(contracts["modules"][0]["exports"], snap)
            self.assertNotIn("sig_symbol_level", [x.get("kind") for x in rep2["class1_additive"]])

    def test_report_only_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            ets = self._ets(Path(d))
            disk = CS.scan_ets_root(ets)
            contracts = {"modules": [{"file": "common/HttpCore.ets", "owner": "seed", "status": "implemented",
                                      "exports": [{"symbol": "HttpCore", "signature": None}]}]}
            rep = CS.reconcile(contracts, disk, {"owners": {}}, apply_class1=False)
        self.assertIsNone(contracts["modules"][0]["exports"][0]["signature"])
        self.assertEqual([x["action"] for x in rep["class1_additive"] if x.get("kind") == "sig_symbol_level"],
                         ["report-only"])

    def test_emit_exports_and_writeback_agree(self):
        with tempfile.TemporaryDirectory() as d:
            ets = self._ets(Path(d))
            emitted = {e["symbol"]: e["signature"]
                       for e in ({"symbol": s, "signature": r.get("signature") or s}
                                 for s, r in CS.extract_exports(ROUTER)["symbols"].items())}
            disk = CS.scan_ets_root(ets)
            contracts = {"modules": []}
            CS.reconcile(contracts, disk, {"owners": {"seed": ["entry/src/main/ets/common/**"]}}, apply_class1=True)
            router = next(m for m in contracts["modules"] if m["file"].endswith("Router.ets"))
            written = {e["symbol"]: e["signature"] for e in router["exports"]}
        for sym, sig in written.items():
            self.assertEqual(sig, emitted[sym], sym)


if __name__ == "__main__":
    unittest.main()
