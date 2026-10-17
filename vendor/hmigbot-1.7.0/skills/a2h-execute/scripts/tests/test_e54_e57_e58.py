"""E54 / E57 / E58 回归（AIPPT_0903 test4 收尾三补）。
E54：a3_finalize --op ownership 给域写权同时授予 features/<key>/** 与 components/<key>/**（CONTRACT §1 页面私有组件目录）。
E57：land_results OK 落账时核验任务书里「…缺失 → FAIL」点名的 spec 副产物是否存在——只报（side_products_missing）不判。
E58：handoff_check 按现算契约哈希对账全部 plan-*.json，失配 → contract-drift warn。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from test_scheduler_kernel import KernelFixture, VALID_ALPHA, VALID_BETA

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
A3 = SCRIPTS.parent.parent / "a2h-plan" / "scripts" / "a3_finalize.py"


class TestOwnershipDirs(KernelFixture):
    def test_domain_owner_gets_features_and_components(self):
        bp = self.blueprint
        self._write(bp / "domain-map.json", json.dumps({"version": 1, "domains": [{"key": "alpha", "spec_file": "spec/domains/alpha.md", "pages": ["AlphaActivity"]}]}))
        self._write(bp / "ownership.json", json.dumps({"version": 1, "owners": {"seed": ["entry/src/main/ets/common/**"]}, "mainloop_owned": []}))
        self._write(bp / "page-names.json", json.dumps({"version": 1, "domains": {"alpha": {"AlphaActivity": "AlphaPage"}}}))
        r = subprocess.run([sys.executable, str(A3), "--op", "ownership", "--blueprint", str(bp)], capture_output=True, text=True, cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        globs = json.loads((bp / "ownership.json").read_text(encoding="utf-8"))["owners"]["domain:alpha"]
        self.assertIn("entry/src/main/ets/features/alpha/**", globs); self.assertIn("entry/src/main/ets/components/alpha/**", globs)
        self.assertIn("entry/src/main/ets/pages/AlphaPage.ets", globs)


class TestCarveCore(KernelFixture):
    def test_parent_glob_narrowed_to_shared(self):
        import generate_waves as G
        own = ["entry/src/main/ets/pages/HomePage.ets", "entry/src/main/ets/features/home/**", "entry/src/main/ets/components/home/**"]
        used = {"entry/src/main/ets/pages/HomePage.ets", "entry/src/main/ets/components/home/HomePage/**"}
        self.assertEqual(G._carve_core(own, used), ["entry/src/main/ets/components/home/_shared/**", "entry/src/main/ets/features/home/**"])
        self.assertEqual(G._carve_core(["a/**"], set()), ["a/**"])


class TestSideProducts(KernelFixture):
    def test_missing_named_side_product_is_reported_not_retried(self):
        plan = self.base_plan(); self.write_plan(plan)
        pf = self.proj / plan["tasks"][0]["prompt_file"]
        self._write(pf, "任务书\n并把理解笔记落盘 spec/domains/alpha.source-notes.md（round-1 审计复用）。缺失 → FAIL。\n")
        self.next_batch(); self.write_result("alpha", VALID_ALPHA); self.write_result("beta", VALID_BETA, fenced=False)
        out = self.land()
        self.assertEqual({r["id"]: r["status"] for r in out["landed"]}, {"impl:alpha": "OK", "impl:beta": "OK"})   # 不 RETRY
        self.assertEqual(out["side_products_missing"], [{"task": "impl:alpha", "path": "spec/domains/alpha.source-notes.md"}])
        self._write(self.proj / "spec/domains/alpha.source-notes.md", "# notes\n")
        import handoff_check as H
        checks, facts = H.run_checks(self.proj, self.blueprint)
        self.assertEqual(next(c for c in checks if c["id"] == "side-products")["status"], "warn")   # journal 里已记欠账


class TestContractDrift(KernelFixture):
    def test_plan_hash_mismatch_reported(self):
        self.write_plan(self.base_plan())
        import handoff_check as H
        checks, facts = H.run_checks(self.proj, self.blueprint)
        self.assertEqual(next(c for c in checks if c["id"] == "contract-drift")["status"], "ok")
        self._write(self.blueprint / "ownership.json", json.dumps({"version": 1, "owners": {"seed": ["x/**"]}}))   # 计划生成后改契约
        checks, facts = H.run_checks(self.proj, self.blueprint)
        c = next(c for c in checks if c["id"] == "contract-drift")
        self.assertEqual(c["status"], "warn"); self.assertIn("plan-domains.json", c["detail"])
        self.assertIn("契约漂移", H.render_message(checks, facts))


if __name__ == "__main__":
    import unittest
    unittest.main()
