"""seed_resources.py 回归：资源 JSON 单写者（播种 + 波尾 sweep）。
立此闸的事实：color/string/float.json 不在任何任务写权里、也无 reduce 合并，页面任务书却让
agent「缺条目就自己往 element JSON 里新增」——53 个并发任务改同一文件。AIPPT_915_test3 实证
agent 的应对是绕开 $r()（硬编码 hex 223 处，string 只引用 8 个）。
固定判据：
  · --seed：安卓 values 名沿用（清洗成合法名），layout/代码无名字面量按稳定规则命名；
    已有同名不覆盖；同值复用既有名；产 resource-index.json（原值 → 资源名）；
  · 幂等：第二次 --seed 新增 0；
  · --sweep：回执 resources_needed[] 合法条目补写、非法条目进 invalid、同名异值记 conflicts
    并给新值换名（值一定可引用）；
  · 缺 literals 产物 → exit 1（不静默）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SCRIPT = SCRIPTS / "seed_resources.py"
sys.path.insert(0, str(SCRIPTS))
import seed_resources as SR  # noqa: E402

ELEM = "entry/src/main/resources/base/element"


def _project(root: Path):
    (root / ELEM).mkdir(parents=True)
    (root / ELEM / "color.json").write_text(json.dumps({"color": [
        {"name": "brand", "value": "#FF3366"}]}), encoding="utf-8")
    (root / ELEM / "string.json").write_text(json.dumps({"string": [
        {"name": "app_name", "value": "AIPPT"}]}), encoding="utf-8")
    (root / "spec/baseline").mkdir(parents=True)
    (root / "spec/baseline/android-literals.json").write_text(json.dumps({
        "values_map": {
            "strings": {"app_name": "AIPPT", "btn_ok": "确定", "bad-name": "带横线"},
            "colors": {"brand": "#ff3366", "text_main": "#333333"},
            "dimens": {"pad_l": "16dp", "title_sp": "18sp"},
        },
        "by_layout": {
            "activity_home.xml": {"texts": ["确定", "关于我们", "Hello World", "已用 %1$s 次"],
                                  "colors": ["#333333", "#F7F7F7"], "dims": ["16dp", "12dp", "0.5dp"]},
        },
        "code_texts": ["网络异常"], "code_colors": ["#FF112233"],
    }, ensure_ascii=False), encoding="utf-8")


def _run(root: Path, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "--project", str(root), *args, "--json"],
                          capture_output=True, text=True)


def _table(root: Path, kind: str) -> dict:
    d = json.loads((root / ELEM / ("%s.json" % kind)).read_text(encoding="utf-8"))
    return {e["name"]: e["value"] for e in d[kind]}


class TestSeed(unittest.TestCase):
    def test_seed_names_values_index_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _project(root)
            r = _run(root, "--seed")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = json.loads(r.stdout)
            strings, colors, floats = _table(root, "string"), _table(root, "color"), _table(root, "float")
            # 安卓资源名沿用；非法字符清洗
            self.assertEqual(strings["btn_ok"], "确定")
            self.assertEqual(strings["bad_name"], "带横线")
            self.assertEqual(strings["app_name"], "AIPPT")            # 既有条目不动
            self.assertEqual(colors["brand"], "#FF3366")              # 既有 brand 不被 values 的 #ff3366 覆盖
            self.assertEqual(colors["text_main"], "#FF333333")        # 6 位归一为 8 位
            self.assertEqual(floats["pad_l"], "16vp"); self.assertEqual(floats["title_sp"], "18fp")
            # layout 无名字面量：ASCII 取 slug、CJK 取稳定哈希、色值/尺寸按值命名
            self.assertEqual(strings["s_hello_world"], "Hello World")
            self.assertEqual(colors["c_fff7f7f7"], "#FFF7F7F7")
            self.assertEqual(floats["d_12vp"], "12vp"); self.assertEqual(floats["d_0_5vp"], "0.5vp")
            self.assertIn("#FF112233", colors.values())                # 代码色值也进
            idx = json.loads((root / "spec/baseline/resource-index.json").read_text(encoding="utf-8"))
            self.assertEqual(idx["texts"]["确定"], "btn_ok")            # 同值复用安卓名，不另造哈希名
            self.assertEqual(idx["texts"]["网络异常"], SR.text_name("网络异常"))
            self.assertEqual(idx["colors"]["#FF333333"], "text_main")
            self.assertEqual(idx["dims"]["16vp"], "pad_l")
            self.assertEqual(idx["texts"]["已用 %1$s 次"][:2], "s_")   # 模板文案照收，占位符不改写
            self.assertEqual(out["conflicts"], 0)
            # 幂等
            r2 = _run(root, "--seed"); out2 = json.loads(r2.stdout)
            self.assertEqual(out2["added"], {"string": 0, "color": 0, "float": 0})
            self.assertEqual(_table(root, "string"), strings)

    def test_seed_without_literals_fails_loud(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / ELEM).mkdir(parents=True)
            r = _run(root, "--seed")
            self.assertEqual(r.returncode, 1)
            self.assertIn("harvest-literals", json.loads(r.stdout)["reason"])


class TestSweep(unittest.TestCase):
    def test_sweep_merges_valid_flags_invalid_and_renames_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _project(root)
            self.assertEqual(_run(root, "--seed").returncode, 0)
            rd = root / "spec/waves/results/domains"; rd.mkdir(parents=True)
            (rd / "impl-a.json").write_text(json.dumps({
                "task": "impl:a", "final_state": "PASS", "files": [],
                "resources_needed": [
                    {"kind": "string", "name": "hint_empty", "value": "暂无数据"},
                    {"kind": "color", "name": "divider", "value": "#EEEEEE"},
                    {"kind": "float", "name": "gap_s", "value": "8vp"},
                    {"kind": "color", "name": "brand", "value": "#000000"},      # 同名异值 → 冲突改名
                    {"kind": "string", "name": "btn_ok", "value": "确定"},       # 同名同值 → 无事
                    {"kind": "string", "name": "1bad", "value": "x"},           # 非法名
                    {"kind": "color", "name": "c_bad", "value": "red"},         # 非法色值
                ]}, ensure_ascii=False), encoding="utf-8")
            # 围栏 JSON 形态的回执也要能扫
            (rd / "impl-b.md").write_text("回执\n```json\n" + json.dumps({
                "task": "impl:b", "final_state": "PASS", "files": [],
                "resources_needed": [{"kind": "string", "name": "hint_empty", "value": "暂无数据"}]},
                ensure_ascii=False) + "\n```\n", encoding="utf-8")
            r = _run(root, "--sweep", "--results-dir", "spec/waves/results/domains")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["scanned"], 2)
            self.assertEqual(out["added"], {"string": 1, "color": 2, "float": 1})   # brand 冲突值另起一名
            strings, colors, floats = _table(root, "string"), _table(root, "color"), _table(root, "float")
            self.assertEqual(strings["hint_empty"], "暂无数据")
            self.assertEqual(colors["divider"], "#FFEEEEEE"); self.assertEqual(floats["gap_s"], "8vp")
            self.assertEqual(colors["brand"], "#FF3366")                               # 既有值不被覆盖
            self.assertEqual(len(out["conflicts"]), 1); self.assertEqual(out["conflicts"][0]["name"], "brand")
            self.assertIn("#FF000000", colors.values())                                # 冲突值仍可引用
            self.assertEqual(sorted(e["entry"]["name"] for e in out["invalid"]), ["1bad", "c_bad"])

    def test_sweep_without_results_dir_is_noop(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); _project(root)
            r = _run(root, "--sweep", "--results-dir", "spec/waves/results/nope")
            self.assertEqual(r.returncode, 0)
            self.assertEqual(json.loads(r.stdout)["added"], {"string": 0, "color": 0, "float": 0})


class TestNaming(unittest.TestCase):
    def test_pure_functions(self):
        self.assertEqual(SR.sanitize_name("9lives"), "r_9lives")
        self.assertEqual(SR.sanitize_name("a-b.c"), "a_b_c")
        self.assertEqual(SR.norm_hex("#abc"), None)
        self.assertEqual(SR.norm_hex("#AABBCC"), "#FFAABBCC")
        self.assertEqual(SR.norm_dim("14sp"), "14fp"); self.assertEqual(SR.norm_dim("wrap"), None)
        self.assertEqual(SR.text_name("Hello World"), "s_hello_world")
        self.assertEqual(SR.text_name("确定"), SR.text_name("确定"))       # 稳定
        self.assertNotEqual(SR.text_name("确定"), SR.text_name("取消"))


if __name__ == "__main__":
    unittest.main()
