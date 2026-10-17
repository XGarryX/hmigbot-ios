#!/usr/bin/env python3
"""E244：前向引用桩位判据 stub-cleared——登记时脚本打标记记指纹，兑现=标记已去+锚点代码已改+非空实现。"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import verify_handoffs as VH  # noqa: E402
import contract_sync as CS  # noqa: E402

CONSUMER = """import { Http } from '../net/Http';

@ComponentV2
export struct RenewPage {
  @Local busy: boolean = false;

  private cancelRenew(id: string): void {
    // 等 pay 域 RenewManageViewModel.cancelRenew 落盘
    return;
  }

  build() {
    Column() {}
  }
}
"""
FILE = "entry/src/main/ets/pages/RenewPage.ets"


def _project(td):
    root = Path(td)
    (root / "entry/src/main/ets/pages").mkdir(parents=True)
    (root / FILE).write_text(CONSUMER, encoding="utf-8")
    (root / "spec/blueprint").mkdir(parents=True)
    (root / "spec/blueprint/contracts.json").write_text(json.dumps({"deferred": []}), encoding="utf-8")
    return root


class TestStubApi(unittest.TestCase):
    def test_insert_at_anchor_with_indent_and_idempotent(self):
        new, where = VH.insert_stub_marker(CONSUMER, "cancelRenew", "P-DOM-RP-001")
        self.assertEqual(where, "anchor")
        self.assertIn("  // FWD-REF(P-DOM-RP-001)\n  private cancelRenew(", new)
        again, where2 = VH.insert_stub_marker(new, "cancelRenew", "P-DOM-RP-001")
        self.assertEqual((again, where2), (new, "present"))

    def test_insert_file_top_when_anchor_missing(self):
        new, where = VH.insert_stub_marker(CONSUMER, "noSuchSymbol", "P-DOM-RP-002")
        self.assertEqual(where, "file-top")
        self.assertTrue(new.startswith("// FWD-REF(P-DOM-RP-002)\n"))

    def test_descriptive_anchor_uses_file_fingerprint(self):
        """描述性锚点（click:xxx）找不到声明 → 整文件指纹：只删标记仍判未兑现，文件真改了才算。"""
        fp = VH.anchor_fingerprint(CONSUMER, "click:tv_create")
        self.assertTrue(fp.startswith("f:"))
        marked, _ = VH.insert_stub_marker(CONSUMER, "click:tv_create", "ID-9")
        self.assertEqual(VH.anchor_fingerprint(marked, "click:tv_create"), fp)
        trig = {"type": VH.STUB_TYPE, "arg": "a.ets#ID-9", "anchor": "click:tv_create", "fingerprint": fp}
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(VH.eval_stub_cleared(trig, Path(td), text_override=CONSUMER)[0])
            changed = CONSUMER.replace("    return;\n", "    this.create();\n")
            self.assertTrue(VH.eval_stub_cleared(trig, Path(td), text_override=changed)[0])

    def test_fingerprint_ignores_marker_and_remove(self):
        new, _ = VH.insert_stub_marker(CONSUMER, "cancelRenew", "P-DOM-RP-001")
        self.assertEqual(VH.anchor_fingerprint(CONSUMER, "cancelRenew"), VH.anchor_fingerprint(new, "cancelRenew"))
        self.assertEqual(VH.remove_stub_marker(new, "P-DOM-RP-001"), CONSUMER)

    def test_eval_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.ets").write_text(CONSUMER, encoding="utf-8")
            marked, _ = VH.insert_stub_marker(CONSUMER, "cancelRenew", "ID-1")
            trig = {"type": VH.STUB_TYPE, "arg": "a.ets#ID-1", "anchor": "cancelRenew",
                    "fingerprint": VH.anchor_fingerprint(CONSUMER, "cancelRenew")}
            self.assertFalse(VH.eval_stub_cleared(trig, root, text_override=marked)[0])          # 标记仍在
            self.assertFalse(VH.eval_stub_cleared(trig, root, text_override=CONSUMER)[0])        # 只删标记
            wired = CONSUMER.replace("    // 等 pay 域 RenewManageViewModel.cancelRenew 落盘\n    return;\n",
                                     "    RenewManageViewModel.getInstance().cancelRenew(id);\n")
            ok, why = VH.eval_stub_cleared(trig, root, text_override=wired)
            self.assertTrue(ok, why)
            noop = CONSUMER.replace("    // 等 pay 域 RenewManageViewModel.cancelRenew 落盘\n    return;\n", "    return ;\n")
            self.assertFalse(VH.eval_stub_cleared(trig, root, text_override=noop)[0])            # 改成另一种空实现
            self.assertIsNone(VH.eval_stub_cleared(dict(trig, arg="gone.ets#ID-1"), root)[0])    # 文件不在
            self.assertTrue(VH._trigger_holds(trig, [], root)[0] is False)                        # 盘上仍是原文（标记未插）→ 只删标记形态


class TestRegisterAndResolve(unittest.TestCase):
    ITEM = {"kind": "forward-ref", "location": FILE + "#cancelRenew", "resolve_by": "wiring",
            "owner_domain": "app-mine", "trigger": "pay-loginpay-wechat 的 RenewManageViewModel.cancelRenew（契约为 planned）"}

    def test_prose_trigger_registers_as_stub_with_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = _project(td)
            contracts = {"deferred": []}
            rep, has_new = CS.merge_deferred(contracts, [(dict(self.ITEM), "app-mine")], root=root)
            self.assertTrue(has_new, rep)
            e = contracts["deferred"][0]
            self.assertEqual(e["trigger"]["type"], "stub-cleared")
            self.assertEqual(e["trigger"]["arg"], FILE + "#" + e["id"])
            self.assertIn("RenewManageViewModel", str(e.get("trigger_hint")))
            self.assertIn("// FWD-REF(%s)" % e["id"], (root / FILE).read_text(encoding="utf-8"))
            # 同 location+kind 再申报：幂等去重，不插第二个标记
            rep2, _ = CS.merge_deferred(contracts, [(dict(self.ITEM), "app-mine")], root=root)
            self.assertEqual(rep2["summary"]["duplicates"], 1)
            self.assertEqual((root / FILE).read_text(encoding="utf-8").count("FWD-REF("), 1)

    def test_without_root_keeps_legacy_rejection(self):
        rep, has_new = CS.merge_deferred({"deferred": []}, [(dict(self.ITEM), "app-mine")])
        self.assertFalse(has_new)
        self.assertEqual(rep["summary"]["rejected"], 1)

    def test_external_trigger_types_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root = _project(td)
            contracts = {"deferred": []}
            item = dict(self.ITEM, kind="forward-ref-uncertain", resolve_by="closeout",
                        trigger={"type": "sdk-available", "arg": "@hw/pay"})
            CS.merge_deferred(contracts, [(item, "app-mine")], root=root)
            self.assertEqual(contracts["deferred"][0]["trigger"]["type"], "sdk-available")
            self.assertNotIn("FWD-REF(", (root / FILE).read_text(encoding="utf-8"))

    def test_resolved_refs_needs_code_change_then_script_removes_marker(self):
        with tempfile.TemporaryDirectory() as td:
            root = _project(td)
            contracts = {"deferred": []}
            CS.merge_deferred(contracts, [(dict(self.ITEM), "app-mine")], root=root)
            rid = contracts["deferred"][0]["id"]
            res = CS.apply_resolved_refs(contracts, [(rid, "wiring:app-mine")], root=root)
            self.assertEqual(len(res["rejected"]), 1, res)                      # 没改代码：拒绝，标记留着
            self.assertIn("FWD-REF(%s)" % rid, (root / FILE).read_text(encoding="utf-8"))
            text = (root / FILE).read_text(encoding="utf-8").replace(
                "    // 等 pay 域 RenewManageViewModel.cancelRenew 落盘\n    return;\n",
                "    RenewManageViewModel.getInstance().cancelRenew(id);\n")
            (root / FILE).write_text(text, encoding="utf-8")
            res = CS.apply_resolved_refs(contracts, [(rid, "wiring:app-mine")], root=root)
            self.assertEqual(len(res["resolved"]), 1, res)
            self.assertEqual(contracts["deferred"][0]["status"], "resolved")
            self.assertNotIn("FWD-REF(", (root / FILE).read_text(encoding="utf-8"))


class TestResourceReady(unittest.TestCase):
    def test_media_and_element(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "entry/src/main/resources/base/media").mkdir(parents=True)
            (root / "entry/src/main/resources/base/media/icon_x.png").write_bytes(b"x")
            (root / "entry/src/main/resources/base/element").mkdir(parents=True)
            (root / "entry/src/main/resources/base/element/string.json").write_text(
                '{"string":[{"name":"s_ok","value":"好"}]}', encoding="utf-8")
            for arg, want in (("app.media.icon_x", True), ("$r('app.media.icon_y')", False),
                              ("@drawable/icon_x", True), ("app.string.s_ok", True), ("icon_x", True)):
                self.assertEqual(VH._trigger_holds({"type": "resource-ready", "arg": arg}, [], root)[0], want, arg)


class TestParserOptionalTrigger(unittest.TestCase):
    def _run(self, items):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "r.json"
            f.write_text(json.dumps({"task": "domain:x", "final_state": "PASS", "files": [], "deferred_items": items},
                                    ensure_ascii=False), encoding="utf-8")
            return subprocess.run([sys.executable, str(HERE / "parse_agent_output.py"), "--file", str(f),
                                   "--schema", "impl", "--raw-json"], capture_output=True, text=True).returncode

    def test_forward_ref_without_trigger_ok_sdk_without_trigger_rejected(self):
        self.assertEqual(self._run([{"kind": "forward-ref", "location": FILE + "#cancelRenew", "resolve_by": "wiring"}]), 0)
        # E250：handoff 不走桩位判据，必写断言型 trigger
        self.assertNotEqual(self._run([{"kind": "handoff", "location": FILE + "#build", "note": "owner=x"}]), 0)
        self.assertEqual(self._run([{"kind": "handoff", "location": FILE + "#build", "note": "owner=x",
                                     "trigger": {"type": "grep", "arg": "SettingsPage\\("}}]), 0)
        self.assertNotEqual(self._run([{"kind": "thirdparty-sdk", "location": FILE + "#build", "side_effects": "none"}]), 0)


sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_scheduler_kernel import KernelFixture  # noqa: E402


class TestLocationCheckedAtLanding(KernelFixture):
    """桩位文件不存在 → 落账期 DEFERRED_LOCATION_MISSING 走重试（代理还在上下文里）；实存的正常落账。"""

    def test_missing_stub_location_is_retry(self):
        self.write_plan(self.base_plan())
        self.next_batch()
        fwd = {"kind": "forward-ref", "resolve_by": "wiring", "owner_domain": "alpha"}
        self.write_result("alpha", {"task": "domain:alpha", "final_state": "PASS", "files": ["features/alpha/A.ets"],
                                    "deferred_items": [dict(fwd, location="features/alpha/Nope.ets#go")]})
        self.write_result("beta", {"task": "domain:beta", "final_state": "PASS", "files": ["features/beta/B.ets"],
                                   "deferred_items": [dict(fwd, owner_domain="beta", location="features/beta/B.ets#go")]})
        out = self.land(expect=0)
        by = {r["id"]: r for r in out["landed"]}
        self.assertEqual(by["impl:alpha"]["status"], "RETRY_NEEDED", by["impl:alpha"])
        self.assertIn("DEFERRED_LOCATION_MISSING", by["impl:alpha"]["error"])
        self.assertIn("features/alpha/Nope.ets", by["impl:alpha"]["error"])
        self.assertEqual(by["impl:beta"]["status"], "OK", by["impl:beta"])


class TestPendingRefsRevision(unittest.TestCase):
    """E244 修订（09-22 真实代理全链测试发现）：桩位已按契约名调用 → 提供方落盘即兑现，消费方不改；空实现桩须改成真实调用。"""

    VM = "entry/src/main/ets/features/app-home/HomeViewModel.ets"
    PROVIDER = "entry/src/main/ets/features/pay-vip/VipService.ets"
    CONSUMER_CALL = ("import { VipService } from '../pay-vip/VipService';\n\n"
                     "export class HomeViewModel {\n"
                     "  /** onResume 刷新会员角标 */\n"
                     "  refreshVipStatus(): Promise<boolean> {\n"
                     "    // FWD-REF: pay-vip 域 VipService.queryVipStatus 尚未落盘，按契约签名调用\n"
                     "    return VipService.queryVipStatus();\n"
                     "  }\n}\n")
    CONSUMER_NOOP = ("import { VipService } from '../pay-vip/VipService';\n\n"
                     "export class HomeViewModel {\n"
                     "  refreshVipStatus(): Promise<boolean> {\n"
                     "    // 等 pay-vip 域落查询接口\n"
                     "    return Promise.resolve(false);\n"
                     "  }\n}\n")
    PROV_OLD = "export class VipService {\n  static openVipCenter(): void {\n    console.info('x');\n  }\n}\n"
    PROV_NEW = ("export class VipService {\n  static openVipCenter(): void {\n    console.info('x');\n  }\n\n"
                "  static async queryVipStatus(): Promise<boolean> {\n    return VipService.level() > 0;\n  }\n\n"
                "  private static level(): number {\n    return 1;\n  }\n}\n")

    def _proj(self, td, consumer):
        root = Path(td)
        (root / self.VM).parent.mkdir(parents=True)
        (root / self.PROVIDER).parent.mkdir(parents=True)
        (root / self.VM).write_text(consumer, encoding="utf-8")
        (root / self.PROVIDER).write_text(self.PROV_OLD, encoding="utf-8")
        (root / "spec/blueprint").mkdir(parents=True)
        (root / "spec/blueprint/contracts.json").write_text(json.dumps({"deferred": []}), encoding="utf-8")
        return root

    def _register(self, root):
        contracts = {"deferred": []}
        item = {"kind": "forward-ref", "location": self.VM + "#refreshVipStatus", "resolve_by": "wiring", "owner_domain": "app-home"}
        rep, has_new = CS.merge_deferred(contracts, [(item, "app-home")], root=root)
        self.assertTrue(has_new, rep)
        return contracts, contracts["deferred"][0]

    def test_contract_name_call_resolves_when_provider_lands(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._proj(td, self.CONSUMER_CALL)
            contracts, e = self._register(root)
            self.assertEqual(e["trigger"]["pending_refs"], [self.PROVIDER + "#VipService.queryVipStatus"])
            ok, why = VH.eval_stub_cleared(e["trigger"], root)
            self.assertFalse(ok); self.assertIn("仍引用未落盘的符号", why)
            (root / self.PROVIDER).write_text(self.PROV_NEW, encoding="utf-8")          # 提供方落盘；消费方一字不改
            ok, why = VH.eval_stub_cleared(e["trigger"], root)
            self.assertTrue(ok, why)
            res = VH.reconcile_triggers(contracts, [], root)                             # gate:handoffs 对账自动销账
            self.assertEqual([r["id"] for r in res["met"]], [e["id"]])
            self.assertEqual(e["status"], "resolved")
            self.assertNotIn("FWD-REF(%s)" % e["id"], (root / self.VM).read_text(encoding="utf-8"))   # 标记被删
            self.assertIn("return VipService.queryVipStatus();", (root / self.VM).read_text(encoding="utf-8"))  # 代码未动

    def test_noop_stub_needs_real_call_and_declaration(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._proj(td, self.CONSUMER_NOOP)
            contracts, e = self._register(root)
            self.assertEqual(e["trigger"]["pending_refs"], [])
            (root / self.PROVIDER).write_text(self.PROV_NEW, encoding="utf-8")
            self.assertFalse(VH.eval_stub_cleared(e["trigger"], root)[0])              # 提供方落了也不算：桩还是占位、标记仍在
            f = root / self.VM
            marked = f.read_text(encoding="utf-8")
            comment_only = marked.replace("// 等 pay-vip 域落查询接口", "// 已接入（其实没接）")
            f.write_text(comment_only, encoding="utf-8")
            res = CS.apply_resolved_refs(contracts, [(e["id"], "wiring:app-home")], root=root)
            self.assertEqual([r["id"] for r in res["rejected"]], [e["id"]])             # 只改注释 → 拒
            f.write_text(marked.replace("return Promise.resolve(false);", "return VipService.queryVipStatusV2();"), encoding="utf-8")
            res = CS.apply_resolved_refs(contracts, [(e["id"], "wiring:app-home")], root=root)
            self.assertEqual([r["id"] for r in res["rejected"]], [e["id"]])             # 改成调用未落盘的符号 → 拒
            f.write_text(marked.replace("return Promise.resolve(false);", "return VipService.queryVipStatus();"), encoding="utf-8")
            res = CS.apply_resolved_refs(contracts, [(e["id"], "wiring:app-home")], root=root)
            self.assertEqual([r["id"] for r in res["resolved"]], [e["id"]])             # 真实调用 + 申报 → 兑现
            self.assertNotIn("FWD-REF(", f.read_text(encoding="utf-8"))

    def test_private_member_and_missing_module_do_not_count(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._proj(td, self.CONSUMER_CALL.replace("VipService.queryVipStatus()", "VipService.level()"))
            (root / self.PROVIDER).write_text(self.PROV_NEW, encoding="utf-8")
            refs = VH.stub_refs((root / self.VM).read_text(encoding="utf-8"), "refreshVipStatus", root, self.VM)
            self.assertEqual(refs, [{"ref": self.PROVIDER + "#VipService.level", "ok": False}])   # private 成员不可外部调用
            gone = self.CONSUMER_CALL.replace("'../pay-vip/VipService'", "'../pay-vip/NoSuchFile'")
            refs = VH.stub_refs(gone, "refreshVipStatus", root, self.VM)
            self.assertEqual(refs, [{"ref": "entry/src/main/ets/features/pay-vip/NoSuchFile.ets#VipService.queryVipStatus", "ok": False}])

    def test_fingerprint_ignores_comments(self):
        a = "class A {\n  f(): void {\n    // 注释一\n    this.g();\n  }\n}\n"
        b = "class A {\n  f(): void {\n    /* 换了注释 */\n    this.g();  // 行尾注释\n  }\n}\n"
        self.assertEqual(VH.anchor_fingerprint(a, "f"), VH.anchor_fingerprint(b, "f"))
        self.assertNotEqual(VH.anchor_fingerprint(a, "f"), VH.anchor_fingerprint(a.replace("this.g()", "this.h()"), "f"))
        self.assertEqual(VH.strip_ts_comments("let s = 'http://x'; // c\n"), "let s = 'http://x'; \n")


if __name__ == "__main__":
    unittest.main()
