"""E25 页状态翻转回归：域 impl 落账时，把 page-names 里已有 pages/<hmos>.ets 产物的页置 converted。
立此闸的事实：state_update 的 op page 此前没有任何自动调用方——test3 83 页、DR_0903 1 页全程 pending，
报告「converted 0」是假象；DR_0903 主会话最后只能手跑 3 次 state_update 补账（X1 同类）。
固定判据：有产物的页 → converted + ets 工程相对路径 + domain；无产物的页不翻；无 page-names 的域不翻；只进不退。
"""
from __future__ import annotations

import json

from test_scheduler_kernel import KernelFixture


class TestPageStatusFlip(KernelFixture):
    def test_pages_with_artifact_flip_to_converted(self) -> None:
        self._write(self.blueprint / "domain-map.json", json.dumps({"version": 1, "domains": [
            {"key": "alpha", "pages": ["HomeActivity", "HomeActivity$Dlg", "CartActivity"]},
            {"key": "beta", "pages": ["ProfileActivity"]}]}))
        self._write(self.blueprint / "page-names.json", json.dumps({"domains": {
            "alpha": {"HomeActivity": "HomePage", "CartActivity": "CartPage"}}}))
        self._write(self.proj / "entry/src/main/ets/pages/HomePage.ets", "@Builder export function HomePageBuilder() {}\n")
        self._write(self.proj / "entry/src/main/ets/pages/ProfilePage.ets", "// beta 无 page-names 映射，不应被翻\n")
        self.write_plan(self.base_plan())
        self.next_batch()
        self.write_result("alpha", {"task": "domain:alpha", "final_state": "PASS",
                                    "files": ["entry/src/main/ets/pages/HomePage.ets"]})
        self.write_result("beta", {"task": "domain:beta", "final_state": "PASS", "files": []})
        self.land(expect=0)
        st = json.loads(self.state.read_text(encoding="utf-8"))
        pages = st.get("pages") or {}
        home = pages.get("HomeActivity")
        self.assertIsNotNone(home, pages)
        self.assertEqual(home["status"], "converted")
        self.assertEqual(home["domain"], "alpha")
        self.assertEqual(home["ets"], "entry/src/main/ets/pages/HomePage.ets")
        self.assertNotEqual((pages.get("CartActivity") or {}).get("status"), "converted")   # 无产物不翻
        self.assertNotIn("HomeActivity$Dlg", pages)                                       # 内嵌页不算页
        self.assertNotIn("ProfileActivity", pages)                                        # 无映射不翻
        self.assertEqual(st["domains"]["alpha"]["final_state"], "PASS")                    # 域账照旧

    def test_missing_blueprint_is_silent(self) -> None:
        self.write_plan(self.base_plan())                  # 夹具 domain-map 为 {}、无 page-names
        self.next_batch()
        self.write_result("alpha", {"task": "domain:alpha", "final_state": "PASS", "files": []})
        self.write_result("beta", {"task": "domain:beta", "final_state": "PASS", "files": []})
        out = self.land(expect=0)
        self.assertFalse(out.get("errors"), out)
        self.assertEqual(json.loads(self.state.read_text(encoding="utf-8")).get("pages") or {}, {})


if __name__ == "__main__":
    import unittest
    unittest.main()
