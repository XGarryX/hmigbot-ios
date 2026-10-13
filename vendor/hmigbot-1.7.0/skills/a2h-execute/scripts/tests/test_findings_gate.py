"""DevEco-830 A2 findings 销账门回归。立此闸的事实：830/test3 的 round0 findings 无门销账（100/67 条静默放行）。

E265②（缺省阻断）后的固定判据——实证：AIPPT_930_ds 的 findings-gate.json 是 mode=report-only /
passed=true / P1 119，119 条 P1 全部放行，交棒只记一条 warn：
  · 缺省 **blocking**：P0/P1 未销账 → exit 1；
  · 关阻断必须 gates.findings_blocking=false **且** gates.findings_blocking_off{by,reason} 署名，
    少一把或占位署名 → 关不掉，报告 switch_rejected 写明原因；关成了 blocking_off 在报告里显形；
  · 豁免逐条带责任人+理由：waivers.json（check 不许 `*`、file 不许匹配一切、单条不超 5 命中）、
    源码 `// A2H-WAIVE(<责任人>): <check> <理由>`（P0 不收行内）；打回的豁免 = 该 finding 回到 open；
  · severity 枚举外（非 P0/P1/P2）按阻断算，不当 P2 放行；
  · P2 进 backlog；auditfix 波尾挂 gate:round0-clear，fix-backlog 门等它；handoff_check 记 findings 项。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS)); sys.path.insert(0, str(SCRIPTS / "tests"))
import findings_gate as FG  # noqa: E402
import test_page_chunks as TPC  # noqa: E402


def _fixture(root: Path):
    """A.ets 第 1 行 P1 无豁免；第 3 行 P1 由上一行的新式标记豁免；Theme.ets P0 走 waivers.json；1 条 P2。"""
    rep = root / "spec/reports/round0"; rep.mkdir(parents=True)
    src = root / "entry/src/main/ets/pages"; src.mkdir(parents=True)
    (src / "A.ets").write_text(
        "Text('#123456')\n// A2H-WAIVE(ventiu): design-tokens 品牌色常量，设计确认保留\nText('#abcdef')\n",
        encoding="utf-8")
    (src / "Theme.ets").write_text("const X = '#ffffff'\n", encoding="utf-8")
    (rep / "alpha.json").write_text(json.dumps({"findings": [
        {"file": "entry/src/main/ets/pages/A.ets", "line": 1, "severity": "P1", "check": "design-tokens", "summary": "hex"},
        {"file": "entry/src/main/ets/pages/A.ets", "line": 3, "severity": "P1", "check": "design-tokens", "summary": "hex（上一行有豁免标记）"},
        {"file": "entry/src/main/ets/pages/Theme.ets", "line": 1, "severity": "P0", "check": "eval-call", "summary": "x"},
        {"file": "entry/src/main/ets/pages/A.ets", "line": 5, "severity": "P2", "check": "ohos-legacy-import", "summary": "p2"},
    ]}), encoding="utf-8")
    bp = root / "spec/blueprint"; bp.mkdir(parents=True, exist_ok=True)
    (bp / "findings-waivers.json").write_text(json.dumps({"waivers": [
        {"check": "eval-call", "file": "entry/**/Theme.ets", "waived_by": "ventiu", "reason": "常量表，非动态求值"}]}),
        encoding="utf-8")
    return bp


def _run(root: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / "findings_gate.py"), "--project", str(root), "--json", *flags],
                          capture_output=True, text=True, encoding="utf-8")


def _report(root: Path) -> dict:
    return json.loads((root / "spec/reports/findings-gate.json").read_text(encoding="utf-8"))


def _params(bp: Path, gates: dict) -> None:
    (bp / "workflow-params.json").write_text(json.dumps({"gates": gates}), encoding="utf-8")


def _findings(root: Path, items: list) -> Path:
    d = root / "spec/reports/round0"; d.mkdir(parents=True, exist_ok=True)
    (d / "alpha.json").write_text(json.dumps({"findings": items}), encoding="utf-8")
    (root / "spec/blueprint").mkdir(parents=True, exist_ok=True)
    return root / "spec/blueprint"


class TestBlockingByDefault(unittest.TestCase):
    def test_default_blocks_and_waivers_take_effect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _fixture(root)
            r = _run(root)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)      # E265②：缺省就拦，不再 exit 0
            out = json.loads(r.stdout); self.assertEqual(out["mode"], "blocking")
            rep = _report(root)
            self.assertEqual([f["line"] for f in rep["open"]], [1])     # 只剩第 1 行的 P1 未销账
            self.assertEqual(sorted(w["check"] for w in rep["waived"]), ["design-tokens", "eval-call"])
            self.assertEqual(sorted(w["waived_by"] for w in rep["waived"]), ["ventiu", "ventiu"])
            self.assertEqual([b["severity"] for b in rep["backlog"]], ["P2"])
            self.assertEqual(rep["waivers_rejected"], [])
            # next_batch 的 GATE_REPORT_SPECS 按 open_items 摘清单给 repair 任务书（E265①）——别名不能掉
            self.assertEqual(rep["open_items"], rep["open"])
            self.assertTrue((root / "spec/reports/findings-backlog.json").is_file())

    def test_clean_project_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _findings(root, [{"file": "a.ets", "line": 1, "severity": "P2", "check": "x"}])
            r = _run(root)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(json.loads(r.stdout)["ok"])

    def test_explicit_true_and_cli_flag_still_block(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); bp = _fixture(root)
            _params(bp, {"findings_blocking": True})
            self.assertEqual(_run(root).returncode, 1)
            self.assertEqual(_run(root, "--blocking").returncode, 1)

    def test_unknown_severity_counts_as_blocking(self):
        """severity 枚举只有 P0|P1|P2；枚举外 = findings 数据坏了，不能按 P2 放行。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _findings(root, [{"file": "a.ets", "line": 1, "severity": "minor", "check": "x"}])
            r = _run(root)
            self.assertEqual(r.returncode, 1, r.stdout)
            rep = _report(root)
            self.assertEqual(rep["counts"]["other"], 1); self.assertEqual(len(rep["open"]), 1)


