"""E247（机制 3：机器能确定的信息由脚本给出）：每份任务书的红线头写明安卓源码根。

AIPPT_930_ds：任务书没写安卓源码根，01:03 起 8 个会话读了同级目录里的另一个同名工程 Android_app/AIPPT（存有旧流水线产物），
closure 代理甚至 `ls Android_app/` 后自选。09-22 在线 A/B（每组 5 次）：不写 2/5 答对、4 次读错工程；写一行 5/5、零误读、token 中位减半。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assemble_prompt as AP  # noqa: E402


class TestE247AndroidRootInRedlines(unittest.TestCase):
    def test_root_line_rendered_with_configured_path(self):
        bp = {"workflow_params": {"project": {"android_src": "/abs/Android_app/X_mock_kit", "root": "/abs/proj"},
                                  "pollution_blocklist": ["<android_src>/spec/"]}, "_dir": Path("/abs/proj/spec/blueprint")}
        txt = AP.section_redlines(bp)
        self.assertIn("安卓源码根：`/abs/Android_app/X_mock_kit`", txt)
        self.assertIn("不要到它的上级目录里另找同名或名字相近的工程", txt)
        self.assertLess(txt.index("安卓源码根"), txt.index("禁止读取"))      # 先给根，再给禁读清单
        self.assertNotIn("{{android_src}}", txt)


if __name__ == "__main__":
    unittest.main()
