"""DevEco-830 A8 + A3 回执可信核验回归。
立此闸的事实：830 落账链只信一行回执——「回执 OK、声明写了文件、文件不存在」一路过关（Opus 5 越界读正文手工抓出 6 次）；
`onHomeResume` 函数体只有 `return;` 却经 resolved_refs 标 resolved（症状 2/3）。
固定判据：A8 声明文件缺失 → RETRY_NEEDED（结构化不合格，走重试配额，不算 INFRA）；
A3 CLI 路径下 resolved_refs 必须 trigger 可验且成立、目标非 no-op，否则 rejected 留原状态；
body_is_noop：空体/只 return/只 return 字面量 → True；有语句 → False；A2H-NOOP 标记豁免；找不到定义 → None。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS)); sys.path.insert(0, str(SCRIPTS / "tests"))
import verify_handoffs as VH  # noqa: E402
import contract_sync as CS  # noqa: E402
from test_scheduler_kernel import KernelFixture  # noqa: E402


class TestNoop(unittest.TestCase):
    def test_body_is_noop(self):
        t = ("export class HomeBridges {\n  static onHomeResume(): void {\n    // FWD-REF: 等 user 域\n    return;\n  }\n"
             "  static fetchHomeTemplates() {}\n  static real(): void {\n    this.vm.load();\n  }\n"
             "  static legit(): boolean {\n    // A2H-NOOP: Android 本就空 override\n    return false;\n  }\n"
             "  static lit(): number { return 0; }\n}\n")
        self.assertTrue(VH.body_is_noop(t, "onHomeResume"))
        self.assertTrue(VH.body_is_noop(t, "fetchHomeTemplates"))
        self.assertFalse(VH.body_is_noop(t, "real"))
        self.assertFalse(VH.body_is_noop(t, "legit"))
        self.assertTrue(VH.body_is_noop(t, "lit"))
        self.assertIsNone(VH.body_is_noop(t, "missing"))

    def test_trigger_symbol_implemented_rejects_noop(self):
        corpus = [("entry/src/main/ets/x/HomeBridges.ets", "class A {\n  onHomeResume() {\n    return;\n  }\n  go() { this.x(); }\n}\n")]
        ok, why = VH._trigger_holds({"type": "symbol-implemented", "arg": "entry/src/main/ets/x/HomeBridges.ets#onHomeResume"}, corpus, Path("."))
        self.assertFalse(ok); self.assertIn("no-op", why)
        ok2, _ = VH._trigger_holds({"type": "symbol-implemented", "arg": "entry/src/main/ets/x/HomeBridges.ets#go"}, corpus, Path("."))
        self.assertTrue(ok2)


class TestApplyResolvedRefs(unittest.TestCase):
    def _contracts(self):
        return {"deferred": [
            {"id": "D-1", "kind": "forward-ref", "status": "registered",
             "location": {"file": "entry/src/main/ets/x/HomeBridges.ets", "anchor": "onHomeResume"},
             "trigger": {"type": "symbol-implemented", "arg": "entry/src/main/ets/x/HomeBridges.ets#onHomeResume"}},
            {"id": "D-2", "kind": "forward-ref", "status": "registered",
             "location": {"file": "entry/src/main/ets/x/HomeBridges.ets", "anchor": "go"},
             "trigger": {"type": "symbol-implemented", "arg": "entry/src/main/ets/x/HomeBridges.ets#go"}},
            {"id": "D-3", "kind": "forward-ref", "status": "registered",
             "location": {"file": "entry/src/main/ets/x/Other.ets", "anchor": "z"}, "trigger": "散文"},
        ]}

    def test_with_root_requires_assertion_and_non_noop(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); f = root / "entry/src/main/ets/x/HomeBridges.ets"; f.parent.mkdir(parents=True)
            f.write_text("class A {\n  onHomeResume() {\n    return;\n  }\n  go() { this.x(); }\n}\n", encoding="utf-8")
            (root / "entry/src/main/ets/x/Other.ets").write_text("class B { z() { this.y(); } }\n", encoding="utf-8")
            c = self._contracts()
            res = CS.apply_resolved_refs(c, [("D-1", "impl:a"), ("D-2", "impl:a"), ("D-3", "impl:a")], root=root)
            self.assertEqual([r["id"] for r in res["resolved"]], ["D-2"])
            self.assertEqual(sorted(r["id"] for r in res["rejected"]), ["D-1", "D-3"])
            self.assertEqual(c["deferred"][0]["status"], "registered")   # no-op 不翻
            self.assertEqual(c["deferred"][2]["status"], "registered")   # 无判据不翻

    def test_without_root_keeps_legacy_behavior(self):
        c = self._contracts()
        res = CS.apply_resolved_refs(c, [("D-1", "impl:a")])
        self.assertEqual([r["id"] for r in res["resolved"]], ["D-1"]); self.assertEqual(res["rejected"], [])


class TestDeclaredFiles(KernelFixture):
    def test_missing_declared_file_is_retry(self):
        self.write_plan(self.base_plan())
        self.next_batch()
        obj = {"task": "domain:alpha", "final_state": "PASS", "files": ["features/alpha/Ghost.ets"]}
        self.write_result("alpha", obj)
        (self.proj / "features/alpha/Ghost.ets").unlink()          # 夹具会 touch，这里故意删掉模拟假回执
        self.write_result("beta", {"task": "domain:beta", "final_state": "PASS", "files": ["features/beta/B.ets"]})
        out = self.land(expect=0)
        by = {r["id"]: r for r in out["landed"]}
        self.assertEqual(by["impl:alpha"]["status"], "RETRY_NEEDED", by["impl:alpha"])
        self.assertIn("FILES_MISSING", by["impl:alpha"]["error"])
        self.assertEqual(by["impl:beta"]["status"], "OK")
        st = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(next(t for t in st["waves"]["domains"]["tasks"] if t["id"] == "impl:alpha")["status"], "failed")


if __name__ == "__main__":
    unittest.main()
