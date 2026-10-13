#!/usr/bin/env python3
"""任务 id → owner_domain 推导回归（AIPPT_915_test3 2026-09-01 实证驱动）。

事故：closure 波的任务 id 是三段式 `closure:r1:domain:common-common`（r<N> 是我加 closure
波时为防撞账引入的轮次段）。而 _task_to_domain 只 split(':', 1) 剥一次，剩下
'r1:domain:common-common'，冒号未消，_OWNER_DOMAIN_RE 不匹配 → deferred 申报被判
「owner_domain 'r1:domain:common-common' 不合法」整条拒收：

    deferred-merge: 输入=1 登记=0 去重=0 拒绝=1 台账=162 → REJECTED

加轮次段时没顾到「下游从任务 id 反推域名」这条路径。改为逐段剥离取末段。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import contract_sync as C  # noqa: E402


class TestTaskToDomain(unittest.TestCase):
    def test_closure_three_segment_id(self):
        """事故复刻：轮次段必须被剥掉。"""
        self.assertEqual(C._task_to_domain("closure:r1:domain:common-common"), "common-common")
        self.assertEqual(C._task_to_domain("closure:r8:domain:app-home"), "app-home")

    def test_page_chunk_id(self):
        """domains 波按页分块的 impl:<key>:p<N>——尾部分块段必须剥掉。"""
        self.assertEqual(C._task_to_domain("impl:app-home:p2"), "app-home")
        self.assertEqual(C._task_to_domain("impl:app-home"), "app-home")

    def test_classic_two_segment_ids(self):
        self.assertEqual(C._task_to_domain("domain:member-pay"), "member-pay")
        self.assertEqual(C._task_to_domain("infra:api-core"), "api-core")
        self.assertEqual(C._task_to_domain("wiring:app-misc"), "app-misc")

    def test_bare_key_unchanged(self):
        self.assertEqual(C._task_to_domain("seed"), "seed")

    def test_result_always_passes_owner_domain_regex(self):
        """推导结果必须能过契约校验——否则申报整条被拒（这正是事故的表现）。"""
        for tid in ("closure:r1:domain:common-common", "domain:member-pay",
                    "infra:api-core", "wiring:app-misc", "seed",
                    "closure:r12:domain:app-cn-sanfate-pub-loginpay-wechat"):
            got = C._task_to_domain(tid)
            self.assertIsNotNone(got, tid)
            self.assertRegex(got, C._OWNER_DOMAIN_RE, "%s → %r 过不了 owner_domain 校验" % (tid, got))

    def test_empty_and_malformed(self):
        for bad in (None, "", "   ", 123, ":::"):
            self.assertIsNone(C._task_to_domain(bad), repr(bad))


if __name__ == "__main__":
    unittest.main()