class TestOffSwitchMustBeSigned(unittest.TestCase):
    """关阻断可以，但必须显式 + 署名 + 在报告里显形（不能静默关）。"""

    def _open_one(self, root: Path) -> Path:
        return _findings(root, [{"file": "a.ets", "line": 1, "severity": "P1", "check": "x"}])

    def test_false_alone_does_not_turn_it_off(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); bp = self._open_one(root)
            _params(bp, {"findings_blocking": False})
            r = _run(root)
            self.assertEqual(r.returncode, 1, r.stdout)
            out = json.loads(r.stdout)
            self.assertEqual(out["mode"], "blocking")
            self.assertIn("findings_blocking_off", out["switch_rejected"])
            self.assertIn("findings_blocking_off", _report(root)["switch_rejected"])
            self.assertIn("关闭阻断被拒", r.stderr)

    def test_placeholder_signature_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); bp = self._open_one(root)
            for off in ({"by": "auto", "reason": "先观察一轮再说"},        # 占位责任人
                        {"by": "ventiu", "reason": "暂缓"},               # 理由不足 8 字
                        {"by": "", "reason": "先观察一轮再说"}):
                _params(bp, {"findings_blocking": False, "findings_blocking_off": off})
                r = _run(root)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertEqual(json.loads(r.stdout)["mode"], "blocking")

    def test_signed_off_switch_shows_in_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); bp = self._open_one(root)
            _params(bp, {"findings_blocking": False,
                         "findings_blocking_off": {"by": "ventiu", "reason": "本轮只观察新检查器误报率"}})
            r = _run(root)
            self.assertEqual(r.returncode, 0, r.stdout)
            out = json.loads(r.stdout)
            self.assertEqual(out["mode"], "report-only")
            self.assertEqual(out["blocking_off"]["by"], "ventiu")
            self.assertEqual(_report(root)["blocking_off"]["by"], "ventiu")
            self.assertIn("ventiu", r.stderr)                    # 关了也要吆喝一声
            self.assertEqual(len(_report(root)["open"]), 1)      # 放行 ≠ 没问题：open 照记

    def test_cli_blocking_overrides_signed_off_switch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); bp = self._open_one(root)
            _params(bp, {"findings_blocking": False,
                         "findings_blocking_off": {"by": "ventiu", "reason": "本轮只观察新检查器误报率"}})
            self.assertEqual(_run(root, "--blocking").returncode, 1)


