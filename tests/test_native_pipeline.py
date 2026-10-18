"""iOS checks must participate in the original findings lifecycle and source contract."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import MigrationError, digest, snapshot
from hmigbot_ios.native_pipeline import configure, index_source, check_source, source_paths, resolve, findings_module


class NativeSourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ios 原流水线 ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source, self.project = self.root / 'ios', self.root / 'harmony'
        shutil.copytree(ROOT / 'tests/fixtures/uikit_interaction', self.source)
        shutil.copytree(ROOT / 'tests/fixtures/a2h-native-spec', self.project)
        configure(self.source, self.project)
        index_source(self.project)

    def test_findings_sections_survive_ios_failure_and_repair(self):
        queue = findings_module()
        other = queue.make('PLAN.TEST', 'plan', 'fixture', 'Unrelated section must remain')
        queue.replace_section(str(self.project), 'plan.fixture', [other])
        self.assertEqual(check_source(self.project)[1], 0)
        page = self.project / 'spec/baseline/ui/page_0001_CounterViewController.md'
        original = page.read_bytes()
        page.write_text(page.read_text(encoding='utf-8').replace('CounterViewController.swift', 'missing.swift'), encoding='utf-8')
        result, code = check_source(self.project)
        self.assertEqual(code, 2)
        self.assertIn('IOS.INVALID_SOURCE_ANCHOR', [f['rule'] for f in result['findings']])
        page.write_bytes(original)
        self.assertEqual(check_source(self.project, after_repair=True)[1], 0)
        self.assertEqual(queue.load(str(self.project))['sections']['plan.fixture']['findings'][0]['rule'], 'PLAN.TEST')

    def test_unmapped_file_cannot_be_silently_ignored(self):
        file = self.source / 'Extra.swift'
        file.write_text('class Extra {}')
        self.assertIn('IOS.STALE_SOURCE', [f['rule'] for f in check_source(self.project)[0]['findings']])
        # Explicit test-only baseline refresh, not a production stale-source repair.
        (self.project / 'spec/baseline/ios-source-index.json').unlink()
        index_source(self.project)
        self.assertIn('IOS.SOURCE_UNACCOUNTED', [f['rule'] for f in check_source(self.project)[0]['findings']])
        disposition = self.project / 'spec/baseline/ios-source-disposition.json'
        reviewed = {'source_sha256': snapshot(self.source)['sha256'], 'files': [{
            'path': 'Extra.swift', 'disposition': 'test', 'reason': 'Fixture only',
            'line': 1, 'end_line': 1, 'source_sha256': digest((self.source / 'Extra.swift').read_bytes())}]}
        # Evidence without the literal exclusion proof fails at this gate, not in Stage 0.
        incomplete = json.loads(json.dumps(reviewed))
        for field in ('line', 'end_line', 'source_sha256'):
            del incomplete['files'][0][field]
        disposition.write_text(json.dumps(reviewed))
        self.assertEqual(check_source(self.project)[1], 0)
        for stale in (incomplete, {**reviewed, 'source_sha256': '0' * 64}):
            disposition.write_text(json.dumps(stale))
            self.assertEqual(check_source(self.project)[1], 2)
        disposition.write_text('{"files": [null]}')
        self.assertEqual(check_source(self.project)[1], 2)

    def test_anchor_spaces_resolver_ambiguity_and_traversal(self):
        self.assertEqual(source_paths('source_anchors:\n  - path: "Screens/My View.swift"\n'), ['Screens/My View.swift'])
        for folder in ('A', 'B'):
            (self.source / folder).mkdir()
            (self.source / folder / 'Shared.swift').write_text('struct Shared {}')
        self.assertEqual(resolve(self.source, 'Shared.swift')[0]['status'], 'AMBIGUOUS')
        with self.assertRaises(MigrationError): resolve(self.source, '../outside.swift')

    def test_config_does_not_repurpose_android_or_nest_source(self):
        cfg = json.loads((self.project / '.migbot/config.json').read_text())
        self.assertEqual(cfg['source_platform'], 'ios')
        self.assertNotIn('android', cfg)
        with self.assertRaises(MigrationError): configure(self.source, self.root)
        with self.assertRaises(MigrationError): index_source(self.project)


if __name__ == '__main__':
    unittest.main()
