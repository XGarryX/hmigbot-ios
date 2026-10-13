#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_waves --domain 旧键经 spec/blueprint/domain-remap.json 解析（A3 拆域/改名之后）。

AIPPT_token3（2026-09-21）实证：A3 `a3_finalize --op split` 把 app-ppttemplate-preview-page 拆成 -1/-2，主会话随后按旧键跑
`generate_waves.py --wave specfix --domain app-ppttemplate-preview-page`，得到「在 specfix 波任务集中不存在」。

用法示例:
    cd a2h-execute/scripts/tests && PYTHONPATH=.. python3 -m unittest test_domain_filter_remap
    python3 -m pytest a2h-execute/scripts/tests/test_domain_filter_remap.py -q

覆盖:
    拆域旧键 → 展开为本波任务集里在的子键（specfix 只含 shop-2：只取 shop-2 并打印 shop-1 未纳入；understand 两子都在）；
    改名旧键 → 新键；旧键与现行键混写；拆后再改名的链式追踪；
    解析不到 → exit 1，报错列本波可选 key 与台账候选（无记录 / 后继均不在本波 / 台账缺失）。
"""

from __future__ import annotations

import json
import sys
import unittest

from test_generate_plan import PlanFixture, SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import generate_waves as GW  # noqa: E402

REMAP = {"version": 1, "entries": [
    {"op": "move-page", "page": "PromoDialog", "from": "alpha", "to": "shop", "at": "2026-09-21T17:57:13"},
    {"op": "split", "from": "shop", "into": ["shop-1", "shop-2"],
     "page_partition": {"shop-1": ["ShopActivity"], "shop-2": ["CartActivity"]}, "at": "2026-09-21T17:57:13"},
    {"op": "rename", "from": "beta", "to": "beta-new", "at": "2026-09-21T17:57:13"},
    {"op": "respec", "domain": "beta-new", "action": "renamed-dir", "source": "spec/domains/beta/",
     "spec_dir": "spec/domains/beta-new/", "spec_file": "spec/domains/beta-new/spec.md", "at": "2026-09-21T17:57:14"},
    {"op": "respec", "domain": "shop-1", "action": "kept", "at": "2026-09-21T17:57:14"},
]}


class RemapFixture(PlanFixture):
    def setUp(self) -> None:
        super().setUp()
        doms = ["alpha", "shop-1", "shop-2", "beta-new"]
        self._write(self.blueprint / "domain-map.json", json.dumps({"version": 1, "app": "demo", "domains": [
            {"key": k, "title": k, "spec_file": "spec/domains/%s.md" % k, "pages": []} for k in doms]}))
        own = json.loads((self.blueprint / "ownership.json").read_text(encoding="utf-8"))
        own["owners"] = dict({"domain:%s" % k: ["features/%s/**" % k] for k in doms}, **{"infra:core": ["common/**"]})
        self._write(self.blueprint / "ownership.json", json.dumps(own))
        for k in doms:
            self._write(self.proj / "spec" / "domains" / ("%s.md" % k), "# %s\n" % k)
        # specfix 波任务集 = spec-tasks.json 的域：shop-1 不在（只有 shop-2 判薄）
        self._write(self.proj / "spec" / "reports" / "spec-tasks.json",
                    json.dumps({"domains": {"alpha": ["AActivity"], "shop-2": ["CartActivity"], "beta-new": ["BActivity"]}}))
        self._write(self.blueprint / "domain-remap.json", json.dumps(REMAP))

    def agent_keys(self, wave: str) -> list:
        return sorted(t["id"] for t in self.plan(wave)["tasks"] if t["kind"] == "agent")

    def gen_json(self, wave: str, domain: str, expect: int = 0):
        proc = self.gen(wave, "--domain", domain, "--json", expect=expect)
        return json.loads(proc.stdout), proc.stderr


class TestDomainFilterRemap(RemapFixture):
    def test_split_parent_expands_to_children_present_in_wave(self) -> None:
        out, err = self.gen_json("specfix", "shop")
        self.assertEqual(self.agent_keys("specfix"), ["read:shop-2"])
        self.assertIn("--domain shop → shop-2", err)
        self.assertIn("shop-1 不在 specfix 波任务集", err)
        self.assertEqual(len(out["waves"][0]["domain_remap"]), 1)

    def test_split_parent_takes_all_children_when_all_present(self) -> None:
        self.gen("understand", "--domain", "shop")
        self.assertEqual(self.agent_keys("understand"), ["read:shop-1", "read:shop-2"])

    def test_renamed_key_resolves_and_mixes_with_current_keys(self) -> None:
        self.gen_json("specfix", "beta")
        self.assertEqual(self.agent_keys("specfix"), ["read:beta-new"])
        self.gen_json("specfix", "alpha,shop")
        self.assertEqual(self.agent_keys("specfix"), ["read:alpha", "read:shop-2"])

    def test_current_key_needs_no_ledger(self) -> None:
        (self.blueprint / "domain-remap.json").unlink()
        out, err = self.gen_json("specfix", "shop-2")
        self.assertEqual(self.agent_keys("specfix"), ["read:shop-2"])
        self.assertNotIn("domain_remap", out["waves"][0])

    def test_unknown_key_lists_valid_keys_and_candidates(self) -> None:
        out, err = self.gen_json("specfix", "gone", expect=1)
        self.assertFalse(out["ok"])
        msg = out["error"]
        self.assertIn("--domain gone 在 specfix 波任务集中不存在", msg)
        self.assertIn("domain-remap.json 无该键记录", msg)
        for k in ("alpha", "shop-2", "beta-new"):
            self.assertIn(k, msg.split("本波可选 key", 1)[1])

    def test_successors_outside_wave_fail_with_chain(self) -> None:
        self._write(self.proj / "spec" / "reports" / "spec-tasks.json", json.dumps({"domains": {"alpha": ["AActivity"]}}))
        out, _ = self.gen_json("specfix", "shop", expect=1)
        self.assertIn("shop --split--> shop-1", out["error"])
        self.assertIn("台账后继均不在本波任务集", out["error"])
        self.assertIn("move-page PromoDialog: alpha → shop", out["error"])

    def test_missing_ledger_is_named(self) -> None:
        (self.blueprint / "domain-remap.json").unlink()
        out, _ = self.gen_json("specfix", "shop", expect=1)
        self.assertIn("domain-remap.json 不存在", out["error"])


class TestRemapUnit(unittest.TestCase):
    def test_chain_split_then_rename(self) -> None:
        succ = {"a": [("a-1", "split"), ("a-2", "split")], "a-2": [("b", "rename")]}
        hits, chain, leaves = GW._follow_remap("a", succ, {"a-1", "b", "c"})
        self.assertEqual((sorted(hits), leaves), (["a-1", "b"], []))
        self.assertIn("a-2 --rename--> b", chain)
        hits, _, leaves = GW._follow_remap("a", succ, {"c"})
        self.assertEqual((hits, sorted(leaves)), ([], ["a-1", "b"]))

    def test_cycle_safe(self) -> None:
        hits, _, _ = GW._follow_remap("x", {"x": [("y", "rename")], "y": [("x", "rename")]}, {"z"})
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
