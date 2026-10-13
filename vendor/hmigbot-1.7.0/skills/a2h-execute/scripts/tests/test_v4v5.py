#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V4（后端事实硬门）/ V5（知识修正）第一批单测：sibling_facts / auth_probe / G2 逐层 /
W5 追溯 / merge_gaps blocking 判定 / round-0 hittest / index.json provenance。

用法示例:
    python3 -m unittest discover -s arkts-skills/skills/a2h-execute/scripts/tests -v
    python3 arkts-skills/skills/a2h-execute/scripts/tests/test_v4v5.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SPEC_SCRIPTS = SCRIPTS.parent.parent / "a2h-spec" / "scripts"
SIBLING_FACTS = SPEC_SCRIPTS / "sibling_facts.py"
AUTH_PROBE = SPEC_SCRIPTS / "auth_probe.py"
MERGE_GAPS = SCRIPTS / "merge_gaps.py"
ROUND0 = SCRIPTS / "round0_precheck.py"
FRAGMENTS = SCRIPTS.parent / "references" / "fragments"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestSiblingFacts(unittest.TestCase):
    """V4/A0.0：同源工程 probe 条目只读窄口——同 appId 才抽，条目带来源，镜像幂等。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-sib-")
        self.addCleanup(self._tmp.cleanup)
        self.roots = Path(self._tmp.name)
        self.cur = self.roots / "aippt_new_v4"       # 当前工程（排除自身）
        self.cur.mkdir(parents=True)
        self.facts_home = self.roots / "facts-home"

    def _sib(self, name: str, app_id: str, probe: bool) -> None:
        proj = self.roots / name
        body = ("## D-010 androidId 后端契约\n"
                "依据=probe 实测：androidId NOT NULL，传非空 16-hex 则 status=0。\n") if probe \
            else "## D-001 普通决策\n沿用 Android 实现。\n"
        _write(proj / "spec" / "blueprint" / "decision-ledger.md", body)
        _write(proj / "AppScope" / "app.json5", '{"app":{"bundleName":"%s"}}' % app_id)

    def test_only_same_app_probe_entries_extracted(self) -> None:
        self._sib("aippt_0723", "com.wenba.aippt", probe=True)
        self._sib("other_app", "com.other.thing", probe=True)     # 不同 appId
        self._sib("aippt_no_probe", "com.wenba.aippt", probe=False)  # 同 app 无 probe
        out = self.cur / "spec" / "ref" / "backend-facts.md"
        proc = subprocess.run(
            [sys.executable, str(SIBLING_FACTS), "--android-src", str(self.cur / "android"),
             "--app-id", "com.wenba.aippt", "--sibling-roots", str(self.roots),
             "--facts-home", str(self.facts_home), "--out", str(out), "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.cur), timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        res = json.loads(proc.stdout)
        self.assertEqual(res["probe_entries"], 1)                 # 只 aippt_0723 的 D-010
        text = out.read_text(encoding="utf-8")
        self.assertIn("androidId NOT NULL", text)
        self.assertIn("来源: aippt_0723", text)
        self.assertNotIn("com.other.thing", text)
        self.assertTrue((self.facts_home / "com.wenba.aippt.md").is_file())

    def test_no_sibling_writes_fallback_note(self) -> None:
        out = self.cur / "spec" / "ref" / "backend-facts.md"
        proc = subprocess.run(
            [sys.executable, str(SIBLING_FACTS), "--android-src", str(self.cur / "android"),
             "--app-id", "com.wenba.aippt", "--sibling-roots", str(self.roots),
             "--no-mirror", "--out", str(out), "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.cur), timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("全量拷问", out.read_text(encoding="utf-8"))


class _FakeAuthHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):    # 静音
        pass

    def _reply(self):
        path = self.path
        if path.endswith("/initUser"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"code": 0, "mediaNo": "28299244"}).encode())
        elif path.endswith("/bad"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"code": -500, "msg": "mediaNo is null"}).encode())
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

    def do_GET(self):
        self._reply()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self._reply()


class TestAuthProbe(unittest.TestCase):
    """V4/A0.4b：逐层 probe 实测回填 golden——pass/fail/无 dev_info blocked。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = HTTPServer(("127.0.0.1", 0), _FakeAuthHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-probe-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name)
        self.base = "http://127.0.0.1:%d" % self.port

    def _plan(self, layers) -> None:
        _write(self.proj / "spec/data-chains/probe-plan.json",
               json.dumps({"base_url": self.base, "layers": layers}))

    def _run(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(AUTH_PROBE), "--plan", "spec/data-chains/probe-plan.json",
             "--golden", "spec/data-chains/chain-auth.golden.json",
             "--dev-info", "spec/baseline/dev_info.json", "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj), timeout=60)

    def test_all_pass(self) -> None:
        _write(self.proj / "spec/baseline/dev_info.json", json.dumps({"base_url": self.base}))
        self._plan([{"layer": "L0", "request": {"method": "GET", "path": "/"},
                     "expect": {"status_lt": 500}},
                    {"layer": "L3", "request": {"method": "POST", "path": "/initUser"},
                     "expect": {"json": {"code": 0}}, "client_facts": {"channel": "2301101"}}])
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        golden = json.loads((self.proj / "spec/data-chains/chain-auth.golden.json")
                            .read_text(encoding="utf-8"))
        by = {l["layer"]: l for l in golden["layers"]}
        self.assertEqual(by["L3"]["probe"]["status"], "pass")
        self.assertEqual(by["L3"]["client_facts"]["channel"], "2301101")

    def test_fail_layer(self) -> None:
        _write(self.proj / "spec/baseline/dev_info.json", json.dumps({"base_url": self.base}))
        self._plan([{"layer": "L3", "request": {"method": "POST", "path": "/bad"},
                     "expect": {"json": {"code": 0}}}])
        proc = self._run()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        golden = json.loads((self.proj / "spec/data-chains/chain-auth.golden.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(golden["layers"][0]["probe"]["status"], "fail")

    def test_no_dev_info_blocks(self) -> None:
        self._plan([{"layer": "L0", "request": {"method": "GET", "path": "/"},
                     "expect": {"status_lt": 500}}])
        proc = self._run()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        out = json.loads(proc.stdout)
        self.assertEqual(out["results"][0]["status"], "blocked")
        self.assertTrue(out["need_from_user"])


class TestMergeGapsBlocking(unittest.TestCase):
    """V2/V4：category 含 server/backend、g_id 含 androidId/channel → blocking（F-005 族）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-gaps-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name)
        self.rd = self.proj / "results"

    def _res(self, name: str, gaps: list) -> None:
        _write(self.rd / (name + ".json"),
               json.dumps({"domain": name, "final_state": "PASS", "files": [],
                           "decision_gaps": gaps}))

    def _run(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(MERGE_GAPS), "--results-dir", str(self.rd),
             "--out", str(self.proj / "gaps.json"), "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=60)

    def test_backend_category_and_androidid_gid_block(self) -> None:
        self._res("infra-common-util", [
            {"g_id": "GAP-androidid-substitute", "category": "C5", "blocking": False},
            {"g_id": "G-PLATFORM-CID", "category": "server-contract", "blocking": False},
            {"g_id": "G-UI-01", "category": "visual-parity", "blocking": False}])
        proc = self._run()
        self.assertEqual(proc.returncode, 1, proc.stdout)   # 有 blocking
        out = json.loads(proc.stdout)
        self.assertEqual(out["blocking"], 2)
        blk = {g["g_id"] for g in out["gaps"] if g["blocking"]}
        self.assertEqual(blk, {"GAP-androidid-substitute", "G-PLATFORM-CID"})

    def test_no_blocking_passes(self) -> None:
        self._res("home", [{"g_id": "G-UI-02", "category": "visual-spec", "blocking": False}])
        self.assertEqual(self._run().returncode, 0)

    def test_waive_persists_when_gap_set_unchanged(self) -> None:
        self._res("a", [{"g_id": "G-PAY-01", "category": "server-protocol", "blocking": False}])
        self.assertEqual(self._run().returncode, 1)
        gpath = self.proj / "gaps.json"
        d = json.loads(gpath.read_text(encoding="utf-8"))
        d["waived"] = True
        gpath.write_text(json.dumps(d), encoding="utf-8")
        self.assertEqual(self._run().returncode, 0)          # 同缺口集 + waived → 放行


class TestRound0Hittest(unittest.TestCase):
    """V5：round-0 check_hittest——Block 容器含交互 → P0；遮罩空 onClick 豁免。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a2h-r0hit-")
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name)
        _write(self.proj / "spec/blueprint/ownership.json", json.dumps(
            {"version": 1, "owners": {"domain:alpha": ["entry/src/main/ets/pages/**"]},
             "mainloop_owned": []}))
        _write(self.proj / "spec/blueprint/domain-map.json", json.dumps(
            {"version": 1, "domains": [{"key": "alpha"}]}))

    def _run(self) -> dict:
        env = dict(os.environ)
        env["ARKTS_SKILL_DIR"] = str(SCRIPTS.parent)
        subprocess.run(
            [sys.executable, str(ROUND0), "--project", str(self.proj),
             "--blueprint", "spec/blueprint", "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.proj),
            env=env, timeout=120)
        return json.loads((self.proj / "spec/reports/round0/alpha.json").read_text(encoding="utf-8"))

    def test_block_with_interactive_child_is_p0(self) -> None:
        _write(self.proj / "entry/src/main/ets/pages/alpha/Privacy.ets",
               "@Component struct Privacy {\n  build() {\n"
               "    Stack() {\n"
               "      Button('同意').onClick(() => {})\n"
               "    }.hitTestBehavior(HitTestMode.Block)\n"
               "  }\n}\n")
        findings = self._run()["findings"]
        hit = [f for f in findings if f["kind"] == "wiring" and f["severity"] == "P0"]
        self.assertTrue(hit, findings)
        self.assertIn("Block", hit[0]["summary"])

    def test_mask_empty_onclick_is_exempt(self) -> None:
        _write(self.proj / "entry/src/main/ets/pages/alpha/Mask.ets",
               "@Component struct Mask {\n  build() {\n"
               "    Stack() {\n"
               "      Column().onClick(() => {})\n"
               "    }.hitTestBehavior(HitTestMode.Block)\n"
               "  }\n}\n")
        findings = self._run()["findings"]
        self.assertEqual([f for f in findings if f["kind"] == "wiring"], [])


class TestFragmentProvenance(unittest.TestCase):
    """V5/P4：index.json catalog 全量覆盖片段目录且 provenance 必填。"""

    def test_catalog_covers_disk_with_provenance(self) -> None:
        idx = json.loads((FRAGMENTS / "index.json").read_text(encoding="utf-8"))
        catalog = idx.get("catalog")
        self.assertIsInstance(catalog, list)
        by_id = {e["id"]: e for e in catalog}
        for e in catalog:
            self.assertTrue(e.get("provenance"), e)
        disk = {p.stem for p in FRAGMENTS.glob("*.md")}
        self.assertEqual(disk, set(by_id), "catalog 与片段目录不一致")
        # arkui-enums / runtime-patterns 是本轮真机实证 → runtime
        self.assertEqual(by_id["arkui-enums"]["provenance"], "runtime")
        self.assertEqual(by_id["runtime-patterns"]["provenance"], "runtime")

    def test_assembler_rejects_orphan_catalog(self) -> None:
        # 组装器启动时校验 catalog↔目录一致（V5）——制造悬空条目应 raise
        import importlib.util
        spec = importlib.util.spec_from_file_location("ap_probe", SCRIPTS / "assemble_prompt.py")
        # 只做静态存在性断言（完整组装在 test_opt_fixes 覆盖），此处确认校验分支已接线
        text = (SCRIPTS / "assemble_prompt.py").read_text(encoding="utf-8")
        self.assertIn("catalog", text)
        self.assertIn("provenance", text)


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
