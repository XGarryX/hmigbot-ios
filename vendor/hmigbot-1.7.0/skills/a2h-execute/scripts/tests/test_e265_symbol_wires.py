# -*- coding: utf-8 -*-
"""E265⑦：符号接线边按**来源**分流判——机械抽取的（E260 `prefill:shared-holder`）未接即阻断；
spec 代理自由文本写的仍只呈报，并由 A3 出口闸 lint_blueprint B13 的 symbol 合法性判据在上游收口。

ds 实证：contracts.json 的 store 62 条里 11 条 symbol 根本不是标识符
（`state:intent:parameters`（VideoPlayActivity.Builder）`、`（无本域自有 key）`、`文件系统读写`、
`page:RefundProgressActivity`、`tag:cancel_btn` / `tag:agree_btn` …），verify_wires 永远 0/62，
交棒面只能降 warn 放行 = 质量不达标却没人拦。B13 回放在 ds 上抓出 22 条。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
SKILLS = SCRIPTS.parents[1]
LINT = SKILLS / "a2h-plan" / "scripts" / "lint_blueprint.py"
sys.path.insert(0, str(SCRIPTS))
import handoff_check as HC  # noqa: E402


def _w(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj, encoding="utf-8")


class TestB13SymbolLegality(unittest.TestCase):
    def _run(self, wires):
        with tempfile.TemporaryDirectory() as td:
            bp = Path(td) / "spec/blueprint"
            _w(bp / "contracts.json", {"version": 1, "modules": [], "wires": wires})
            _w(bp / "domain-map.json", {"version": 1, "domains": [{"key": "a", "spec_file": "spec/domains/a.md", "pages": [], "android_files": []},
                                                                  {"key": "b", "spec_file": "spec/domains/b.md", "pages": [], "android_files": []}]})
            _w(bp / "interface-prefill.json", {"version": 1, "domains": {}, "shared_state": [], "shared_holders": []})
            r = subprocess.run([sys.executable, str(LINT), "--blueprint", str(bp), "--json"], capture_output=True, text=True)
            rep = json.loads(r.stdout)
            c = next(x for x in rep["checks"] if x["id"] == "B13")
            return [m for m in (c.get("fails") or []) if "不是可核销符号" in str(m)]

    def test_legal_symbols_pass(self):
        ok = [{"kind": "store", "symbol": "AppContant", "consumer_domain": "a", "provider_domain": "b"},
              {"kind": "store", "symbol": "kv:read_agreement", "consumer_domain": "a", "provider_domain": "b"},
              {"kind": "event", "symbol": "event:PaySuccessEvent", "consumer_domain": "a", "provider_domain": "b"},
              {"kind": "store", "symbol": "com.x.AppConfig", "consumer_domain": "a", "provider_domain": "b"}]
        self.assertEqual(self._run(ok), [])

    def test_free_text_symbols_fail(self):
        bad = [{"kind": "store", "symbol": "state:intent:parameters`（VideoPlayActivity.Builder）", "consumer_domain": "a", "provider_domain": "b"},
               {"kind": "store", "symbol": "（无本域自有 key）", "consumer_domain": "a", "provider_domain": "b"},
               {"kind": "store", "symbol": "文件系统读写", "consumer_domain": "a", "provider_domain": "b"},
               {"kind": "event", "symbol": "tag:cancel_btn` / `tag:agree_btn", "consumer_domain": "a", "provider_domain": "b"}]
        self.assertEqual(len(self._run(bad)), 4)
        # nav-edge / service-call 不受这条判据管（它们的证据形态不同）
        self.assertEqual(self._run([{"kind": "service-call", "symbol": "随便写的描述", "consumer_domain": "a", "provider_domain": "b"}]), [])


class TestHandoffSharedHolders(unittest.TestCase):
    """机械抽取的持有者边（E260 `prefill:shared-holder`）未接 → blocked；自由文本那批仍只 warn。"""

    def _run(self, holders, by_kind):
        td = tempfile.TemporaryDirectory(prefix="a2h-e265-")
        self.addCleanup(td.cleanup)
        proj = Path(td.name) / "proj"
        _w(proj / "spec/blueprint/domain-map.json", {"version": 1, "domains": [{"key": "alpha"}]})
        _w(proj / "spec/blueprint/workflow-params.json", {"profile": "flagship", "gates": {"device_smoke": "off"}})
        _w(proj / "spec/reports/wires-check-final.json",
           {"wave": "final", "total": 1, "wired": 1, "counts": {}, "unwired": [],
            "symbol_wires": {"by_kind": by_kind, "unwired": [], "shared_holders": holders}})
        r = subprocess.run([sys.executable, str(SCRIPTS / "handoff_check.py"), "--project", str(proj),
                            "--blueprint", "spec/blueprint", "--json"],
                           capture_output=True, text=True, encoding="utf-8", cwd=str(proj), timeout=120)
        return json.loads(r.stdout)

    def test_unwired_holder_blocks(self):
        out = self._run([{"kind": "store", "symbol": "AppContant", "consumer_domain": "app-home",
                          "status": "multi-definition", "definitions": 2},
                         {"kind": "event", "symbol": "event:PaySuccessEvent", "consumer_domain": "app-mine",
                          "status": "wired"}],
                        {"store": {"wired": 0, "total": 62}, "event": {"wired": 56, "total": 63}})
        self.assertIn("shared-holders", out["blocked"])
        # 自由文本那批仍然只呈报，不阻断
        self.assertNotIn("symbol-wires", out["blocked"])

    def test_all_holders_wired_ok(self):
        out = self._run([{"kind": "store", "symbol": "AppContant", "consumer_domain": "app-home", "status": "wired"}],
                        {"store": {"wired": 62, "total": 62}})
        self.assertNotIn("shared-holders", out["blocked"])

    def test_no_holders_no_verdict(self):
        """旧工程（契约里没有机械抽取的持有者边）不因这条判据多出阻断项。"""
        out = self._run([], {"store": {"wired": 0, "total": 62}})
        self.assertNotIn("shared-holders", out["blocked"])


if __name__ == "__main__":
    unittest.main()
