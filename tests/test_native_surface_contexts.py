"""Exact reviewed comparison lines must not hide active legacy-source commands."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('audit_native_surface', ROOT / 'scripts/audit_native_surface.py')
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class NativeSurfaceContextsTests(unittest.TestCase):
    def fixture(self, tmp, content=b'Do not use Android source instructions.\n'):
        root = Path(tmp)
        (root / 'skills/native').mkdir(parents=True)
        (root / 'docs/upstream').mkdir(parents=True)
        (root / 'policies').mkdir()
        (root / 'skills/native/SKILL.md').write_bytes(content)
        (root / 'docs/upstream/retired-skills.json').write_text('[]', encoding='utf-8')
        context = {'id': 'NATIVE-CONTEXT-001', 'path': 'skills/native/SKILL.md',
                   'text': 'Do not use Android source instructions.',
                   'line_sha256': hashlib.sha256(b'Do not use Android source instructions.\n').hexdigest(),
                   'kind': 'prohibition', 'reason': 'Explicitly prohibits the old source workflow.'}
        (root / 'policies/native-surface-contexts.json').write_text(
            json.dumps({'schema_version': 1, 'contexts': [context]}), encoding='utf-8')
        return root

    def test_exact_reviewed_line_is_disclosed_and_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = AUDIT.audit(self.fixture(tmp))
            self.assertEqual(report['status'], 'passed')
            self.assertEqual(len(report['reviewed_contexts']), 1)
            self.assertEqual(report['reviewed_contexts'][0]['id'], 'NATIVE-CONTEXT-001')
            self.assertEqual(report['reviewed_contexts'][0]['line'], 1)
            self.assertEqual(report['findings'], [])

    def test_edited_text_and_line_ending_do_not_inherit_review(self):
        for content in [b'Do not use Android source instructions.\r\n',
                        b'Use Android source instructions.\n',
                        b'Do not use Android source instructions. `adb install app.apk`\n']:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                report = AUDIT.audit(self.fixture(tmp, content))
                self.assertEqual(report['status'], 'failed')
                self.assertTrue(any(f.get('rule') == 'reviewed-context-stale' for f in report['findings']))
                self.assertEqual(report['reviewed_contexts'], [])

    def test_nearby_real_android_commands_remain_findings(self):
        for command in [b'adb install app.apk\n', b'Run android-source-analysis then parse res/layout.\n',
                        b'Use Gradle to build the Android source.\n']:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp:
                root = self.fixture(tmp, b'Do not use Android source instructions.\n' + command)
                report = AUDIT.audit(root)
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(len(report['reviewed_contexts']), 1)
                self.assertTrue(any(f.get('line') == 2 for f in report['findings']))

    def test_retired_source_skill_is_never_waived_by_line_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp)
            (root / 'docs/upstream/retired-skills.json').write_text('["native"]', encoding='utf-8')
            report = AUDIT.audit(root)
            self.assertEqual(report['status'], 'failed')
            self.assertTrue(any(f.get('rule') == 'retired-source-skill-discoverable'
                                for f in report['findings']))

    def test_same_text_in_another_file_is_not_globally_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp)
            (root / 'skills/native/extra.md').write_bytes(b'Do not use Android source instructions.\n')
            report = AUDIT.audit(root)
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(len(report['reviewed_contexts']), 1)
            self.assertTrue(any(f.get('path') == 'skills/native/extra.md'
                                and f.get('rule') == 'unreviewed-legacy-surface'
                                for f in report['findings']))

    def test_removed_or_duplicated_context_is_reported(self):
        for content, rule in [(b'iOS-only instructions.\n', 'reviewed-context-stale'),
                              (b'Do not use Android source instructions.\n' * 2, 'reviewed-context-ambiguous')]:
            with self.subTest(rule=rule), tempfile.TemporaryDirectory() as tmp:
                report = AUDIT.audit(self.fixture(tmp, content))
                self.assertEqual(report['status'], 'failed')
                self.assertTrue(any(f.get('rule') == rule for f in report['findings']))

    def test_policy_is_required_and_invalid_scope_is_not_an_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp)
            policy = root / 'policies/native-surface-contexts.json'
            value = json.loads(policy.read_text(encoding='utf-8'))
            value['contexts'][0]['path'] = 'skills/**'
            policy.write_text(json.dumps(value), encoding='utf-8')
            report = AUDIT.audit(root)
            self.assertEqual(report['status'], 'failed')
            self.assertTrue(any(f.get('rule') == 'reviewed-context-policy-invalid' for f in report['findings']))
            policy.unlink()
            report = AUDIT.audit(root)
            self.assertEqual(report['status'], 'failed')
            self.assertTrue(any(f.get('rule') == 'reviewed-context-policy-invalid' for f in report['findings']))


if __name__ == '__main__':
    unittest.main()
