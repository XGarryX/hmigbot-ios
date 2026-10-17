"""E252：页面级文案须在安卓源里有证据（android-literals.json：布局 / 默认 strings / 代码文案）才按页面级强制；
spec 独有的（示例数据、说明文字）降为 ref 级 WARN。ds 实证：503 条页面级只有 256 条在安卓源里，closure 残账 152 条全是这类。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "literal_gate.py"


def _project(root: Path, with_android: bool):
    el = root / "entry/src/main/resources/base/element"; el.mkdir(parents=True)
    (el / "string.json").write_text(json.dumps({"string": [{"name": "btn_ok", "value": "确定"}]}, ensure_ascii=False), encoding="utf-8")
    (el / "color.json").write_text(json.dumps({"color": []}), encoding="utf-8")
    pages = root / "entry/src/main/ets/pages"; pages.mkdir(parents=True)
    (pages / "A.ets").write_text("Text($r('app.string.btn_ok'))\n", encoding="utf-8")
    (root / "spec/baseline").mkdir(parents=True)
    (root / "spec/baseline/literal-ledger.json").write_text(json.dumps({"texts": [
        {"value": "确定", "page_level": True, "sources": ["android:layout/a.xml"]},
        {"value": "保存到相册", "page_level": True, "sources": ["domains/x.md:10"]},        # 安卓源有，产物缺 → FAIL
        {"value": "2026年09月21日 10:30", "page_level": True, "sources": ["domains/x.md:12"]},   # spec 示例数据
        {"value": "token 失效跳登录页", "page_level": True, "sources": ["domains/x.md:30"]},    # spec 说明文字
    ], "colors": [], "dims": [], "durations_ms": []}, ensure_ascii=False), encoding="utf-8")
    if with_android:
        (root / "spec/baseline/android-literals.json").write_text(json.dumps({
            "by_layout": {"a.xml": {"texts": ["确定", "保存到相册"]}}, "values_map": {"strings": {"btn_ok": "确定"}},
            "code_texts": []}, ensure_ascii=False), encoding="utf-8")


class TestSpecOnlyDemoted(unittest.TestCase):
    def _run(self, with_android):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _project(root, with_android)
            r = subprocess.run([sys.executable, str(SCRIPT), "--project", str(root), "--json", "--output-json", str(root / "o.json")],
                               capture_output=True, text=True)
            return r.returncode, json.loads((root / "o.json").read_text(encoding="utf-8"))

    def test_spec_only_texts_warn_android_backed_fail(self):
        rc, rep = self._run(True)
        fails = [f["message"] for f in rep["findings"] if f["severity"] == "FAIL"]
        self.assertEqual(len(fails), 1)
        self.assertIn("保存到相册", fails[0])
        self.assertEqual(rep["stats"]["texts"]["spec_only_demoted"], 2)
        warns = " ".join(f["message"] for f in rep["findings"] if f["severity"] == "WARN")
        self.assertIn("2026年09月21日", warns)
        self.assertEqual(rc, 1)

    def test_without_android_evidence_keeps_old_behavior(self):
        rc, rep = self._run(False)
        self.assertEqual(sum(1 for f in rep["findings"] if f["severity"] == "FAIL"), 3)
        self.assertFalse(rep["stats"]["texts"]["android_evidence"])



class TestE257ContainmentEvidence(unittest.TestCase):
    """E257：spec 常只写安卓原文的一部分——是某条安卓文案的子串就算有证据（保持页面级）；
    反过来 spec 比安卓多出内容（示例数字）仍按 spec 独有降级。ds 回放：236 条降级里 24 条其实有安卓出处。"""

    def test_substring_of_android_text_stays_page_level(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            el = root / "entry/src/main/resources/base/element"; el.mkdir(parents=True)
            (el / "string.json").write_text(json.dumps({"string": []}), encoding="utf-8")
            (el / "color.json").write_text(json.dumps({"color": []}), encoding="utf-8")
            pages = root / "entry/src/main/ets/pages"; pages.mkdir(parents=True)
            (pages / "Home.ets").write_text("promptAction.showToast({ message: '再按一次退出程序' })\n", encoding="utf-8")
            (root / "spec/baseline").mkdir(parents=True)
            (root / "spec/baseline/literal-ledger.json").write_text(json.dumps({"texts": [
                {"value": "保存", "page_level": True, "sources": ["domains/x.md:3"]},            # ⊂ 保存本地，产物缺 → FAIL
                {"value": "再按一次退出", "page_level": True, "sources": ["domains/x.md:4"]},    # ⊂ 代码文案，产物有 → ok
                {"value": "作品库（3）", "page_level": True, "sources": ["domains/x.md:5"]},     # ⊃ 安卓文案 → spec 独有
            ], "colors": [], "dims": [], "durations_ms": []}, ensure_ascii=False), encoding="utf-8")
            (root / "spec/baseline/android-literals.json").write_text(json.dumps({
                "by_layout": {"page_outline.xml": {"texts": ["保存本地", "作品库"]}}, "values_map": {"strings": {}},
                "code_texts": ["再按一次退出程序"]}, ensure_ascii=False), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), "--project", str(root), "--json", "--output-json", str(root / "o.json")],
                               capture_output=True, text=True)
            rep = json.loads((root / "o.json").read_text(encoding="utf-8"))
        fails = [f["message"] for f in rep["findings"] if f["severity"] == "FAIL"]
        self.assertEqual(len(fails), 1, fails)
        self.assertIn("「保存」", fails[0])
        self.assertEqual(rep["stats"]["texts"]["spec_only_demoted"], 1)
        self.assertEqual(rep["stats"]["texts"]["ok"], 1)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
