"""E250：handoff 判据回归断言型 + 登记自检 + 对账 / 到期覆盖（AIPPT_930_ds 31 条 handoff：26 条无 resolve_by 永不报到期；
P-DOM-AH-011 正则双重转义永不命中；对账器只看 forward-ref 系）。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import contract_sync as CS  # noqa: E402
import verify_handoffs as VH  # noqa: E402

SLOT = "entry/src/main/ets/components/app-home/HomePage/WorksFragmentSlot.ets"
SLOT_TEXT = "@ComponentV2\nexport struct WorksFragmentSlot {\n  build() {\n    Column() {}\n  }\n}\n"


def _item(**kw):
    it = {"kind": "handoff", "location": SLOT + "#build", "owner_domain": "app-home",
          "note": "owner=app-ppttemplate-preview-page-1：由 WorksFragmentSlot 承载作品页"}
    it.update(kw)
    return it


class TestRegistration(unittest.TestCase):
    def _root(self, td):
        root = Path(td)
        (root / SLOT).parent.mkdir(parents=True)
        (root / SLOT).write_text(SLOT_TEXT, encoding="utf-8")
        return root

    def test_double_escaped_grep_is_normalized_and_resolve_by_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            contracts = {"deferred": []}
            item = _item(trigger={"type": "grep", "arg": "WorksFragmentPage\\\\(\\\\{",
                                  "check_cmd": "grep -rEn \"WorksFragmentPage\\\\(\\\\{\" entry/src/main/ets/"})
            rep, has_new = CS.merge_deferred(contracts, [(item, "app-home")], root=root)
            self.assertTrue(has_new, rep)
            e = contracts["deferred"][0]
            self.assertEqual(e["trigger"]["type"], "grep")                       # 不转桩位判据
            self.assertEqual(e["trigger"]["arg"], "WorksFragmentPage\\(\\{")
            self.assertIn("WorksFragmentPage\\(\\{", e["trigger"]["check_cmd"])
            self.assertEqual(e["trigger"]["normalized_from"], "WorksFragmentPage\\\\(\\\\{")
            self.assertEqual(e["resolve_by"], "wiring")
            self.assertIn("resolve_by 缺省 wiring", e["note"])
            self.assertNotIn("FWD-REF(", (root / SLOT).read_text(encoding="utf-8"))   # handoff 不打桩位标记

    def test_owner_domain_with_ownership_prefix_is_normalized(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            contracts = {"deferred": []}
            item = _item(owner_domain="infra:network-basis", trigger={"type": "grep", "arg": "WorksFragmentPage\\("})
            rep, has_new = CS.merge_deferred(contracts, [(item, "app-home")], root=root)
            self.assertTrue(has_new, rep)
            self.assertEqual(contracts["deferred"][0]["owner_domain"], "network-basis")

    def test_invalid_regex_and_missing_trigger_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            for trig in ({"type": "grep", "arg": "WorksFragmentPage("}, None):
                contracts = {"deferred": []}
                it = _item(trigger=trig) if trig else _item()
                rep, has_new = CS.merge_deferred(contracts, [(it, "app-home")], root=root)
                self.assertFalse(has_new, rep)
                self.assertEqual(rep["summary"]["rejected"], 1)


class TestReconcileAndDue(unittest.TestCase):
    def _contracts(self, status="registered", resolve_by=None):
        return {"deferred": [{"id": "P-DOM-AH-011", "kind": "handoff", "status": status, "owner_domain": "app-home",
                              "resolve_by": resolve_by, "location": {"file": SLOT, "anchor": "build"},
                              "trigger": {"type": "grep", "arg": "WorksFragmentPage\\(\\{"}}]}

    def test_reconcile_resolves_handoff_when_assertion_holds(self):
        c = self._contracts()
        res = VH.reconcile_triggers(c, [("entry/src/main/ets/pages/HomePage.ets", "Column() {}\n")], Path("."))
        self.assertEqual([r["id"] for r in res["unmet"]], ["P-DOM-AH-011"])
        corpus = [("entry/src/main/ets/pages/HomePage.ets", "if (this.tab === 2) { WorksFragmentPage({ tabType: 1 }) }\n")]
        res = VH.reconcile_triggers(c, corpus, Path("."))
        self.assertEqual([r["id"] for r in res["met"]], ["P-DOM-AH-011"])
        self.assertEqual(c["deferred"][0]["status"], "resolved")

    def test_legacy_handoff_without_resolve_by_becomes_due_after_wiring(self):
        c = self._contracts(resolve_by=None)
        self.assertEqual(VH.find_dangling_fwd_refs(c, {"waves": {"domains": {}}}), [])
        due = VH.find_dangling_fwd_refs(c, {"waves": {"domains": {}, "wiring": {}}})
        self.assertEqual([d["id"] for d in due], ["P-DOM-AH-011"])
        self.assertEqual(due[0]["kind"], "handoff")


if __name__ == "__main__":
    unittest.main()
