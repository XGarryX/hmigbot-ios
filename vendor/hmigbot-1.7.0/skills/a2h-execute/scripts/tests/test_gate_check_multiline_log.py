"""gate_check.parse_build_log 多行 hvigor 格式回归（第十五批 E23）。
DR_0903 冒烟：DevEco 6 / hvigor 6.x 的 ArkTS 错误分两行——`N ERROR: 10505001 ArkTS Compiler Error` +
`Error Message: … At File: /abs/x.ets:65:32`。旧解析只看含 ERROR 的行 → errors=0、by_domain 空，quick_fix 无清单。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import gate_check as G  # noqa: E402

NEW = """> hvigor ERROR: Failed :entry:default@CompileArkTS...
> hvigor ERROR: ArkTS Compiler Error
1 ERROR: 10505001 ArkTS Compiler Error
Error Message: Declaration or statement expected. At File: /Users/x/proj/entry/src/main/ets/pages/MainPage.ets:91:1
2 ERROR: 10505001 ArkTS Compiler Error
Error Message: No overload matches this call.
  Overload 1 of 2, '(value: string): ImageAttribute', gave the following error.
    Argument of type 'string | Resource' is not assignable to parameter of type 'string'.
      Type 'string' is not assignable to type 'Resource'. At File: /Users/x/proj/entry/src/main/ets/pages/MainPage.ets:65:32
3 ERROR: 10605038 ArkTS Compiler Error
Error Message: Property 'foo' does not exist. At File: /Users/x/proj/entry/src/main/ets/features/main/DiceRandom.ets:7:3
COMPILE RESULT:FAIL {ERROR:3}
> hvigor ERROR: BUILD FAILED in 7 s 984 ms
"""
OLD = "ERROR: ArkTS:ERROR File: /Users/x/entry/src/main/ets/pages/HomePage.ets:12:5 Property 'x' does not exist\nBUILD SUCCESSFUL in 3 s\n"


class TestMultilineLog(unittest.TestCase):
    def test_new_format_attributes_every_error(self):
        errors, unparsed, ok = G.parse_build_log(NEW)
        self.assertEqual([(e["file"].rsplit("/", 1)[1], e["line"]) for e in errors],
                         [("MainPage.ets", 91), ("MainPage.ets", 65), ("DiceRandom.ets", 7)])
        self.assertIn("No overload matches", errors[1]["message"])
        self.assertFalse(ok)
        self.assertTrue(all("COMPILE RESULT" not in u and "BUILD FAILED" not in u for u in unparsed))

    def test_old_format_unchanged(self):
        errors, unparsed, ok = G.parse_build_log(OLD)
        self.assertEqual([(e["file"].rsplit("/", 1)[1], e["line"]) for e in errors], [("HomePage.ets", 12)])
        self.assertTrue(ok); self.assertEqual(unparsed, [])


if __name__ == "__main__":
    unittest.main()
