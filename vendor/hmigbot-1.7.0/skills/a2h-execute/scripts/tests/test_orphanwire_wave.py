#!/usr/bin/env python3
"""orphanwire 波回归（对齐参照运行 2026-08-28 的 c2 接线波）。

参照运行在 domains 与 audit 之间有一个独立的接线波：39 个 owner-chunk 并行任务，
agent_type=worker，fork_turns=all。本方案此前只有 SKILL.md 的散文指示要主会话照
`orphan-tasks.<gate>.json` 派发——能力等价，但要模型自觉，故收编为正式的计划波。

设计关键（参照原话「各 owner-chunk 并行处理，随后由 seed 根统一挂载这些 owner-local
接线文件」）：每块**只写自己的一个 wiring/<key>.ets**，绝不改共享入口。否则同一 owner 的
多个分块写权相交——lint_plan R3 会拒（实为并发写同一批文件的 P0）。挂载由 mount_wiring.py
机械完成，不需要模型判断。
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

import generate_waves as G  # noqa: E402
sys.path.insert(0, str(SCRIPTS.parents[1] / "a2h-plan" / "scripts"))


def _blueprint(root: Path, tasks):
    bp = root / "spec" / "blueprint"
    bp.mkdir(parents=True)
    (root / "spec" / "reports").mkdir(parents=True)
    (root / "spec" / "domains").mkdir(parents=True)
    (root / "spec" / "domains" / "main.md").write_text("# main", encoding="utf-8")
    (bp / "domain-map.json").write_text(json.dumps({
        "version": 1, "draft": False, "domains": [{
            "key": "main", "title": "Main", "tier": "core", "complexity": 5.0,
            "spec_file": "spec/domains/main.md", "pages": ["MainActivity"],
            "android_files": ["app/Main.kt"]}]}), encoding="utf-8")
    (bp / "workflow-params.json").write_text(json.dumps({
        "version": 1, "profile": "flagship",
        "project": {"root": ".", "build_cmd": "hvigorw assembleHap", "encoding": "utf-8"}}),
        encoding="utf-8")
    (bp / "ownership.json").write_text(json.dumps({
        "version": 1, "draft": False,
        "owners": {"seed": ["entry/src/main/ets/common/*.ets"],
                   "domain:main": ["entry/src/main/ets/features/main/**"]},
        "mainloop_owned": ["AppScope/**"]}), encoding="utf-8")
    (bp / "contracts.json").write_text(json.dumps({
        "version": 1, "draft": False, "modules": [], "wires": [], "chains": [],
        "acceptance": [], "deferred": [], "open_blockers": []}), encoding="utf-8")
    (bp / "decisions.json").write_text('{"version":1,"decisions":[]}', encoding="utf-8")
    (bp / "decision-ledger.md").write_text("# decisions", encoding="utf-8")
    (root / "spec" / "reports" / "orphan-tasks.compile-2.json").write_text(json.dumps({
        "gate": "compile#2", "chunk": 12, "owners": 2, "tasks": tasks,
        "rule": "每个接线代理只领一个 owner 的一份 chunk；禁跨 owner 合派"}), encoding="utf-8")
    return bp


TASKS = [
    {"owner": "domain:main", "part": 1, "parts": 2,
     "files": ["entry/src/main/ets/features/main/A.ets", "entry/src/main/ets/features/main/B.ets"]},
    {"owner": "domain:main", "part": 2, "parts": 2,
     "files": ["entry/src/main/ets/features/main/C.ets"]},
    {"owner": "seed", "part": 1, "parts": 1,
     "files": ["entry/src/main/ets/common/Theme.ets"]},
]


def _gen(root: Path):
    subprocess.run([PY, str(SCRIPTS / "generate_waves.py"), "--blueprint", "spec/blueprint",
                    "--out", "spec/waves", "--wave", "orphanwire", "--json"],
                   cwd=str(root), capture_output=True, text=True)
    p = root / "spec" / "waves" / "plan-orphanwire.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


class TestOrphanwireWave(unittest.TestCase):
    def test_wave_is_in_order_between_domains_and_auditfix(self):
        o = list(G.WAVE_ORDER)
        self.assertIn("orphanwire", o)
        self.assertEqual(o.index("orphanwire"), o.index("depthfix") + 1)
        self.assertEqual(o.index("auditfix"), o.index("orphanwire") + 1)

    def test_one_task_per_chunk_not_per_owner(self):
        """粒度由 gate_check 切死；此处只搬运，禁合并（v5：49 个孤儿一个 agent 撞轮次上限）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root, TASKS)
            plan = _gen(root)
        ag = [t for t in plan["tasks"] if t.get("kind") == "agent"]
        self.assertEqual(len(ag), 3)

    def test_ownership_is_pairwise_disjoint(self):
        """同 owner 的多块必须写权不相交——否则并发写同一批文件（lint R3 红线）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root, TASKS)
            plan = _gen(root)
        ag = [t for t in plan["tasks"] if t.get("kind") == "agent"]
        for i in range(len(ag)):
            for j in range(i + 1, len(ag)):
                a, b = set(ag[i]["ownership"]), set(ag[j]["ownership"])
                self.assertEqual(a & b, set(),
                                 "%s × %s 写权相交" % (ag[i]["id"], ag[j]["id"]))

    def test_each_chunk_owns_its_own_wiring_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root, TASKS)
            plan = _gen(root)
        for t in [x for x in plan["tasks"] if x.get("kind") == "agent"]:
            key = t["id"].split(":", 1)[1]
            self.assertIn("entry/src/main/ets/wiring/%s.ets" % key, t["ownership"])

    def test_plan_passes_lint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root, TASKS)
            _gen(root)
            r = subprocess.run(
                [PY, str(CODEX / "skills" / "a2h-plan" / "scripts" / "lint_plan.py"),
                 "--plan", "spec/waves/plan-orphanwire.json",
                 "--blueprint", "spec/blueprint", "--json"],
                cwd=str(root), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_mount_node_present_before_build(self):
        """挂载必须在重建之前——否则接线文件进不了这一轮的构建图。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root, TASKS)
            plan = _gen(root)
        by = {t["id"]: t for t in plan["tasks"]}
        self.assertIn("reduce:mount-wiring", by)
        self.assertIn("reduce:mount-wiring", by["reduce:probe"]["parents"]); self.assertEqual(by["reduce:build-orphanwire"]["parents"], ["reduce:probe"])

    def test_empty_dispatch_sheet_yields_no_tasks(self):
        """条件波：compile#2 没判孤儿时任务集为空，属预期。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _blueprint(root, [])
            plan = _gen(root)
        ag = [t for t in plan["tasks"] if t.get("kind") == "agent"] if plan else []
        self.assertEqual(ag, [])

    def test_fork_turns_is_all(self):
        self.assertEqual(G.WAVE_FORK_TURNS.get("orphanwire"), "all")


class TestMountWiring(unittest.TestCase):
    def _run(self, root):
        return subprocess.run([PY, str(SCRIPTS / "mount_wiring.py"),
                               "--project", str(root), "--json"],
                              capture_output=True, text=True)

    def test_mounts_all_chunk_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w = root / "entry/src/main/ets/wiring"; w.mkdir(parents=True)
            for n in ("domain-main-p1", "seed-p1"):
                (w / (n + ".ets")).write_text("export function mount(): void {}\n", encoding="utf-8")
            r = self._run(root)
            body = (w / "WiringRoot.ets").read_text(encoding="utf-8")
        self.assertEqual(r.returncode, 0)
        self.assertIn("domain_main_p1()", body)
        self.assertIn("seed_p1()", body)
        self.assertNotIn("WiringRoot", body.split("export function")[0].replace("WiringRoot.ets", ""))

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w = root / "entry/src/main/ets/wiring"; w.mkdir(parents=True)
            (w / "a-p1.ets").write_text("export function mount(): void {}\n", encoding="utf-8")
            self._run(root); first = (w / "WiringRoot.ets").read_text(encoding="utf-8")
            self._run(root); second = (w / "WiringRoot.ets").read_text(encoding="utf-8")
        self.assertEqual(first, second)

    def test_no_chunks_still_emits_valid_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            r = self._run(root)
            body = (root / "entry/src/main/ets/wiring/WiringRoot.ets").read_text(encoding="utf-8")
        self.assertEqual(r.returncode, 0)
        self.assertIn("export function mountAllWiring", body)


if __name__ == "__main__":
    unittest.main()


class TestAttachToEntry(unittest.TestCase):
    """接线链的最后一跳：WiringRoot 必须接进 EntryAbility（AIPPT_915_test3 实证驱动）。

    事故：32 个 chunk 全部完成、24+ 个 owner-local 接线文件落盘、WiringRoot 聚合了 32 个
    import——而 compile#2b 仍判 graph-mismatch(3/249)，ratio 纹丝不动。因为**聚合根自己
    也是孤儿**：没有任何代码 import 它。参照运行的原话是「由 seed 根统一挂载」，此前只做了
    聚合、漏了接入应用入口，整条链（WiringRoot → 32 接线文件 → 246 孤儿）悬在构建图外。
    """

    ENTRY = "entry/src/main/ets/entryability/EntryAbility.ets"
    SRC = ("import { UIAbility } from '@kit.AbilityKit';\n"
           "import { hilog } from '@kit.PerformanceAnalysisKit';\n\n"
           "export default class EntryAbility extends UIAbility {\n"
           "  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {\n"
           "    hilog.info(0x0000, 'testTag', 'onCreate');\n"
           "  }\n}\n")

    def _setup(self, root: Path, chunks=2, entry=True):
        w = root / "entry/src/main/ets/wiring"; w.mkdir(parents=True)
        for i in range(chunks):
            (w / ("c%d.ets" % i)).write_text("export function mount(): void {}\n", encoding="utf-8")
        if entry:
            e = root / self.ENTRY; e.parent.mkdir(parents=True, exist_ok=True)
            e.write_text(self.SRC, encoding="utf-8")

    def _run(self, root):
        return subprocess.run([PY, str(SCRIPTS / "mount_wiring.py"),
                               "--project", str(root), "--json"],
                              capture_output=True, text=True)

    def test_attaches_import_and_call(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._setup(root)
            r = json.loads(self._run(root).stdout)
            body = (root / self.ENTRY).read_text(encoding="utf-8")
        self.assertEqual(r["attached"], "ok")
        self.assertIn("import { mountAllWiring } from '../wiring/WiringRoot';", body)
        self.assertIn("mountAllWiring();", body)
        # 调用必须在 onCreate 体内，不能落在类外
        self.assertLess(body.index("onCreate"), body.index("mountAllWiring();"))

    def test_idempotent_no_duplicate_injection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._setup(root)
            self._run(root)
            r2 = json.loads(self._run(root).stdout)
            body = (root / self.ENTRY).read_text(encoding="utf-8")
        self.assertEqual(r2["attached"], "already")
        self.assertEqual(body.count("mountAllWiring"), 2)   # 1 个 import + 1 次调用

    def test_no_chunks_means_no_attach(self):
        """没有接线文件时不该往入口塞空调用。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._setup(root, chunks=0)
            r = json.loads(self._run(root).stdout)
            body = (root / self.ENTRY).read_text(encoding="utf-8")
        self.assertTrue(r["attached"].startswith("skip"))
        self.assertNotIn("mountAllWiring", body)

    def test_missing_entry_does_not_break_the_chain(self):
        """EntryAbility 缺席只报原因、不抛错——挂载文件已生成，接入失败该由编译图门禁暴露。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._setup(root, entry=False)
            p = self._run(root); r = json.loads(p.stdout)
        self.assertEqual(p.returncode, 0)
        self.assertIn("skip", r["attached"])
