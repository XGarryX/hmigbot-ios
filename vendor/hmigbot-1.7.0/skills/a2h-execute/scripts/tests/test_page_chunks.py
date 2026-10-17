#!/usr/bin/env python3
"""UI 域按页分块回归（AIPPT_915_test3 2026-09-01 质量对比驱动）。

事实：同一首页，830 串行线（逐页转换）用 1464 行还原；v915 域级扇出让 impl:app-home 一个任务
背 22 页 + 39 个安卓文件（任务书 81KB），只剩 ~400 行；$r 引用 2229→593、硬编码 hex 4→223。
并行提速的单位选错了——应按页并行，而不是按域并行。

设计：UI 域 → 域核心 impl:<key>（VM/模型/仓储，写权 = 非页面 glob）+ 页面块 impl:<key>:pN
（每块 ≤ PAGE_CHUNK 页，写权 = 本块页面文件，父节点 = 核心）。块间与核心两两不相交（lint R3）。
内嵌弹窗页（Host$showX）随宿主页同块；无鸿蒙页名映射或无页面 glob 的页留给核心。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
CODEX = SCRIPTS.parents[2]
PY = sys.executable or "python3"
sys.path.insert(0, str(SCRIPTS))

import assemble_prompt as AP  # noqa: E402
import _wavelib as W  # noqa: E402

PAGES = ["HomeActivity", "HomeActivity$showCampaignDialog", "GuideActivity", "MineActivity",
         "WorksPage", "AboutUsActivity", "SettingsActivity", "SearchActivity", "OrphanNoMap"]
NAMES = {"HomeActivity": "HomePage", "GuideActivity": "GuidePage", "MineActivity": "MinePage",
         "WorksPage": "WorksPage", "AboutUsActivity": "AboutUsPage",
         "SettingsActivity": "SettingsPage", "SearchActivity": "SearchPage"}
SPEC = """# big 域规格
## 1. 域边界
略
## 2. 屏幕与完整 UI 规格
### 2.1 HomeActivity（Activity，`activity_home.xml`）
- TextView 标题 "首页" 18sp #333333
- 弹窗 showCampaignDialog：活动图 + 关闭按钮
### 2.2 GuideActivity（Activity，`activity_guide.xml`）
- ViewPager 三页引导
### 2.3 MineActivity（Activity）
- 头像 ImageView 64dp 圆角
### 2.4 WorksPage
- RecyclerView 两列网格
### 2.5 AboutUsActivity
- 版本号 TextView
### 2.6 SettingsActivity
- Switch 推送开关
### 2.7 SearchActivity
- EditText 搜索框
## 3. 行为
略
"""


def _blueprint(root: Path, big_pages=PAGES, small_pages=("AActivity", "BActivity")):
    bp = root / "spec" / "blueprint"; bp.mkdir(parents=True)
    (root / "spec" / "domains").mkdir(parents=True)
    (root / "spec" / "domains" / "big.md").write_text(SPEC, encoding="utf-8")
    (root / "spec" / "domains" / "small.md").write_text("# small\n### 2.1 AActivity\n- x\n", encoding="utf-8")
    (bp / "domain-map.json").write_text(json.dumps({"version": 1, "draft": False, "domains": [
        {"key": "big", "title": "Big", "tier": "core", "complexity": 9.0,
         "spec_file": "spec/domains/big.md", "pages": list(big_pages),
         "android_files": ["app/A.kt"]},
        {"key": "small", "title": "Small", "tier": "standard", "complexity": 2.0,
         "spec_file": "spec/domains/small.md", "pages": list(small_pages),
         "android_files": ["app/B.kt"]}]}), encoding="utf-8")
    (bp / "workflow-params.json").write_text(json.dumps({
        "version": 1, "profile": "flagship",
        "gates": {"page_chunk": 3, "single_block_domain": False},   # 本夹具验证旧分块口径；E194 新缺省见 test_single_block_domain
        "project": {"root": str(root), "build_cmd": "hvigorw assembleHap", "encoding": "utf-8"}}), encoding="utf-8")
    big_globs = ["entry/src/main/ets/features/big/**"] + \
        ["entry/src/main/ets/pages/%s.ets" % NAMES[p] for p in big_pages if p in NAMES]
    (bp / "ownership.json").write_text(json.dumps({
        "version": 1, "draft": False,
        "owners": {"seed": ["entry/src/main/ets/common/*.ets"],
                   "domain:big": big_globs,
                   "domain:small": ["entry/src/main/ets/features/small/**",
                                    "entry/src/main/ets/pages/APage.ets", "entry/src/main/ets/pages/BPage.ets"]},
        "mainloop_owned": ["AppScope/**"]}), encoding="utf-8")
    (bp / "page-names.json").write_text(json.dumps({
        "version": 1, "domains": {"big": NAMES, "small": {"AActivity": "APage", "BActivity": "BPage"}}}),
        encoding="utf-8")
    (bp / "contracts.json").write_text(json.dumps({
        "version": 1, "draft": False, "modules": [], "wires": [], "chains": [],
        "acceptance": [], "deferred": [], "open_blockers": []}), encoding="utf-8")
    (bp / "decisions.json").write_text('{"version":1,"decisions":[]}', encoding="utf-8")
    (bp / "decision-ledger.md").write_text("# decisions", encoding="utf-8")
    return bp


def _load_bp(root: Path):
    import generate_waves as G
    return G.load_blueprint_for(str(root / "spec" / "blueprint"), ["domains"])


def _gen(root: Path):
    r = subprocess.run([PY, str(SCRIPTS / "generate_waves.py"), "--blueprint", "spec/blueprint",
                        "--out", "spec/waves", "--wave", "domains", "--json"],
                       cwd=str(root), capture_output=True, text=True)
    p = root / "spec" / "waves" / "plan-domains.json"
    return (json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None), r


class TestPageChunks(unittest.TestCase):
    def test_chunking_shape(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root); bp = _load_bp(root)
            big = AP.find_domain(bp, "big")
            chunks = AP.page_chunks(bp, big)
        self.assertEqual([len(c["hmos"]) for c in chunks], [3, 3, 1])
        # 内嵌弹窗随宿主页同块，且不占页数
        self.assertIn("HomeActivity$showCampaignDialog", chunks[0]["pages"])
        self.assertEqual(chunks[0]["hmos"], ["HomePage", "GuidePage", "MinePage"])
        # 无映射的页不进任何块（留给核心）
        self.assertFalse(any("OrphanNoMap" in c["pages"] for c in chunks))

    def test_small_domain_not_chunked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root); bp = _load_bp(root)
            self.assertEqual(AP.page_chunks(bp, AP.find_domain(bp, "small")), [])

    def test_plan_ids_parents_and_disjoint_ownership(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root)
            plan, r = _gen(root)
        self.assertIsNotNone(plan, r.stdout + r.stderr)
        by = {t["id"]: t for t in plan["tasks"] if t.get("kind") == "agent"}
        self.assertEqual(sorted(by), ["impl:big", "impl:big:p1", "impl:big:p2", "impl:big:p3", "impl:small"])
        for i in (1, 2, 3):
            self.assertEqual(by["impl:big:p%d" % i]["parents"], ["impl:big"])
            self.assertEqual(by["impl:big:p%d" % i]["fork_turns"], "none")
        # 核心不含任何页面文件；块只含页面文件；两两不相交
        core = set(by["impl:big"]["ownership"])
        self.assertIn("entry/src/main/ets/features/big/**", core)
        self.assertFalse(any("/pages/" in g for g in core))
        owns = [set(by[k]["ownership"]) for k in sorted(by) if k.startswith("impl:big")]
        for i in range(len(owns)):
            for j in range(i + 1, len(owns)):
                self.assertEqual(owns[i] & owns[j], set())
        self.assertEqual(by["impl:small"]["parents"], [])

    def test_plan_passes_lint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root); _gen(root)
            r = subprocess.run([PY, str(CODEX / "skills" / "a2h-plan" / "scripts" / "lint_plan.py"),
                                "--plan", "spec/waves/plan-domains.json", "--blueprint", "spec/blueprint", "--json"],
                               cwd=str(root), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_page_brief_inlines_only_its_sections(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root); _gen(root)
            p1 = (root / "spec/waves/prompts/domains/big-p1.txt").read_text(encoding="utf-8")
            p3 = (root / "spec/waves/prompts/domains/big-p3.txt").read_text(encoding="utf-8")
            core = (root / "spec/waves/prompts/domains/big.txt").read_text(encoding="utf-8")
        self.assertIn("### 2.1 HomeActivity", p1)
        self.assertIn("### 2.3 MineActivity", p1)
        self.assertNotIn("### 2.7 SearchActivity", p1)
        self.assertIn("### 2.7 SearchActivity", p3)
        self.assertIn("entry/src/main/ets/pages/HomePage.ets", p1)
        # 页面块的 YOUR FILES 是任务书里最后一处；其后只许出现本块页面文件
        tail = p1.rsplit("YOUR FILES", 1)[1]
        self.assertNotIn("entry/src/main/ets/features/big/**", tail)
        self.assertNotIn("WorksPage.ets", tail)
        # 页名配对必须逐页正确，内嵌弹窗标注宿主
        self.assertIn("MineActivity → MinePage.ets", p1)
        self.assertIn("GuideActivity → GuidePage.ets", p1)
        self.assertIn("随宿主页 HomeActivity", p1)
        # 域核心只读列表不得含任何块的页面文件
        core_ro = p1.split("域核心（impl:big）")[1].split("YOUR FILES")[0]
        self.assertNotIn("/pages/", core_ro)
        self.assertIn("本域已按页分块", core)
        self.assertIn("impl:big:p1..p3", core)

    def test_page_chunk_scopes_knowledge_and_skips_vm_fragment(self):
        """页面块的片段/SDK/沉浸式按本块页面收窄；vm-three-phase 只给域核心。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root); bp = _load_bp(root)
            _, m_core = AP._build_once(bp, "domains", "big", False, None)
            _, m_p1 = AP._build_once(bp, "domains", "big.p1", False, None)
            big = AP.find_domain(bp, "big")
            view = AP.chunk_domain_view(bp, big, 1)
            _, m_p3 = AP._build_once(bp, "domains", "big.p3", False, None)   # 必须在临时目录存活期内
        self.assertIn("vm-three-phase", m_core["fragments"])
        self.assertNotIn("vm-three-phase", m_p1["fragments"])
        self.assertEqual(m_p1["variant"], "p1")
        # 精确的作用域断言：夹具 spec 里 "ViewPager" 只在 2.2 GuideActivity（p1 块），
        # "RecyclerView" 只在 2.4 WorksPage（p2 块）。核心扫整份 spec 两个片段都该有；
        # p1 只该因 ViewPager 触发 gesture-refresh-traps，不该拿到 RecyclerView 触发的 component；
        # p3（Search/…）两个都不该有。
        self.assertIn("gesture-refresh-traps", m_core["fragments"])
        self.assertIn("component", m_core["fragments"])
        self.assertIn("gesture-refresh-traps", m_p1["fragments"])
        self.assertNotIn("component", m_p1["fragments"])
        self.assertNotIn("gesture-refresh-traps", m_p3["fragments"])
        self.assertNotIn("component", m_p3["fragments"])
        self.assertEqual(sorted(view["pages"]), sorted(["HomeActivity", "HomeActivity$showCampaignDialog",
                                                        "GuideActivity", "MineActivity"]))
        self.assertIn("### 2.1 HomeActivity", view["_scope_text"])
        self.assertNotIn("### 2.7 SearchActivity", view["_scope_text"])
        self.assertEqual(len(big["pages"]), len(PAGES))          # 原域对象未被改写

    def test_domain_key_normalization(self):
        for tid, want in (("impl:app-home", "app-home"), ("impl:app-home:p2", "app-home"),
                          ("closure:r1:domain:x", "x"), ("wiring:app-misc", "app-misc"), ("seed", "seed")):
            self.assertEqual(W.domain_key_of(tid), want, tid)


