"""infra_carve.py 回归（第十五批 S1：基座进 infra 波）。
立此闸的事实：v915 的 infra owner 是 A3 手写的"工程裁决"，AIPPT_915_test3 一个没切——192 模块全归
domain:*，基座被 coverage_reconcile 补成 15 个无页面域与业务域并排跑，infra 波空计划，域核心空心。
固定判据：
  · 无页面域按包段/文件名分层（bean→model、network→net、util→shared、event→event、aliauth→sdk）；
  · domain:<key> 写权整体迁到 infra:<key> 并追加 infra/<层>/<key>/** 落点；既有模块改 owner，
    落在写权外的字面路径补进写权；每个安卓文件一条 planned 模块；
  · UI 域按 Kotlin import 命中 infra 类名得到 depends_on_infra（模块引用形态，可被 _match_modules 尾段匹配）；
  · 幂等：第二次 --apply 零新增；默认 dry-run 不写盘；
  · generate_waves：domains 波不派 layer=infra 域，infra 波按模块组派 impl:<key>，auditfix 写权回退 infra:<key>。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
CARVE = SCRIPTS.parent.parent / "a2h-spec" / "scripts" / "infra_carve.py"
GEN = SCRIPTS / "generate_waves.py"
sys.path.insert(0, str(SCRIPTS.parent.parent / "a2h-spec" / "scripts"))
import infra_carve as IC  # noqa: E402


def _blueprint(root: Path):
    bp = root / "spec/blueprint"; bp.mkdir(parents=True)
    android = root / "android"
    (android / "app/src/main/java/com/x/page").mkdir(parents=True)
    (android / "net/src/main/java/cn/pub/network/bean").mkdir(parents=True)
    (android / "net/src/main/java/cn/pub/network").mkdir(parents=True, exist_ok=True)
    (android / "app/src/main/java/com/x/util").mkdir(parents=True)
    (android / "app/src/main/java/com/x/page/HomeActivity.kt").write_text(
        "package com.x.page\nimport cn.pub.network.bean.UserBean\nimport cn.pub.network.ApiException\n"
        "import android.os.Bundle\nclass HomeActivity {}\n", encoding="utf-8")
    (android / "net/src/main/java/cn/pub/network/bean/UserBean.kt").write_text("class UserBean", encoding="utf-8")
    (android / "net/src/main/java/cn/pub/network/ApiException.kt").write_text("class ApiException", encoding="utf-8")
    (android / "app/src/main/java/com/x/util/ClipUtils.kt").write_text("object ClipUtils", encoding="utf-8")
    dm = {"version": 1, "app": "demo", "domains": [
        {"key": "app-home", "title": "Home", "spec_file": "spec/domains/app-home.md", "pages": ["HomeActivity"],
         "android_files": ["app/src/main/java/com/x/page/HomeActivity.kt"], "depends_on_infra": []},
        {"key": "network-bean", "title": "bean", "spec_file": "spec/domains/network-bean.md", "pages": [],
         "android_files": ["net/src/main/java/cn/pub/network/bean/UserBean.kt"], "depends_on_infra": []},
        {"key": "network-network", "title": "net", "spec_file": "spec/domains/network-network.md", "pages": [],
         "android_files": ["net/src/main/java/cn/pub/network/ApiException.kt"], "depends_on_infra": []},
        {"key": "app-util", "title": "util", "spec_file": "spec/domains/app-util.md", "pages": [],
         "android_files": ["app/src/main/java/com/x/util/ClipUtils.kt"], "depends_on_infra": []},
    ]}
    (bp / "domain-map.json").write_text(json.dumps(dm), encoding="utf-8")
    (bp / "ownership.json").write_text(json.dumps({"version": 1, "owners": {
        "seed": ["entry/src/main/ets/common/Constants.ets"],
        "domain:app-home": ["entry/src/main/ets/features/app-home/**", "entry/src/main/ets/pages/HomePage.ets"],
        "domain:network-bean": ["entry/src/main/ets/features/network-bean/**"],
        "domain:network-network": ["entry/src/main/ets/features/network-network/**"],
        "domain:app-util": ["entry/src/main/ets/features/app-util/**"],
    }, "mainloop_owned": []}), encoding="utf-8")
    (bp / "contracts.json").write_text(json.dumps({"version": 1, "modules": [
        {"file": "entry/src/main/ets/services/ApiService.ets", "owner": "domain:network-network",
         "status": "planned", "exports": [{"symbol": "ApiService", "signature": "class ApiService"}]},
    ], "wires": [], "deferred": [], "chains": [], "acceptance": []}), encoding="utf-8")
    (bp / "decisions.json").write_text(json.dumps({"version": 1, "decisions": []}), encoding="utf-8")
    (bp / "workflow-params.json").write_text(json.dumps({
        "profile": "flagship",
        "gates": {"single_block_domain": False},   # 本夹具验证旧口径（小域=核心单任务）；E194 新缺省见 test_page_chunks.test_single_block_domain
        "project": {"root": str(root), "android_src": str(android), "build_cmd": "true", "encoding": "utf-8"},
        "waves": {"domains": {"fragments_default": []}, "infra": {"fragments_default": []},
                  "auditfix": {"fragments_default": []}}}), encoding="utf-8")
    (bp / "decision-ledger.md").write_text("# ledger\n", encoding="utf-8")
    (bp / "page-names.json").write_text(json.dumps({"version": 1, "domains": {"app-home": {"HomeActivity": "HomePage"}}}), encoding="utf-8")
    (root / "spec/domains").mkdir(parents=True)
    for k in ("app-home", "network-bean", "network-network", "app-util"):
        (root / ("spec/domains/%s.md" % k)).write_text("# %s\n\n### 2.1 HomeActivity\n- 列表\n" % k, encoding="utf-8")
    return bp


def _run(root: Path, *args):
    return subprocess.run([sys.executable, str(CARVE), "--blueprint", str(root / "spec/blueprint"), *args],
                          capture_output=True, text=True, encoding="utf-8")


def _gen(root: Path, wave: str):
    env = dict(os.environ); env["ARKTS_SKILL_DIR"] = str(SCRIPTS.parent)
    r = subprocess.run([sys.executable, str(GEN), "--blueprint", "spec/blueprint", "--out", "spec/waves",
                        "--wave", wave, "--json"], capture_output=True, text=True, encoding="utf-8",
                       cwd=str(root), env=env, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads((root / ("spec/waves/plan-%s.json" % wave)).read_text(encoding="utf-8"))


class TestClassify(unittest.TestCase):
    def test_layers(self):
        self.assertEqual(IC.classify_files(["net/src/main/java/cn/pub/network/bean/UserBean.kt"])[0], "model")
        self.assertEqual(IC.classify_files(["net/src/main/java/cn/pub/network/ApiException.kt"])[0], "net")
        self.assertEqual(IC.classify_files(["app/src/main/java/com/x/util/ClipUtils.kt"])[0], "shared")
        self.assertEqual(IC.classify_files(["e/src/main/java/cn/pub/event/VolcEventEnginImp.kt"])[0], "event")
        self.assertEqual(IC.classify_files(["a/src/main/java/cn/pub/aliauth/AuthEventExt.kt"])[0], "sdk")
        self.assertEqual(IC.classify_files(["a/src/main/java/cn/pub/zzz/Foo.kt"])[0], "shared")   # 全零兜底


class TestCarve(unittest.TestCase):
    def test_dry_run_then_apply_then_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); bp = _blueprint(root)
            before = (bp / "ownership.json").read_text(encoding="utf-8")
            r = _run(root, "--json"); self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((bp / "ownership.json").read_text(encoding="utf-8"), before)      # dry-run 不写盘
            out = json.loads(r.stdout); self.assertEqual(out["carved"], 3); self.assertFalse(out["applied"])
            r = _run(root, "--apply", "--json"); out = json.loads(r.stdout)
            self.assertEqual(out["layers"], {"model": 1, "net": 1, "shared": 1})
            dm = json.loads((bp / "domain-map.json").read_text(encoding="utf-8"))
            byk = {d["key"]: d for d in dm["domains"]}
            self.assertEqual(byk["network-bean"]["layer"], "infra"); self.assertEqual(byk["network-bean"]["infra_layer"], "model")
            self.assertNotIn("layer", byk["app-home"])
            own = json.loads((bp / "ownership.json").read_text(encoding="utf-8"))["owners"]
            self.assertNotIn("domain:network-network", own)
            self.assertEqual(own["infra:network-network"], sorted([
                "entry/src/main/ets/features/network-network/**",
                "entry/src/main/ets/infra/net/network-network/**",
                "entry/src/main/ets/services/ApiService.ets"]))                                 # 既有模块字面路径补进写权
            self.assertIn("domain:app-home", own)
            ct = json.loads((bp / "contracts.json").read_text(encoding="utf-8"))
            api = next(m for m in ct["modules"] if m["file"].endswith("ApiService.ets"))
            self.assertEqual(api["owner"], "infra:network-network")                            # 改 owner，exports 不动
            self.assertEqual(api["exports"][0]["symbol"], "ApiService")
            carved = [m for m in ct["modules"] if m.get("carved_by") == "infra_carve"]
            self.assertEqual(sorted(m["file"] for m in carved), [
                "entry/src/main/ets/infra/model/network-bean/UserBean.ets",
                "entry/src/main/ets/infra/net/network-network/ApiException.ets",
                "entry/src/main/ets/infra/shared/app-util/ClipUtils.ets"])
            self.assertTrue(all(m["status"] == "planned" and m["exports"] == [] for m in carved))
            # depends_on_infra：HomeActivity import 了 UserBean 与 ApiException，没 import ClipUtils
            self.assertEqual(byk["app-home"]["depends_on_infra"], [
                "entry/src/main/ets/infra/model/network-bean/UserBean",
                "entry/src/main/ets/infra/net/network-network/ApiException"])
            # 幂等
            r2 = _run(root, "--apply", "--json"); o2 = json.loads(r2.stdout)
            self.assertEqual((o2["carved"], o2["already"], o2["modules_added"], o2["modules_reowned"], o2["deps_added"]), (0, 3, 0, 0, {}))
            self.assertEqual(json.loads((bp / "ownership.json").read_text(encoding="utf-8"))["owners"], own)

    def test_waves_after_carve(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root)
            self.assertEqual(_run(root, "--apply").returncode, 0)
            infra = _gen(root, "infra"); ids = {t["id"]: t for t in infra["tasks"] if t["kind"] == "agent"}
            self.assertEqual(sorted(ids), ["impl:app-util", "impl:network-bean", "impl:network-network"])
            self.assertIn("entry/src/main/ets/infra/net/network-network/**", ids["impl:network-network"]["ownership"])
            domains = _gen(root, "domains"); dids = [t["id"] for t in domains["tasks"] if t["kind"] == "agent"]
            self.assertEqual(dids, ["impl:app-home"])                                          # infra 层域不再进 domains 波
            audit = _gen(root, "auditfix"); fix = next(t for t in audit["tasks"] if t["id"] == "fix:network-bean")
            self.assertIn("entry/src/main/ets/infra/model/network-bean/**", fix["ownership"])   # 写权回退 infra:<key>
            und = _gen(root, "understand"); uids = [t["id"] for t in und["tasks"] if t["kind"] == "agent"]
            self.assertEqual(len(uids), 4)
            self.assertTrue(all(u != "read:app-home" for u in uids[:3]))                         # 基座层先派


if __name__ == "__main__":
    unittest.main()
