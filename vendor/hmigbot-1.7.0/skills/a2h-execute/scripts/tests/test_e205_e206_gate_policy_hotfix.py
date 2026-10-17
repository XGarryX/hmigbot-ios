#!/usr/bin/env python3
"""E205/E206 回归（2026-09-21 行为级回退）：_wavelib.gate_policy（阶段门机械策略单点）、hotfix_ledger.py（可选留痕工具）、
handoff_check 呈报两者。

用户裁决（2026-09-21）：带欠账放行拉低产品质量——缺省（gates.stage_debt 未开）阶段门 FAIL 永远 exit 非 0、不写
gate-attempts.json / <gate>-debt.json，只给 retry_hint，主会话修到 PASS 为止；「修一次仍 FAIL → PASS_WITH_DEBT」只在
gates.stage_debt=true（仅设备/账号类门，需显式开启）时存在。handoff_check 仍把 *-debt.json 列进交棒消息（warn，不阻断）。

热改一项的口径在 E265⑦ 再次收紧：E219 撤回 E206 后「脚本报错 = 停机呈报，不得热改脚本/数据绕过」，
hotfix_ledger.py 只剩「人工裁定热改」的留痕用途。所以交棒时账上还有热改 = 要么是禁止行为、要么是人裁定的，
两者都不能只记 warn 放行——逐条带 approved_by + quote（人认领）才降 warn，否则 blocked。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import pathlib

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import _wavelib as W  # noqa: E402
import hotfix_ledger as HL  # noqa: E402

PY = sys.executable or "python3"


def _repair_touch(root):
    """E213：模拟「修过东西再重跑」——gate_policy 只把 spec/ 有新改动的重跑计为第 2 次尝试。"""
    import os, time
    p = pathlib.Path(root) / "spec" / "domains" / "_e213_repair.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("repaired", encoding="utf-8")
    t = time.time() + 5
    os.utime(p, (t, t))


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _j(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


class _Proj(unittest.TestCase):
    unattended = True
    stage_debt = False        # 缺省：不欠账；走欠账路径的用例显式置 True

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp) / "proj"
        (self.root / "spec/blueprint").mkdir(parents=True)
        gates = {"unattended": self.unattended}
        if self.stage_debt:
            gates["stage_debt"] = True
        _w(self.root / "spec/blueprint/workflow-params.json", {"gates": gates})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class GatePolicyUnattendedDefault(_Proj):
    """缺省（unattended，未开 stage_debt）：FAIL 每次都 exit 1，只给 retry_hint，不落任何计数/欠账文件。"""
    ITEMS = [{"check": "B2", "fails": ["app/Home.kt 未认领"]}]

    def test_fail_twice_never_passes_and_writes_nothing(self):
        for n in range(3):
            if n:
                _repair_touch(self.root)
            r = W.gate_policy(self.root, "demo", True, self.ITEMS, "跑 --op anchors", wave="plan")
            self.assertEqual((r["mode"], r["verdict"], r["exit_code"], r["debt_file"]), ("unattended", "FAIL", 1, None))
            self.assertEqual(r["retry_hint"]["items"], self.ITEMS); self.assertEqual(r["retry_hint"]["fix"], "跑 --op anchors")
            self.assertIn("直到 PASS", r["retry_hint"]["next"]); self.assertNotIn("PASS_WITH_DEBT（exit 0）", r["retry_hint"]["next"])
            self.assertTrue(W.gate_policy_line(r).startswith("retry_hint: "))
        self.assertFalse((self.root / "spec/state/gate-attempts.json").exists())
        self.assertFalse((self.root / "spec/reports").exists())
        self.assertEqual(W.load_adjudications(self.root), [])
        r = W.gate_policy(self.root, "demo", False, [], "f")
        self.assertEqual((r["verdict"], r["exit_code"], r["retry_hint"]), ("PASS", 0, None))
        self.assertFalse((self.root / "spec/state").exists())
        self.assertFalse(W.stage_debt(self.root))


class GatePolicyLib(_Proj):
    """gates.stage_debt=true（显式开启）：原 E205 机制——修一次仍 FAIL 记欠账 PASS_WITH_DEBT。
    F8：只对 DEBT_ALLOWED_GATES（auth-probe / cold-start / smoke-1page / b4 / device-smoke）生效，用例改用表内门名。"""
    stage_debt = True
    ITEMS = [{"check": "B2", "fails": ["app/Home.kt 未认领"]}]

    def test_fail_fail_pass_cycle(self):
        r1 = W.gate_policy(self.root, "auth-probe", True, self.ITEMS, "跑 --op anchors", wave="plan")
        self.assertEqual((r1["mode"], r1["attempt"], r1["verdict"], r1["exit_code"]), ("unattended", 1, "FAIL", 1))
        self.assertEqual(r1["retry_hint"]["items"], self.ITEMS); self.assertEqual(r1["retry_hint"]["fix"], "跑 --op anchors")
        self.assertIn("PASS_WITH_DEBT", r1["retry_hint"]["next"])
        self.assertIsNone(r1["debt_file"])
        self.assertEqual(W.load_gate_attempts(self.root)["auth-probe"]["attempts"], 1)
        self.assertTrue(W.gate_policy_line(r1).startswith("retry_hint: "))
        _repair_touch(self.root)
        r2 = W.gate_policy(self.root, "auth-probe", True, self.ITEMS, "跑 --op anchors", wave="plan", extra={"note": "x"})
        self.assertEqual((r2["attempt"], r2["verdict"], r2["exit_code"]), (2, "PASS_WITH_DEBT", 0))
        self.assertEqual(r2["debt_file"], "spec/reports/auth-probe-debt.json")
        debt = _j(self.root / "spec/reports/auth-probe-debt.json")
        self.assertEqual((debt["gate"], debt["attempt"], debt["items"], debt["note"]), ("auth-probe", 2, self.ITEMS, "x"))
        self.assertTrue(debt["rule"] and debt["generated_at"])
        adj = W.load_adjudications(self.root)
        self.assertEqual([(e["kind"], e["wave"], e["id"], e["by"]) for e in adj], [("auth-probe-debt", "plan", "gate:auth-probe", "auto-policy")])
        self.assertIn("PASS_WITH_DEBT: gate=auth-probe attempt=2", W.gate_policy_line(r2))
        # 第 3 次 FAIL 仍是 exit 0（绝不第二次非 0）
        r3 = W.gate_policy(self.root, "auth-probe", True, self.ITEMS, "f")
        self.assertEqual((r3["attempt"], r3["exit_code"]), (3, 0))
        # PASS：归零 + 撤欠账
        r4 = W.gate_policy(self.root, "auth-probe", False, [], "f")
        self.assertEqual((r4["verdict"], r4["exit_code"]), ("PASS", 0))
        self.assertEqual(W.load_gate_attempts(self.root)["auth-probe"]["attempts"], 0)
        self.assertFalse((self.root / "spec/reports/auth-probe-debt.json").exists())
        self.assertEqual(W.gate_policy_line(r4), "")

    def test_counters_are_per_gate_and_adj_id_override(self):
        W.gate_policy(self.root, "cold-start", True, [], "f")
        r = W.gate_policy(self.root, "smoke-1page", True, [], "f", adj_id="gate:custom")
        self.assertEqual(r["attempt"], 1)
        _repair_touch(self.root)
        W.gate_policy(self.root, "smoke-1page", True, [], "f", adj_id="gate:custom")
        self.assertEqual(W.load_adjudications(self.root)[0]["id"], "gate:custom")
        self.assertEqual({k: v["attempts"] for k, v in W.load_gate_attempts(self.root).items()}, {"cold-start": 1, "smoke-1page": 2})

    def test_items_capped_but_count_kept(self):
        items = [{"i": n} for n in range(80)]
        r = W.gate_policy(self.root, "b4", True, items, "f")
        self.assertEqual((len(r["retry_hint"]["items"]), r["retry_hint"]["failing"]), (60, 80))


class GatePolicyAttended(_Proj):
    unattended = False

    def test_attended_reads_and_writes_nothing(self):
        for _ in range(3):
            r = W.gate_policy(self.root, "demo", True, [{"x": 1}], "f")
            self.assertEqual((r["mode"], r["verdict"], r["exit_code"], r["attempt"]), ("attended", "FAIL", 1, 0))
            self.assertIsNone(r["retry_hint"])
        self.assertEqual(W.gate_policy(self.root, "demo", False, [], "f")["exit_code"], 0)
        self.assertFalse((self.root / "spec/state").exists())
        self.assertFalse((self.root / "spec/reports").exists())


class HotfixLedger(_Proj):
    def _cli(self, *args):
        return subprocess.run([PY, str(SCRIPTS / "hotfix_ledger.py"), "--project", str(self.root), *args],
                              capture_output=True, text=True, encoding="utf-8", timeout=60)

    def test_add_is_idempotent_by_file_and_error(self):
        r = self._cli("--add", "--file", "a2h-execute/scripts/x.py", "--error", "KeyError: 'foo'\n  File ...", "--note", "补默认值", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["created"])
        r = self._cli("--add", "--file", "a2h-execute/scripts/x.py", "--error", "KeyError: 'foo'", "--note", "再补一处", "--json")
        out = json.loads(r.stdout)
        self.assertFalse(out["created"]); self.assertEqual(out["count"], 1); self.assertEqual(out["entry"]["times"], 2)
        self.assertEqual(out["entry"]["note"], "再补一处")
        diff = self.root / "fix.diff"; diff.write_text("--- a\n+++ b\n", encoding="utf-8")
        r = self._cli("--add", "--file", "spec/blueprint/contracts.json", "--error", "ValueError: bad json", "--note", "修 JSON",
                      "--diff-file", str(diff))
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = HL.load_ledger(self.root)
        self.assertEqual(len(rows), 2); self.assertEqual(rows[1]["diff"], "--- a\n+++ b\n")
        self.assertEqual(rows[0]["error"], "KeyError: 'foo'")                  # 只取首行
        r = self._cli("--list")
        self.assertEqual(r.returncode, 0); self.assertIn("2 条热改记录", r.stdout); self.assertIn("(x2)", r.stdout)
        self.assertEqual(json.loads(self._cli("--list", "--json").stdout)["count"], 2)

    def test_usage_errors(self):
        self.assertEqual(self._cli("--add", "--file", "x").returncode, 2)          # 缺 --error
        self.assertEqual(self._cli("--add", "--list").returncode, 2)
        self.assertEqual(self._cli().returncode, 2)
        self.assertEqual(self._cli("--list").returncode, 0)                       # 空账可列
        self.assertFalse((self.root / "spec/state/hotfix-ledger.json").exists())


class HandoffReportsDebtsAndHotfixes(_Proj):
    def test_debts_warn_and_unclaimed_hotfixes_block(self):
        """E265⑦：阶段门欠账仍是 warn；无人认领的热改改判 blocked（E219 明令禁止热改绕过）。"""
        import handoff_check as H
        _w(self.root / "spec/reports/hygiene-debt.json", {"gate": "hygiene", "attempt": 2, "items": [{"check": "x"}], "failing": 3,
                                                          "rule": "r", "generated_at": "2026-09-20T00:00:00+00:00"})
        _w(self.root / "spec/reports/depth-gate-debt.json", {"gate": "depth-gate", "attempt": 2, "blocking": 5, "items": []})
        HL.add_entry(self.root, "a2h-execute/scripts/x.py", "KeyError: 'foo'", "补默认值")
        HL.add_entry(self.root, "spec/state/state.json", "ValueError: bad json", "修 JSON")
        checks, facts = H.run_checks(self.root, self.root / "spec/blueprint")
        by = {c["id"]: c for c in checks}
        self.assertEqual(by["stage-debts"]["status"], "warn"); self.assertIn("hygiene（attempt=2，3 项）", by["stage-debts"]["detail"])
        self.assertEqual(by["hotfixes"]["status"], "blocked")
        self.assertIn("热改记录 2 条、其中 2 条无人认领", by["hotfixes"]["detail"])
        self.assertIn("E219", by["hotfixes"]["detail"]); self.assertIn("approved_by", by["hotfixes"]["detail"])
        self.assertEqual(facts["hotfixes_unclaimed"], 2)
        self.assertNotIn("stage-debts", [c["id"] for c in checks if c["status"] == "blocked"])
        self.assertEqual([d["gate"] for d in facts["stage_debts"]], ["depth-gate", "hygiene"])
        msg = H.render_message(checks, facts)
        self.assertIn("- 欠账（阶段门 PASS_WITH_DEBT，gates.stage_debt）2 份：", msg)
        self.assertIn("spec/reports/hygiene-debt.json：gate=hygiene attempt=2 未清项=3", msg)
        self.assertIn("- 热改记录 2 条（spec/state/hotfix-ledger.json）：", msg)
        self.assertIn("a2h-execute/scripts/x.py ← 「KeyError: 'foo'」：补默认值（无人认领", msg)

    def test_claimed_hotfixes_downgrade_to_warn(self):
        """人亲自裁定的热改：补 approved_by + quote 后降 warn，并把原话摆出来让用户核对（E49 口径）。"""
        import handoff_check as H
        HL.add_entry(self.root, "a2h-execute/scripts/x.py", "KeyError: 'foo'", "补默认值")
        led = self.root / "spec/state/hotfix-ledger.json"
        rows = json.loads(led.read_text(encoding="utf-8"))
        rows[0]["approved_by"] = "ventiu"; rows[0]["quote"] = "这个脚本崩了，你改一下继续"
        led.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        checks, facts = H.run_checks(self.root, self.root / "spec/blueprint")
        by = {c["id"]: c for c in checks}
        self.assertEqual(by["hotfixes"]["status"], "warn")
        self.assertEqual(facts["hotfixes_unclaimed"], 0)
        self.assertIn("ventiu", by["hotfixes"]["detail"])
        self.assertNotIn("无人认领", H.render_message(checks, facts))

    def test_clean_project_says_none(self):
        import handoff_check as H
        checks, facts = H.run_checks(self.root, self.root / "spec/blueprint")
        by = {c["id"]: c for c in checks}
        self.assertEqual((by["stage-debts"]["status"], by["hotfixes"]["status"]), ("ok", "ok"))
        self.assertIn("- 热改记录 0 条（spec/state/hotfix-ledger.json）", H.render_message(checks, facts))


if __name__ == "__main__":
    unittest.main()


class TestE213NoRepairRerunDoesNotCount(unittest.TestCase):
    def test_same_failure_without_change_keeps_attempt(self):
        import json, os, tempfile, time
        from pathlib import Path
        import _wavelib
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "spec/blueprint").mkdir(parents=True); (root / "spec/domains").mkdir()
            (root / "spec/blueprint/workflow-params.json").write_text(json.dumps({"gates": {"unattended": True, "stage_debt": True}}), encoding="utf-8")
            (root / "spec/domains/a.md").write_text("x", encoding="utf-8")
            r1 = _wavelib.gate_policy(root, "device-smoke", True, ["i1", "i2"], "fix it")   # F8：欠账只对表内门生效
            self.assertEqual((r1["attempt"], r1["exit_code"]), (1, 1))
            r2 = _wavelib.gate_policy(root, "device-smoke", True, ["i2", "i1"], "fix it")     # 立刻重跑，什么都没改
            self.assertEqual((r2["attempt"], r2["verdict"], r2["exit_code"]), (1, "FAIL", 1))
            self.assertIn("E213", r2["retry_hint"]["note"])
            time.sleep(1.1); (root / "spec/domains/a.md").write_text("y", encoding="utf-8")   # 修过东西再跑
            r3 = _wavelib.gate_policy(root, "device-smoke", True, ["i1", "i2"], "fix it")
            self.assertEqual((r3["attempt"], r3["verdict"], r3["exit_code"]), (2, "PASS_WITH_DEBT", 0))
