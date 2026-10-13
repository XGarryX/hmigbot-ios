"""E272 安卓属性名逐处内联注明 ArkUI 写法。

立此判据的事实（ds2 首轮编译错误归因）：域 spec 是 understand 波代理写的散文，里面直接写 `marginStart=40dp`，
任务书原样嵌入、从不给 ArkUI 对应写法 → 代理翻成 `.margin({ start: $r(…) })` → 命中 LocalizedEdges 重载
（只收 LengthMetrics，`$r()` 不兼容）→ **34 条编译错误，占首轮 15%**。
对照：任务书里**没出现过**的名字只造成 5 条错误（`VideoPlayViewModel`，代理自己编）。53 vs 5。

形态是「逐处内联」不是「一张映射表」：`state.md` 的 `@Param @Once` 规则已注入几乎每份出错任务书、
照样错 24 次（通用规则无效）；E259 的逐页形态注明则 3/3→0/3（具体事实有效）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import assemble_prompt as A   # noqa: E402


class TestAnnotate(unittest.TestCase):
    def test_margin_start_gets_left(self):
        out, n = A.annotate_android_attrs("`marginStart=40dp`、`marginTop=120dp`")
        self.assertEqual(n, 1)
        self.assertIn(".margin({ left: 40vp })", out)
        self.assertIn("LocalizedEdges", out)
        self.assertNotIn("marginTop=120dp（", out)      # 无歧义清单之外的不碰

    def test_end_maps_to_right_and_padding(self):
        out, n = A.annotate_android_attrs("marginEnd=16dp paddingStart=8dp paddingEnd=8dp")
        self.assertEqual(n, 3)
        self.assertIn(".margin({ right: 16vp })", out)
        self.assertIn(".padding({ left: 8vp })", out)
        self.assertIn(".padding({ right: 8vp })", out)

    def test_layout_weight(self):
        out, n = A.annotate_android_attrs("`layout_weight=1`")
        self.assertEqual(n, 1)
        self.assertIn(".layoutWeight(1)", out)

    def test_gravity_untouched(self):
        """gravity 146 处但**不碰**——Text 用 textAlign、容器用 justifyContent，按语境定，属判程度（E264 铁律）。"""
        src = "`gravity=center`、`layout_gravity=bottom`、`drawableStart=@drawable/x`"
        out, n = A.annotate_android_attrs(src)
        self.assertEqual((out, n), (src, 0))

    def test_annotation_lands_outside_code_span(self):
        """注解写在反引号外面，否则被裹进代码段、可读性差。"""
        out, _ = A.annotate_android_attrs("`marginStart=40dp`、后续")
        self.assertIn("`marginStart=40dp`（ArkUI", out)

    def test_idempotent(self):
        """任务书可能被重渲多次（重派 / 符号级裁剪重建），注明必须幂等。"""
        once, n1 = A.annotate_android_attrs("`marginStart=40dp`")
        twice, n2 = A.annotate_android_attrs(once)
        self.assertEqual((n1, n2), (1, 0))
        self.assertEqual(once, twice)

    def test_non_dp_value_passthrough(self):
        out, n = A.annotate_android_attrs("marginStart=@dimen/gap")
        self.assertEqual(n, 1)
        self.assertIn(".margin({ left: @dimen/gap })", out)   # 非 dp 值原样带过，不瞎换算


if __name__ == "__main__":
    unittest.main()


class TestE280Prefix(unittest.TestCase):
    """E280：安卓 XML 真实写法带 layout_ / android:layout_ 前缀。

    原正则 `\b(marginStart|…)` 在下划线前匹配不上（下划线是词字符），
    ds4 实测 87 处靶子漏 76 处（87%）——E272 从落地起就基本没生效。
    """

    def test_layout_prefix_is_matched(self):
        out, n = A.annotate_android_attrs("layout_marginStart=20dp")
        self.assertEqual(n, 1)
        self.assertIn("layout_marginStart=20dp（ArkUI", out)
        self.assertIn(".margin({ left: 20vp })", out)

    def test_android_namespace_prefix_is_matched(self):
        out, n = A.annotate_android_attrs('android:layout_marginEnd="8dp"')
        self.assertEqual(n, 1)
        self.assertIn(".margin({ right: 8vp })", out)

    def test_quotes_are_preserved_verbatim(self):
        """注明器会就地改写域 spec，不得动原文的引号。"""
        out, _ = A.annotate_android_attrs('android:layout_marginEnd="8dp"')
        self.assertIn('android:layout_marginEnd="8dp"（ArkUI', out)
        out2, _ = A.annotate_android_attrs("layout_marginStart='4dp'")
        self.assertIn("layout_marginStart='4dp'（ArkUI", out2)

    def test_bare_form_still_works(self):
        _, n = A.annotate_android_attrs("marginStart=15dp")
        self.assertEqual(n, 1)

    def test_layout_gravity_still_untouched(self):
        """gravity 判语境，E264 铁律下不碰——加前缀支持后也不能漏进来。"""
        for s in ("gravity=center", "layout_gravity=top", "android:layout_gravity=end"):
            _, n = A.annotate_android_attrs(s)
            self.assertEqual(n, 0, s)

    def test_idempotent_with_prefix(self):
        out, n1 = A.annotate_android_attrs("layout_marginStart=20dp")
        _, n2 = A.annotate_android_attrs(out)
        self.assertEqual((n1, n2), (1, 0))

    def test_multiple_on_one_line(self):
        out, n = A.annotate_android_attrs("layout_marginStart=20dp；layout_marginEnd=8dp")
        self.assertEqual(n, 2)
        self.assertIn("left: 20vp", out)
        self.assertIn("right: 8vp", out)

    def test_does_not_match_inside_identifier(self):
        """不能把 xxxmarginStart / a.marginStart 之类误判成属性。"""
        for s in ("foomarginStart=1dp", "obj.marginStart=1dp"):
            _, n = A.annotate_android_attrs(s)
            self.assertEqual(n, 0, s)
