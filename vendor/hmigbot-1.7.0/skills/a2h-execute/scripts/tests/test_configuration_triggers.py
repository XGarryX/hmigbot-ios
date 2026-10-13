"""E170（AIPPT_930 移植）：`<config>.json5#<字段/权限>` 型 symbol-implemented 触发器按真实配置求值——
requestPermissions 实际声明或字段非空才成立；注释/描述文本/相似名不算；解析失败判不成立。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import verify_handoffs as V  # noqa: E402


class ConfigurationTriggerTests(unittest.TestCase):
    def evaluate(self, text, anchor):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'module.json5').write_text(text)
            return V._trigger_holds({'type': 'symbol-implemented', 'arg': 'module.json5#' + anchor}, [], root)

    def test_permission_declared_and_not_only_comment_or_decoy(self):
        self.assertTrue(self.evaluate('{"module":{"requestPermissions":[{"name":"ohos.permission.APP_TRACKING_CONSENT"}]}}', 'APP_TRACKING_CONSENT')[0])
        for text in ('// APP_TRACKING_CONSENT\n{"module":{}}', '{"module":{"description":"APP_TRACKING_CONSENT"}}',
                     '{"module":{"requestPermissions":[{"name":"ohos.permission.APP_TRACKING_CONSENT_FAKE"}]}}'):
            self.assertFalse(self.evaluate(text, 'APP_TRACKING_CONSENT')[0])

    def test_query_schemes_nonempty_actual_config_field(self):
        self.assertTrue(self.evaluate('{"module":{"querySchemes":["wx"],},}', 'querySchemes')[0])
        self.assertFalse(self.evaluate('{"module":{"querySchemes":[]}}', 'querySchemes')[0])
        self.assertFalse(self.evaluate('{"module":{"description":"querySchemes"}}', 'querySchemes')[0])

    def test_strings_commas_urls_and_comments_preserved(self):
        text = '{/* note */"module":{"querySchemes":["https://demo/a,}",],},}'
        self.assertTrue(self.evaluate(text, 'module.querySchemes')[0])

    def test_malformed_config_fails(self):
        self.assertFalse(self.evaluate('{"module": BROKEN}', 'querySchemes')[0])


if __name__ == '__main__':
    unittest.main()
