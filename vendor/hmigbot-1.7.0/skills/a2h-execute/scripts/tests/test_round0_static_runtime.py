# -*- coding: utf-8 -*-
"""round0_precheck 收编静态运行期三条（同源 _static_runtime，只报不修）：auditfix round-0 把落账期漏网的
module-init-runtime-dependency / avoid-area-px-as-vp / dimen-binding-literal-drift 按域落盘，finding 形态与其余检查一致，
产物文件不被改写（--fix 只在 land_results 落账时跑）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent


def _w(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8")


class TestRound0StaticRuntime(unittest.TestCase):
    def test_three_checks_registered_and_findings_attributed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); ets = root / "entry/src/main/ets"
            _w(root / "spec/blueprint/ownership.json", json.dumps({"version": 1, "owners": {"domain:x": ["entry/src/main/ets/**"]}}))
            _w(ets / "services/Svc.ets", "export class Svc {\n  constructor() { this.c = getContext(); }\n  static instance = new Svc();\n}\n")
            _w(ets / "pages/Home.ets", "struct Home {\n  build() { Column().padding({ top: this.area.topRect.height }) }\n}\n"
                                       "const t = $r('app.float.gap')\n")
            _w(root / "spec/baseline/android-literals.json", json.dumps({"values_map": {"dimens": {"gap": "12dp"}}}))
            _w(root / "entry/src/main/resources/base/element/float.json", json.dumps({"float": [{"name": "gap", "value": "10vp"}]}))
            before = (ets / "services/Svc.ets").read_text(encoding="utf-8")
            env = dict(os.environ); env["ARKTS_SKILL_DIR"] = str(root / "no-skills")
            r = subprocess.run([sys.executable, str(SCRIPTS / "round0_precheck.py"), "--project", str(root),
                                "--blueprint", str(root / "spec/blueprint"), "--json"], capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = json.loads(r.stdout)
            names = {c["name"]: c for c in out["checks"]}
            for n in ("module-init-runtime-dependency", "avoid-area-px-as-vp", "dimen-binding-literal-drift"):
                self.assertIn(n, names); self.assertEqual(names[n]["status"], "ok", names[n])
                self.assertEqual(names[n]["findings"], 1)
            rep = json.loads((root / "spec/reports/round0/x.json").read_text(encoding="utf-8"))
            by = {f["check"]: f for f in rep["findings"] if f["check"].startswith(("module-init", "avoid-area", "dimen-binding"))}
            self.assertEqual(sorted(by), ["avoid-area-px-as-vp", "module-init-runtime-dependency"])
            # float.json 不在任何域 ownership（资源面）→ 归 _unassigned，主循环在阶段边界处理
            una = json.loads((root / "spec/reports/round0/_unassigned.json").read_text(encoding="utf-8"))
            by.update({f["check"]: f for f in una["findings"] if f["check"] == "dimen-binding-literal-drift"})
            self.assertIn("dimen-binding-literal-drift", by)
            f = by["module-init-runtime-dependency"]
            self.assertEqual(sorted(f), ["check", "file", "fix", "kind", "line", "severity", "summary"])
            self.assertEqual((f["severity"], f["kind"], f["file"], f["line"]), ("P0", "runtime", "entry/src/main/ets/services/Svc.ets", 3))
            self.assertEqual(by["avoid-area-px-as-vp"]["severity"], "P1")
            self.assertEqual(by["dimen-binding-literal-drift"]["file"], "entry/src/main/resources/base/element/float.json")
            # 只报不修
            self.assertEqual((ets / "services/Svc.ets").read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
