#!/usr/bin/env python3
"""宿主子代理并行上限自检回归（AIPPT_915_test1 2026-08-30 事故驱动）。

事故：计划按 max_parallel=12 一次性派 12 个 spawn_agent，而 Codex 的
`agents.max_concurrent_threads_per_session` 没配、走内置默认值（偏小）。超出上限的
子代理**静默挂住**——dispatch 账上记为「在飞」，与真在跑的长得一模一样，
表征是整批任务卡在完全相同的时长且与域体量无关（3 个文件的域和 41 个文件的域
一起卡 32 分钟）。两次整批消亡、一个多小时才定位，而装机时一秒可查。

顺带修掉一处悬空引用：SKILL.md 原先指向 `install_check.py`——该文件从未存在。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SCRIPT = SCRIPTS / "host_parallel_check.py"
PY = sys.executable or "python3"


def run(cfg_text, *extra):
    with tempfile.TemporaryDirectory() as td:
        if cfg_text is not None:
            (Path(td) / "config.toml").write_text(cfg_text, encoding="utf-8")
        p = subprocess.run([PY, str(SCRIPT), "--codex-home", td, "--json", *extra],
                           capture_output=True, text=True)
    return p.returncode, p.stdout


class TestHostParallelCheck(unittest.TestCase):
    def test_unconfigured_is_failure(self):
        """事故原样：没有 [agents] 段 → 必须判失败并给修法。"""
        rc, out = run("model = \"gpt-5\"\n[features]\njs_repl = false\n")
        self.assertEqual(rc, 1)
        self.assertIn('"ok": false', out)
        self.assertIn("[agents]", out)          # 修法里必须含可直接粘贴的配置块

    def test_configured_below_need_passes_but_reports_cap(self):
        """配低于缺省不是失败——generate_waves 会按它封顶，只是慢；
        真正致命的是「不可知」（内置默认值未知，计划无从封顶）。"""
        rc, out = run("[agents]\nmax_concurrent_threads_per_session = 3\n")
        self.assertEqual(rc, 0)
        self.assertIn('"configured": 3', out)
        self.assertIn("降到 2 并行", out)

    def test_configured_at_need_passes(self):
        rc, out = run("[agents]\nmax_concurrent_threads_per_session = 12\n")
        self.assertEqual(rc, 0)
        self.assertIn('"ok": true', out)

    def test_higher_than_need_passes(self):
        self.assertEqual(run("[agents]\nmax_concurrent_threads_per_session = 32\n")[0], 0)

    def test_same_key_in_other_section_not_counted(self):
        """只认 [agents] 段下的键——别处的同名键不得冒充。"""
        rc, _ = run("[other]\nmax_concurrent_threads_per_session = 99\n")
        self.assertEqual(rc, 1)

    def test_commented_out_key_not_counted(self):
        rc, _ = run("[agents]\n# max_concurrent_threads_per_session = 99\n")
        self.assertEqual(rc, 1)

    def test_missing_config_file_is_failure(self):
        self.assertEqual(run(None)[0], 1)

    def test_need_defaults_to_generate_waves_constant(self):
        """需求值从 generate_waves.DEFAULT_MAX_PARALLEL 实读，两处不得漂移。"""
        import re
        src = (SCRIPTS / "generate_waves.py").read_text(encoding="utf-8")
        want = int(re.search(r"^DEFAULT_MAX_PARALLEL\s*=\s*(\d+)", src, re.M).group(1))
        rc, out = run("[agents]\nmax_concurrent_threads_per_session = %d\n" % want)
        self.assertEqual(rc, 0)
        self.assertIn('"need": %d' % want, out)

    def test_installers_wire_the_check(self):
        """两个安装器都必须跑这个自检——只修一个等于半修。"""
        codex = SCRIPTS.parents[2]
        for name in ("install.sh", "install.ps1"):
            self.assertIn("host_parallel_check.py",
                          (codex / name).read_text(encoding="utf-8"),
                          "%s 未接装机自检" % name)

    def test_skill_md_has_no_dangling_install_check_reference(self):
        skill = (SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("install_check.py", skill, "SKILL.md 仍指向从未存在的脚本")


if __name__ == "__main__":
    unittest.main()


class TestPlanCapsToHost(unittest.TestCase):
    """计划并行度必须按宿主上限封顶——两个数字分家就会静默挂住（AIPPT_915_test1 事故）。"""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import generate_waves
        self.G = generate_waves

    def test_caps_to_host_limit_minus_side_agent_reserve(self):
        """E19：宿主 8 − 侧代理预留 1 = 7；显式 side_agent_reserve=0 才回到 8；缺省 12 想要 → 7。"""
        self.G.host_parallel_cap = lambda: 8
        self.assertEqual(self.G._effective_max_parallel({}), 7)
        bp0 = {"workflow_params": {"gates": {"side_agent_reserve": 0}}}
        self.assertEqual(self.G._effective_max_parallel({}, bp0), 8)
        bp2 = {"workflow_params": {"gates": {"side_agent_reserve": 2}}}
        self.assertEqual(self.G._effective_max_parallel({"max_parallel": 12}, bp2), 6)
        self.assertEqual(self.G._effective_max_parallel({"max_parallel": 5}, bp2), 5)   # 未触顶不动

    def test_does_not_raise_above_configured_want(self):
        """宿主允许更多不等于要多派——配置值仍是上界。"""
        self.G.host_parallel_cap = lambda: 64
        self.assertEqual(self.G._effective_max_parallel({}), self.G.DEFAULT_MAX_PARALLEL)

    def test_explicit_zero_means_full_concurrency_untouched(self):
        """显式 0 = 整批全并发，是刻意语义，不得被封顶改写。"""
        self.G.host_parallel_cap = lambda: 8
        self.assertEqual(self.G._effective_max_parallel({"max_parallel": 0}), 0)

    def test_unknown_host_limit_keeps_configured(self):
        self.G.host_parallel_cap = lambda: None
        self.assertEqual(self.G._effective_max_parallel({}), self.G.DEFAULT_MAX_PARALLEL)
