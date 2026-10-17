"""I1–I4 接口层回归：interface_prefill（机械预填）→ 任务书第八维注入 → lint_interface 对账 → a3 --op wires → lint_blueprint B13。
立此闸的事实（AIPPT_0903 test4 审计）：27 份 spec 跨域引用声明率 9%、导航覆盖 73%、AC 46% 代码级判据、contracts.wires=0、
38 处 startActivity 最终只接了 5 处。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent.parent
PREFILL = SKILLS / "a2h-spec" / "scripts" / "interface_prefill.py"
LINT = SKILLS / "a2h-spec" / "scripts" / "lint_interface.py"
A3 = SKILLS / "a2h-plan" / "scripts" / "a3_finalize.py"
LINT_BP = SKILLS / "a2h-plan" / "scripts" / "lint_blueprint.py"
sys.path.insert(0, str(SKILLS / "a2h-spec" / "scripts"))
import interface_prefill as IP  # noqa: E402
import lint_interface as LI  # noqa: E402

KT_HOME = """package com.x.home
import com.x.pay.PayDialog
class HomeActivity : BaseActivity() {
    override fun initView() {
        binding.btnPay.setOnClickListener { PayDialog.newInstance().show(supportFragmentManager, "pay") }
        binding.btnAbout.setOnClickListener { startActivity(Intent(this, AboutActivity::class.java)) }
    }
    override fun onResume() { super.onResume() }
}
"""
KT_ABOUT = "package com.x.home\nclass AboutActivity : BaseActivity() {\n    override fun initView() { binding.tvOk.setOnClickListener { finish() } }\n}\n"
KT_PAY = "package com.x.pay\nimport com.x.home.HomeActivity\nclass PayDialog : BaseDialogFragment() {\n    fun confirm() { }\n}\n"
KT_BASE = "package com.x.base\nopen class BaseActivity : Activity()\nopen class BaseDialogFragment : DialogFragment()\n"


def _w(p: Path, t: str):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(t, encoding="utf-8")


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(); self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name); self.android = self.root / "android"; self.proj = self.root / "proj"
        _w(self.android / "app/src/main/java/com/x/home/HomeActivity.kt", KT_HOME)
        _w(self.android / "app/src/main/java/com/x/home/AboutActivity.kt", KT_ABOUT)
        _w(self.android / "app/src/main/java/com/x/pay/PayDialog.kt", KT_PAY)
        _w(self.android / "base/src/main/java/com/x/base/Base.kt", KT_BASE)
        bp = self.proj / "spec/blueprint"
        _w(bp / "domain-map.json", json.dumps({"version": 1, "domains": [
            {"key": "home", "spec_file": "spec/domains/home.md", "pages": ["HomeActivity", "AboutActivity"],
             "android_files": ["app/src/main/java/com/x/home/HomeActivity.kt", "app/src/main/java/com/x/home/AboutActivity.kt"]},
            {"key": "pay", "spec_file": "spec/domains/pay.md", "pages": ["PayDialog"], "android_files": ["app/src/main/java/com/x/pay/PayDialog.kt"]},
            {"key": "base", "layer": "infra", "spec_file": "spec/domains/base.md", "android_files": ["base/src/main/java/com/x/base/Base.kt"]}]}))
        _w(self.proj / "spec/toolkit-fact-tree.json", json.dumps({"schema_version": 1, "pages": [{"id": "HomeActivity"}, {"id": "AboutActivity"}], "dialogs": [{"id": "PayDialog"}],
                                                                   "flow_graph": {"nodes": [], "edges": [{"from": "HomeActivity", "to": "PayDialog", "trigger": "click", "is_dynamic": False}]}}))
        for n in ("contracts.json", "decisions.json", "ownership.json", "workflow-params.json"):
            _w(bp / n, json.dumps({"version": 1, "owners": {"seed": []}} if n == "ownership.json" else {"version": 1, "modules": [], "wires": [], "deferred": [], "chains": [], "acceptance": []} if n == "contracts.json" else {"version": 1}))
        _w(bp / "decision-ledger.md", "# ledger\n")
        r = subprocess.run([sys.executable, str(PREFILL), "--project", str(self.proj), "--android-src", str(self.android), "--json"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr); self.summary = json.loads(r.stdout)
        self.pre = json.loads((bp / "interface-prefill.json").read_text(encoding="utf-8"))


class TestPrefill(Fixture):
    def test_edges_imports_interactions_extracted(self):
        home = self.pre["domains"]["home"]
        edges = {(e["from"], e["to"]): e for e in home["nav_edges"]}
        self.assertIn(("HomeActivity", "PayDialog"), edges); self.assertTrue(edges[("HomeActivity", "PayDialog")]["cross_domain"])
        self.assertIn(("HomeActivity", "AboutActivity"), edges); self.assertFalse(edges[("HomeActivity", "AboutActivity")]["cross_domain"])   # 源码扫描补的域内边
        self.assertIn("PayDialog", {i["symbol"] for i in home["imports"]})
        self.assertIn("HomeActivity", {e["symbol"] for e in self.pre["domains"]["home"]["exports"]})  # PayDialog import 了 HomeActivity → home 导出
        self.assertIn("PayDialog", {e["symbol"] for e in self.pre["domains"]["pay"]["exports"]})
        anchors = {i["anchor"] for i in home["interactions"]}
        self.assertIn("HomeActivity#binding.btnPay", anchors) if "HomeActivity#binding.btnPay" in anchors else self.assertTrue(any(a.startswith("HomeActivity#") for a in anchors))
        self.assertTrue(any(a.endswith(".onResume") for a in anchors))
        block = IP.render_domain_block(self.pre, "home")
        self.assertIn("## INTERFACE", block); self.assertIn("| HomeActivity | PayDialog | pay |", block); self.assertIn("## AC 骨架", block); self.assertIn("判: ui_state", block)


class TestLintInterface(Fixture):
    def _lint(self):
        r = subprocess.run([sys.executable, str(LINT), "--project", str(self.proj), "--json"], capture_output=True, text=True)
        return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])

    def test_missing_section_and_uncovered_are_blocking(self):
        _w(self.proj / "spec/domains/home.md", "# home\n\n## BEHAVIOR\n- 略\n\n## 验收\n- [ ] H01-AC1 x 源: HomeActivity.initView 判: persisted_value 真: Android\n")
        rc, rep = self._lint()
        self.assertEqual(rc, 1); bc = rep["by_code"]
        self.assertIn("SPEC.INTERFACE_SECTION_MISSING", bc); self.assertIn("SPEC.UNCOVERED_NAV_EDGE", bc)
        self.assertIn("SPEC.UNCOVERED_INTERACTION", bc); self.assertIn("SPEC.AC_ORACLE_NOT_OBSERVABLE", bc)

    def test_confirmed_spec_passes(self):
        block = IP.render_domain_block(self.pre, "home").replace("（期望：待填——用户做了 click 后设备上可见什么）", "点击后弹出支付弹窗").replace("（期望：待填——用户做了 lifecycle 后设备上可见什么）", "进入页面显示标题")
        _w(self.proj / "spec/domains/home.md", "# home\n\n## BEHAVIOR\n- 略\n\n" + block + "\n")
        rc, rep = self._lint()
        self.assertEqual(rc, 0, rep); self.assertEqual(rep["blocking"], 0)


class TestWires(Fixture):
    def test_op_wires_builds_from_prefill_and_spec(self):
        import re as _re
        block = _re.sub(r"^\| HomeActivity \| PayDialog \| pay \| [^|]+ \| [^|]+ \| [^|]+ \| [^|]+ \|$",
                        "| HomeActivity | PayDialog | pay | click:btnPay | PayParams{orderId:string} | 关闭回首页 | route |",
                        IP.render_domain_block(self.pre, "home"), flags=_re.M)
        _w(self.proj / "spec/domains/home.md", "# home\n\n" + block + "\n")
        r = subprocess.run([sys.executable, str(A3), "--op", "wires", "--blueprint", str(self.proj / "spec/blueprint")], capture_output=True, text=True, cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        wires = json.loads((self.proj / "spec/blueprint/contracts.json").read_text(encoding="utf-8"))["wires"]
        nav = [w for w in wires if w["kind"] == "nav-edge"]
        self.assertEqual([(w["from"], w["to"], w["consumer_domain"], w["provider_domain"]) for w in nav], [("HomeActivity", "PayDialog", "home", "pay")])
        self.assertTrue(nav[0]["confirmed"]); self.assertEqual(nav[0]["params"], "PayParams{orderId:string}")
        self.assertTrue(any(w["kind"] == "service-call" and w["symbol"] == "PayDialog" for w in wires))
        # B13：预填的跨域边全部有 wire → PASS
        r = subprocess.run([sys.executable, str(LINT_BP), "--blueprint", str(self.proj / "spec/blueprint"), "--json"], capture_output=True, text=True, cwd=self.proj)
        out = r.stdout + r.stderr
        self.assertIn("B13", out); self.assertNotIn("跨域导航边未进 wires", out)

    def test_b13_fails_when_wires_empty(self):
        r = subprocess.run([sys.executable, str(LINT_BP), "--blueprint", str(self.proj / "spec/blueprint"), "--json"], capture_output=True, text=True, cwd=self.proj)
        self.assertIn("跨域导航边未进 wires", r.stdout + r.stderr)


class TestExecuteSide(Fixture):
    def _wires(self):
        block = IP.render_domain_block(self.pre, "home")
        _w(self.proj / "spec/domains/home.md", "# home\n\n" + block + "\n")
        subprocess.run([sys.executable, str(A3), "--op", "wires", "--blueprint", str(self.proj / "spec/blueprint")], capture_output=True, text=True, cwd=self.proj)
        _w(self.proj / "spec/blueprint/page-names.json", json.dumps({"version": 1, "domains": {"home": {"HomeActivity": "HomePage", "AboutActivity": "AboutPage"}, "pay": {"PayDialog": "PayPage"}}}))

    def test_verify_wires_states(self):
        self._wires()
        VW = SKILLS / "a2h-execute" / "scripts" / "verify_wires.py"
        ets = self.proj / "entry/src/main/ets"
        _w(ets / "pages/HomePage.ets", "@Builder export function HomePageBuilder() { HomePage() }\n@ComponentV2 struct HomePage { build() { Button('pay').onClick(() => { this.stack.pushPathByName('PayPage', new PayParams()) }) } }\n")
        r = subprocess.run([sys.executable, str(VW), "--project", str(self.proj), "--wave", "domains", "--json"], capture_output=True, text=True)
        rep = json.loads(r.stdout); self.assertEqual((rep["total"], rep["wired"]), (1, 0)); self.assertEqual(rep["counts"], {"provider-missing": 1})
        _w(ets / "pages/PayPage.ets", "@Builder export function PayPageBuilder() { PayPage() }\n@ComponentV2 struct PayPage { build() {} }\n")   # E85：<页名>Builder 也算提供方
        r = subprocess.run([sys.executable, str(VW), "--project", str(self.proj), "--wave", "domains", "--json"], capture_output=True, text=True)
        rep = json.loads(r.stdout); self.assertEqual((rep["total"], rep["wired"]), (1, 1))
        self.assertTrue((self.proj / "spec/reports/wires-check-domains.json").is_file())
        import handoff_check as H
        checks, facts = H.run_checks(self.proj, self.proj / "spec/blueprint")
        self.assertEqual(next(c for c in checks if c["id"] == "wires")["status"], "ok"); self.assertEqual(facts["wires_wired"], 1)

    def test_wires_text_injected_for_consumer_and_provider(self):
        self._wires()
        sys.path.insert(0, str(SKILLS / "a2h-execute" / "scripts"))
        import assemble_prompt as AP
        bp = {"_dir": str(self.proj / "spec/blueprint")}
        home = AP._wires_text(bp, "home"); pay = AP._wires_text(bp, "domain:pay")
        self.assertIn("你要发起的导航", home); self.assertIn("HomeActivity → PayDialog", home); self.assertIn("`PayPage`", home)
        self.assertIn("别域会跳到你的页面", pay); self.assertIn("PayDialog ← HomeActivity", pay)
        self.assertIn("你依赖的别域符号", home); self.assertIn("PayDialog（pay）", home)

    def test_lint_emit_spec_tasks_and_wave_nodes(self):
        _w(self.proj / "spec/domains/home.md", "# home\n\n## BEHAVIOR\n- 略\n")
        _w(self.proj / "spec/reports/spec-tasks.json", json.dumps({"min_ratio": 0.4, "domains": {"pay": ["PayDialog"]}}))
        r = subprocess.run([sys.executable, str(LINT), "--project", str(self.proj), "--emit-spec-tasks", "--json"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        tasks = json.loads((self.proj / "spec/reports/spec-tasks.json").read_text(encoding="utf-8"))
        self.assertEqual(tasks["domains"]["pay"], ["PayDialog"]); self.assertEqual(sorted(tasks["domains"]["home"]), ["AboutActivity", "HomeActivity"]); self.assertEqual(tasks["interface_domains"], ["home"])
        sys.path.insert(0, str(SKILLS / "a2h-execute" / "scripts"))
        import generate_waves as G
        nodes = G._insert_wires_check([{"id": "reduce:build-domains", "kind": "reduce", "parents": []}], "domains")
        self.assertEqual([n["id"] for n in nodes], ["reduce:build-domains", "reduce:wires-check"]); self.assertEqual(nodes[1]["parents"], ["reduce:build-domains"])
        self.assertEqual(G._insert_wires_check([{"id": "x", "kind": "reduce"}], "understand"), [{"id": "x", "kind": "reduce"}])
        src = (SKILLS / "a2h-execute" / "scripts" / "generate_waves.py").read_text(encoding="utf-8")
        self.assertIn('"id": "gate:interface"', src); self.assertIn('"id": "gate:interface-2"', src)


class TestE78NonUiDomain(unittest.TestCase):
    def test_infra_or_pageless_domain_downgrades_to_warn(self):
        sys.path.insert(0, str(SKILLS / "a2h-spec" / "scripts"))
        import lint_interface as LI
        spec = "# net\n\n## AC 骨架\n- [ ] N1-AC01 源:HttpClient.get 判:unit 真:200\n"
        ui = LI.lint_domain("net", spec, {}, {"key": "net", "pages": ["X"]})
        self.assertEqual(sorted(f["code"] for f in ui), ["SPEC.AC_ORACLE_NOT_OBSERVABLE", "SPEC.AC_WITHOUT_INTERACTION", "SPEC.INTERFACE_SECTION_MISSING"])  # E101：预填无交互点/导航边 → 比例规则不触发
        ui2 = LI.lint_domain("net", spec, {"interactions": [{"anchor": "HttpClient#btn", "kind": "click"}]}, {"key": "net", "pages": ["X"]})
        self.assertIn("SPEC.AC_UNANCHORED_RATIO", [f["code"] for f in ui2])                       # 同一类有预填锚点却不用 → 比例阻断（E121）
        ui3 = LI.lint_domain("net", spec, {"interactions": [{"anchor": "Other#btn", "kind": "click"}]}, {"key": "net", "pages": ["X"]})
        self.assertNotIn("SPEC.AC_UNANCHORED_RATIO", [f["code"] for f in ui3])                    # 锚在预填没扫到的类上 = 预填盲区，不算自由发挥
        self.assertTrue(all(f.get("severity") is None for f in ui if f["code"] != "SPEC.AC_WITHOUT_INTERACTION"))
        for d in ({"key": "net", "layer": "infra", "pages": ["X"]}, {"key": "net", "pages": []}):
            infra = LI.lint_domain("net", spec, {}, d)
            sev = {f["code"]: f.get("severity") for f in infra}
            self.assertEqual(sev["SPEC.INTERFACE_SECTION_MISSING"], "warn", d); self.assertEqual(sev["SPEC.AC_ORACLE_NOT_OBSERVABLE"], "warn", d)
        self.assertFalse(LI.is_ui_domain({"layer": "infra", "pages": ["X"]})); self.assertTrue(LI.is_ui_domain({"pages": ["X"]}))


class TestE89WireTodoAtLanding(Fixture):
    def test_unmet_then_met(self):
        block = IP.render_domain_block(self.pre, "home")
        _w(self.proj / "spec/domains/home.md", "# home\n\n" + block + "\n")
        subprocess.run([sys.executable, str(A3), "--op", "wires", "--blueprint", str(self.proj / "spec/blueprint")], capture_output=True, text=True, cwd=self.proj)
        _w(self.proj / "spec/blueprint/page-names.json", json.dumps({"version": 1, "domains": {"home": {"HomeActivity": "HomePage", "AboutActivity": "AboutPage"}, "pay": {"PayDialog": "PayPage"}}}))
        sys.path.insert(0, str(SKILLS / "a2h-execute" / "scripts"))
        import land_results as LR
        task = {"id": "impl:home", "ownership": ["entry/src/main/ets/features/home/**", "entry/src/main/ets/pages/HomePage.ets"]}
        ets = self.proj / "entry/src/main/ets"
        _w(ets / "pages/HomePage.ets", "@Builder export function HomePageBuilder() { HomePage() }\n@ComponentV2 struct HomePage { build() {} }\n")
        self.assertEqual([u[:2] for u in LR._wire_todo_unmet(self.proj, task)], [("HomePage", "PayPage")])
        _w(ets / "pages/HomePage.ets", "@Builder export function HomePageBuilder() { HomePage() }\n@ComponentV2 struct HomePage { build() { Button('p').onClick(() => { this.navPathStack.pushPathByName('PayPage', new PayParams()) }) } }\n")
        self.assertEqual(LR._wire_todo_unmet(self.proj, task), [])
        self.assertEqual(LR._wire_todo_unmet(self.proj, {"id": "x", "ownership": ["entry/src/main/ets/features/x/**"]}), [])   # 无页面白名单不核


class TestE96AcceptanceFromSpec(Fixture):
    def test_parse_ac_lines_and_op_acceptance(self):
        sys.path.insert(0, str(SKILLS / "a2h-spec" / "scripts"))
        import lint_interface as LI
        spec = ("# home\n\n## AC 骨架\n"
                "- [ ] H01-AC1 点击 `HomeActivity#btnPay` 后进入支付页。 源: HomeActivity#btnPay 判: navigation 真: Android 实测\n"
                "  提示: 调用 PayRouter.open()，参数 orderId\n"
                "- [ ] H01-AC2 首页加载后展示用户名。 源: HomeActivity.onResume 判: text 真: Android 实测 决: PD-3\n"
                "- [ ] H01-AC3 token 写入 MMKV。 源: HomeActivity.onResume 判: persisted_value 真: Android 实测\n")
        acs = LI.parse_ac_lines(spec)
        self.assertEqual([a["id"] for a in acs], ["H01-AC1", "H01-AC2", "H01-AC3"])
        self.assertEqual(acs[0]["assertion"], "点击 `HomeActivity#btnPay` 后进入支付页"); self.assertEqual(acs[0]["oracle"], "navigation")
        self.assertEqual(acs[0]["hint"], "调用 PayRouter.open()，参数 orderId"); self.assertIsNone(acs[1]["hint"]); self.assertEqual(acs[1]["truth"], "Android 实测")
        _w(self.proj / "spec/domains/home.md", spec)
        (self.proj / "spec/waves/results/understand").mkdir(parents=True, exist_ok=True)
        _w(self.proj / "spec/waves/results/understand/pay.json", json.dumps({"ac_candidates": [
            "- [ ] P02-AC1 支付成功后回到首页。 源: PayDialog.onPaid 判: navigation 真: Android 实测",
            {"assertion": "- [ ] P02-AC2 支付失败 toast。 源: PayDialog.onFail 判: toast 真: Android 实测", "on_device": True}]}))
        _w(self.proj / "spec/blueprint/page-names.json", json.dumps({"version": 1, "domains": {"home": {"HomeActivity": "HomePage"}, "pay": {"PayDialog": "PayPage"}}}))
        r = subprocess.run([sys.executable, str(A3), "--op", "acceptance", "--blueprint", str(self.proj / "spec/blueprint"), "--allow-unassigned"],
                           capture_output=True, text=True, cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        acc = json.loads((self.proj / "spec/blueprint/contracts.json").read_text(encoding="utf-8"))["acceptance"]
        by = {a["ac_id"]: a for a in acc}
        self.assertIn("H01-AC1", by); self.assertEqual(by["H01-AC1"]["oracle"], "navigation"); self.assertTrue(by["H01-AC1"]["on_device"])
        self.assertEqual(by["H01-AC1"]["hint"], "调用 PayRouter.open()，参数 orderId"); self.assertEqual(by["H01-AC1"]["anchor"]["target_symbol"], "HomePage#btnPay")
        self.assertFalse(by["H01-AC3"]["on_device"])                                       # persisted_value 不是设备可观察判据
        self.assertIn("P02-AC1", by); self.assertEqual(by["P02-AC2"]["oracle"], "toast"); self.assertEqual(by["P02-AC2"]["assertion"], "支付失败 toast")
        self.assertFalse(any(a["assertion"].startswith("- [") for a in acc))
        import assemble_prompt as AP
        bp = {"_dir": self.proj / "spec/blueprint", "contracts": json.loads((self.proj / "spec/blueprint/contracts.json").read_text(encoding="utf-8"))}
        self.assertTrue(AP._domain_acceptance(bp, "home"))


class TestE95E97ModalityAndSpecAddedEdges(Fixture):
    def test_e259_window_dialog_inline_forced_route(self):
        """E259：安卓窗口级组件（PayDialog : DialogFragment）的边，spec 代理改成 inline 也不作数——契约一律 route +
        form=navdest-dialog 并计数；任务书导航行写 DIALOG 模式弹窗页。"""
        uf = self.pre.get("ui_forms") or {}
        comp = {c["android"]: c for c in uf.get("components") or []}
        self.assertEqual(comp["PayDialog"]["form"], "navdest-dialog")
        self.assertTrue((self.proj / "spec/blueprint/ui-forms.json").is_file())
        block = IP.render_domain_block(self.pre, "home")
        self.assertIn("形态由脚本判定", block)
        import re as _re
        block = _re.sub(r"^\| HomeActivity \| PayDialog \| pay \| [^|]+ \| [^|]+ \| [^|]+ \| [^|]+ \|$",
                        "| HomeActivity | PayDialog | pay | click:btnPay | PayParams | 关闭 | inline |", block, flags=_re.M)
        _w(self.proj / "spec/domains/home.md", "# home\n\n" + block + "\n")
        r = subprocess.run([sys.executable, str(A3), "--op", "wires", "--blueprint", str(self.proj / "spec/blueprint")], capture_output=True, text=True, cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("弹窗形态统一改写 1 条", r.stdout)
        wires = json.loads((self.proj / "spec/blueprint/contracts.json").read_text(encoding="utf-8"))["wires"]
        w = next(x for x in wires if x["kind"] == "nav-edge" and x["from"] == "HomeActivity" and x["to"] == "PayDialog")
        self.assertEqual((w["modality"], w["form"]), ("route", "navdest-dialog"))
        _w(self.proj / "spec/blueprint/page-names.json", json.dumps({"version": 1, "domains": {"home": {"HomeActivity": "HomePage"}, "pay": {"PayDialog": "PayDialogPage"}}}))
        sys.path.insert(0, str(SKILLS / "a2h-execute" / "scripts"))
        import assemble_prompt as AP
        txt = AP._wires_text({"_dir": str(self.proj / "spec/blueprint")}, "home")
        self.assertIn("DIALOG 模式弹窗页", txt); self.assertNotIn("inline 弹窗组件", txt)

    def test_inline_modality_and_spec_added_edge(self):
        block = IP.render_domain_block(self.pre, "home")
        self.assertIn("| modality |", block); self.assertIn("route", block)
        # 代理：PayDialog 改 inline；再补一条预填漏扫的边 HomeActivity → AboutActivity（同域，不进 wires）与 HomeActivity → PayDialog2（别域）
        import re as _re
        block = _re.sub(r"^\| HomeActivity \| PayDialog \| pay \| [^|]+ \| [^|]+ \| [^|]+ \| [^|]+ \|$",
                        "| HomeActivity | PayDialog | pay | click:btnPay | PayParams | 关闭 | inline |\n| HomeActivity | PayDialog2 | pay | click | - | - | route 补因：DataBinding onClick |",
                        block, flags=_re.M)
        self.assertIn("| inline |", block)
        _w(self.proj / "spec/domains/home.md", "# home\n\n" + block + "\n")
        dm = json.loads((self.proj / "spec/blueprint/domain-map.json").read_text(encoding="utf-8"))
        for d in dm["domains"]:
            if d["key"] == "pay":
                d["pages"].append("PayDialog2")
        _w(self.proj / "spec/blueprint/domain-map.json", json.dumps(dm))
        # E259 起安卓窗口级组件的形态由脚本定（见 test_e259_window_dialog_inline_forced_route）；这里测的是「内嵌组件」的
        # inline 通路，故去掉 PayDialog 的窗口级形态标记，模拟一个内嵌在宿主页里的组件
        pre = json.loads((self.proj / "spec/blueprint/interface-prefill.json").read_text(encoding="utf-8"))
        pre.pop("ui_forms", None)
        for d in pre["domains"].values():
            for e in d["nav_edges"]:
                e.pop("to_form", None)
        _w(self.proj / "spec/blueprint/interface-prefill.json", json.dumps(pre, ensure_ascii=False))
        r = subprocess.run([sys.executable, str(A3), "--op", "wires", "--blueprint", str(self.proj / "spec/blueprint")], capture_output=True, text=True, cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout); self.assertIn("spec 补边 1 条", r.stdout)
        wires = json.loads((self.proj / "spec/blueprint/contracts.json").read_text(encoding="utf-8"))["wires"]
        nav = {(w["from"], w["to"]): w for w in wires if w["kind"] == "nav-edge"}
        self.assertEqual(nav[("HomeActivity", "PayDialog")]["modality"], "inline")
        self.assertEqual(nav[("HomeActivity", "PayDialog2")]["source"], "spec"); self.assertEqual(nav[("HomeActivity", "PayDialog2")]["modality"], "route")
        # lint：补边是 info，不阻断；modality 非法是 warn
        r = subprocess.run([sys.executable, str(LINT), "--project", str(self.proj), "--json"], capture_output=True, text=True)
        rep = json.loads((self.proj / "spec/reports/interface-lint.json").read_text(encoding="utf-8"))
        self.assertIn("SPEC.ADDED_NAV_EDGE", rep["by_code"]); self.assertNotIn("SPEC.MODALITY_INVALID", rep["by_code"])
        # verify_wires：inline 边——消费方直接渲染组件、提供方导出 struct 即 wired
        _w(self.proj / "spec/blueprint/page-names.json", json.dumps({"version": 1, "domains": {"home": {"HomeActivity": "HomePage"}, "pay": {"PayDialog": "PayPage", "PayDialog2": "Pay2Page"}}}))
        VW = SKILLS / "a2h-execute" / "scripts" / "verify_wires.py"
        ets = self.proj / "entry/src/main/ets"
        _w(ets / "pages/HomePage.ets", "import { PayPage } from '../components/pay/PayPage';\n@Builder export function HomePageBuilder() { HomePage() }\n@ComponentV2 struct HomePage { @Local show: boolean = false; build() { Column() { if (this.show) { PayPage({ onClose: () => { this.show = false } }) } } } }\n")
        _w(ets / "components/pay/PayPage.ets", "@ComponentV2 export struct PayPage { build() {} }\n")
        r = subprocess.run([sys.executable, str(VW), "--project", str(self.proj), "--wave", "domains", "--json"], capture_output=True, text=True)
        rep = json.loads((self.proj / "spec/reports/wires-check-domains.json").read_text(encoding="utf-8"))
        st = {(x["from"], x["to"]): x["status"] for x in rep["rows"]}
        self.assertEqual(st[("HomeActivity", "PayDialog")], "wired"); self.assertEqual(st[("HomeActivity", "PayDialog2")], "both-missing")
        sys.path.insert(0, str(SKILLS / "a2h-execute" / "scripts"))
        import land_results as LR, assemble_prompt as AP
        task = {"id": "impl:home", "ownership": ["entry/src/main/ets/pages/HomePage.ets"]}
        self.assertEqual([u[:2] for u in LR._wire_todo_unmet(self.proj, task)], [("HomePage", "Pay2Page")])          # inline 边已核销，只剩 route 边（E153 起元组带形态/类名）
        txt = AP._wires_text({"_dir": str(self.proj / "spec/blueprint")}, "home")
        self.assertIn("inline 弹窗组件", txt); self.assertIn("PayDialog2", txt)


class TestE102E103SymbolWiresAndNavSites(TestExecuteSide):
    def test_symbol_wires_nav_sites_journeys(self):
        self._wires()
        ct = json.loads((self.proj / "spec/blueprint/contracts.json").read_text(encoding="utf-8"))
        ct["wires"] += [{"kind": "service-call", "symbol": "PayVM", "consumer_domain": "home", "provider_domain": "pay"},
                        {"kind": "event", "symbol": "pay_done", "consumer_domain": "home", "provider_domain": "pay"},
                        {"kind": "store", "symbol": "sp:token", "consumer_domain": "home", "provider_domain": "pay"}]
        _w(self.proj / "spec/blueprint/contracts.json", json.dumps(ct))
        ets = self.proj / "entry/src/main/ets"
        _w(ets / "pages/HomePage.ets", "import { PayVM } from '../features/pay/PayVM';\n@Builder export function HomePageBuilder() { HomePage() }\n@ComponentV2 struct HomePage { vm = new PayVM(); build() { Button('p').onClick(() => { this.navPathStack.pushPathByName('PayPage', new PayParams()); getContext().eventHub.on('pay_done', () => {}); PersistenceV2.connect(Token, 'sp:token') }) } }\n")
        _w(ets / "features/pay/PayVM.ets", "export class PayVM { fire() { getContext().eventHub.emit('pay_done'); PersistenceV2.connect(Token, 'sp:token') } }\n")
        _w(ets / "pages/PayPage.ets", "@Builder export function PayPageBuilder() { PayPage() }\n@ComponentV2 struct PayPage { build() {} }\n")
        # E103 分母：源码清单里的调用点（HomeActivity → PayDialog 在 fixture 源码里以 PayDialog() 出现）
        SI = SKILLS / "a2h-spec" / "scripts" / "source_inventory.py"
        subprocess.run([sys.executable, str(SI), "--android-src", str(self.android), "--out", str(self.proj / "spec/reports/source-inventory.json")], capture_output=True, text=True)
        _w(self.proj / "spec/journeys.json", json.dumps({"journeys": [{"id": "J01", "steps": ["HomeActivity", "PayDialog"]}, {"id": "J02", "steps": ["HomeActivity", "AboutActivity"]}]}))
        VW = SKILLS / "a2h-execute" / "scripts" / "verify_wires.py"
        r = subprocess.run([sys.executable, str(VW), "--project", str(self.proj), "--wave", "domains", "--json"], capture_output=True, text=True)
        summ = json.loads(r.stdout)
        sw = summ["symbol_wires"]
        self.assertGreaterEqual(sw["service-call"]["wired"], 1); self.assertEqual(sw["event"], {"total": 1, "wired": 1}); self.assertEqual(sw["store"], {"total": 1, "wired": 1})
        self.assertTrue(summ["nav_sites"]["available"]); self.assertGreaterEqual(summ["nav_sites"]["total"], 1)
        self.assertEqual(summ["journeys"], {"available": True, "total": 2, "wired": 1})           # J02 的 About 边没接
        import handoff_check as H
        checks, facts = H.run_checks(self.proj, self.proj / "spec/blueprint")
        ids = {c["id"] for c in checks}
        self.assertTrue({"symbol-wires", "nav-sites", "journeys"} <= ids, ids)


class TestE111E113(Fixture):
    def test_auto_seed_and_site_todo(self):
        # E111：ownership 缺 seed → --auto-seed 写装机面
        (self.proj / "spec/blueprint/ownership.json").unlink(missing_ok=True)
        dm = json.loads((self.proj / "spec/blueprint/domain-map.json").read_text(encoding="utf-8"))
        _w(self.proj / "spec/blueprint/page-names.json", json.dumps({"version": 1, "domains": {**{d["key"]: {} for d in dm["domains"]}, "home": {"HomeActivity": "HomePage", "AboutActivity": "AboutPage"}, "pay": {"PayDialog": "PayPage"}}}))
        r = subprocess.run([sys.executable, str(A3), "--op", "ownership", "--blueprint", str(self.proj / "spec/blueprint")], capture_output=True, text=True, cwd=self.proj)
        self.assertEqual(r.returncode, 1); self.assertIn("--auto-seed", r.stderr + r.stdout)
        r = subprocess.run([sys.executable, str(A3), "--op", "ownership", "--blueprint", str(self.proj / "spec/blueprint"), "--auto-seed"], capture_output=True, text=True, cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        own = json.loads((self.proj / "spec/blueprint/ownership.json").read_text(encoding="utf-8"))
        self.assertIn("entry/src/main/ets/wiring/WiringRoot.ets", own["owners"]["seed"]); self.assertIn("domain:home", own["owners"])
        # E113：源码调用点未接的边进任务书待办（契约里没有的域内边）
        _w(self.proj / "spec/reports/wires-check-x.json", json.dumps({"rows": [], "nav_sites": {"rows": [
            {"from": "HomeActivity", "to": "AboutActivity", "from_page": "HomePage", "to_page": "AboutPage", "status": "consumer-missing", "modality": "route", "in_contract": False}]}}))
        sys.path.insert(0, str(SKILLS / "a2h-execute" / "scripts"))
        import assemble_prompt as AP
        txt = AP._unwired_todo({"_dir": str(self.proj / "spec/blueprint")}, "home", {}, 40, None)
        self.assertIn("源码调用点未接（契约外，域内）：`HomePage` 里补 `this.navPathStack.pushPathByName('AboutPage'", txt)
        self.assertEqual(AP._unwired_todo({"_dir": str(self.proj / "spec/blueprint")}, "pay", {}, 40, None), "")   # 起点页不在 pay 域


if __name__ == "__main__":
    unittest.main()


class TestE125NumberedInterfaceHeading(unittest.TestCase):
    def test_numbered_heading_is_recognized(self):
        body = "\n### nav_edges\n| from | to | to_domain | trigger | params | back | modality |\n|---|---|---|---|---|---|---|\n| A | B | d | click | - | back | route |\n\n## 4. AC 骨架\n- x\n"
        for h in ("## INTERFACE", "## 3. INTERFACE（逐行确认）", "## 8、INTERFACE", "##  8: INTERFACE"):
            sec = LI.interface_section("# t\n\n## 2. 行为\n- y\n" + h + body)
            self.assertIsNotNone(sec, h); self.assertIn("### nav_edges", sec); self.assertNotIn("AC 骨架", sec)
            self.assertEqual(LI.parse_tables(sec)["nav_edges"][0]["to"], "B")
        self.assertIsNone(LI.interface_section("# t\n## 2. 接口说明\n- INTERFACE 在别处\n"))


class TestE148InlineAliases(unittest.TestCase):
    def test_inline_dialog_component_without_page_suffix_counts_as_wired(self):
        import tempfile
        sys.path.insert(0, str(SKILLS / "a2h-execute" / "scripts")); import verify_wires as VW
        with tempfile.TemporaryDirectory() as d:
            ets = Path(d); (ets / "pages").mkdir(); (ets / "components/x").mkdir(parents=True)
            (ets / "pages/CreateOutLinePage.ets").write_text("import { AppTipsDialog } from '../components/x/AppTipsDialog';\nstruct P { build() { AppTipsDialog({ options: this.o }) } }\n", encoding="utf-8")
            (ets / "components/x/AppTipsDialog.ets").write_text("@ComponentV2 export struct AppTipsDialog { build() {} }\n", encoding="utf-8")
            files = [ets / "pages/CreateOutLinePage.ets"]
            self.assertTrue(VW.consumer_wired(files, "AppTipsDialogPage", "inline"))                                    # 去 Page 后缀也认（无别名时同样生效）
            self.assertTrue(VW.consumer_wired(files, "AppTipsDialogPage", "inline", aliases=("AppTipsDialog",)))         # E148：契约类名同认
            self.assertTrue(VW.provider_ready(ets, "AppTipsDialogPage", "inline", aliases=("AppTipsDialog",)))
            self.assertFalse(VW.consumer_wired(files, "AppPermissionIntroDialogPage", "inline", aliases=("AppPermissionIntroDialog",)))   # 真没接的仍未接
            self.assertEqual(VW._inline_names("AppTipsDialogPage", ("AppTipsDialog",)), ["AppTipsDialogPage", "AppTipsDialog"])


class TestE149IndirectRouteName(unittest.TestCase):
    def test_route_name_via_array_counts_as_push(self):
        import tempfile
        sys.path.insert(0, str(SKILLS / "a2h-execute" / "scripts")); import verify_wires as VW
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "HomePageBody.ets"
            f.write_text("const routes: string[] = ['HomeFragmentPage', 'RecommendPage'];\nfoo() { this.navPathStack.pushPathByName(routes[index], new P()); }\n", encoding="utf-8")
            self.assertTrue(VW.consumer_pushes([f], "HomeFragmentPage"))
            self.assertTrue(VW.consumer_pushes([f], "RecommendPage"))
            self.assertFalse(VW.consumer_pushes([f], "MinePage"))                     # 没出现的路由名仍不算
            g = Path(d) / "NoPush.ets"; g.write_text("const names = ['MinePage'];\n", encoding="utf-8")
            self.assertFalse(VW.consumer_pushes([g], "MinePage"))                     # 只有字面量没有 push 调用不算


class TestE152AuditTasksSkipWireCheck(unittest.TestCase):
    def test_guard_present_in_land_results(self):
        src = (SKILLS / "a2h-execute" / "scripts" / "land_results.py").read_text(encoding="utf-8")
        self.assertIn('not str(t.get("id") or "").startswith(("audit:", "read:"))', src)


class TestE153InlineAcceptsPush(unittest.TestCase):
    def test_inline_edge_satisfied_by_push_when_consumer_pushes(self):
        import tempfile
        sys.path.insert(0, str(SKILLS / "a2h-execute" / "scripts")); import verify_wires as VW
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "CreateOutLinePage.ets"
            f.write_text("go() { this.navPathStack.pushPathByName('AppPermissionIntroDialogPage', p) }\n", encoding="utf-8")
            self.assertTrue(VW.consumer_wired([f], "AppPermissionIntroDialogPage", "inline", aliases=("AppPermissionIntroDialog",)))
            g = Path(d) / "Other.ets"; g.write_text("build() { Text('x') }\n", encoding="utf-8")
            self.assertFalse(VW.consumer_wired([g], "AppPermissionIntroDialogPage", "inline", aliases=("AppPermissionIntroDialog",)))
