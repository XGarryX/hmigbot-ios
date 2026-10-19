"""Only supported text sources with safe paths and valid line ranges are evidence."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.artifact_contract import _evidence, check_artifacts
from hmigbot_ios.core import MigrationError


class ArtifactSourceReferenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='source-ref-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        for relative in ('工程 配置/project.pbxproj', '配置/Base.xcconfig', '隐私/Info.xcprivacy',
                         'Sample.swift', 'Data.json'):
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('first\nsecond\nthird\n', encoding='utf-8')

    def test_three_new_text_suffixes_and_existing_types_with_multiple_anchors(self):
        for relative in ('工程 配置/project.pbxproj', '配置/Base.xcconfig', '隐私/Info.xcprivacy'):
            with self.subTest(path=relative):
                self.assertEqual(_evidence(self.source, f'`{relative}:1-3`; declaration'),
                                 [(relative, 1, 3)])
        self.assertEqual(_evidence(self.source, '`Sample.swift:1`; code; `Data.json:2`; data'),
                         [('Sample.swift', 1, 1), ('Data.json', 2, 2)])

    def test_missing_zero_outside_reversed_absolute_and_traversal_rejected(self):
        absolute = (self.source / 'Sample.swift').as_posix()
        cases = ['Missing.xcconfig:1', '配置/Base.xcconfig:0', '配置/Base.xcconfig:4',
                 '配置/Base.xcconfig:3-2', '配置/Base.xcconfig:2-4', '../outside.pbxproj:1',
                 absolute + ':1', 'C:/outside.xcprivacy:1']
        for text in cases:
            with self.subTest(text=text), self.assertRaises((MigrationError, OSError, UnicodeError)):
                _evidence(self.source, text)

    def test_binary_unsupported_and_fake_suffixes_do_not_pass(self):
        (self.source / 'Image.png').write_bytes(b'\x89PNG\xff\x00')
        (self.source / 'Binary.xcprivacy').write_bytes(b'\xff\xfe\x00')
        (self.source / 'Fake.xcconfig.bak').write_text('text', encoding='utf-8')
        for text in ('Image.png:1', 'Binary.xcprivacy:1', 'Fake.xcconfig.bak:1', 'explanation only'):
            with self.subTest(text=text), self.assertRaises((MigrationError, OSError, UnicodeError)):
                _evidence(self.source, text)

    def test_link_outside_source_cannot_supply_anchor(self):
        outside = self.root / 'outside.xcconfig'
        outside.write_text('outside\n', encoding='utf-8')
        link = self.source / 'linked.xcconfig'
        try:
            link.symlink_to(outside)
        except OSError as exc:
            self.skipTest('Host cannot create an isolated symlink: ' + str(exc))
        with self.assertRaises(MigrationError):
            _evidence(self.source, 'linked.xcconfig:1')

    def test_bad_table_rows_report_data_index_and_first_column_path(self):
        project = self.root / 'project'
        path = project / 'spec/baseline/source-coverage-report.md'
        path.parent.mkdir(parents=True)
        path.write_text('''# Report
## 源归属
| 源路径 | 源证据 |
| --- | --- |
| A.swift | Missing.xcconfig:1 |
| B.swift | Missing.xcprivacy:1 |
''', encoding='utf-8')
        catalog = {'spec': [{'path': 'spec/baseline/source-coverage-report.md', 'sections': [
            {'title': '源归属', 'headers': ['源路径', '源证据']}]}]}
        findings = []
        with patch('hmigbot_ios.artifact_contract.catalog', return_value=catalog):
            check_artifacts(project, self.source, lambda *args: findings.append(args), {})
        failures = [f for f in findings if f[0] == 'ARTIFACT_SOURCE']
        self.assertEqual(len(failures), 2)
        self.assertIn('Table data row 1 (源路径: A.swift), 源证据:', failures[0][2])
        self.assertIn('Table data row 2 (源路径: B.swift), 源证据:', failures[1][2])


if __name__ == '__main__':
    unittest.main()
