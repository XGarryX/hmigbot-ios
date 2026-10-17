# -*- coding: utf-8 -*-
"""literal_gate dims 值漂移（AIPPT_930_token2）：ledger 尺寸经安卓 dimens 同值名 / resource-index 对到产物 float.json 条目，
数值不等 → page_level FAIL dimen-value-drift / ref WARN；同值不报；无 android-literals 且无 resource-index 时 dims 仍只是覆盖率报表。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "literal_gate.py"


def _project(root: Path, *, with_android=True, with_index=False):
    el = root / "entry/src/main/resources/base/element"; el.mkdir(parents=True)
    (el / "string.json").write_text(json.dumps({"string": []}), encoding="utf-8")
    (el / "color.json").write_text(json.dumps({"color": []}), encoding="utf-8")
    (el / "float.json").write_text(json.dumps({"float": [
        {"name": "margin_big", "value": "16vp"}, {"name": "margin_small", "value": "8vp"},
        {"name": "text_size", "value": "14fp"}, {"name": "d_30vp", "value": "20vp"}]}), encoding="utf-8")
    pages = root / "entry/src/main/ets/pages"; pages.mkdir(parents=True)
    (pages / "A.ets").write_text("Text('x').margin($r('app.float.margin_big')).fontSize(16)\n", encoding="utf-8")
    (root / "spec/baseline").mkdir(parents=True)
    if with_android:
        (root / "spec/baseline/android-literals.json").write_text(json.dumps({"values_map": {"dimens": {
            "margin_big": "24dp", "margin_small": "8dp", "text_size": "16sp"}}}), encoding="utf-8")
    if with_index:
        (root / "spec/baseline/resource-index.json").write_text(json.dumps({"dims": {"30vp": "d_30vp"}}), encoding="utf-8")
    (root / "spec/baseline/literal-ledger.json").write_text(json.dumps({"texts": [], "colors": [], "durations_ms": [], "dims": [
        {"value": "24dp", "page_level": True, "sources": ["p1"]},     # margin_big 24 vs 16 → FAIL
        {"value": "8dp", "page_level": True, "sources": ["p1"]},      # margin_small 同值 → 不报
        {"value": "16sp", "page_level": False, "sources": ["p2"]},    # text_size 16 vs 14 → WARN（ref）
        {"value": "30dp", "page_level": True, "sources": ["p3"]},     # 经 resource-index d_30vp=20 → FAIL（仅 with_index）
    ]}), encoding="utf-8")


def _run(root: Path):
    r = subprocess.run([sys.executable, str(SCRIPT), "--project", str(root), "--json", "--output-json", str(root / "out.json")],
                       capture_output=True, text=True)
    return r.returncode, json.loads((root / "out.json").read_text(encoding="utf-8"))


class TestDimenDrift(unittest.TestCase):
    def test_drift_fail_and_warn(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _project(root)
            rc, rep = _run(root)
            drift = [f for f in rep["findings"] if f["code"] == "dimen-value-drift"]
            self.assertEqual(sorted((f["severity"], f["message"].split("app.float.")[1].split(" ")[0]) for f in drift),
                             [("FAIL", "margin_big"), ("WARN", "text_size")])
            self.assertEqual((rep["stats"]["dims"]["drift_page"], rep["stats"]["dims"]["drift_ref"]), (1, 1))
            self.assertEqual(rc, 1)

    def test_index_route_and_no_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _project(root, with_index=True)
            rc, rep = _run(root)
            names = sorted(f["message"].split("app.float.")[1].split(" ")[0] for f in rep["findings"] if f["code"] == "dimen-value-drift")
            self.assertEqual(names, ["d_30vp", "margin_big", "text_size"])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _project(root, with_android=False)
            rc, rep = _run(root)
            self.assertEqual([f for f in rep["findings"] if f["code"] == "dimen-value-drift"], [])
            self.assertEqual(rc, 0)
            self.assertEqual(rep["stats"]["dims"]["drift_page"], 0)


if __name__ == "__main__":
    unittest.main()
