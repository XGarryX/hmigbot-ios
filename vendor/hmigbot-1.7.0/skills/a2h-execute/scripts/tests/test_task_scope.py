"""_task_scope.delegates_page_safearea（AIPPT_930 移植）：拆分域核心任务写权只有 features/components、
本身不写任何页面时，四层 safearea 申报（safearea_layers）由页面块承担，核心回执允许显式 []。
固定判据：页面块（impl:<域>:pN）、写权含 pages/、写权为空或宽泛（ets/** / **）、非 domainImpl schema 一律不得委托；
重入轮次 impl:rN:<域> 与首轮同判。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _task_scope import delegates_page_safearea  # noqa: E402


class ScopeTests(unittest.TestCase):
    def core(self, **kw):
        return dict(id="impl:home", schema="domainImpl",
                    ownership=["entry/src/main/ets/features/home/**", "entry/src/main/ets/components/home/**"], **kw)

    def test_core_delegates(self):
        self.assertTrue(delegates_page_safearea(self.core()))

    def test_page_block_does_not_delegate(self):
        t = self.core(); t["id"] = "impl:home:p1"
        self.assertFalse(delegates_page_safearea(t))

    def test_core_owning_page_cannot_delegate(self):
        t = self.core(); t["ownership"].append("entry/src/main/ets/pages/HomePage.ets")
        self.assertFalse(delegates_page_safearea(t))

    def test_unknown_or_broad_scope_cannot_delegate(self):
        for own in ([], ["entry/src/main/ets/**"], ["**"], [None]):
            t = self.core(); t["ownership"] = own
            self.assertFalse(delegates_page_safearea(t), own)

    def test_infra_schema_cannot_delegate(self):
        t = self.core(); t["schema"] = "infraImpl"
        self.assertFalse(delegates_page_safearea(t))

    def test_reentry_core_delegates(self):
        t = self.core(); t["id"] = "impl:r2:home"
        self.assertTrue(delegates_page_safearea(t))


if __name__ == "__main__":
    unittest.main()
