"""禁写面（forbidden surface）回归：第三档越界 + 拍①快照 + 落账还原。
立此闸的事实：AIPPT_915_test3 30 条越界里 21 条写进 spec/（域 spec 被并发改写），资源 JSON
被任务书明令让 agent 自己加——这些面要么 execute 期只读，要么有专职 reduce 单写，agent 的改动
没有一处合法。此前只分 cross_owner / unowned 两档且都只记账。
固定判据：
  · 不在自身围栏、落在禁写面 → kind=forbidden（优先于 cross_owner/unowned）；
  · 自身围栏内的 spec/资源写入合法（understand 读任务写自己的域 spec、mainloop 写资源）；
  · 回执文件 spec/waves/results/** 免检；
  · 快照只收禁写面范围、跳过 spec/waves 与 spec/state；还原：有快照 → restored、
    快照无此文件（代理新建）→ deleted、无快照 → kept_no_snapshot 不动文件；
  · next_batch 有在途时不刷快照。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import _wavelib as W  # noqa: E402
import land_results as L  # noqa: E402
import next_batch as NB  # noqa: E402

BY_ID = {
    "impl:home": {"id": "impl:home", "kind": "agent",
                  "ownership": ["entry/src/main/ets/features/home/**", "entry/src/main/ets/pages/HomePage.ets"]},
    "impl:pay": {"id": "impl:pay", "kind": "agent",
                 "ownership": ["entry/src/main/ets/features/pay/**"]},
    "read:home": {"id": "read:home", "kind": "agent",
                  "ownership": ["spec/domains/home.md", "spec/domains/home.source-notes.md"]},
    "fix:mainloop": {"id": "fix:mainloop", "kind": "agent",
                     "ownership": ["entry/src/main/resources/**", "entry/src/main/ets/entryability/**"]},
}


class TestForbiddenKind(unittest.TestCase):
    def test_spec_and_resources_outside_fence_are_forbidden(self):
        got = L.fence_breach(BY_ID["impl:home"], [
            "entry/src/main/ets/pages/HomePage.ets",                       # 自身围栏
            "spec/domains/home.md",                                        # 禁写面（即使别的任务围栏含它）
            "entry/src/main/resources/base/element/color.json",            # 禁写面
            "entry/src/main/ets/entryability/EntryAbility.ets",            # 禁写面
            "entry/src/main/ets/wiring/WiringRoot.ets",                    # 禁写面
            "entry/src/main/ets/features/pay/PayVM.ets",                   # cross_owner
            "build-profile.json5",                                         # unowned
            "spec/waves/results/domains/impl-home.json",                   # 回执免检
        ], BY_ID)
        kinds = {g["file"]: g["kind"] for g in got}
        self.assertEqual(kinds, {
            "spec/domains/home.md": "forbidden",
            "entry/src/main/resources/base/element/color.json": "forbidden",
            "entry/src/main/ets/entryability/EntryAbility.ets": "forbidden",
            "entry/src/main/ets/wiring/WiringRoot.ets": "forbidden",
            "entry/src/main/ets/features/pay/PayVM.ets": "cross_owner",
            "build-profile.json5": "unowned",
        })

    def test_own_fence_wins_over_forbidden(self):
        self.assertEqual(L.fence_breach(BY_ID["read:home"], ["spec/domains/home.md"], BY_ID), [])
        self.assertEqual(L.fence_breach(BY_ID["fix:mainloop"], [
            "entry/src/main/resources/base/element/string.json",
            "entry/src/main/ets/entryability/EntryAbility.ets"], BY_ID), [])

    def test_is_forbidden_normalizes_paths(self):
        self.assertTrue(W.is_forbidden(".\\spec\\blueprint\\contracts.json"))
        self.assertTrue(W.is_forbidden("./AGENTS.md"))
        self.assertFalse(W.is_forbidden("entry/src/main/ets/pages/A.ets"))
        self.assertFalse(W.is_forbidden("spec/waves/results/infra/x.json"))
        # E39：AIPPT_0903 test4 实证——domains 首批 7/8 任务因写 theme-receipts / source-notes 被判 FENCE_FORBIDDEN 重派
        self.assertFalse(W.is_forbidden("spec/execution/theme-receipts/AppLoadDialog.json"))
        self.assertFalse(W.is_forbidden("spec/domains/app-tips.source-notes.md"))
        self.assertFalse(W.is_forbidden("spec/domains/app-tips/source-notes.md"))
        self.assertTrue(W.is_forbidden("spec/domains/app-tips.md"))
        self.assertTrue(W.is_forbidden("spec/execution/other.json"))


class TestSnapshotRestore(unittest.TestCase):
    def _tree(self, root: Path):
        for rel, body in {
            "spec/domains/home.md": "# home v1\n",
            "spec/blueprint/contracts.json": "{}\n",
            "spec/waves/prompts/domains/impl-home.txt": "big prompt\n",     # 不入快照
            "spec/state/state.json": "{}\n",                                # 不入快照
            "entry/src/main/resources/base/element/color.json": '{"color": []}\n',
            "entry/src/main/ets/entryability/EntryAbility.ets": "export default class EntryAbility {}\n",
            "entry/src/main/ets/pages/HomePage.ets": "@Entry struct HomePage {}\n",   # 不入快照
            "oh_modules/x/index.js": "junk\n",                              # 剪枝
        }.items():
            p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body, encoding="utf-8")

    def test_snapshot_scope_and_restore_modes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._tree(root)
            info = W.snapshot_forbidden(root)
            snap = root / W.SNAPSHOT_DIR
            self.assertEqual(info["files"], 4)
            self.assertTrue((snap / "spec/domains/home.md").is_file())
            self.assertTrue((snap / "entry/src/main/resources/base/element/color.json").is_file())
            self.assertFalse((snap / "spec/waves/prompts/domains/impl-home.txt").exists())
            self.assertFalse((snap / "spec/state/state.json").exists())
            self.assertFalse((snap / "entry/src/main/ets/pages/HomePage.ets").exists())
            # 代理越界：改了域 spec、新建了一个资源文件
            (root / "spec/domains/home.md").write_text("# home TAMPERED\n", encoding="utf-8")
            (root / "entry/src/main/resources/base/element/float.json").write_text('{"float": []}\n', encoding="utf-8")
            self.assertEqual(W.restore_forbidden(root, "spec/domains/home.md"), "restored")
            self.assertEqual((root / "spec/domains/home.md").read_text(encoding="utf-8"), "# home v1\n")
            self.assertEqual(W.restore_forbidden(root, "entry/src/main/resources/base/element/float.json"), "deleted")
            self.assertFalse((root / "entry/src/main/resources/base/element/float.json").exists())
            self.assertEqual(W.restore_forbidden(root, "spec/domains/nothing.md"), "absent")
            self.assertEqual(W.restore_forbidden(root, "../etc/passwd"), "refused_path")
            # 重拍快照会丢弃旧快照（不残留已删除文件）
            (root / "spec/domains/home.md").unlink()
            W.snapshot_forbidden(root)
            self.assertFalse((snap / "spec/domains/home.md").exists())

    def test_restore_without_snapshot_keeps_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._tree(root)
            self.assertEqual(W.restore_forbidden(root, "spec/domains/home.md"), "kept_no_snapshot")
            self.assertEqual((root / "spec/domains/home.md").read_text(encoding="utf-8"), "# home v1\n")

    def test_next_batch_snapshots_only_when_idle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._tree(root)
            NB._snapshot_if_idle(root, ["impl:x"])
            self.assertFalse((root / W.SNAPSHOT_DIR).exists())
            NB._snapshot_if_idle(root, [])
            self.assertTrue((root / W.SNAPSHOT_DIR / ".manifest.json").is_file())
            self.assertEqual(json.loads((root / W.SNAPSHOT_DIR / ".manifest.json").read_text())["files"], 4)


if __name__ == "__main__":
    unittest.main()
