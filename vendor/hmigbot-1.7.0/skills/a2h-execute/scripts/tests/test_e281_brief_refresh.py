#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E281：E193 符号级裁剪的退化情形 + 领域任务书在 infra 波尾机械刷新。

现场（AIPPT_930_gpt）：domains 任务书在 a2h-plan A3 与 infra 同批生成，那时 contracts.modules[].exports
全空（要等 infra 波尾 gate:contract-sync 补录）→ `_symbol_filter` 把「导出未知」判成「未引用」→
25 份任务书 361 条契约全是「导出 ——」空指针；同份任务书 T1 页眉又写「禁回读其源文件」。
此前重生成靠主会话自己记得跑 `generate_waves --wave domains`（ds2 跑了剥 22%，gpt/ds4 没跑剥 100%）。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import assemble_prompt as A  # noqa: E402
import refresh_domain_briefs as R  # noqa: E402
from test_generate_plan import PlanFixture  # noqa: E402

MOD = {"file": "entry/src/main/ets/infra/shared/net/UserData.ets", "owner": "infra:net", "status": "implemented"}


class TestSymbolFilterDegenerate(unittest.TestCase):
    def test_empty_exports_is_pending_not_unreferenced(self):
        out = A._symbol_filter([dict(MOD, exports=[])], "LoginActivity 调用 UserData.isBinding()")
        self.assertTrue(out[0].get("_exports_pending"))
        self.assertFalse(out[0].get("_unreferenced"))

    def test_missing_exports_key_is_pending(self):
        out = A._symbol_filter([dict(MOD)], "whatever")
        self.assertTrue(out[0].get("_exports_pending"))

    def test_real_exports_unreferenced_still_pointer(self):
        """E193 原意保留：有导出、本任务 spec 一个都没提 → 仍渲染一行指针。"""
        m = dict(MOD, exports=[{"symbol": "UserData.isBinding", "signature": "static isBinding(): boolean"}])
        out = A._symbol_filter([m], "本页只做模板列表，与账号无关")
        self.assertTrue(out[0].get("_unreferenced"))
        self.assertFalse(out[0].get("_exports_pending"))

    def test_real_exports_referenced_kept(self):
        m = dict(MOD, exports=[{"symbol": "UserData.isBinding", "signature": "static isBinding(): boolean"},
                               {"symbol": "UserData.clear", "signature": "static clear(): void"}])
        out = A._symbol_filter([m], "点击登录前判断 isBinding")
        self.assertEqual([e["symbol"] for e in out[0]["exports"]], ["UserData.isBinding"])


class TestRenderAndHeader(unittest.TestCase):
    def test_pending_line_is_honest_and_readable(self):
        txt = A._render_module_contract([dict(MOD, exports=[], _exports_pending=True)])
        self.assertIn("导出待 contract-sync 补录", txt)
        self.assertIn("spec/CONTRACT.md", txt)
        self.assertIn("不受 T1「禁回读」约束", txt)
        self.assertNotIn("未引用", txt)          # 不能再把「导出未知」说成「未引用」

    def test_pointer_line_has_names_and_exemption(self):
        m = dict(MOD, exports=[{"symbol": "UserData.isBinding"}], _unreferenced=True)
        txt = A._render_module_contract([m])
        self.assertIn("导出 UserData.isBinding", txt)   # 导出名不再为空
        self.assertIn("不受 T1「禁回读」约束", txt)

    def test_header_scopes_no_reread_to_inlined_entries(self):
        self.assertIn("禁回读其源文件", A.CHEATSHEET_HEADER)            # T1 纪律本身不动
        self.assertIn("「禁回读」只约束下方**已内联签名**的条目", A.CHEATSHEET_HEADER)

    def test_inline_rendering_unchanged(self):
        m = dict(MOD, exports=[{"symbol": "UserData.isBinding", "signature": "static isBinding(): boolean"}])
        txt = A._render_module_contract([m])
        self.assertTrue(txt.startswith("### entry/src/main/ets/infra/shared/net/UserData.ets — owner: infra:net"))
        self.assertIn("- UserData.isBinding: static isBinding(): boolean", txt)


