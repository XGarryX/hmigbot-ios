"""E59 回归：workflow-params.gates 是运行期旋钮，不进契约哈希；其它键仍进。
立此闸的事实：AIPPT_0903 test4（2026-09-05）仅加 gates.unattended，plan-closure 在 lint 上即 MISMATCH——与 E34–E36 的声明相悖。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import _wavelib as W  # noqa: E402


class TestGatesNotHashed(unittest.TestCase):
    def test_gates_change_keeps_hash_other_keys_change_it(self):
        with tempfile.TemporaryDirectory() as td:
            bp = Path(td)
            for name in W.CONTRACT_FILES:
                (bp / name).write_text("{}" if name.endswith(".json") else "# x\n", encoding="utf-8")
            wp = bp / "workflow-params.json"
            wp.write_text(json.dumps({"waves": {"domains": {"max_parallel": 11}}, "gates": {"dispatch_burst": 4}}), encoding="utf-8")
            h1 = W.compute_contract_hash(bp, [])
            wp.write_text(json.dumps({"gates": {"dispatch_burst": 2, "unattended": True, "max_in_flight": 4}, "waves": {"domains": {"max_parallel": 11}}}, indent=2), encoding="utf-8")
            self.assertEqual(W.compute_contract_hash(bp, []), h1)                                   # 旋钮 + 键序 + 缩进都不算变
            wp.write_text(json.dumps({"waves": {"domains": {"max_parallel": 6}}, "gates": {"dispatch_burst": 4}}), encoding="utf-8")
            self.assertNotEqual(W.compute_contract_hash(bp, []), h1)                                # 契约内容变了
            (bp / "ownership.json").write_text(json.dumps({"owners": {"seed": []}}), encoding="utf-8")
            self.assertNotEqual(W.compute_contract_hash(bp, []), h1)

    def test_contracts_deferred_ledger_not_hashed(self):
        """E65：contracts.json#deferred 是运行期账面（追加 / status 改 resolved），不进哈希；modules/wires 仍进。"""
        with tempfile.TemporaryDirectory() as td:
            bp = Path(td)
            for name in W.CONTRACT_FILES:
                (bp / name).write_text("{}" if name.endswith(".json") else "# x\n", encoding="utf-8")
            c = bp / "contracts.json"
            c.write_text(json.dumps({"version": 1, "modules": [{"id": "m1"}], "deferred": [{"id": "P-1", "status": "registered"}]}), encoding="utf-8")
            h1 = W.compute_contract_hash(bp, [])
            c.write_text(json.dumps({"version": 1, "modules": [{"id": "m1"}], "deferred": [{"id": "P-1", "status": "resolved"}, {"id": "P-2", "status": "registered"}]}), encoding="utf-8")
            self.assertEqual(W.compute_contract_hash(bp, []), h1)
            c.write_text(json.dumps({"version": 1, "modules": [{"id": "m1"}, {"id": "m2"}], "deferred": []}), encoding="utf-8")
            self.assertNotEqual(W.compute_contract_hash(bp, []), h1)


if __name__ == "__main__":
    unittest.main()
