#!/usr/bin/env python3
"""env_doctor 权限体检的扫描范围回归（AIPPT_915_test1 2026-08-30 事故驱动）。

事故：check_permissions 用工程根 rglob("*.ets") 找 http 用法，于是把 install.sh 刚装进
<工程>/.agents/skills/ 的 skill 参考模板也扫了进去——arkts-network-troubleshoot 的
http-client-unwrap.ets 里有 @ohos.net.http。后果是**空模板工程装完 skill 就体检 FAIL**
（"代码用了 http 但缺 INTERNET"），且每个装了本套 skill 的工程必现，FAIL 正卡在迁移
第一道门。业务源码实际命中为 0。

判据：扫描面必须限定在业务模块 <module>/src/**。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILLS / "hmos-env-doctor" / "scripts"))

import env_doctor as ED  # noqa: E402

HTTP_SRC = "import { http } from '@ohos.net.http';\nhttp.createHttp();\n"
MODULE_NO_PERM = '{"module": {"name": "entry", "requestPermissions": []}}'
MODULE_WITH_PERM = '{"module": {"requestPermissions": [{"name": "ohos.permission.INTERNET"}]}}'


def _project(tmp: str, module_json: str, business_ets: str | None,
             skill_ets: str | None) -> str:
    root = Path(tmp)
    main = root / "entry" / "src" / "main"
    (main / "ets" / "pages").mkdir(parents=True)
    (main / "module.json5").write_text(module_json, encoding="utf-8")
    if business_ets is not None:
        (main / "ets" / "pages" / "Index.ets").write_text(business_ets, encoding="utf-8")
    if skill_ets is not None:
        d = root / ".agents" / "skills" / "arkts-network-troubleshoot" / "references" / "templates" / "code"
        d.mkdir(parents=True)
        (d / "http-client-unwrap.ets").write_text(skill_ets, encoding="utf-8")
    return str(root)


class TestPermissionScanScope(unittest.TestCase):
    def test_installed_skill_templates_do_not_trigger_fail(self):
        """装进 .agents/ 的 skill 模板不是业务代码——不得据此判 FAIL。"""
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp, MODULE_NO_PERM, "export struct A {}\n", HTTP_SRC)
            got = ED.check_permissions(p)
        self.assertEqual(got["status"], "PASS", got.get("detail"))

    def test_real_business_http_without_permission_still_fails(self):
        """真业务代码用 http 却没声明 INTERNET——必须照旧 FAIL，不能被改松。"""
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp, MODULE_NO_PERM, HTTP_SRC, None)
            got = ED.check_permissions(p)
        self.assertEqual(got["status"], "FAIL", got.get("detail"))

    def test_business_http_with_permission_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp, MODULE_WITH_PERM, HTTP_SRC, None)
            got = ED.check_permissions(p)
        self.assertEqual(got["status"], "PASS", got.get("detail"))

    def test_skill_template_does_not_mask_real_business_http(self):
        """.agents/ 被排除，但同工程里真业务的 http 仍要抓到。"""
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp, MODULE_NO_PERM, HTTP_SRC, HTTP_SRC)
            got = ED.check_permissions(p)
        self.assertEqual(got["status"], "FAIL", got.get("detail"))

    def test_no_module_json_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ED.check_permissions(tmp)["status"], "WARN")


if __name__ == "__main__":
    unittest.main()