class TestConverterPortIntoChunk(unittest.TestCase):
    """第十五批：converter 手法移植进页面块（对照实验：同页同模型同资源表，converter 270 行/35 节点/129 $r
    vs 页面块 137/30/49）。移植三样：逐 view 映射表先落盘、复合控件拆子组件（每页私有目录写权）、尺寸外置。"""

    def test_chunk_globs_include_per_page_component_dir_and_stay_disjoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root); bp = _load_bp(root)
            big = AP.find_domain(bp, "big"); chunks = AP.page_chunks(bp, big)
            for c in chunks:
                for h in c["hmos"]:
                    self.assertIn("entry/src/main/ets/components/big/%s/**" % h, c["globs"])
            comp = [g for c in chunks for g in c["globs"] if "/components/" in g]
            self.assertEqual(len(comp), len(set(comp)))                      # 块间不重复
            self.assertFalse(any("/components/" in g for g in _load_bp(root)["ownership"]["owners"]["domain:big"]))

    def test_page_brief_has_mapping_step_and_core_does_not(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root); bp = _load_bp(root)
            big = AP.find_domain(bp, "big")
            page = AP.brief_domains_page(bp, big, 1)
            self.assertIn("STEP 0 — 逐 view 映射表", page)
            self.assertIn("spec/waves/results/domains/big-p1.mapping.md", page)
            self.assertIn("android-to-harmonyOS-ui-layout-mapping-reference.md", page)   # 映射参考指针实存
            self.assertIn("android-to-harmonyOS-ui-atomic-component-mapping-reference.md", page)
            self.assertIn("复合控件拆子组件", page)
            self.assertIn("entry/src/main/ets/components/big/", page)
            self.assertIn("$r('app.float.*')", page)
            core = AP.brief_domains(bp, big)
            self.assertNotIn("STEP 0 — 逐 view 映射表", core)
            self.assertNotIn(".mapping.md", core)


