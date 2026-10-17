"""E37 K4 探针机械写入回归。立此闸的事实：AIPPT_0903 compile#1 编译图 3/223 判 graph-mismatch，门禁指引「写探针」但包里只有摘除脚本。
固定判据：--gate 按孤儿清单（小写全路径）解析到真实文件；--all 排除 __probe/、EntryAbility、pages/**；探针每行带 // A2H-PROBE；
EntryAbility 只插两行标记行且幂等；留痕 spec/state/probe-writes.json；build_wave.detach_probe 能整干净、零残留。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import build_wave as BW  # noqa: E402

ENTRY = "import { UIAbility } from '@kit.AbilityKit';\nimport { window } from '@kit.ArkUI';\n\nexport default class EntryAbility extends UIAbility {}\n"


def _w(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8")


class TestWriteProbe(unittest.TestCase):
    def _proj(self, root: Path):
        ets = root / "entry/src/main/ets"
        _w(ets / "entryability/EntryAbility.ets", ENTRY)
        _w(ets / "infra/net/Net-Network/ApiException.ets", "export class ApiException {}\n")
        _w(ets / "infra/shared/Common/GlideUtils.ets", "export function f() {}\n")
        _w(ets / "pages/Index.ets", "@Entry @Component struct Index { build() {} }\n")
        return ets

    def _run(self, root: Path, *args):
        r = subprocess.run([sys.executable, str(SCRIPTS / "write_probe.py"), "--project", str(root), "--json", *args], capture_output=True, text=True)
        return r.returncode, (json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stdout + r.stderr)

    def test_gate_mode_resolves_lowercase_orphan_list(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); ets = self._proj(root)
            low = str((ets / "infra/net/Net-Network/ApiException.ets").resolve()).lower()
            _w(root / "spec/reports/orphan-ets.compile-1.txt", "%s\tinfra:net\n%s\tdomain:x\n" % (low, str((ets / "pages/Index.ets").resolve()).lower()))
            rc, out = self._run(root, "--gate", "compile#1")
            self.assertEqual(rc, 0, out); self.assertEqual(out["modules"], 1)                # pages/** 不探针
            probe = ets / "__probe" / "A2hProbe_compile_1.ets"; t = probe.read_text(encoding="utf-8")
            self.assertIn("import * as P0 from '../infra/net/Net-Network/ApiException'; // A2H-PROBE", t)   # 大小写按实际文件
            self.assertTrue(all("// A2H-PROBE" in l for l in t.strip().split("\n")))
            e = (ets / "entryability/EntryAbility.ets").read_text(encoding="utf-8")
            self.assertEqual(e.count("// A2H-PROBE"), 2); self.assertIn("from '../__probe/A2hProbe_compile_1'", e)
            self.assertTrue(e.split("\n")[2].startswith("import * as A2H_PROBE_compile_1"))   # 插在最后一个 import 之后
            rc, out2 = self._run(root, "--gate", "compile#1")                                   # 幂等
            self.assertEqual((out2["entry_patched"], out2["probe_changed"]), (False, False))
            self.assertEqual((ets / "entryability/EntryAbility.ets").read_text(encoding="utf-8").count("// A2H-PROBE"), 2)
            recs = json.loads((root / "spec/state/probe-writes.json").read_text(encoding="utf-8")); self.assertEqual(len(recs), 2)
            removed, leftovers = BW.detach_probe(ets)                                            # 摘除对偶
            self.assertEqual(leftovers, []); self.assertGreaterEqual(removed, 2); self.assertFalse((ets / "__probe").exists())
            self.assertEqual((ets / "entryability/EntryAbility.ets").read_text(encoding="utf-8"), ENTRY)

    def test_all_mode_excludes_pages_entry_probe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); ets = self._proj(root)
            rc, out = self._run(root, "--all")
            self.assertEqual(rc, 0, out); self.assertEqual(out["modules"], 2)
            rc, out = self._run(root, "--all"); self.assertEqual(out["modules"], 2)               # 不把自己算进去
            rc, out = self._run(root, "--gate", "compile#9"); self.assertEqual(rc, 0); self.assertIn("skipped", out)   # 无清单 → 跳过


if __name__ == "__main__":
    unittest.main()
