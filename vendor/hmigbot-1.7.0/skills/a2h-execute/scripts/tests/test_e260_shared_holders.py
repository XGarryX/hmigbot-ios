"""E260：跨域共享状态持有者 / 事件由语法树抽进契约（E246 推广），全链：预填 → A3 wires → verify_wires → 任务书。

离线实验：AIPPT 抽出跨域依赖 30 条，模型写的契约只覆盖 930 60% / ds 43%；AppContant 在 930 与 ds 都被写成两份定义。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SKILLS = SCRIPTS.parents[1]
PREFILL = SKILLS / "a2h-spec" / "scripts" / "interface_prefill.py"
A3 = SKILLS / "a2h-plan" / "scripts" / "a3_finalize.py"
LINT = SKILLS / "a2h-plan" / "scripts" / "lint_blueprint.py"
VW = SCRIPTS / "verify_wires.py"
J = "app/src/main/java/com/x/"
ETS = "entry/src/main/ets/"


def _w(p: Path, t: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(t, encoding="utf-8")


def _setup(root: Path):
    a = root / "android"
    _w(a / (J + "base/AppConfig.kt"), "package com.x.base\nobject AppConfig {\n  var userConfig: String = \"\"\n  fun log(s: String) {}\n}\n")
    _w(a / (J + "base/LogUtil.kt"), "package com.x.base\nobject LogUtil {\n  fun d(s: String) {}\n}\n")
    _w(a / (J + "base/KV.kt"), "package com.x.base\nobject KV {\n  val KEY_AGREE: String = \"read_agreement\"\n}\n")
    _w(a / (J + "base/PptDao.kt"), "package com.x.base\n@Dao\ninterface PptDao {\n  fun all(): List<String>\n}\n")
    _w(a / (J + "home/HomeActivity.kt"),
       "package com.x.home\nclass HomeActivity : AppCompatActivity() {\n"
       "  fun a() { AppConfig.userConfig = \"x\"; LogUtil.d(\"x\"); MMKVUtil.encodeInt(KV.KEY_AGREE, 1) }\n"
       "  fun b(dao: PptDao) { dao.all() }\n"
       "  @Subscribe(threadMode = ThreadMode.MAIN)\n  fun onPay(e: PaySuccessEvent) { }\n  companion object {\n    var entered: Boolean = false\n  }\n}\n")
    _w(a / (J + "mine/MineActivity.kt"),
       "package com.x.mine\nclass MineActivity : AppCompatActivity() {\n"
       "  fun c() { val s = AppConfig.userConfig; val r = MMKVUtil.decodeInt(KV.KEY_AGREE, 0); EventBus.getDefault().post(PaySuccessEvent(1)); HomeActivity.entered = true }\n}\n"
       "class PaySuccessEvent(val v: Int)\n")
    _w(root / "spec/blueprint/domain-map.json", json.dumps({"version": 1, "domains": [
        {"key": "base", "spec_file": "spec/domains/base.md", "pages": [],
         "android_files": [J + "base/AppConfig.kt", J + "base/LogUtil.kt", J + "base/KV.kt", J + "base/PptDao.kt"]},
        {"key": "home", "spec_file": "spec/domains/home.md", "pages": ["HomeActivity"], "android_files": [J + "home/HomeActivity.kt"]},
        {"key": "mine", "spec_file": "spec/domains/mine.md", "pages": ["MineActivity"], "android_files": [J + "mine/MineActivity.kt"]}]}))
    _w(root / "spec/toolkit-fact-tree.json", json.dumps({"schema_version": 1, "pages": [{"id": "HomeActivity"}, {"id": "MineActivity"}],
                                                        "dialogs": [], "flow_graph": {"nodes": [], "edges": []}}))
    _w(root / "spec/blueprint/workflow-params.json", json.dumps({"version": 1, "project": {"android_src": str(a)}}))
    _w(root / "spec/blueprint/contracts.json", json.dumps({"version": 1, "modules": [], "wires": []}))
    return a


class TestSharedHoldersChain(unittest.TestCase):
    def test_prefill_wires_verify_brief(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = _setup(root)
            r = subprocess.run([sys.executable, str(PREFILL), "--project", str(root), "--android-src", str(a), "--no-journeys", "--json"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            pre = json.loads((root / "spec/blueprint/interface-prefill.json").read_text(encoding="utf-8"))
            hs = {h["name"]: h for h in pre["shared_holders"]}
            self.assertEqual(set(hs), {"AppConfig", "HomeActivity", "PptDao", "kv:read_agreement", "event:PaySuccessEvent"})
            self.assertNotIn("LogUtil", hs)                                  # 只有方法、没有可变状态的工具不算持有者
            self.assertEqual((hs["AppConfig"]["kind"], hs["AppConfig"]["owner_domain"], sorted(hs["AppConfig"]["consumers"])),
                             ("singleton", "base", ["home", "mine"]))
            self.assertTrue(hs["AppConfig"]["consumers"]["home"]["w"])
            self.assertEqual((hs["HomeActivity"]["kind"], sorted(hs["HomeActivity"]["consumers"])), ("companion", ["mine"]))
            self.assertEqual((hs["kv:read_agreement"]["owner_domain"], sorted(hs["kv:read_agreement"]["consumers"])), ("home", ["mine"]))
            self.assertEqual((hs["event:PaySuccessEvent"]["owner_domain"], sorted(hs["event:PaySuccessEvent"]["consumers"])), ("mine", ["home"]))
            # A3：持有者成边，imports 里同一依赖不再重复成 service-call
            r = subprocess.run([sys.executable, str(A3), "--op", "wires", "--blueprint", str(root / "spec/blueprint")],
                               capture_output=True, text=True, cwd=root)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            wires = json.loads((root / "spec/blueprint/contracts.json").read_text(encoding="utf-8"))["wires"]
            hw = [w for w in wires if w.get("source") == "prefill:shared-holder"]
            self.assertEqual(len(hw), 6)
            self.assertEqual({(w["symbol"], w["consumer_domain"]) for w in wires if w["kind"] == "service-call"} &
                             {(w["symbol"], w["consumer_domain"]) for w in hw}, set())
            ev = next(w for w in hw if w["symbol"] == "event:PaySuccessEvent")
            self.assertEqual((ev["kind"], ev["provider_domain"], ev["consumer_domain"]), ("event", "mine", "home"))
            # B13：删掉一条持有者边 → 阻断
            bad = [w for w in wires if not (w.get("symbol") == "AppConfig" and w.get("consumer_domain") == "mine")]
            _w(root / "spec/blueprint/contracts.json", json.dumps({"version": 1, "modules": [], "wires": bad}))
            r = subprocess.run([sys.executable, str(LINT), "--blueprint", str(root / "spec/blueprint"), "--json"], capture_output=True, text=True)
            self.assertIn("共享状态 / 事件未进 wires", r.stdout + r.stderr)
            _w(root / "spec/blueprint/contracts.json", json.dumps({"version": 1, "modules": [], "wires": wires}))
            # 产物：AppConfig 两份定义（base 一份、home 又建一份）；mine 没用 HomeActivity.entered；键走常量
            _w(root / (ETS + "infra/base/AppConfig.ets"), "export class AppConfig { static userConfig: string = ''; }\n")
            _w(root / (ETS + "features/home/AppConfig.ets"), "export class AppConfig { static userConfig: string = ''; }\n")
            _w(root / (ETS + "infra/base/KV.ets"), "export const KEY_AGREE: string = 'read_agreement';\n")
            _w(root / (ETS + "features/home/HomeVm.ets"), "import { KEY_AGREE } from '../../infra/base/KV';\nexport class HomeVm { k: string = KEY_AGREE; x: string = AppConfig.userConfig; }\nexport class HomeActivity { static entered: boolean = false; }\nexport class PptDao {}\n")
            _w(root / (ETS + "features/mine/MineVm.ets"), "import { KEY_AGREE } from '../../infra/base/KV';\nexport class MineVm { k: string = KEY_AGREE; x: string = AppConfig.userConfig; e: string = 'PaySuccessEvent'; }\n")
            _w(root / "spec/blueprint/page-names.json", json.dumps({"version": 1, "domains": {"home": {"HomeActivity": "HomePage"}, "mine": {"MineActivity": "MinePage"}}}))
            _w(root / (ETS + "pages/HomePage.ets"), "@Builder export function HomePageBuilder() { HomePage() }\n@ComponentV2 struct HomePage { e: string = 'PaySuccessEvent'; build() { Column() {} } }\n")
            subprocess.run([sys.executable, str(VW), "--project", str(root), "--wave", "domains", "--json"], capture_output=True, text=True)
            rep = json.loads((root / "spec/reports/wires-check-domains.json").read_text(encoding="utf-8"))
            st = {(x["symbol"], x["consumer_domain"]): x["status"] for x in rep["symbol_wires"]["shared_holders"]}
            self.assertEqual(st[("AppConfig", "mine")], "multi-definition")
            self.assertEqual(st[("HomeActivity", "mine")], "consumer-missing")
            self.assertEqual(st[("kv:read_agreement", "mine")], "wired")             # 读方经常量名引用同一个键
            self.assertEqual(st[("event:PaySuccessEvent", "home")], "wired")
            # 任务书：owner 看到「唯一定义方」；多出那份所在域（home）收到重入待办
            sys.path.insert(0, str(SCRIPTS))
            import assemble_prompt as AP
            bp = {"_dir": root / "spec/blueprint", "domain_map": json.loads((root / "spec/blueprint/domain-map.json").read_text(encoding="utf-8")),
                  "workflow_params": {"project": {"root": str(root)}}}
            self.assertIn("你是 `AppConfig` 的唯一定义方", AP._wires_text(bp, "base"))
            home = AP._wires_text(bp, "home")
            self.assertIn("共享状态多份定义：`AppConfig`", home)
            self.assertIn("禁止在本域另建同名类", home)


if __name__ == "__main__":
    unittest.main()