class TestWaiverDiscipline(unittest.TestCase):
    """豁免必须逐条留理由与责任人，不能整批 waive；写坏的豁免 = 没豁免（finding 回到 open）。"""

    def _one(self, root: Path, **over) -> Path:
        item = {"file": "entry/a.ets", "line": 1, "severity": "P1", "check": "design-tokens"}
        item.update(over)
        return _findings(root, [item])

    def _waivers(self, bp: Path, *rows) -> None:
        (bp / "findings-waivers.json").write_text(json.dumps({"waivers": list(rows)}), encoding="utf-8")

    def test_blanket_and_unsigned_waivers_rejected(self):
        base = {"check": "design-tokens", "file": "entry/a.ets", "waived_by": "ventiu", "reason": "品牌色常量保留"}
        cases = [({**base, "check": "*"}, "check"),
                 ({**base, "file": "*"}, "file"),
                 ({**base, "file": "**/*"}, "file"),
                 ({**base, "waived_by": "model"}, "waived_by"),
                 ({**base, "reason": "ok"}, "reason")]
        for row, field in cases:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td); bp = self._one(root)
                self._waivers(bp, row)
                r = _run(root)
                self.assertEqual(r.returncode, 1, "%s 应被打回: %s" % (field, r.stdout))
                rep = _report(root)
                self.assertEqual(len(rep["open"]), 1); self.assertEqual(rep["waived"], [])
                self.assertIn(field, rep["waivers_rejected"][0]["why"])

    def test_batch_waive_over_span_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bp = _findings(root, [{"file": "entry/f%d.ets" % i, "line": 1, "severity": "P1", "check": "design-tokens"}
                                  for i in range(FG.WAIVER_MAX_SPAN + 1)])
            self._waivers(bp, {"check": "design-tokens", "file": "entry/*.ets",
                               "waived_by": "ventiu", "reason": "整批品牌色，先不改"})
            r = _run(root)
            self.assertEqual(r.returncode, 1, r.stdout)
            rep = _report(root)
            self.assertEqual(len(rep["open"]), FG.WAIVER_MAX_SPAN + 1)   # 全部回到 open
            self.assertIn("整批 waive", rep["waivers_rejected"][0]["why"])
            self.assertEqual(rep["waiver_usage"], [])

    def test_span_at_limit_still_waives(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bp = _findings(root, [{"file": "entry/f%d.ets" % i, "line": 1, "severity": "P1", "check": "design-tokens"}
                                  for i in range(FG.WAIVER_MAX_SPAN)])
            self._waivers(bp, {"check": "design-tokens", "file": "entry/*.ets",
                               "waived_by": "ventiu", "reason": "五条同源，逐条核过"})
            self.assertEqual(_run(root).returncode, 0)
            self.assertEqual(_report(root)["waiver_usage"], [{"id": "W1", "used": FG.WAIVER_MAX_SPAN}])


class TestSourceMarker(unittest.TestCase):
    def _mark(self, root: Path, text: str, **over) -> Path:
        (root / "entry").mkdir(parents=True, exist_ok=True)
        (root / "entry/a.ets").write_text(text, encoding="utf-8")
        item = {"file": "entry/a.ets", "line": 2, "severity": "P1", "check": "safearea-layers"}
        item.update(over)
        return _findings(root, [item])

    def test_legacy_marker_without_owner_is_rejected(self):
        """ds 那两条 `// A2H-WAIVE: safearea-layers …` 是无主豁免——模型给自己开的条子，不再生效。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._mark(root, "// A2H-WAIVE: safearea-layers 本页无自有前景可避让\nColumn()\n")
            r = _run(root)
            self.assertEqual(r.returncode, 1, r.stdout)
            rep = _report(root)
            self.assertEqual(len(rep["open"]), 1); self.assertEqual(rep["waived"], [])
            self.assertIn("缺责任人", rep["waivers_rejected"][0]["why"])

    def test_signed_marker_waives_and_records_owner(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._mark(root, "// A2H-WAIVE(ventiu): safearea-layers 本页无自有前景可避让\nColumn()\n")
            self.assertEqual(_run(root).returncode, 0)
            rep = _report(root)
            self.assertEqual(len(rep["waived"]), 1)
            self.assertEqual(rep["waived"][0]["waived_by"], "ventiu")
            self.assertTrue(rep["waived"][0]["waiver"].startswith("source-marker@entry/a.ets:"))

    def test_star_marker_and_short_reason_rejected(self):
        for text, why in (("// A2H-WAIVE(ventiu): * 全都别管了 whatever\nColumn()\n", "整批豁免"),
                          ("// A2H-WAIVE(ventiu): safearea-layers 已确认\nColumn()\n", "理由不足"),
                          ("// A2H-WAIVE(auto): safearea-layers 本页无自有前景可避让\nColumn()\n", "占位词")):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                self._mark(root, text)
                r = _run(root)
                self.assertEqual(r.returncode, 1, text)
                self.assertIn(why, _report(root)["waivers_rejected"][0]["why"])

    def test_p0_cannot_be_waived_inline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._mark(root, "// A2H-WAIVE(ventiu): eval-call 这里是常量表不是动态求值\nColumn()\n",
                       severity="P0", check="eval-call")
            r = _run(root)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("P0 不接受行内豁免", _report(root)["waivers_rejected"][0]["why"])

    def test_file_level_marker_reads_head_lines(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._mark(root, "// A2H-WAIVE(ventiu): safearea-layers 本页无自有前景可避让\n" + "x\n" * 5,
                       line=0)
            self.assertEqual(_run(root).returncode, 0)
            self.assertEqual(len(_report(root)["waived"]), 1)

    def test_marker_beyond_head_window_does_not_waive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._mark(root, "x\n" * (FG.MARKER_HEAD_LINES + 2)
                       + "// A2H-WAIVE(ventiu): safearea-layers 本页无自有前景可避让\n", line=0)
            self.assertEqual(_run(root).returncode, 1)


class TestHandoffConsumesGate(unittest.TestCase):
    """E265⑦：交棒面与门同口径——未销账即 blocked；报告缺失也 blocked；署名关闭才降 warn。"""

    def _proj(self, td: str, gate: dict = None) -> Path:
        root = Path(td) / "proj"; (root / "spec/blueprint").mkdir(parents=True)
        (root / "spec/reports").mkdir(parents=True, exist_ok=True)
        if gate is not None:
            (root / "spec/reports/findings-gate.json").write_text(json.dumps(gate), encoding="utf-8")
        return root

    def _check(self, root: Path) -> dict:
        import handoff_check as H
        checks, facts = H.run_checks(root, root / "spec/blueprint")
        return {c["id"]: c for c in checks}

    def test_missing_report_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            by = self._check(self._proj(td))
            self.assertEqual(by["findings"]["status"], "blocked")
            self.assertIn("gate:round0-clear", by["findings"]["detail"])

    def test_open_findings_block(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._proj(td, {"mode": "blocking", "open": [{"check": "x"}] * 119,
                                   "counts": {"P2": 11}, "waived": [], "waivers_rejected": [{"why": "y"}]})
            by = self._check(root)
            self.assertEqual(by["findings"]["status"], "blocked")
            self.assertIn("119", by["findings"]["detail"])
            self.assertIn("豁免被打回 1 条", by["findings"]["detail"])

    def test_signed_off_switch_downgrades_to_warn_and_names_signer(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._proj(td, {"mode": "report-only", "open": [{"check": "x"}],
                                   "counts": {"P2": 0}, "waived": [],
                                   "blocking_off": {"by": "ventiu", "reason": "本轮只观察误报率"}})
            by = self._check(root)
            self.assertEqual(by["findings"]["status"], "warn")
            self.assertIn("ventiu", by["findings"]["detail"])

    def test_cleared_findings_ok(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._proj(td, {"mode": "blocking", "open": [], "counts": {"P2": 3},
                                   "waived": [{"check": "x"}]})
            self.assertEqual(self._check(root)["findings"]["status"], "ok")


class TestPlanWiring(unittest.TestCase):
    def test_auditfix_tail_has_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); TPC._blueprint(root)
            import os
            env = dict(os.environ); env["ARKTS_SKILL_DIR"] = str(SCRIPTS.parent)
            r = subprocess.run([sys.executable, str(SCRIPTS / "generate_waves.py"), "--blueprint", "spec/blueprint",
                                "--out", "spec/waves", "--wave", "auditfix", "--json"], capture_output=True, text=True,
                               cwd=str(root), env=env, timeout=180)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            plan = json.loads((root / "spec/waves/plan-auditfix.json").read_text(encoding="utf-8"))
            by = {t["id"]: t for t in plan["tasks"]}
            self.assertIn("gate:round0-clear", by); self.assertIn("--rerun", by["gate:round0-clear"]["run"])
            self.assertEqual(by["gate:round0-clear"]["parents"], ["reduce:build-auditfix"])
            self.assertIn("gate:round0-clear", by["gate:fix-backlog"]["parents"])


if __name__ == "__main__":
    unittest.main()
