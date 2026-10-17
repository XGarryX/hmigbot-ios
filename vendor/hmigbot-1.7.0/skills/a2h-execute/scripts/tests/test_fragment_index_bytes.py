"""E268：fragments/index.json 的 bytes 必须等于片段实测字节数。

立此闸的事实（2026-09-23，E267 收尾时顺带发现）：18 个片段的 bytes 与实际对不上，最大偏差 runtime-patterns.md
记 3187 / 实际 4543、mapping.md 记 3130 / 实际 4751——那张表从落库起就没人跟着片段一起更新。
该字段目前**没有任何消费者**（assemble_prompt._load_trigger_tables 只读 id / triggers.keywords / file / stage，
catalog 只读 provenance；prompt 预算门量的是现场 encode 的真字节），所以漂了也不报错、只会误导看表的人。
本测试把它变成会响的：改片段忘了改 bytes → 套件红。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

FRAGMENTS = Path(__file__).resolve().parent.parent.parent / "references" / "fragments"


def _entries(node, out):
    if isinstance(node, dict):
        if node.get("file") and "bytes" in node:
            out.append(node)
        for v in node.values():
            _entries(v, out)
    elif isinstance(node, list):
        for v in node:
            _entries(v, out)
    return out


class TestFragmentIndexBytes(unittest.TestCase):
    def setUp(self):
        self.index = FRAGMENTS / "index.json"
        self.assertTrue(self.index.is_file(), "片段索引缺失: %s" % self.index)
        self.rows = _entries(json.loads(self.index.read_text(encoding="utf-8")), [])
        self.assertTrue(self.rows, "index.json 里没有带 bytes 的片段条目")

    def test_declared_bytes_match_files(self):
        bad = []
        for e in self.rows:
            f = FRAGMENTS / e["file"]
            if not f.is_file():
                bad.append("%s 文件不存在" % e["file"])
                continue
            real = f.stat().st_size
            if e["bytes"] != real:
                bad.append("%s 记 %d / 实际 %d" % (e["file"], e["bytes"], real))
        self.assertEqual(bad, [], "index.json bytes 与片段实测不符（改片段后请同步该字段）：\n  " + "\n  ".join(bad))

    def test_bytes_are_positive_ints(self):
        for e in self.rows:
            self.assertIsInstance(e["bytes"], int, e.get("file"))
            self.assertGreater(e["bytes"], 0, e.get("file"))


if __name__ == "__main__":
    unittest.main()