class TestRefreshScript(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.proj = Path(self._t.name)
        (self.proj / "spec" / "blueprint").mkdir(parents=True)
        (self.proj / "spec" / "waves" / "prompts" / "domains").mkdir(parents=True)

    def tearDown(self):
        self._t.cleanup()

    def _w(self, rel, obj):
        p = self.proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def test_skip_when_no_domains_plan(self):
        code, res = R.refresh(self.proj, "spec/blueprint", "spec/waves")
        self.assertEqual((code, res["action"]), (0, "skipped"))

    def test_skip_when_domains_already_dispatched(self):
        self._w("spec/waves/plan-domains.json", {"tasks": []})
        self._w("spec/state/dispatch.json", {"version": 1, "waves": {"domains": {"contract_hash": "x"}}})
        code, res = R.refresh(self.proj, "spec/blueprint", "spec/waves")
        self.assertEqual((code, res["action"]), (0, "skipped"))
        self.assertIn("首派", res["reason"])

    def test_skip_when_journal_has_domains_rows(self):
        """续跑时 dispatch 分区缺失但 journal 已有 domains 代理行 → 不得借刷新开出 r2（回放 gpt 现场撞出来的）。"""
        self._w("spec/waves/plan-domains.json", {"tasks": []})
        self._w("spec/state/journal.json", {"operation_outputs": [
            {"workflow_id": "domains", "kind": "agent", "task_id": "impl:app-home", "status": "OK"}]})
        code, res = R.refresh(self.proj, "spec/blueprint", "spec/waves")
        self.assertEqual((code, res["action"]), (0, "skipped"))
        self.assertIn("第二轮", res["reason"])

    def test_scan_counts_three_kinds(self):
        body = "\n".join([
            A.CHEATSHEET_HEADER,
            A._render_module_contract([dict(MOD, exports=[{"symbol": "X", "signature": "x()"}])]),
            A._render_module_contract([dict(MOD, file="a/B.ets", exports=[{"symbol": "B"}], _unreferenced=True)]),
            A._render_module_contract([dict(MOD, file="a/C.ets", exports=[], _exports_pending=True)]),
            "## 下一段", "- a/D.ets（owner x，status y；导出待 contract-sync 补录——段外不计）"])
        self._w("spec/waves/prompts/domains/t.txt", body)
        s = R.scan_briefs(self.proj / "spec/waves/prompts/domains")
        self.assertEqual((s["inline"], s["pointer"], s["pending"]), (1, 1, 1))
        self.assertEqual(s["pending_files"], {"a/C.ets": ["t.txt"]})

    def test_selfcheck_fails_when_synced_module_still_pending(self):
        """刷新后若已有导出的模块仍渲染成「待补录」= 没读到同步后的契约 → exit 1。"""
        self._w("spec/waves/plan-domains.json", {"tasks": []})
        self._w("spec/blueprint/contracts.json", {"modules": [dict(MOD, exports=[{"symbol": "U"}])]})

        def fake_run(args):
            self._w("spec/waves/prompts/domains/t.txt", A.CHEATSHEET_HEADER + "\n" +
                    A._render_module_contract([dict(MOD, exports=[], _exports_pending=True)]))
            return {"ok": True, "contract_hash": "sha256:x"}

        with mock.patch("generate_waves.run", side_effect=fake_run):
            code, res = R.refresh(self.proj, "spec/blueprint", "spec/waves")
        self.assertEqual(code, 1)
        self.assertIn(MOD["file"], res["stale_pending"])

    def test_generation_error_is_loud(self):
        self._w("spec/waves/plan-domains.json", {"tasks": []})
        with mock.patch("generate_waves.run", side_effect=RuntimeError("boom")):
            code, res = R.refresh(self.proj, "spec/blueprint", "spec/waves")
        self.assertEqual((code, res["action"]), (1, "failed"))
        self.assertIn("boom", res["error"])


class TestInfraTailRefreshEndToEnd(PlanFixture):
    """真实四拍：A3 同批生成 infra+domains（导出全空）→ 跑完 infra 波 → 领域任务书被机械刷新成带签名。"""

    def setUp(self):
        super().setUp()
        cp = self.blueprint / "contracts.json"
        c = json.loads(cp.read_text(encoding="utf-8"))
        c["modules"].append({"file": "common/Zeta.ets", "owner": "infra:core", "status": "planned", "exports": []})
        self._write(cp, json.dumps(c))
        # 两个域 spec 都落盘 → domains 任务书走符号级裁剪（E193 的真实路径）
        self._write(self.proj / "spec/domains/alpha.md", "# alpha\n### 1 AlphaActivity\n- 打开时调用 ZetaHelper.load() 取数据\n")
        self._write(self.proj / "spec/domains/beta.md", "# beta\n### 1 BetaActivity\n- 纯静态说明页\n")
        # infra 波尾 host-page / resource-coverage 的输入（同 TestInfraWaveEndToEnd）
        self._write(self.proj / "spec" / "journeys.json", json.dumps({"start": ["SplashActivity"]}))
        self._write(self.blueprint / "page-names.json", json.dumps({"domains": {"alpha": {"SplashActivity": "SplashPage"}}}))
        self._write(self.proj / "android/app/src/main/res/values/strings.xml",
                    '<resources><string name="app_name">Demo</string></resources>\n')
        self._write(self.proj / "android/app/src/main/java/demo/A.java", "class A { int x = R.string.app_name; }\n")
        self._write(self.proj / "entry/src/main/resources/base/element/string.json",
                    json.dumps({"string": [{"name": "app_name", "value": "Demo"}]}))

    def _cheats(self, key):
        txt = (self.proj / ("spec/waves/prompts/domains/%s.txt" % key)).read_text(encoding="utf-8")
        return "\n".join(R._cheatsheet_lines(txt))

    def test_domains_briefs_refreshed_after_infra(self):
        # ── A3：infra/domains 同批生成，此刻导出全空 ──
        self.gen("infra")
        self.gen("domains")
        before = self._cheats("alpha")
        self.assertIn("导出待 contract-sync 补录", before)       # 退化情形如实标注，不再写「未引用」
        self.assertNotIn("本任务 spec 未直接引用", before)
        self.assertIn("reduce:refresh-domain-briefs", {t["id"] for t in self.plan("infra")["tasks"]})

        def on_dispatch(batch):
            ets = self.proj / "entry/src/main/ets/common"
            self._write(ets / "Seed.ets", "export class Seed {\n  boot(): void {}\n}\n")
            self._write(ets / "Zeta.ets", "export class ZetaHelper {\n  load(): string { return ''; }\n}\n")
            self.write_result(batch[0]["result_path"],
                              {"task": "infra:core", "final_state": "PASS",
                               "files": ["common/Seed.ets", "common/Zeta.ets"],
                               "exports": ["Seed: class Seed { boot(): void }",
                                           "ZetaHelper: class ZetaHelper { load(): string }"]})
            self.write_build_log("infra")

        self.run_to_done("infra", on_dispatch)

        journal = json.loads((self.state.parent / "journal.json").read_text(encoding="utf-8"))
        rows = {r["task_id"]: r["status"] for r in journal["operation_outputs"] if r["kind"] == "reduce"}
        self.assertEqual(rows.get("reduce:refresh-domain-briefs"), "REDUCE_PASS", rows)

        alpha, beta = self._cheats("alpha"), self._cheats("beta")
        self.assertNotIn("导出待 contract-sync 补录", alpha + beta)   # 刷新后不应再有「待补录」
        self.assertIn("### common/Zeta.ets — owner: infra:core", alpha)   # alpha 引用了 ZetaHelper → 内联签名
        self.assertIn("ZetaHelper", alpha)
        self.assertRegex(beta, r"common/Zeta\.ets（owner infra:core，本任务 spec 未直接引用 → 未内联签名；导出 ZetaHelper")


if __name__ == "__main__":
    unittest.main()
