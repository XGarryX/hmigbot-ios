# -*- coding: utf-8 -*-
"""E275：unattended_runner 单实例锁。

ds3 2026-09-26 实测：无锁时同一工程并存 3 个 runner 实例同写 spec/state/runner.jsonl
（监工会话再起一次 a2h_run.py + 孤儿 codex exec 的代理自己又起一次）。账本必脏。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import unattended_runner as ur  # noqa: E402


class TestRunnerLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._held = []

    def tearDown(self):
        for fh in self._held:
            try:
                fh.close()
            except Exception:
                pass
        self.tmp.cleanup()

    def _acquire(self):
        fh, holder = ur.acquire_singleton_lock(self.root)
        if fh is not None:
            self._held.append(fh)
        return fh, holder

    def test_first_acquires_second_refused(self):
        fh1, holder1 = self._acquire()
        self.assertIsNotNone(fh1, "第一个实例应当拿到锁")
        self.assertIsNone(holder1)

        fh2, holder2 = self._acquire()
        self.assertIsNone(fh2, "第二个实例必须拿不到锁")
        self.assertIsInstance(holder2, str)
        self.assertIn(str(os.getpid()), holder2, "占用者信息里要能看到持锁进程的 pid")

    def test_lock_file_records_pid_and_project(self):
        fh, _ = self._acquire()
        self.assertIsNotNone(fh)
        payload = json.loads((self.root / ur.LOCK_REL).read_text(encoding="utf-8"))
        self.assertEqual(payload["pid"], os.getpid())
        self.assertEqual(payload["project"], str(self.root))
        self.assertIn("started", payload)

    def test_release_allows_reacquire(self):
        fh1, _ = self._acquire()
        self.assertIsNotNone(fh1)
        fh1.close()                      # 进程退出等价于此
        self._held.remove(fh1)
        fh2, holder = self._acquire()
        self.assertIsNotNone(fh2, "锁释放后应当能重新获取")
        self.assertIsNone(holder)

    def test_creates_state_dir_when_absent(self):
        self.assertFalse((self.root / "spec" / "state").exists())
        fh, _ = self._acquire()
        self.assertIsNotNone(fh)
        self.assertTrue((self.root / ur.LOCK_REL).is_file())

    def test_second_process_exits_with_code_4(self):
        """端到端：持锁时再起一个真进程，必须 rc=4 且 stderr 说明占用者。"""
        fh, _ = self._acquire()
        self.assertIsNotNone(fh)
        prompt = self.root / "P.md"
        prompt.write_text("x", encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "unattended_runner.py"),
             "--project", str(self.root), "--prompt", str(prompt),
             "--log", str(self.root / "spec/state/runner.jsonl"),
             "--codex", "/bin/true"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(r.returncode, 4, f"stdout={r.stdout!r} stderr={r.stderr!r}")
        self.assertIn("已有 unattended_runner 在跑", r.stderr)

    def test_dry_run_does_not_take_lock(self):
        """--dry-run 只打印，不该占锁，否则排查命令会把真跑批挡在门外。"""
        prompt = self.root / "P.md"
        prompt.write_text("x", encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "unattended_runner.py"),
             "--project", str(self.root), "--prompt", str(prompt),
             "--log", str(self.root / "spec/state/runner.jsonl"),
             "--codex", "/bin/true", "--dry-run"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        fh, holder = self._acquire()
        self.assertIsNotNone(fh, f"--dry-run 之后锁必须是空闲的，实际占用者={holder}")


if __name__ == "__main__":
    unittest.main()
