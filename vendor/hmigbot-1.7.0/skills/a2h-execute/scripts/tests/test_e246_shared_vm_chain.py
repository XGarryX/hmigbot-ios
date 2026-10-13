"""E246 全链：共享 ViewModel 实例 interface_prefill → a3 --op wires（store 边）→ lint_blueprint B13 → 任务书 → verify_wires 核销。

AIPPT_930_ds：安卓 AIPptViewModel 在 HomeActivity 作用域内是同一个对象（宿主预拉模板、Recommend 系 Fragment 读）；
鸿蒙侧 HomeFragmentBody 自己 new、Recommend 走 AppStorageV2 单例、HomePage 两边都不是 → 模版 Tab 永远空。
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
A3 = SKILLS / "a2h-plan" / "scripts" / "a3_finalize.py"
LINT_BP = SKILLS / "a2h-plan" / "scripts" / "lint_blueprint.py"
VW = SKILLS / "a2h-execute" / "scripts" / "verify_wires.py"
sys.path.insert(0, str(SKILLS / "a2h-spec" / "scripts"))
sys.path.insert(0, str(SKILLS / "a2h-execute" / "scripts"))
import interface_prefill as IP  # noqa: E402

PKG = "app/src/main/java/com/x/"
ANDROID = {
    "home/HomeActivity.kt": ("package com.x.home\nclass HomeActivity : AppCompatActivity() {\n"
                             "    private val vm by lazy { ViewModelProvider(this)[SharedVM::class.java] }\n"
                             "    private val tabs = listOf(TabFragment.newInstance(), ListFragment())\n"
                             "    override fun onCreate() { vm.fetchList() }\n}\n"),
    "home/TabFragment.kt": ("package com.x.home\nclass TabFragment : Fragment() {\n    private val vm by activityViewModels<SharedVM>()\n"
                            "    fun show() { vm.items }\n    companion object { fun newInstance() = TabFragment() }\n}\n"),
    "home/ListFragment.kt": "package com.x.home\nclass ListFragment : Fragment() {\n    private val vm: SharedVM by activityViewModels()\n}\n",
    "vm/SharedVM.kt": "package com.x.vm\nclass SharedVM : ViewModel() { fun fetchList() {} }\n",
}


def _w(p: Path, t: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(t, encoding="utf-8")


class SharedVmChain(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        a = root / "android"
        for rel, text in ANDROID.items():
            _w(a / PKG / rel, text)
        self.proj = root / "proj"
        self.bp = self.proj / "spec/blueprint"
        _w(self.bp / "domain-map.json", json.dumps({"version": 1, "domains": [
            {"key": "home", "spec_file": "spec/domains/home.md", "pages": ["HomeActivity", "TabFragment", "ListFragment"],
             "android_files": [PKG + "home/HomeActivity.kt", PKG + "home/TabFragment.kt", PKG + "home/ListFragment.kt"]},
            {"key": "basis", "layer": "infra", "spec_file": "spec/domains/basis.md", "android_files": [PKG + "vm/SharedVM.kt"]}]}))
        _w(self.proj / "spec/toolkit-fact-tree.json", json.dumps({"schema_version": 1, "pages": [{"id": "HomeActivity", "type": "Activity"}],
                                                                   "fragments": [{"id": "TabFragment"}, {"id": "ListFragment"}], "dialogs": [],
                                                                   "flow_graph": {"nodes": [], "edges": []}}))
        for n in ("contracts.json", "decisions.json", "ownership.json", "workflow-params.json"):
            _w(self.bp / n, json.dumps({"version": 1, "owners": {"seed": []}} if n == "ownership.json" else
                                       {"version": 1, "modules": [], "wires": [], "deferred": [], "chains": [], "acceptance": []} if n == "contracts.json" else {"version": 1}))
        _w(self.bp / "decision-ledger.md", "# ledger\n")
        r = subprocess.run([sys.executable, str(PREFILL), "--project", str(self.proj), "--android-src", str(a), "--json"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["shared_state"], 1)
        self.pre = json.loads((self.bp / "interface-prefill.json").read_text(encoding="utf-8"))
        # spec 代理原样保留预填行（含机械 vm 行）→ a3 不得重复成边
        _w(self.proj / "spec/domains/home.md", "# home\n\n" + IP.render_domain_block(self.pre, "home") + "\n")
        r = subprocess.run([sys.executable, str(A3), "--op", "wires", "--blueprint", str(self.bp)], capture_output=True, text=True, cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        _w(self.bp / "page-names.json", json.dumps({"version": 1, "domains": {"home": {"HomeActivity": "HomePage", "TabFragment": "TabPage", "ListFragment": "ListPage"}}}))
        self.ets = self.proj / "entry/src/main/ets"
        _w(self.ets / "infra/basis/SharedVM.ets", "@ObservedV2 export class SharedVM { fetchList(): void {} }\n")

    def _store(self):
        wires = json.loads((self.bp / "contracts.json").read_text(encoding="utf-8"))["wires"]
        return [w for w in wires if w["kind"] == "store"]

    def _verify(self):
        r = subprocess.run([sys.executable, str(VW), "--project", str(self.proj), "--wave", "w1", "--json"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads((self.proj / "spec/reports/wires-check-w1.json").read_text(encoding="utf-8"))
        rows = rep["symbol_wires"]["shared_vm"]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_contract_edge_and_b13(self):
        st = self._store()
        self.assertEqual(len(st), 1)                                             # spec 回填的同名行不重复
        w = st[0]
        self.assertEqual((w["symbol"], w["vm"], w["host"], w["holder"], w["users"]), ("vm:SharedVM@HomeActivity", "SharedVM", "HomeActivity", "HomeActivity", ["ListFragment", "TabFragment"]))
        self.assertEqual((w["owner_domain"], w["source"], w["confirmed"]), ("home", "prefill:shared-vm", True))
        self.assertEqual(w["access"]["HomeActivity"], ["fetchList"])
        r = subprocess.run([sys.executable, str(LINT_BP), "--blueprint", str(self.bp), "--json"], capture_output=True, text=True, cwd=self.proj)
        self.assertNotIn("共享实例未进 wires", r.stdout + r.stderr)
        ct = json.loads((self.bp / "contracts.json").read_text(encoding="utf-8"))
        ct["wires"] = [x for x in ct["wires"] if x["kind"] != "store"]
        (self.bp / "contracts.json").write_text(json.dumps(ct), encoding="utf-8")
        r = subprocess.run([sys.executable, str(LINT_BP), "--blueprint", str(self.bp), "--json"], capture_output=True, text=True, cwd=self.proj)
        self.assertIn("共享实例未进 wires 1 条: vm:SharedVM@HomeActivity", r.stdout + r.stderr)

    def test_brief_carries_constraint_for_host_and_users(self):
        import assemble_prompt as AP
        bp = {"_dir": str(self.bp)}
        txt = AP._wires_text(bp, "home")
        self.assertIn("**共享 ViewModel 实例**", txt)
        self.assertIn("- `SharedVM`：宿主 HomeActivity（鸿蒙 `HomePage`；安卓宿主调用 fetchList）；使用方 ListFragment（`ListPage`）、TabFragment（`TabPage`：items）", txt)
        self.assertIn("共享 ViewModel 实例", AP._wires_text(bp, "home", pages=["TabFragment"]))   # 页面块：使用方在本块
        self.assertEqual(AP._wires_text(bp, "home", pages=["NoSuchPage"]), "")

    def test_verify_multi_instance_then_todo(self):
        _w(self.ets / "pages/HomePage.ets", "import { SharedVM } from '../infra/basis/SharedVM';\n@ComponentV2 struct HomePage { vm: SharedVM = new SharedVM(); build() {} }\n")
        _w(self.ets / "components/home/TabPage/TabBody.ets", "import { SharedVM } from '../../../infra/basis/SharedVM';\n@ComponentV2 export struct TabBody { vm: SharedVM = new SharedVM(); build() {} }\n")
        _w(self.ets / "pages/ListPage.ets", "import { SharedVM } from '../infra/basis/SharedVM';\n@ComponentV2 struct ListPage { @Consumer('vm') vm: SharedVM = new SharedVM(); build() {} }\n".replace(" = new SharedVM()", ""))
        row = self._verify()
        self.assertEqual(row["status"], "multi-instance")
        self.assertEqual(row["instance_sources"], {"HomeActivity": "private:HomePage", "TabFragment": "private:TabPage", "ListFragment": None})
        import assemble_prompt as AP
        todo = AP._wires_text({"_dir": str(self.bp)}, "home")
        self.assertIn("共享实例断开：`SharedVM` 在安卓是 HomeActivity 作用域内的同一个对象，鸿蒙侧实例来源不一（`HomePage` ← 自己 new；`TabPage` ← 自己 new）", todo)

    def test_verify_wired_via_provider_or_shared_singleton(self):
        _w(self.ets / "pages/HomePage.ets", "import { SharedVM } from '../infra/basis/SharedVM';\n@ComponentV2 struct HomePage { @Provider('vm') vm: SharedVM = new SharedVM(); build() {} }\n")
        _w(self.ets / "components/home/TabPage/TabBody.ets", "import { SharedVM } from '../../../infra/basis/SharedVM';\n@ComponentV2 export struct TabBody { @Consumer('vm') vm: SharedVM; build() {} }\n")
        _w(self.ets / "pages/ListPage.ets", "import { SharedVM } from '../infra/basis/SharedVM';\n@ComponentV2 struct ListPage { @Consumer('vm') vm: SharedVM; build() {} }\n")
        self.assertEqual(self._verify()["status"], "wired")
        # 三方都经同一个共享仓库（AppStorageV2 单例）拿 → 来源一致，同样算接通
        _w(self.ets / "features/home/Repo.ets", "import { SharedVM } from '../../infra/basis/SharedVM';\nexport function sharedVm(): SharedVM { return AppStorageV2.connect(SharedVM, 'vm', () => new SharedVM())!; }\n")
        for rel, up in (("pages/HomePage.ets", ".."), ("components/home/TabPage/TabBody.ets", "../../.."), ("pages/ListPage.ets", "..")):
            _w(self.ets / rel, "import { sharedVm } from '%s/features/home/Repo';\nconst v = sharedVm();\n" % up)
        row = self._verify()
        self.assertEqual(row["status"], "wired")
        self.assertEqual(set(row["instance_sources"].values()), {"features/home/Repo.ets"})

    def test_verify_consumer_missing_when_user_never_touches_vm(self):
        _w(self.ets / "pages/HomePage.ets", "import { SharedVM } from '../infra/basis/SharedVM';\n@ComponentV2 struct HomePage { @Provider('vm') vm: SharedVM = new SharedVM(); build() {} }\n")
        _w(self.ets / "components/home/TabPage/TabBody.ets", "@ComponentV2 export struct TabBody { build() {} }\n")
        _w(self.ets / "pages/ListPage.ets", "import { SharedVM } from '../infra/basis/SharedVM';\n@ComponentV2 struct ListPage { @Consumer('vm') vm: SharedVM; build() {} }\n")
        row = self._verify()
        self.assertEqual((row["status"], row["users_without_vm"]), ("consumer-missing", ["TabFragment"]))
        import assemble_prompt as AP
        self.assertIn("共享实例未接：`TabPage` 的文件（含其 import）里没有用到 `SharedVM`", AP._wires_text({"_dir": str(self.bp)}, "home"))


if __name__ == "__main__":
    unittest.main()
