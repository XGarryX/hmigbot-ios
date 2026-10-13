#!/usr/bin/env python3
"""F12 回归（AIPPT_930_token2 2026-09-20：一波里 4 份合法回执被校验器拒收 → RETRY）：

  (a) findings[].kind='ui_state' 等枚举外值 → 同义表机械归一（记 mechanical_fixes），不再 RETRY；
  (b) findings 是「按文件分组的对象」→ 摊平成数组、注入 file；
  (c) impl/fix 的 skipped[].finding_ref 接受正整数或非空字符串（E243：ID 真实性改由 land_results 按本任务书精确匹配）；
  (d) 装机面禁写声明进 fix: 类任务书（从 _wavelib.FORBIDDEN_GLOBS 取，不硬编码）；
  (e) escalated-ratio 只数「最新一波判决仍是 ESCALATED」的域——state_update --op domain 后波落 PASS 即翻回。

parse_agent_output 由 land_results 经 subprocess 调用，归一放在 parse_agent_output 自己的校验路径上，对任何调用方生效。
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
sys.path.insert(0, str(SCRIPTS))
import parse_agent_output as PAO  # noqa: E402
import assemble_prompt as AP  # noqa: E402
import state_update as SU  # noqa: E402
import gate_check as GC  # noqa: E402
import _wavelib as W  # noqa: E402

PY = sys.executable or "python3"
SCRIPT = SCRIPTS / "parse_agent_output.py"


def _run(schema: str, obj, *extra):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
        name = f.name
    try:
        p = subprocess.run([PY, str(SCRIPT), "--file", name, "--schema", schema, "--raw-json", "--json", *extra],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
    finally:
        os.unlink(name)
    out = None
    if p.returncode == 0:
        out = json.loads(p.stdout)
    return p.returncode, out, p.stderr


FINDING = {"file": "entry/src/main/ets/pages/Home.ets", "line": 10, "severity": "P1", "kind": "visual",
           "summary": "s", "fix": "f"}


class TestKindSynonyms(unittest.TestCase):
    def test_table(self):
        cases = {"ui_state": "visual", "UI": "visual", "layout": "visual", "style-mismatch": "visual", "theme": "visual",
                 "visual_regression": "visual", "navigation": "nav", "route": "nav", "router": "nav", "crash": "runtime",
                 "exception": "runtime", "runtime-leak": "runtime", "lint": "arkts", "arkts-strict": "arkts",
                 "compile": "arkts", "type_error": "arkts", "wire": "wiring", "contract": "wiring",
                 "something-else": "functional", "": "functional", None: "functional"}
        for raw, want in cases.items():
            self.assertEqual(PAO.normalize_finding_kind(raw), (want, True), repr(raw))
        for k in PAO.ENUM_FINDING_KIND:
            self.assertEqual(PAO.normalize_finding_kind(k), (k, False))

    def test_cli_unknown_kind_passes_with_trace(self):
        rc, out, err = _run("findings", {"domain": "home", "findings": [dict(FINDING, kind="ui_state")]})
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["findings"][0]["kind"], "visual")
        self.assertTrue(any("ui_state" in n and "visual" in n for n in out["mechanical_fixes"]))
        self.assertIn("mechanical:", err)

    def test_cli_valid_kind_untouched(self):
        rc, out, _ = _run("findings", {"domain": "home", "findings": [FINDING]})
        self.assertEqual(rc, 0)
        self.assertEqual(out["mechanical_fixes"], [])


class TestFindingsDictFlatten(unittest.TestCase):
    def test_unit(self):
        data = {"domain": "d", "findings": {
            "a.ets": [{"severity": "P0", "kind": "nav", "summary": "s", "fix": "f"},
                      {"file": "explicit.ets", "severity": "P2", "kind": "ui", "summary": "s", "fix": "f"}],
            "b.ets": {"severity": "P1", "kind": "runtime", "summary": "s", "fix": "f"},
        }}
        out, notes = PAO.normalize_findings(data)
        self.assertEqual([f["file"] for f in out["findings"]], ["a.ets", "explicit.ets", "b.ets"])
        self.assertEqual([f["kind"] for f in out["findings"]], ["nav", "visual", "runtime"])
        self.assertEqual(len(notes), 2)
        self.assertEqual(out["mechanical_fixes"], notes)
        self.assertIsInstance(data["findings"], dict)      # 不改入参

    def test_cli_dict_keyed_findings_pass(self):
        rc, out, err = _run("findings", {"domain": "common-basis", "findings": {
            "entry/src/main/ets/infra/shared/common-basis/A.ets": [
                {"severity": "P1", "kind": "functional", "summary": "s", "fix": "f"}]}})
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["findings"][0]["file"], "entry/src/main/ets/infra/shared/common-basis/A.ets")

    def test_missing_findings_still_rejected(self):
        rc, _, err = _run("findings", {"domain": "d"})
        self.assertEqual(rc, 1)
        self.assertIn("必填且须为对象数组", err)


class TestFindingRefIds(unittest.TestCase):
    BASE = {"task": "closure:r2:domain:home", "final_state": "PASS", "files": []}

    def test_impl_accepts_ids_by_shape(self):
        # E243：流水线自家 ID（P-DOM-…、APPP2-004、theme-receipt）此前被正则拒收；现只查形状
        for ref in (1, "3", "BK-4", "CL-012", "CV-001", "XYZAB-9", "P-DOM-AR-002", "APPP2-004", "theme-receipt", "invented"):
            rc, out, err = _run("impl", dict(self.BASE, skipped=[{"finding_ref": ref, "reason": "越界"}]))
            self.assertEqual(rc, 0, "%r: %s" % (ref, err))
        for ref in (0, -1, "", "   ", "x" * 201, None, True):
            rc, _, err = _run("impl", dict(self.BASE, skipped=[{"finding_ref": ref, "reason": "越界"}]))
            self.assertEqual(rc, 1, repr(ref))
            self.assertIn("finding_ref", err)

    def test_fix_keeps_refs(self):
        rc, out, err = _run("fix", {"domain": "home", "fixed": [], "skipped": [
            {"finding_ref": "CL-3", "reason": "r"}, {"finding_ref": "2", "reason": "r"}, {"finding_ref": " nope ", "reason": "r"}]})
        self.assertEqual(rc, 0, err)
        self.assertEqual([s["finding_ref"] for s in out["skipped"]], ["CL-3", 2, "nope"])

    def test_helper(self):
        self.assertTrue(PAO._valid_finding_ref("CL-001"))
        self.assertTrue(PAO._valid_finding_ref("P-DOM-AR-002"))
        self.assertTrue(PAO._valid_finding_ref(7))
        self.assertFalse(PAO._valid_finding_ref(True))
        self.assertFalse(PAO._valid_finding_ref(0))
        self.assertFalse(PAO._valid_finding_ref(""))


class TestInstallSurfaceLine(unittest.TestCase):
    def test_line_from_wavelib_fence(self):
        line = AP._install_surface_line()
        self.assertIn(AP.INSTALL_SURFACE_SENTENCE, line)
        self.assertEqual(AP.INSTALL_SURFACE_SENTENCE, "越界需求写 skipped 附 required_owner，禁止直接写这些文件")
        for g in W.FORBIDDEN_GLOBS:
            if g.startswith(("spec/", "AGENTS.md", ".agents/", ".codex/")):
                self.assertNotIn("`%s`" % g, line)
            else:
                self.assertIn("`%s`" % g, line)
        for must in ("EntryAbility.ets", "WiringRoot.ets", "resources/**", "module.json5", "pages/Index.ets"):
            self.assertIn(must, line)

    def test_fix_task_texts_carry_line(self):
        bp = {"domain_map": {"domains": [{"key": "home"}]},
              "ownership": {"owners": {"domain:home": ["entry/src/main/ets/features/home/**"]}},
              "contracts": {}}
        text = AP.brief_fix(bp, {"key": "home"})
        self.assertIn(AP.INSTALL_SURFACE_SENTENCE, text)
        self.assertIn("EntryAbility.ets", text)


class TestEscalatedRatioLatestVerdict(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp()
        os.chdir(self.tmp)                       # gate_check 读 spec/reports/fix-backlog.json 于 cwd

    def tearDown(self):
        os.chdir(self.cwd)

    def test_escalated_then_pass_not_counted(self):
        st = {"domains": {}}
        SU.op_domain(st, {"domain": "home", "final_state": "ESCALATED", "impl": "impl:home",
                          "escalation": {"reason": "sdk missing", "g_id": "G1"}})
        SU.op_domain(st, {"domain": "pay", "final_state": "ESCALATED", "impl": "impl:pay",
                          "escalation": {"reason": "blocked", "g_id": "G2"}})
        r = GC.check_escalated_ratio(st, {"gates": {"escalated_block_ratio": 0.1}}, None)
        self.assertEqual((r["verdict"], r["escalated"]), ("FAIL", ["home", "pay"]))
        SU.op_domain(st, {"domain": "home", "final_state": "PASS", "impl": "closure:r2:domain:home"})   # 后波修好了
        rec = st["domains"]["home"]
        self.assertEqual(rec["final_state"], "PASS")
        self.assertIsNone(rec["escalation"])                                   # 陈旧 escalation 清掉
        self.assertEqual([h["final_state"] for h in rec["final_state_history"]], ["ESCALATED", "PASS"])
        r = GC.check_escalated_ratio(st, {"gates": {"escalated_block_ratio": 0.6}}, None)
        self.assertEqual((r["verdict"], r["escalated"]), ("PASS", ["pay"]))
        self.assertEqual(r["ratio"], 0.5)

    def test_pass_then_escalated_counted(self):
        st = {"domains": {}}
        SU.op_domain(st, {"domain": "home", "final_state": "PASS", "impl": "impl:home"})
        SU.op_domain(st, {"domain": "home", "final_state": "ESCALATED", "impl": "auditfix:home",
                          "escalation": {"reason": "x", "g_id": "G"}})
        self.assertEqual(GC.check_escalated_ratio(st, {}, None)["escalated"], ["home"])

    def test_legacy_record_without_history(self):
        st = {"domains": {"a": {"final_state": "ESCALATED", "escalation": {"reason": "r"}}, "b": {"final_state": "PASS"}}}
        self.assertEqual(GC.check_escalated_ratio(st, {}, None)["escalated"], ["a"])

    def test_history_wins_over_stale_final_state(self):
        st = {"domains": {"a": {"final_state": "ESCALATED", "final_state_history": [
            {"final_state": "ESCALATED", "at": "t1"}, {"final_state": "PASS", "at": "t2"}]}}}
        self.assertEqual(GC.check_escalated_ratio(st, {}, None)["escalated"], [])


if __name__ == "__main__":
    unittest.main()
