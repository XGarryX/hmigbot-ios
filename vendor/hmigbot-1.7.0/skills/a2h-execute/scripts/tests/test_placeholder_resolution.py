"""seed_resources --sweep 占位替换与显式别名（AIPPT_930 移植）。
固定判据：
  · 回执显式请求的资源名即使同值已有别名也照写（页面已 $r() 引用该名，回既有别名会让引用落空）；
  · 只有 E138 回填报告登记过的占位（洋红/1vp 哨兵、name-humanization 文案）且当前值仍精确等于占位值，
    才允许 sweep 原名替换；真实 1vp/洋红、已被人改过的值、index 反查得到的真实文案一律记 conflicts 不动；
  · 来源账 spec/reports/resource-placeholders-<module>.json 在报告刷新后仍保留 resolved 历史，重复 sweep 幂等。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_seed_resources import _project, _run, _table, ELEM  # noqa: E402


class PlaceholderResolution(unittest.TestCase):
    def write(self, root, relative, value):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def sweep(self, root, entries):
        self.write(root, "spec/waves/results/auditfix/owner.json", {"resources_needed": entries})
        result = _run(root, "--sweep", "--results-dir", "spec/waves/results/auditfix")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_explicit_alias_exists_even_when_value_already_has_another_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _project(root)
            self.write(root, ELEM + "/float.json", {"float": [{"name": "old_gap", "value": "16vp"}]})
            entries = [{"kind": "float", "name": "requested_gap", "value": "16vp"}]
            self.sweep(root, entries)
            self.assertEqual(_table(root, "float")["requested_gap"], "16vp")
            self.assertEqual(_table(root, "float")["old_gap"], "16vp")
            self.assertEqual(self.sweep(root, entries)["added"]["float"], 0)

    def test_only_recorded_exact_placeholders_are_replaced_and_history_survives_report_refresh(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _project(root)
            self.write(root, ELEM + "/float.json", {"float": [{"name": "logo", "value": "1vp"}, {"name": "real_border", "value": "1vp"}]})
            self.write(root, ELEM + "/color.json", {"color": [{"name": "privacy", "value": "#FFFF00FF"}, {"name": "real_magenta", "value": "#FFFF00FF"}]})
            self.write(root, "spec/reports/resource-backfill.json", {"added": [
                {"kind": "float", "name": "logo", "value": "1vp", "placeholder": True, "value_source": "color-float-sentinel"},
                {"kind": "color", "name": "privacy", "value": "#FFFF00FF", "placeholder": True, "value_source": "color-float-sentinel"}]})
            self.sweep(root, [])
            self.write(root, "spec/reports/resource-backfill.json", {"added": []})   # 报告被下一轮刷新
            entries = [{"kind": "float", "name": "logo", "value": "64vp"},
                       {"kind": "color", "name": "privacy", "value": "#333333"},
                       {"kind": "float", "name": "real_border", "value": "2vp"},
                       {"kind": "color", "name": "real_magenta", "value": "#333333"}]
            result = self.sweep(root, entries)
            self.assertEqual(_table(root, "float")["logo"], "64vp")
            self.assertEqual(_table(root, "color")["privacy"], "#FF333333")
            self.assertEqual(_table(root, "float")["real_border"], "1vp")
            self.assertEqual(_table(root, "color")["real_magenta"], "#FFFF00FF")
            self.assertEqual(len(result["conflicts"]), 2)
            provenance = json.loads((root / "spec/reports/resource-placeholders-entry.json").read_text(encoding="utf-8"))
            self.assertEqual(len(provenance["resolved"]), 2)
            self.assertEqual(provenance["pending"], [])
            self.sweep(root, entries)
            again = json.loads((root / "spec/reports/resource-placeholders-entry.json").read_text(encoding="utf-8"))
            self.assertEqual(len(again["resolved"]), 2)

    def test_stale_provenance_does_not_overwrite_a_real_change(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _project(root)
            self.write(root, ELEM + "/float.json", {"float": [{"name": "logo", "value": "48vp"}]})
            self.write(root, "spec/reports/resource-backfill.json", {"added": [
                {"kind": "float", "name": "logo", "value": "1vp", "placeholder": True, "value_source": "color-float-sentinel"}]})
            result = self.sweep(root, [{"kind": "float", "name": "logo", "value": "64vp"}])
            self.assertEqual(_table(root, "float")["logo"], "48vp")
            self.assertEqual(len(result["conflicts"]), 1)

    def test_humanized_string_is_replaced_but_reverse_index_text_is_protected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _project(root)
            self.write(root, ELEM + "/string.json", {"string": [
                {"name": "upload_allow", "value": "upload allow"}, {"name": "real_english", "value": "real english"}]})
            self.write(root, "spec/reports/resource-backfill.json", {"added": [
                {"kind": "string", "name": "upload_allow", "value": "upload allow", "placeholder": True, "value_source": "name-humanization"},
                {"kind": "string", "name": "real_english", "value": "real english", "placeholder": False, "value_source": "index-reverse"}]})
            result = self.sweep(root, [{"kind": "string", "name": "upload_allow", "value": "允许"},
                                       {"kind": "string", "name": "real_english", "value": "中文"}])
            self.assertEqual(_table(root, "string")["upload_allow"], "允许")
            self.assertEqual(_table(root, "string")["real_english"], "real english")
            self.assertEqual(len(result["conflicts"]), 1)

    def test_backfill_marks_value_source_and_records_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _project(root)
            ets = root / "entry/src/main/ets/pages"; ets.mkdir(parents=True)
            (ets / "P.ets").write_text("Text($r('app.string.hint_go')).fontColor($r('app.color.c_missing'))"
                                       ".width($r('app.float.d_missing'))", encoding="utf-8")
            r = _run(root, "--sweep", "--results-dir", "spec/waves/results/none", "--backfill-refs")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            rep = json.loads((root / "spec/reports/resource-backfill.json").read_text(encoding="utf-8"))
            self.assertEqual(rep["module"], "entry")
            src = {(a["kind"], a["name"]): a["value_source"] for a in rep["added"]}
            self.assertEqual(src[("string", "hint_go")], "name-humanization")
            self.assertEqual(src[("color", "c_missing")], "color-float-sentinel")
            self.assertEqual(src[("float", "d_missing")], "color-float-sentinel")
            self.assertEqual(rep["placeholders"], 2)   # 人话化 string 不计入 placeholders（E138 既有口径），但仍进来源账
            prov = json.loads((root / "spec/reports/resource-placeholders-entry.json").read_text(encoding="utf-8"))
            self.assertEqual({(p["kind"], p["name"]) for p in prov["pending"]},
                             {("string", "hint_go"), ("color", "c_missing"), ("float", "d_missing")})


if __name__ == "__main__":
    unittest.main()
