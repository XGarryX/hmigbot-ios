"""The catalog core index owns scope; a target component is not a filename."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))

from hmigbot_ios.core import MigrationError
from hmigbot_ios.plan_contract import validate_plan
import test_plan_contract as plan_fixture


class CatalogTargetTests(unittest.TestCase):
    def setUp(self):
        self.fixture = plan_fixture.PlanContractTests('test_valid_explicit_merge_and_transitive_consumer')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.project, self.request = self.fixture.project, self.fixture.request
        self.manifest = self.project / 'spec/baseline/ui-manifest.md'

    def test_catalog_combined_filename_component_column_accepts_one_path(self):
        original = self.manifest.read_text(encoding='utf-8')
        for target in ['entry/Counter.ets / Counter', '`entry/Counter.ets` / `Counter`', '`entry/Counter.ets / Counter`']:
            with self.subTest(target=target):
                self.manifest.write_text(original.replace('entry/Counter.ets', target), encoding='utf-8')
                self.assertEqual(validate_plan(self.project, self.request)['status'], 'PASS')

    def test_unrelated_tables_with_same_page_and_feature_ids_do_not_define_scope(self):
        with self.manifest.open('a', encoding='utf-8') as stream:
            stream.write('\n## Runtime evidence\n| page_id | status | target_path |\n|---|---|---|\n| page_0001 | failed | entry/Other.ets |\n')
        with (self.project / 'spec/baseline/feature-index.md').open('a', encoding='utf-8') as stream:
            stream.write('\n## Review\n| ID | status |\n|---|---|\n| F001 | failed |\n')
        self.assertEqual(validate_plan(self.project, self.request)['status'], 'PASS')

    def test_target_filename_with_spaces_still_matches_exact_owned_path(self):
        path = 'entry/src/main/ets/pages/Coffee Timer.ets'
        self.manifest.write_text(self.manifest.read_text(encoding='utf-8').replace('entry/Counter.ets', path + ' / CoffeeTimer'), encoding='utf-8')
        self.fixture.items[1]['ownership'] = [path]
        self.fixture.write_plans()
        self.request['tasks'][1] = self.fixture.task('counter', self.fixture.items[1:3], parents=['base'], mapping_reason='UI and service share one owner')
        self.assertEqual(validate_plan(self.project, self.request)['status'], 'PASS')

    def test_ambiguous_target_and_actual_path_change_are_rejected(self):
        original = self.manifest.read_text(encoding='utf-8')
        for target in ['entry/Other.ets / Counter', 'entry/Counter.ets / entry/Other.ets',
                       'entry/Counter.ets, entry/Other.ets', 'entry/Counter.ets / Counter / Other',
                       'entry/Counter.ets;entry/Other.ets', 'entry/Counter.ets/Other.ets',
                       '../Counter.ets / Counter', 'Counter']:
            with self.subTest(target=target):
                self.manifest.write_text(original.replace('entry/Counter.ets', target), encoding='utf-8')
                with self.assertRaises(MigrationError):
                    validate_plan(self.project, self.request)

    def test_wrong_heading_or_incomplete_core_header_is_rejected(self):
        original = self.manifest.read_text(encoding='utf-8')
        for text in [original.replace('## 页面与覆盖层', '## Runtime evidence'),
                     original.replace('| confidence |', '| evidence |')]:
            self.manifest.write_text(text, encoding='utf-8')
            with self.assertRaises(MigrationError):
                validate_plan(self.project, self.request)

    def test_duplicate_full_core_table_cannot_impersonate_another_progress_section(self):
        original = self.manifest.read_text(encoding='utf-8')
        self.manifest.write_text(original + original, encoding='utf-8')
        with self.assertRaises(MigrationError):
            validate_plan(self.project, self.request)


if __name__ == '__main__':
    unittest.main()
