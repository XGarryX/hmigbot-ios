"""E33 AC 结构规范化回归。立此闸的事实：AIPPT_0903 334 条 AC 内容齐全但 ID 不合 `^[A-Z]{1,4}\\d+-AC\\d+$`，27 份无 anchors，
A2 覆盖 lint 27/27 判无 AC；交代理重写撞 429 三次。固定判据：ID 按域前缀+序号重编且合规；正文与四锚点一字不动；
文件内旧 ID 引用同步改写；anchors 块只插一次、只收 .kt/.java；无 AC 的 spec 不造 AC；dry-run 不落盘。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent.parent.parent / "a2h-spec" / "scripts" / "ac_normalize.py"
sys.path.insert(0, str(SCRIPT.parent))
import ac_normalize as AN  # noqa: E402

STRICT = re.compile(r"^\s*-\s*\[[ xX]\]\s*([A-Z]{1,4}\d+-AC\d+)\s+")


class TestNormalize(unittest.TestCase):
    def test_prefix_and_role(self):
        self.assertEqual(AN.prefix_for("app-splash", 8), "AS08")
        self.assertTrue(re.fullmatch(r"[A-Z]{1,4}\d{2}", AN.prefix_for("app-create-out-line-page", 12)))
        self.assertEqual(AN.role_for("app/src/main/java/x/HomeViewModel.kt"), "viewmodel")
        self.assertEqual(AN.role_for("x/SplashActivity.kt"), "presenter")

    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "spec/domains").mkdir(parents=True); (root / "spec/blueprint").mkdir(parents=True)
            (root / "spec/blueprint/domain-map.json").write_text(json.dumps({"version": 1, "domains": [
                {"key": "app-splash", "spec_file": "spec/domains/app-splash.md",
                 "android_files": ["app/src/main/java/p/SplashActivity.kt", "app/src/main/res/layout/a.xml", "app/src/main/java/p/SplashViewModel.kt"]},
                {"key": "pay-bean", "spec_file": "spec/domains/pay-bean.md", "android_files": ["pay/src/main/java/p/Bean.kt"]}]}), encoding="utf-8")
            body = ("# app-splash 域规格\n\n## 范围\n- 略\n\n## 验收断言候选（830 四锚点）\n"
                    "- [ ] SPLASH-AC1 冷启动进 Guide 源: SplashActivity.gotoHome 判: ui_state 真: Android 实测\n"
                    "- [ ] SPLASH-AC3 热启动不开 Guide 源: SplashActivity.gotoHome 判: ui_state 真: Android 实测 [决: PD-1]\n"
                    "- [x] SPLASH-AC10 协议拒绝即 finish 源: LaunchAgreementDialog 判: no_crash 真: Android 实测\n"
                    "supersedes: [SPLASH-AC1, SPLASH-AC10]\n")
            (root / "spec/domains/app-splash.md").write_text(body, encoding="utf-8")
            (root / "spec/domains/pay-bean.md").write_text("# pay-bean\n\n## 范围\n- 无 AC\n", encoding="utf-8")
            run = lambda *extra: subprocess.run([sys.executable, str(SCRIPT), "--spec-dir", "spec/domains", "--domain-map", "spec/blueprint/domain-map.json", "--json", *extra], cwd=root, capture_output=True, text=True)
            r = run(); self.assertEqual(r.returncode, 0, r.stderr); out = json.loads(r.stdout)
            self.assertEqual((out["acs"], out["renamed"], out["anchors"], out["files_changed"]), (3, 3, 3, 2))
            self.assertEqual(out["no_ac_domains"], ["pay-bean"])
            self.assertEqual((root / "spec/domains/app-splash.md").read_text(encoding="utf-8"), body)   # dry-run 不落盘
            r = run("--apply"); self.assertEqual(r.returncode, 0, r.stderr)
            t = (root / "spec/domains/app-splash.md").read_text(encoding="utf-8")
            ids = [STRICT.match(l).group(1) for l in t.split("\n") if STRICT.match(l)]
            self.assertEqual(ids, ["AS01-AC1", "AS01-AC2", "AS01-AC3"])
            self.assertIn("- [ ] AS01-AC2 热启动不开 Guide 源: SplashActivity.gotoHome 判: ui_state 真: Android 实测 [决: PD-1]", t)
            self.assertIn("supersedes: [AS01-AC1, AS01-AC3]", t)                      # 旧 ID 引用同步；长 ID 优先不吞
            self.assertEqual(t.count("android_source_anchors:"), 1)
            self.assertIn('path: "app/src/main/java/p/SplashActivity.kt"', t); self.assertNotIn("a.xml", t)
            self.assertTrue(t.startswith("# app-splash 域规格\n\n```yaml\nandroid_source_anchors:"))
            pb = (root / "spec/domains/pay-bean.md").read_text(encoding="utf-8")
            self.assertNotIn("-AC", pb); self.assertIn("android_source_anchors:", pb)
            # 幂等
            r = run("--apply"); out2 = json.loads(r.stdout); self.assertEqual((out2["renamed"], out2["anchors"], out2["files_changed"]), (0, 0, 0))
            self.assertEqual((root / "spec/domains/app-splash.md").read_text(encoding="utf-8"), t)


if __name__ == "__main__":
    unittest.main()
