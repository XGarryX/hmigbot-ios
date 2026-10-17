"""E73–E76 回归（AIPPT_0903 2026-09-05 r2 domains 实验暴露）：
E73 fence-audit 不是可修门；E74 compile 门 --rerun-reduce 连带复位 build 父节点 + repair 任务书附编译错误清单；
E75 旧接线块不渲染新形态 wires；E76 重入任务书附上次 verify_wires 未接线待办。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import next_batch as NB  # noqa: E402
import land_results as LR  # noqa: E402
import assemble_prompt as AP  # noqa: E402


class TestE73(unittest.TestCase):
    def test_fence_audit_not_blocking(self):
        self.assertFalse(NB._is_blocking_gate("gate:fence-audit"))
        for g in ("gate:compile-2", "reduce:build-domains", "reduce:pagemap", "gate:round0-clear"):
            self.assertTrue(NB._is_blocking_gate(g), g)


class TestE74(unittest.TestCase):
    PLAN = {"wave": "domains", "tasks": [
        {"id": "reduce:build-domains", "kind": "reduce", "run": "x", "parents": []},
        {"id": "gate:compile-2", "kind": "reduce", "run": "gate_check.py --gate compile#2 --build-log spec/reports/build-domains.log", "parents": ["reduce:build-domains"]},
        {"id": "gate:depth", "kind": "reduce", "run": "y", "parents": ["gate:compile-2"]}]}

    def test_rerun_compile_resets_build_parent(self):
        rl = {"reduce:build-domains": "REDUCE_PASS", "gate:compile-2": "REDUCE_FAIL"}
        self.assertEqual(LR._rerun_reset_ids(self.PLAN, "gate:compile-2", rl), ["reduce:build-domains"])
        self.assertEqual(LR._rerun_reset_ids(self.PLAN, "gate:depth", {"gate:depth": "REDUCE_FAIL"}), [])   # 非 compile 门不连带
        self.assertEqual(LR._rerun_reset_ids(self.PLAN, "gate:compile-2", {"gate:compile-2": "REDUCE_FAIL"}), [])  # build 未跑不动

    def test_compile_error_excerpt(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "spec/reports").mkdir(parents=True)
            (root / "spec/reports/build-domains.log").write_text(
                "\x1b[31m1 ERROR: \x1b[31m10605999 ArkTS Compiler Error\nError Message: Object is possibly 'undefined'. At File: /abs/entry/src/main/ets/pages/PPTFilePage.ets:56:20\n\x1b[39m\n"
                "> hvigor ERROR: Could not resolve \"./PromotedFragmentWorkPage\" from \"entry/src/main/ets/pages/PageRouteAdapter.ets\"\n", encoding="utf-8")
            txt = NB._compile_error_excerpt(root, self.PLAN["tasks"][1])
            self.assertIn("PPTFilePage.ets:56:20", txt); self.assertIn("possibly 'undefined'", txt)
            self.assertIn("PageRouteAdapter.ets ← 缺模块 ./PromotedFragmentWorkPage", txt)
            self.assertEqual(NB._compile_error_excerpt(root, {"run": "no-log-flag"}), "")


class TestE75E76(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.proj = Path(self.tmp.name)
        bp = self.proj / "spec/blueprint"; bp.mkdir(parents=True); (self.proj / "spec/reports").mkdir()
        wires = [{"kind": "nav-edge", "from": "HomeActivity", "to": "PayDialog", "consumer_domain": "home", "provider_domain": "pay", "owner_domain": "home", "trigger": "click"},
                 {"kind": "nav-edge", "from": "SplashActivity", "to": "HomeActivity", "consumer_domain": "splash", "provider_domain": "home", "owner_domain": "splash", "trigger": "onCreate"}]
        (bp / "contracts.json").write_text(json.dumps({"wires": wires}), encoding="utf-8")
        (bp / "page-names.json").write_text(json.dumps({"domains": {"home": {"HomeActivity": "HomePage"}, "pay": {"PayDialog": "PayPage"}, "splash": {"SplashActivity": "SplashPage"}}}), encoding="utf-8")
        (bp / "workflow-params.json").write_text(json.dumps({"project": {"root": str(self.proj)}}), encoding="utf-8")
        self.bp = {"_dir": bp, "contracts": {"wires": wires}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_e76_unwired_todo_by_role(self):
        rows = [{"kind": "nav-edge", "from": "HomeActivity", "to": "PayDialog", "consumer_domain": "home", "provider_domain": "pay", "trigger": "click", "status": "consumer-missing", "from_page": "HomePage", "to_page": "PayPage"},
                {"kind": "nav-edge", "from": "SplashActivity", "to": "HomeActivity", "consumer_domain": "splash", "provider_domain": "home", "trigger": "onCreate", "status": "both-missing", "from_page": "SplashPage", "to_page": "HomePage"}]
        (self.proj / "spec/reports/wires-check-domains.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
        home = AP._wires_text(self.bp, "home")
        self.assertIn("上次核销未接线", home)
        self.assertIn("消费方缺：`HomePage` 里没有 pushPathByName('PayPage')", home)
        self.assertIn("提供方缺：`pages/HomePage.ets` 未导出 `HomePageBuilder`", home)
        self.assertIn("禁止把导航改成 @Event/@Param 回调抛给父组件", home)
        splash = AP._wires_text(self.bp, "splash")
        self.assertIn("消费方缺：`SplashPage` 里没有 pushPathByName('HomePage')", splash)
        self.assertNotIn("提供方缺", splash)

    def test_e76_silent_without_report(self):
        self.assertNotIn("上次核销未接线", AP._wires_text(self.bp, "home"))

    def test_e75_legacy_block_skips_new_shape(self):
        # 旧块只认 consumer_page 形态；新形态 wires 不该渲染成 "? ← ?"
        self.assertEqual([w for w in AP._domain_wires(self.bp, "home") if w.get("consumer_page")], [])
        src = (SCRIPTS / "assemble_prompt.py").read_text(encoding="utf-8")
        self.assertIn('wires = [w for w in _domain_wires(bp, key) if w.get("consumer_page")]', src)


class TestE81StaleResultFirstAttempt(unittest.TestCase):
    """E81：attempt=1 的任务，result 文件 mtime 早于派发时刻 → 在途（不落账），而不是把上一轮同名旧回执落成 OK。"""
    def test_old_result_is_pending_not_landed(self):
        import os, time, subprocess
        from test_scheduler_kernel import KernelFixture, VALID_ALPHA, VALID_BETA
        class K(KernelFixture):
            def runTest(self): pass
        k = K(); k.setUp()
        try:
            k.write_plan(k.base_plan()); k.next_batch()
            k.write_result("alpha", VALID_ALPHA); k.write_result("beta", VALID_BETA)
            plan = json.loads(k.plan_path.read_text(encoding="utf-8"))
            alpha = next(t for t in plan["tasks"] if t["id"] == "impl:alpha")
            f = k.proj / alpha["result_path"]
            old = time.time() - 86400
            os.utime(f, (old, old))                                              # alpha 回执是"昨天"的旧文件
            proc = k._run(SCRIPTS / "land_results.py", "--plan", str(k.plan_path), "--state", str(k.state), "--json")
            out = json.loads(proc.stdout)
            self.assertEqual([x["id"] for x in out.get("landed") or []], ["impl:beta"], out)
            self.assertIn("impl:alpha", out.get("pending") or [], out)
        finally:
            k.tearDown()


class TestE84ReduceErrorKeepsAllLines(unittest.TestCase):
    def test_exec_reduce_keeps_multiline_stderr(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            node = {"run": "python3 -c \"import sys; sys.stderr.write('a: route X\\nb: route Y\\nc: route Z\\n'); sys.exit(1)\""}
            rc, err, _ = LR._exec_reduce(node, "/nonexistent-skills", Path(d))
            self.assertEqual(rc, 1)
            for s in ("route X", "route Y", "route Z"):
                self.assertIn(s, err)


class TestE82DryRun(unittest.TestCase):
    def test_dry_run_records_nothing(self):
        from test_scheduler_kernel import KernelFixture
        class K(KernelFixture):
            def runTest(self): pass
        k = K(); k.setUp()
        try:
            k.write_plan(k.base_plan())
            proc = k._run(SCRIPTS / "next_batch.py", "--plan", str(k.plan_path), "--state", str(k.state), "--dry-run", "--json")
            out = json.loads(proc.stdout)
            self.assertEqual(out["action"], "dispatch"); self.assertEqual(len(out["batch"]), 2)
            self.assertFalse((k.proj / "spec/state/dispatch.json").exists() and
                             (json.loads((k.proj / "spec/state/dispatch.json").read_text(encoding="utf-8")).get("waves") or {}).get("domains"))
            out2 = k.next_batch()                                                    # 真拍：同一批仍就绪、这次才记
            self.assertEqual([b["id"] for b in out2["batch"]], [b["id"] for b in out["batch"]])
            self.assertTrue((k.proj / "spec/state/dispatch.json").exists())
        finally:
            k.tearDown()


class TestE88PagemapExcerpt(unittest.TestCase):
    def test_excerpt_lists_all_duplicates(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "spec/reports").mkdir(parents=True)
            (root / "spec/reports/pagemap-check.json").write_text(json.dumps({"violations": [
                {"file": "/x/ets/pages/A.ets", "builder": "APageBuilder", "issue": "重名"}, {"file": "/x/ets/pages/Adapter.ets", "builder": "APageBuilder", "issue": "重名"},
                {"file": "/x/ets/pages/B.ets", "builder": "BPageBuilder", "issue": "重名"}, {"file": "/x/ets/pages/Adapter.ets", "builder": "BPageBuilder", "issue": "重名"}],
                "unregistered_pushes": {"Ghost": ["/x/ets/pages/C.ets"]}}), encoding="utf-8")
            txt = NB._pagemap_excerpt(root)
            self.assertIn("3 条", txt); self.assertIn("重名 APageBuilder：pages/A.ets, pages/Adapter.ets", txt); self.assertIn("未注册路由 'Ghost'", txt)
            self.assertEqual(NB._pagemap_excerpt(Path(d) / "nope"), "")


class TestE105AcCandidateCoercion(unittest.TestCase):
    def test_on_device_string_moves_to_oracle(self):
        import parse_agent_output as PO
        data = {"area": "x", "specFile": "spec/domains/x.md", "screens": [], "apis": [], "risks": [],
                "ac_candidates": [{"assertion": "a", "source_symbol": "A.b", "on_device": "ui_state"},
                                  {"assertion": "b", "on_device": "false"}, {"assertion": "c", "on_device": "persisted_value"},
                                  {"assertion": "d", "on_device": 3}]}
        errs = []
        PO.check_summary(data, errs)
        ac = data["ac_candidates"]
        self.assertEqual((ac[0]["oracle"], ac[0]["on_device"]), ("ui_state", True))
        self.assertEqual(ac[1]["on_device"], False)
        self.assertEqual((ac[2]["oracle"], ac[2]["on_device"]), ("persisted_value", False))
        self.assertTrue(any("ac_candidates[3].on_device" in e for e in errs))


class TestE110E116Unattended(unittest.TestCase):
    def test_grill_autodecide_picks_recommended(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "spec/blueprint").mkdir(parents=True); (root / "spec/state").mkdir()
            (root / "spec/blueprint/workflow-params.json").write_text(json.dumps({"gates": {"unattended": True}}), encoding="utf-8")
            (root / "spec/blueprint/decisions.json").write_text(json.dumps({"decisions": [
                {"id": "PD-C0-001", "status": "proposed", "options": [{"label": "完整复刻", "recommended": True}, {"label": "降档"}]},
                {"id": "PD-C3-001", "status": "proposed", "selected": "API 12", "choice": "按 Android targetSdk 对齐"},
                {"id": "PD-C9-001", "status": "proposed"},
                {"id": "PD-C1-001", "status": "approved", "approved_by": "user", "approved_at": "x"}]}), encoding="utf-8")
            G = SCRIPTS.parent.parent / "a2h-spec" / "scripts" / "grill_autodecide.py"
            r = subprocess.run([sys.executable, str(G), "--project", str(root), "--apply", "--allow-partial", "--json"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stderr + r.stdout)                       # 有 1 条无法裁
            out = json.loads(r.stdout); self.assertEqual(out["decided"], ["PD-C0-001", "PD-C3-001"]); self.assertEqual(out["unresolved"], ["PD-C9-001"])
            dec = {x["id"]: x for x in json.loads((root / "spec/blueprint/decisions.json").read_text(encoding="utf-8"))["decisions"]}
            self.assertEqual((dec["PD-C0-001"]["status"], dec["PD-C0-001"]["selected"], dec["PD-C0-001"]["approved_by"]), ("approved", "完整复刻", "auto-policy"))
            self.assertEqual(dec["PD-C9-001"]["status"], "proposed"); self.assertEqual(dec["PD-C1-001"]["approved_by"], "user")
            adj = json.loads((root / "spec/state/auto-adjudications.json").read_text(encoding="utf-8"))
            self.assertEqual([x["id"] for x in adj if x["kind"] == "grill-decision"], ["PD-C0-001", "PD-C3-001"])
            # E124：--default-first 下无推荐项但有 options 的卡按首项（default: true 优先）裁；无 options 的仍 unresolved
            dec_doc = json.loads((root / "spec/blueprint/decisions.json").read_text(encoding="utf-8"))
            dec_doc["decisions"].append({"id": "PD-C10-001", "status": "proposed", "options": [{"label": "A"}, {"label": "B", "default": True}, {"label": "C"}]})
            dec_doc["decisions"].append({"id": "PD-C11-001", "status": "proposed", "options": [{"label": "首项"}, {"label": "次项"}]})
            (root / "spec/blueprint/decisions.json").write_text(json.dumps(dec_doc), encoding="utf-8")
            r = subprocess.run([sys.executable, str(G), "--project", str(root), "--apply", "--default-first", "--allow-partial", "--json"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stderr + r.stdout); out = json.loads(r.stdout)
            self.assertEqual((out["defaulted"], out["unresolved"]), (["PD-C10-001", "PD-C11-001"], ["PD-C9-001"]))
            dec = {x["id"]: x for x in json.loads((root / "spec/blueprint/decisions.json").read_text(encoding="utf-8"))["decisions"]}
            self.assertEqual((dec["PD-C10-001"]["selected"], dec["PD-C10-001"]["approved_by"]), ("B", "auto-policy-default"))
            self.assertEqual(dec["PD-C11-001"]["selected"], "首项")
            adj = json.loads((root / "spec/state/auto-adjudications.json").read_text(encoding="utf-8"))
            self.assertEqual([x["id"] for x in adj if x["kind"] == "grill-decision-default"], ["PD-C10-001", "PD-C11-001"])

    def test_handoff_drift_exempts_A_stage_plans(self):
        src = (SCRIPTS / "handoff_check.py").read_text(encoding="utf-8")
        self.assertIn('if pp.name in ("plan-understand.json", "plan-specfix.json"):', src)

    def test_unattended_runner_helpers(self):
        import tempfile, importlib.util
        spec = importlib.util.spec_from_file_location("ur", SCRIPTS / "unattended_runner.py"); UR = importlib.util.module_from_spec(spec); spec.loader.exec_module(UR)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "spec/state").mkdir(parents=True); (root / "spec/waves").mkdir()
            log = root / "run.jsonl"
            log.write_text('{"type":"item.completed"}\n{"type":"turn.failed","error":{"message":"Selected model is at capacity"}}\n', encoding="utf-8")
            self.assertEqual(UR._tail_events(log)[0], "turn.failed"); self.assertIn("capacity", UR._tail_events(log)[1])
            # E123：主会话按铁律停在 escalate 也是 turn.completed → 必须识别为「非完成」
            log.write_text('{"type":"item.completed","item":{"type":"agent_message","text":"按铁律已停止：拍①返回 escalate\\n{\\"action\\": \\"escalate\\"}"}}\n{"type":"turn.completed"}\n', encoding="utf-8")
            last, _, msg = UR._tail_events(log); self.assertEqual(last, "turn.completed"); self.assertTrue(UR._ended_by_escalate(msg))
            log.write_text('{"type":"item.completed","item":{"type":"agent_message","text":"closeout 完成，handoff PASS"}}\n{"type":"turn.completed"}\n', encoding="utf-8")
            self.assertFalse(UR._ended_by_escalate(UR._tail_events(log)[2]))
            (root / "spec/waves/plan-domains.json").write_text(json.dumps({"wave": "domains", "tasks": []}), encoding="utf-8")
            (root / "spec/state/dispatch.json").write_text(json.dumps({"waves": {"domains": {"dispatched": {"impl:a": {"attempts": 2}, "impl:b": {"attempts": 1}}}}}), encoding="utf-8")
            (root / "spec/state/journal.json").write_text(json.dumps({"operation_outputs": [{"workflow_id": "domains", "task_id": "impl:a", "kind": "agent"}, {"workflow_id": "domains", "task_id": "impl:b", "kind": "agent"}]}), encoding="utf-8")
            inflight = UR._in_flight(root)
            self.assertEqual([(p.name, ids) for p, ids in inflight], [("plan-domains.json", ["impl:a"])])   # a 派 2 次落 1 次 → 孤儿

    def test_e116_closure_unowned_records_adjudication_when_unattended(self):
        src = (SCRIPTS / "generate_waves.py").read_text(encoding="utf-8")
        self.assertIn("closure-unowned-defer", src)


if __name__ == "__main__":
    unittest.main()


class TestE126E130UnattendedA3(unittest.TestCase):
    """E126/E127/E128（a3_finalize 无人值守裁决脚本化）与 E130（grill id 归一）。"""
    A3 = SCRIPTS.parent.parent / "a2h-plan" / "scripts" / "a3_finalize.py"
    G = SCRIPTS.parent.parent / "a2h-spec" / "scripts" / "grill_autodecide.py"

    def _root(self, d, domains, unattended=True):
        import tempfile  # noqa: F401
        root = Path(d); (root / "spec/blueprint").mkdir(parents=True); (root / "spec/state").mkdir(); (root / "spec/domains").mkdir()
        (root / "spec/blueprint/workflow-params.json").write_text(json.dumps({"gates": {"unattended": unattended}}), encoding="utf-8")
        (root / "spec/blueprint/domain-map.json").write_text(json.dumps({"version": 1, "domains": domains}), encoding="utf-8")
        return root

    def _run(self, root, *argv):
        import subprocess
        return subprocess.run([sys.executable, str(self.A3), "--blueprint", "spec/blueprint", *argv], cwd=root, capture_output=True, text=True)

    def test_e126_page_name_conflicts_auto_resolved(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = self._root(d, [
                {"key": "app-home", "title": "home", "pages": ["HomeActivity", "WorksPage"], "android_files": [], "spec_file": "spec/domains/app-home.md"},
                {"key": "app-mine", "title": "mine", "pages": ["HomeFragment", "WorksFragment", "MineFragment", "MineActivity"], "android_files": [], "spec_file": "spec/domains/app-mine.md"}])
            r = self._run(root, "--op", "page-names")
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            pn = json.loads((root / "spec/blueprint/page-names.json").read_text(encoding="utf-8"))
            self.assertEqual(pn["domains"]["app-home"], {"HomeActivity": "HomePage", "WorksPage": "WorksPage"})
            self.assertEqual(pn["domains"]["app-mine"], {"HomeFragment": "HomeFragmentPage", "WorksFragment": "WorksFragmentPage", "MineFragment": "MineFragmentPage", "MineActivity": "MinePage"})
            self.assertEqual(set(pn["auto_resolved"]), {"HomeFragment", "WorksFragment", "MineFragment"})
            adj = json.loads((root / "spec/state/auto-adjudications.json").read_text(encoding="utf-8"))
            self.assertEqual([x["kind"] for x in adj], ["page-name-auto"])
            # 非无人值守且无 --auto-resolve → 仍 FAIL
            (root / "spec/blueprint/workflow-params.json").write_text(json.dumps({"gates": {}}), encoding="utf-8")
            r = self._run(root, "--op", "page-names"); self.assertNotEqual(r.returncode, 0); self.assertIn("命名冲突", r.stderr)

    def test_e128_auto_split_partitions_files_and_pages(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            files = ["app/src/main/java/com/x/works/W%02d.kt" % i for i in range(24)] + ["app/src/main/java/com/x/tpl/T%02d.kt" % i for i in range(20)]
            files += ["app/src/main/java/com/x/works/WorksPage.kt", "app/src/main/java/com/x/tpl/TemplatePage.kt"]
            root = self._root(d, [
                {"key": "app-big", "title": "big", "pages": ["WorksPage", "TemplatePage", "_promoted_page_x"], "android_files": files, "spec_file": "spec/domains/app-big.md", "complexity": 10},
                {"key": "app-small", "title": "small", "pages": ["SmallPage"], "android_files": ["app/src/main/java/com/x/s/SmallPage.kt"], "spec_file": "spec/domains/app-small.md"}])
            (root / "spec/domains/app-big.md").write_text("# big\n", encoding="utf-8"); (root / "spec/domains/app-small.md").write_text("# small\n", encoding="utf-8")
            r = self._run(root, "--op", "split", "--auto")
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            dm = {x["key"]: x for x in json.loads((root / "spec/blueprint/domain-map.json").read_text(encoding="utf-8"))["domains"]}
            self.assertNotIn("app-big", dm); self.assertIn("app-small", dm)
            kids = [dm["app-big-1"], dm["app-big-2"]]
            self.assertEqual(sorted(sum((k["android_files"] for k in kids), [])), sorted(files))        # 父文件恰好各归一处
            self.assertEqual(sorted(sum((k["pages"] for k in kids), [])), ["TemplatePage", "WorksPage", "_promoted_page_x"])
            self.assertTrue(all(len(k["android_files"]) <= 40 for k in kids))
            self.assertIn("WorksPage", [p for k in kids for p in k["pages"] if any(f.endswith("WorksPage.kt") for f in k["android_files"])])   # 页面跟随同名文件
            self.assertTrue((root / "spec/blueprint/a3-split-auto.json").is_file())
            adj = json.loads((root / "spec/state/auto-adjudications.json").read_text(encoding="utf-8"))
            self.assertEqual([(x["kind"], x["id"]) for x in adj], [("split-auto", "app-big")])
            r = self._run(root, "--op", "split", "--auto"); self.assertEqual(r.returncode, 0); self.assertIn("无需拆分", r.stdout)

    def test_e127_acceptance_resolves_by_symbol_and_drops_rest_when_unattended(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = self._root(d, [
                {"key": "pay-misc", "title": "pay", "pages": [], "android_files": ["app/src/main/java/com/x/pay/PayUtil.kt"], "spec_file": "spec/domains/pay-misc.md"},
                {"key": "app-tpl-1", "title": "tpl", "pages": ["MoreDialog"], "android_files": ["app/src/main/java/com/x/tpl/MoreDialog.kt"], "spec_file": "spec/domains/app-tpl-1.md"}])
            (root / "spec/blueprint/contracts.json").write_text(json.dumps({"acceptance": []}), encoding="utf-8")
            res = root / "spec/waves/results/understand"; res.mkdir(parents=True)
            (res / "app-tpl.json").write_text(json.dumps({"ac_candidates": [
                {"assertion": "更多菜单显示三行", "source_symbol": "MoreDialog.initView"},          # 结果文件域 app-tpl 已拆没 → 按类名归 app-tpl-1
                {"assertion": "工具类可用", "source_symbol": "PayUtil.format"},                    # 按 android_files 同名文件归 pay-misc
                {"assertion": "无处可归", "source_symbol": "GhostClass.run"}]}), encoding="utf-8")   # 归不了 → 无人值守弃单留痕
            r = self._run(root, "--op", "acceptance")
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            acc = json.loads((root / "spec/blueprint/contracts.json").read_text(encoding="utf-8"))["acceptance"]
            self.assertEqual(sorted((a["domain"], a["anchor"]["source_symbol"]) for a in acc), [("app-tpl-1", "MoreDialog.initView"), ("pay-misc", "PayUtil.format")])
            adj = json.loads((root / "spec/state/auto-adjudications.json").read_text(encoding="utf-8"))
            self.assertEqual([x["kind"] for x in adj], ["ac-unassigned-drop"]); self.assertEqual(adj[0]["detail"][0]["source_symbol"], "GhostClass.run")
            # 有人值守：归不了的仍 FAIL
            (root / "spec/blueprint/workflow-params.json").write_text(json.dumps({"gates": {}}), encoding="utf-8")
            r = self._run(root, "--op", "acceptance"); self.assertNotEqual(r.returncode, 0); self.assertIn("无法归属", r.stderr)

    def test_e130_grill_ids_normalized(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "spec/blueprint").mkdir(parents=True); (root / "spec/state").mkdir()
            (root / "spec/blueprint/decisions.json").write_text(json.dumps({"decisions": [
                {"id": "D0", "status": "proposed", "options": [{"label": "A", "recommended": True}]},
                {"id": "D-C1", "status": "proposed", "options": [{"label": "B", "recommended": True}]},
                {"id": "PD-C2-U1-001", "status": "proposed", "options": [{"label": "C", "recommended": True}]}]}), encoding="utf-8")
            r = subprocess.run([sys.executable, str(self.G), "--project", str(root), "--apply", "--normalize-ids", "--allow-partial", "--json"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout); out = json.loads(r.stdout)
            self.assertEqual(out["renamed"], {"D0": "PD-ROOT-AUTO-001", "D-C1": "PD-C1-AUTO-001"})
            dec = json.loads((root / "spec/blueprint/decisions.json").read_text(encoding="utf-8"))["decisions"]
            self.assertEqual([x["id"] for x in dec], ["PD-ROOT-AUTO-001", "PD-C1-AUTO-001", "PD-C2-U1-001"]); self.assertEqual(dec[0]["orig_id"], "D0")
            adj = json.loads((root / "spec/state/auto-adjudications.json").read_text(encoding="utf-8"))
            self.assertEqual([x["kind"] for x in adj][:2], ["grill-id-normalized", "grill-id-normalized"])

    def test_e131_anchors_auto_filled(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            files = ["app/src/main/java/com/x/splash/SplashActivity.kt", "app/src/main/java/com/x/splash/SplashViewModel.kt",
                     "app/src/main/java/com/x/splash/SplashRepository.kt", "app/src/main/java/com/x/splash/AgreementBean.kt",
                     "app/src/main/java/com/x/splash/AdHelper.kt", "app/src/main/res/layout/activity_splash.xml"]
            root = self._root(d, [
                {"key": "app-splash", "title": "s", "tier": "core", "complexity": 235.7, "pages": ["SplashActivity"], "android_files": files, "android_anchors": [], "spec_file": "spec/domains/app-splash.md"},
                {"key": "app-tips", "title": "t", "tier": "peripheral", "complexity": 20, "pages": ["TipsActivity"], "android_files": ["app/src/main/java/com/x/TipsActivity.kt"], "android_anchors": [], "spec_file": "spec/domains/app-tips.md"},
                {"key": "app-done", "title": "d", "tier": "core", "pages": [], "android_files": ["x.kt"], "android_anchors": [{"role": "page", "path": "x.kt"}], "spec_file": "spec/domains/app-done.md"}])
            r = self._run(root, "--op", "anchors", "--only-complex")
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            dm = {x["key"]: x for x in json.loads((root / "spec/blueprint/domain-map.json").read_text(encoding="utf-8"))["domains"]}
            roles = {a["path"].split("/")[-1]: a["role"] for a in dm["app-splash"]["android_anchors"]}
            self.assertEqual(roles, {"SplashActivity.kt": "page", "SplashViewModel.kt": "viewmodel", "SplashRepository.kt": "repository",
                                     "AgreementBean.kt": "model", "AdHelper.kt": "util", "activity_splash.xml": "layout"})
            self.assertEqual(dm["app-tips"]["android_anchors"], [])                       # --only-complex 不碰周边域
            self.assertEqual(dm["app-done"]["android_anchors"], [{"role": "page", "path": "x.kt"}])   # 已有的不覆盖
            adj = json.loads((root / "spec/state/auto-adjudications.json").read_text(encoding="utf-8"))
            self.assertEqual([(x["kind"], x["detail"]) for x in adj], [("anchors-auto", {"app-splash": 6})])
            r = self._run(root, "--op", "anchors"); self.assertEqual(r.returncode, 0)
            dm = {x["key"]: x for x in json.loads((root / "spec/blueprint/domain-map.json").read_text(encoding="utf-8"))["domains"]}
            self.assertEqual(dm["app-tips"]["android_anchors"], [{"role": "page", "path": "app/src/main/java/com/x/TipsActivity.kt"}])


class TestE132DepthGateUnattended(unittest.TestCase):
    def _findings(self):
        return [
            {"rule": "SPEC.UNCOVERED_ANCHOR_FILE", "severity": "blocking", "subject": "app/src/main/java/x/ScreenUtils.java", "subject_ref": "app-activity.md", "detail": "无 AC 指向", "fix_hint": "补 AC"},
            {"rule": "SPEC.INSTANCE_UNACCOUNTED", "severity": "blocking", "subject": "app-activity.md::numeric_const", "subject_ref": "x.kt:3", "detail": "3 个命名常量未被任何 AC 交代：const:A", "fix_hint": "补 AC"},
            {"rule": "SPEC.UNCOVERED_ANCHOR_FILE", "severity": "blocking", "subject": "pay/src/main/java/x/PayContants.kt", "subject_ref": "pay-basis.md", "detail": "无 AC 指向", "fix_hint": "补 AC"},
            {"rule": "SPEC.MANIFEST_ACTIVITY_SDK_SHELL", "severity": "blocking", "subject": "com.mobile.auth.LoginAuthActivity", "subject_ref": None, "detail": "x", "fix_hint": "y"},
            {"rule": "SPEC.KIND_LIKELY_MISSING", "severity": "advisory", "subject": "app-activity.md::render", "subject_ref": "app-activity.md", "detail": "建议", "fix_hint": "z"}]

    def test_emit_spec_tasks_groups_blocking_by_domain(self):
        import tempfile, importlib.util
        spec = importlib.util.spec_from_file_location("lc132", SCRIPTS.parent.parent / "a2h-spec" / "scripts" / "lint_coverage.py"); LC = importlib.util.module_from_spec(spec); spec.loader.exec_module(LC)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "spec/blueprint").mkdir(parents=True); (root / "spec/reports").mkdir()
            (root / "spec/blueprint/domain-map.json").write_text(json.dumps({"domains": [
                {"key": "app-activity", "pages": ["MemberCenterActivitiy", "RefundProgressActivity"]}, {"key": "pay-basis", "pages": []}]}), encoding="utf-8")
            (root / "spec/reports/spec-tasks.json").write_text(json.dumps({"domains": {"app-guide": ["GuideActivity"]}, "min_ratio": 0.4}), encoding="utf-8")
            tasks = LC.emit_spec_tasks(str(root), self._findings(), str(root / "spec/domains"))
            self.assertEqual(tasks["domains"], {"app-guide": ["GuideActivity"], "app-activity": ["MemberCenterActivitiy", "RefundProgressActivity"], "pay-basis": ["PayContants"]})
            self.assertEqual(tasks["depth_gate_domains"], ["app-activity", "pay-basis"])
            self.assertEqual([f["rule"] for f in tasks["depth_gate_findings"]["app-activity"]], ["SPEC.UNCOVERED_ANCHOR_FILE", "SPEC.INSTANCE_UNACCOUNTED"])
            self.assertEqual(len(tasks["depth_gate_findings"]["_project"]), 1)          # manifest 项无域归属，留 _project（欠账面）
            self.assertEqual(tasks["min_ratio"], 0.4)                                     # 既有账面保留
            # 任务书渲染
            sys.path.insert(0, str(SCRIPTS)); import assemble_prompt as AP
            bp = {"_dir": root / "spec/blueprint", "workflow_params": {}}
            txt = AP._depth_gate_findings_text(bp, {"key": "app-activity"})
            self.assertIn("### 深度门判定", txt); self.assertIn("UNCOVERED_ANCHOR_FILE：app/src/main/java/x/ScreenUtils.java", txt); self.assertIn("const:A", txt)
            self.assertEqual(AP._depth_gate_findings_text(bp, {"key": "app-guide"}), "")

    def test_depth_gate_debt_records_adjudication(self):
        import subprocess, tempfile
        G = SCRIPTS.parent.parent / "a2h-plan" / "scripts" / "depth_gate_debt.py"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "spec/.a2h").mkdir(parents=True); (root / "spec/state").mkdir()
            (root / "spec/.a2h/open-findings.json").write_text(json.dumps({"version": 1, "sections": {"spec/lint_coverage": {"findings": self._findings(), "context": {}}}}), encoding="utf-8")
            # E266⑥ 给 depth_gate_debt 加了「必须真派过 specfix 返工」的前置；本用例验的是记账与留痕本身，
            # 用 --min-specfix-rounds 0 关掉前置（前置的正反例在 a2h-plan 的 test_e266_depth_gate_rework_first 里）。
            r = subprocess.run([sys.executable, str(G), "--project", str(root), "--apply", "--json",
                                "--min-specfix-rounds", "0"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout); out = json.loads(r.stdout)
            self.assertEqual((out["blocking"], out["by_rule"]["SPEC.UNCOVERED_ANCHOR_FILE"], out["by_domain"]), (4, 2, {"_project": 1, "app-activity": 2, "pay-basis": 1}))
            self.assertTrue((root / "spec/reports/depth-gate-debt.json").is_file())
            adj = json.loads((root / "spec/state/auto-adjudications.json").read_text(encoding="utf-8"))
            self.assertEqual([(x["kind"], x["id"]) for x in adj], [("depth-gate-debt", "gate:a2-depth")])
            (root / "spec/.a2h/open-findings.json").write_text(json.dumps({"version": 1, "sections": {"spec/lint_coverage": {"findings": []}}}), encoding="utf-8")
            self.assertEqual(subprocess.run([sys.executable, str(G), "--project", str(root)], capture_output=True, text=True).returncode, 1)

    def test_runner_markers_cover_plan_stage_stop(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ur132", SCRIPTS / "unattended_runner.py"); UR = importlib.util.module_from_spec(spec); spec.loader.exec_module(UR)
        self.assertTrue(UR._ended_by_escalate("A2 深度 lint 仍失败，依据 a2h-plan §1b 必须升级并停止。"))
        self.assertFalse(UR._ended_by_escalate("closeout 完成：handoff-check BLOCKED（escalated-ratio 0.27>0.1 记欠账）"))   # E123b：跑完但带 escalated-ratio 不算 escalate
        self.assertTrue(UR._ended_by_escalate("next_batch 返回 escalate，原样输出升级材料"))


class TestE137WiringOwnerInfra(unittest.TestCase):
    def test_wiring_owner_falls_back_to_infra_prefix(self):
        sys.path.insert(0, str(SCRIPTS)); import assemble_prompt as AP
        bp = {"ownership": {"owners": {"infra:app-basis": ["entry/src/main/ets/infra/shared/app-basis/**"], "domain:app-home": ["entry/src/main/ets/pages/HomePage.ets"]}}}
        self.assertEqual(AP._wiring_owner_files(bp, "app-basis"), ["entry/src/main/ets/infra/shared/app-basis/**"])
        self.assertEqual(AP._wiring_owner_files(bp, "app-home"), ["entry/src/main/ets/pages/HomePage.ets"])
        self.assertEqual(AP._wiring_owner_files(bp, "ghost"), [])
        bp["ownership"]["owners"]["seed"] = ["entry/src/main/ets/pages/Index.ets", "entry/src/main/ets/entryability/EntryAbility.ets"]
        bp["ownership"]["mainloop_owned"] = ["entry/src/main/ets/wiring/WiringRoot.ets"]
        self.assertEqual(AP._wiring_owner_files(bp, "app-entry"), sorted(["entry/src/main/ets/pages/Index.ets", "entry/src/main/ets/entryability/EntryAbility.ets", "entry/src/main/ets/wiring/WiringRoot.ets"]))   # E137b


class TestE138E141PostAcceptanceFixes(unittest.TestCase):
    def test_e139_excerpt_groups_all_errors_and_repair_limit(self):
        import tempfile
        sys.path.insert(0, str(SCRIPTS)); import next_batch as NB
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "spec/reports").mkdir(parents=True)
            lines = []
            for i in range(20):
                lines.append("%d ERROR: ArkTS Compiler Error\nError Message: Type 'A' is not assignable to type 'B'. At File: /p/entry/src/main/ets/pages/P%d.ets:%d:5\n" % (i, i % 3, i))
            lines.append("21 ERROR: 10605008 ArkTS Compiler Error\nError Message: Use explicit types instead of \"any\", \"unknown\" (arkts-no-any-unknown) At File: /p/entry/src/main/ets/infra/shared/common-misc/GsonExt.ets:91:32\n")
            (root / "spec/reports/build-x.log").write_text("".join(lines), encoding="utf-8")
            ex = NB._compile_error_excerpt(root, {"run": "python3 gate_check.py --build-log spec/reports/build-x.log"})
            self.assertIn("共 21 条 / 4 个文件", ex); self.assertIn("GsonExt.ets:91:32", ex); self.assertIn("arkts-no-any-unknown", ex)   # 尾部 strict 错不再被 cap 掉
            self.assertIn("P0.ets（7 条）", ex)
            ex2 = NB._compile_error_excerpt(root, {"run": "python3 gate_check.py --build-log spec/reports/build-x.log"}, cap=5)
            self.assertIn("另 16 条", ex2)
            j = {"operation_outputs": [
                {"workflow_id": "domains", "task_id": "gate:compile-2", "kind": "reduce", "error": "gate compile#2: errors=16 threshold=33"},
                {"workflow_id": "domains", "task_id": "gate:compile-2", "kind": "reduce", "error": "gate compile#2: errors=1 threshold=33"}]}
            # E266（用户裁决「一轮不够就修两轮，最多修两轮」）：上限改为无条件 2 轮——
            # 旧的「有进展才给第 2 轮」依赖错误串里抓得到 errors=<n>，只有编译门满足，
            # depth / interface / wires-check 这些质量门于是永远只有 1 轮，与裁定不符。
            self.assertEqual(NB._repair_limit(j, "domains", "gate:compile-2", None), 2)
            j["operation_outputs"][1]["error"] = "gate compile#2: errors=16 threshold=33"
            self.assertEqual(NB._repair_limit(j, "domains", "gate:compile-2", None), 2)     # 没进展也给满 2 轮
            self.assertEqual(NB._repair_limit({"operation_outputs": []}, "domains", "gate:compile-2", None), 2)

    def test_e138_backfill_refs_adds_missing_resources(self):
        import tempfile, importlib.util
        spec = importlib.util.spec_from_file_location("sr138", SCRIPTS / "seed_resources.py"); SR = importlib.util.module_from_spec(spec); spec.loader.exec_module(SR)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); el = root / "entry/src/main/resources/base/element"; el.mkdir(parents=True); (root / "entry/src/main/resources/base/media").mkdir()
            (el / "string.json").write_text(json.dumps({"string": [{"name": "app_name", "value": "AIPPT"}]}), encoding="utf-8")
            (el / "color.json").write_text(json.dumps({"color": [{"name": "c_primary", "value": "#FF112233"}]}), encoding="utf-8")
            (el / "float.json").write_text(json.dumps({"float": []}), encoding="utf-8")
            (root / "spec/baseline").mkdir(parents=True)
            (root / "spec/baseline/resource-index.json").write_text(json.dumps({"texts": {"确定": "btn_ok"}, "colors": {"#FFABCDEF": "c_accent"}, "dims": {}}), encoding="utf-8")
            ets = root / "entry/src/main/ets/pages"; ets.mkdir(parents=True)
            (ets / "A.ets").write_text("Text($r('app.string.app_name')); Text($r('app.string.btn_ok')); Text($r('app.string.title_settings'))\n"
                                       ".fontColor($r('app.color.c_accent')).backgroundColor($r('app.color.c_ghost')).width($r('app.float.w_card'))\n"
                                       "Image($r('app.media.ic_missing'))\n", encoding="utf-8")
            rep = SR.backfill_refs(root, "entry", root / "entry/src/main/ets")
            added = {(a["kind"], a["name"]): a for a in rep["added"]}
            self.assertEqual(set(added), {("string", "btn_ok"), ("string", "title_settings"), ("color", "c_accent"), ("color", "c_ghost"), ("float", "w_card"), ("media", "ic_missing")})
            self.assertEqual((added[("string", "btn_ok")]["value"], added[("string", "btn_ok")]["placeholder"]), ("确定", False))   # 反查台账
            self.assertEqual(added[("string", "title_settings")]["value"], "settings")                                            # 人话化
            self.assertEqual((added[("color", "c_accent")]["value"], added[("color", "c_ghost")]["placeholder"]), ("#FFABCDEF", True))
            self.assertEqual(rep["placeholders"], 3); self.assertEqual(rep["unresolved"], [])                       # E155：缺图给占位 PNG
            self.assertTrue((root / "entry/src/main/resources/base/media/ic_missing.png").is_file())
            names = {r["name"] for r in json.loads((el / "string.json").read_text(encoding="utf-8"))["string"]}
            self.assertEqual(names, {"app_name", "btn_ok", "title_settings"})
            self.assertTrue((root / "spec/reports/resource-backfill.json").is_file())

    def test_e140_closure_backlog_includes_unmigrated_classes(self):
        import tempfile, importlib.util
        spec = importlib.util.spec_from_file_location("cb140", SCRIPTS / "closure_backlog.py"); CB = importlib.util.module_from_spec(spec); spec.loader.exec_module(CB)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); bp = root / "spec/blueprint"; bp.mkdir(parents=True)
            (bp / "domain-map.json").write_text(json.dumps({"domains": [
                {"key": "app-home", "android_files": ["app/src/main/java/x/HomeActivity.kt", "app/src/main/java/x/HomeVM.kt"]},
                {"key": "net-basis", "android_files": ["net/src/main/java/x/Api.kt"]}]}), encoding="utf-8")
            owners = {"domain:app-home": ["entry/src/main/ets/features/app-home/**"], "infra:net-basis": ["entry/src/main/ets/infra/shared/net-basis/**"]}
            inv = {"classes": {"x.HomeVM": {"name": "HomeVM", "file": "app/src/main/java/x/HomeVM.kt"}, "x.Api": {"name": "Api", "file": "net/src/main/java/x/Api.kt"}, "o.Ghost": {"name": "Ghost", "file": "other/G.kt"}},
                   "check": {"I3_class_coverage": {"ui_missing": [], "non_ui_missing": ["HomeVM", "Api", "Ghost"]}}}
            out = CB.coverage_findings(root, bp, owners, inv)
            self.assertEqual([(f["anchor"], f["_owner"], f["code"]) for f in out], [("HomeVM", "domain:app-home", "class-unmigrated"), ("Api", "infra:net-basis", "class-unmigrated"), ("Ghost", None, "class-unmigrated")])
            self.assertIn("features/<域>/", out[0]["suggested_action"])
            self.assertEqual(CB.coverage_findings(root, bp, owners, {"classes": {}, "check": {"I3_class_coverage": {"ui_missing": [], "non_ui_missing": []}}}), [])

    def test_e141_journeys_default_on(self):
        src = (SCRIPTS.parent.parent / "a2h-spec" / "scripts" / "interface_prefill.py").read_text(encoding="utf-8")
        self.assertIn('ap.add_argument("--journeys", action="store_true", default=True', src); self.assertIn('"--no-journeys"', src)

    def test_e129_bisect_threshold_accounts_for_non_source_files(self):
        sys.path.insert(0, str(SCRIPTS.parent.parent / "a2h-spec" / "scripts")); import domain_partition as DP
        nodes = ["p%d/F%02d.kt" % (i % 3, i) for i in range(30)]
        files = {n: {"package": n.split("/")[0]} for n in nodes}
        self.assertEqual(len(DP._bisect(sorted(nodes), files, 40)), 1)                       # 30 源文件 ≤ 40：原样
        self.assertGreaterEqual(len(DP._bisect(sorted(nodes), files, max(2, 40 - 11))), 2)     # 扣掉 11 个 layout 份额 → 29 → 必二分


class TestE143AStageHandoff(unittest.TestCase):
    def test_specfix_done_points_to_grill_not_infra(self):
        import tempfile
        sys.path.insert(0, str(SCRIPTS)); import next_batch as NB
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "spec/state").mkdir(parents=True); (root / "spec/blueprint").mkdir(); (root / "spec/reports").mkdir(); (root / "spec/waves").mkdir()
            h = NB._next_hint({"wave": "specfix"}, root / "spec/waves/plan-specfix.json", root)
            self.assertEqual(h["kind"], "skill"); self.assertIn("grill 尚未做", h["reason"]); self.assertTrue(any("grill_autodecide" in s_ for s_ in h["steps"]))
            (root / "spec/blueprint/decisions.json").write_text("{}", encoding="utf-8")
            h = NB._next_hint({"wave": "understand"}, root / "spec/waves/plan-understand.json", root)
            self.assertEqual(h["kind"], "skill"); self.assertIn("审批门尚未通过", h["reason"])
            (root / "spec/state/approval-request.json").write_text(json.dumps({"approved": True}), encoding="utf-8")
            h = NB._next_hint({"wave": "specfix"}, root / "spec/waves/plan-specfix.json", root)
            self.assertEqual((h["kind"], h["wave"]), ("wave", "infra"))


class TestE144GrillCoverage(unittest.TestCase):
    def test_partial_draft_is_rejected(self):
        import subprocess, tempfile
        G = SCRIPTS.parent.parent / "a2h-spec" / "scripts" / "grill_autodecide.py"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "spec/blueprint").mkdir(parents=True); (root / "spec/state").mkdir()
            cards = [{"id": "PD-C%d-X" % c, "status": "proposed", "options": [{"label": "A", "recommended": True}]} for c in (0, 1, 2, 3)]
            (root / "spec/blueprint/decisions.json").write_text(json.dumps({"decisions": cards}), encoding="utf-8")
            r = subprocess.run([sys.executable, str(G), "--project", str(root), "--apply", "--json"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1); out = json.loads(r.stderr.strip().splitlines()[-1]); self.assertTrue(out["incomplete"]); self.assertIn("C7", out["missing_categories"])
            dec = json.loads((root / "spec/blueprint/decisions.json").read_text(encoding="utf-8"))["decisions"]
            self.assertTrue(all(x["status"] == "proposed" for x in dec))                         # 不完整不裁
            full = [{"id": "PD-C%d-X" % c, "status": "proposed", "options": [{"label": "A", "recommended": True}]} for c in range(18)]
            (root / "spec/blueprint/decisions.json").write_text(json.dumps({"decisions": full}), encoding="utf-8")
            r = subprocess.run([sys.executable, str(G), "--project", str(root), "--apply", "--json"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(len(json.loads(r.stdout)["decided"]), 18)


class TestE145E147ApprovalGate(unittest.TestCase):
    AR = SCRIPTS.parent.parent / "a2h-plan" / "scripts" / "approval_request.py"

    def _root(self, d, unattended=True):
        root = Path(d); (root / "spec/blueprint").mkdir(parents=True); (root / "spec/state").mkdir(); (root / "spec/reports").mkdir(); (root / "spec/.a2h").mkdir(); (root / "spec/waves").mkdir()
        (root / "spec/blueprint/workflow-params.json").write_text(json.dumps({"gates": {"unattended": unattended, "device_smoke": "off"}}), encoding="utf-8")
        (root / "spec/blueprint/domain-map.json").write_text(json.dumps({"domains": [{"key": "a", "title": "A", "tier": "core"}]}), encoding="utf-8")
        (root / "spec/blueprint/decisions.json").write_text(json.dumps({"decisions": [{"id": "PD-C0-X", "status": "proposed"}, {"id": "PD-C7-Y", "status": "approved"}]}), encoding="utf-8")
        return root

    def _run(self, root):
        import subprocess
        return subprocess.run([sys.executable, str(self.AR), "--blueprint", "spec/blueprint", "--no-device-probe", "--json"], cwd=root, capture_output=True, text=True)

    def test_prechecks_block_until_a_stage_gates_handled_then_auto_approve(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = self._root(d)
            r = self._run(root); out = json.loads(r.stdout)
            self.assertEqual(r.returncode, 1); self.assertTrue(any("卫生闸" in b for b in out["blockers"])); self.assertTrue(any("深度门未跑" in b for b in out["blockers"]))
            self.assertFalse(json.loads((root / "spec/state/approval-request.json").read_text(encoding="utf-8"))["approved"])
            (root / "spec/reports/hygiene-gate.json").write_text(json.dumps({"verdict": "PASS"}), encoding="utf-8")
            (root / "spec/.a2h/open-findings.json").write_text(json.dumps({"sections": {"spec/lint_coverage": {"findings": [{"severity": "blocking", "rule": "SPEC.X"}]}}}), encoding="utf-8")
            r = self._run(root); out = json.loads(r.stdout)
            self.assertEqual(r.returncode, 1); self.assertTrue(any("1 条阻断未处置" in b for b in out["blockers"]))
            (root / "spec/reports/depth-gate-debt.json").write_text("{}", encoding="utf-8")
            r = self._run(root); out = json.loads(r.stdout)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            ap = json.loads((root / "spec/state/approval-request.json").read_text(encoding="utf-8"))
            self.assertEqual((ap["approved"], ap["approved_by"], ap["pd_decisions"]), (True, "auto-policy", {"PD-C0-X": "approve"}))   # E145：只批 proposed 的卡
            adj = json.loads((root / "spec/state/auto-adjudications.json").read_text(encoding="utf-8"))
            self.assertEqual([x["kind"] for x in adj], ["approval-gate-auto"])

    def test_attended_mode_never_auto_approves(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = self._root(d, unattended=False)
            (root / "spec/reports/hygiene-gate.json").write_text(json.dumps({"verdict": "PASS"}), encoding="utf-8")
            (root / "spec/.a2h/open-findings.json").write_text(json.dumps({"sections": {"spec/lint_coverage": {"findings": []}}}), encoding="utf-8")
            r = self._run(root); self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            self.assertFalse(json.loads((root / "spec/state/approval-request.json").read_text(encoding="utf-8"))["approved"])


class TestE154E155BuildSideMechanics(unittest.TestCase):
    def test_e154_sanitize_kit_imports_from_log(self):
        import tempfile, importlib.util
        spec = importlib.util.spec_from_file_location("bw154", SCRIPTS / "build_wave.py"); BW = importlib.util.module_from_spec(spec); spec.loader.exec_module(BW)
        log = ("1 ERROR: ArkTS Compiler Error\nError Message: Module '\"@kit.ArkUI\"' has no exported member 'NavDestination'. At File: /p/a.ets:1:10\n"
               "2 ERROR: 'NavPathStack' is not exported from Kit '@kit.ArkUI'.\n")
        ill = BW._illegal_imports_from_log(log); self.assertEqual(ill, {"@kit.ArkUI": {"NavDestination", "NavPathStack"}})
        with tempfile.TemporaryDirectory() as d:
            ets = Path(d); (ets / "pages").mkdir()
            (ets / "pages/A.ets").write_text("import { NavDestination, NavPathStack, window } from '@kit.ArkUI';\nimport { NavDestination } from '@kit.ArkUI';\nimport { hilog } from '@kit.PerformanceAnalysisKit';\nstruct A {}\n", encoding="utf-8")
            ch = BW.sanitize_kit_imports(ets, ill)
            txt = (ets / "pages/A.ets").read_text(encoding="utf-8")
            self.assertEqual(ch, {"pages/A.ets": ["NavDestination", "NavPathStack", "NavDestination"]})
            self.assertIn("import { window } from '@kit.ArkUI';", txt); self.assertNotIn("NavDestination", txt); self.assertIn("hilog", txt)
            self.assertEqual(BW.sanitize_kit_imports(ets, ill), {})                                  # 幂等

    def test_e155_media_placeholder(self):
        import tempfile, importlib.util
        spec = importlib.util.spec_from_file_location("sr155", SCRIPTS / "seed_resources.py"); SR = importlib.util.module_from_spec(spec); spec.loader.exec_module(SR)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); el = root / "entry/src/main/resources/base/element"; el.mkdir(parents=True)
            for k in ("string", "color", "float"): (el / ("%s.json" % k)).write_text(json.dumps({k: []}), encoding="utf-8")
            (root / "spec/baseline").mkdir(parents=True); (root / "spec/baseline/resource-index.json").write_text(json.dumps({"texts": {}, "colors": {}, "dims": {}}), encoding="utf-8")
            ets = root / "entry/src/main/ets/pages"; ets.mkdir(parents=True)
            (ets / "A.ets").write_text("Image($r('app.media.icon_home_top_mine'))\n", encoding="utf-8")
            rep = SR.backfill_refs(root, "entry", root / "entry/src/main/ets")
            self.assertTrue((root / "entry/src/main/resources/base/media/icon_home_top_mine.png").is_file())
            self.assertEqual([(a["kind"], a["placeholder"]) for a in rep["added"]], [("media", True)]); self.assertEqual(rep["unresolved"], [])


class TestE157AutoApproveAtLanding(unittest.TestCase):
    def test_auto_approve_payload_helper(self):
        import tempfile
        sys.path.insert(0, str(SCRIPTS)); import _wavelib as W
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "spec/state/approvals").mkdir(parents=True)
            (root / "spec/state/approvals/fix-backlog.json").write_text(json.dumps({"approved": False, "open": 33, "p0": 4}), encoding="utf-8")
            self.assertTrue(W.auto_approve_payload(root, "auditfix", "gate:fix-backlog", "spec/state/approvals/fix-backlog.json"))
            d_ = json.loads((root / "spec/state/approvals/fix-backlog.json").read_text(encoding="utf-8"))
            self.assertEqual((d_["approved"], d_["by"], d_["auto"]), (True, "auto-policy", True))
            self.assertFalse(W.auto_approve_payload(root, "auditfix", "gate:fix-backlog", "spec/state/approvals/fix-backlog.json"))   # 已批不重写
            adj = json.loads((root / "spec/state/auto-adjudications.json").read_text(encoding="utf-8"))
            self.assertEqual([(a["kind"], a["id"], a["detail"]) for a in adj], [("approve", "gate:fix-backlog", {"open": 33, "p0": 4})])
        src = (SCRIPTS / "land_results.py").read_text(encoding="utf-8")
        self.assertEqual(src.count('summary["approval"]["auto_approved"] = True'), 2)


class TestE158MassTerminationIsInfra(unittest.TestCase):
    def test_constant_and_branch_present(self):
        src = (SCRIPTS / "land_results.py").read_text(encoding="utf-8")
        self.assertIn("MASS_INFRA_MIN = 3", src); self.assertIn("len(_MISSING_AS_FAILED) >= MASS_INFRA_MIN", src)
        self.assertIn("按基础设施失败处置不耗配额（E158）", src)