if __name__ == "__main__":
    unittest.main()


class TestSingleBlockDomain(unittest.TestCase):
    """E194（S1）：≤page_chunk 页的域 = 一个页面块任务（域核心并入，写权=整域），不再派核心任务；任务书仍走页面块形态。"""

    def test_single_block_domain(self):
        import tempfile, shutil
        tmp = Path(tempfile.mkdtemp())
        try:
            _blueprint(tmp, big_pages=["HomeActivity", "GuideActivity", "MineActivity", "AboutActivity"])
            bp = tmp / "spec" / "blueprint"
            wp = json.loads((bp / "workflow-params.json").read_text(encoding="utf-8"))
            wp["gates"] = {}   # 新缺省：page_chunk=4, single_block_domain=true
            (bp / "workflow-params.json").write_text(json.dumps(wp), encoding="utf-8")
            b = _load_bp(tmp)
            big = AP.find_domain(b, "big")
            chunks = AP.page_chunks(b, big)
            self.assertEqual(len(chunks), 1)
            self.assertTrue(chunks[0].get("single"))
            self.assertIn("entry/src/main/ets/features/big/**", chunks[0]["globs"])
            brief = AP.brief_domains_page(b, big, 1)
            self.assertIn("整域单块", brief)
            self.assertIn("STEP 0", brief)
            self.assertNotIn("只读 import，禁改", brief)
            plan, r = _gen(tmp)
            self.assertIsNotNone(plan, r.stderr)
            ids = [t["id"] for t in plan["tasks"] if t.get("kind") == "agent"]
            self.assertIn("impl:big:p1", ids)
            self.assertNotIn("impl:big", ids)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
