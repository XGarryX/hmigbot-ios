"""Adversarial baseline freezing at the actual scheduler input boundary."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))

from hmigbot_ios.core import MigrationError
from hmigbot_ios.ios_harness import check
from hmigbot_ios.ios_scheduler import baseline_inputs
from hmigbot_ios.plan_contract import structural_digest
from spec_contract_fixture import strict_contract
from test_ios_harness import fixture


FEATURE_INDEX = 'spec/baseline/feature-index.md'


class FreezeContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='freeze-contract-')
        self.addCleanup(self.temp.cleanup)
        self.source, self.project, self.graph = fixture(Path(self.temp.name))
        strict_contract(self.project)
        self.index = self.project / FEATURE_INDEX
        # Base is an ordering dependency; this source fixture has no separate
        # cross-feature contract and must not spell it as a Markdown ref.
        self.index.write_text(self.index.read_text(encoding='utf-8').replace('| base | base |', '| base | 无 |'), encoding='utf-8')

    def append_before_dependencies(self, content):
        text = self.index.read_text(encoding='utf-8')
        self.index.write_text(text.replace('## 依赖图', content + '\n## 依赖图'), encoding='utf-8')

    def test_adjacent_business_table_is_frozen_after_real_source_gate(self):
        # Same width as the core index, no blank line: the original scanner
        # carried the core progress-column mask into this unrelated table.
        headers = ['audit_id', 'topic', 'priority', 'order', 'contract', 'page',
                   'creator', 'complexity', 'tier', 'depth', 'result', 'evidence']
        self.append_before_dependencies('| ' + ' | '.join(headers) + ' |\n'
            + '|' + '|'.join(['---'] * len(headers)) + '|\n'
            + '| audit-1 | API | P0 | base | base | none | none | simple | standard | full | failed | independent |')
        report, code = check(self.project, report_only=True)
        self.assertEqual(code, 0, report['findings'])
        before = baseline_inputs(self.project, 'domains')
        self.index.write_text(self.index.read_text(encoding='utf-8').replace('| failed |', '| passed |'), encoding='utf-8')
        self.assertNotEqual(before, baseline_inputs(self.project, 'domains'))

    def test_business_status_table_with_blank_line_is_not_progress(self):
        self.append_before_dependencies('\n## Payment outcome\n\n| ID | status |\n|---|---|\n| payment-1 | failed |')
        before = baseline_inputs(self.project, 'domains')
        self.index.write_text(self.index.read_text(encoding='utf-8').replace('| failed |', '| passed |'), encoding='utf-8')
        self.assertNotEqual(before, baseline_inputs(self.project, 'domains'))

    def test_data_cell_named_status_cannot_redefine_the_mask(self):
        text = self.index.read_text(encoding='utf-8')
        extra = ('| F002 | status | P0 | base | 无 | page_0001 | page_0001 | simple | standard | full | pending | features/F002.md |\n'
                 '| F003 | failed | P0 | base | 无 | page_0001 | page_0001 | simple | standard | full | pending | features/F003.md |\n')
        text = text.replace('## 依赖图', extra + '## 依赖图')
        self.index.write_text(text, encoding='utf-8')
        before = baseline_inputs(self.project, 'domains')
        self.index.write_text(text.replace('| F003 | failed |', '| F003 | passed |'), encoding='utf-8')
        self.assertNotEqual(before, baseline_inputs(self.project, 'domains'))

    def test_exemption_requires_core_artifact_heading_headers_and_stable_id(self):
        original = self.index.read_text(encoding='utf-8')
        def same_projection(text, artifact=FEATURE_INDEX):
            return structural_digest(text, artifact=artifact) == structural_digest(text.replace('pending', 'implemented'), artifact=artifact)
        self.assertTrue(same_projection(original))
        for text, artifact in [
            (original, 'spec/ref/feature-index.md'),
            (original, None),
            (original.replace('## 功能清单', '## Business state'), FEATURE_INDEX),
            (original.replace('| depth |', '| ownership |'), FEATURE_INDEX),
            (original.replace('| F001 |', '| payment-1 |'), FEATURE_INDEX),
        ]:
            with self.subTest(artifact=artifact, text=text[:100]):
                self.assertFalse(same_projection(text, artifact))

    def test_scope_and_all_nonprogress_core_cells_stay_frozen(self):
        original = self.index.read_text(encoding='utf-8')
        before = structural_digest(original, artifact=FEATURE_INDEX)
        for old, new in [('pending', 'skipped'), ('pending', 'excluded'),
                         ('Counter | P0', 'Counter | P1'), ('| base | 无 |', '| F002 | 无 |'),
                         ('| page_0001 | page_0001 |', '| page_0001 | page_0002 |'),
                         ('features/F001-counter.md', 'features/F001-other.md')]:
            with self.subTest(change=(old, new)):
                self.assertNotEqual(before, structural_digest(original.replace(old, new), artifact=FEATURE_INDEX))

    def test_nonprogress_cell_source_text_is_not_normalized_away(self):
        original = self.index.read_text(encoding='utf-8')
        changed = original.replace('| Counter | P0', '|  Counter  | P0')
        self.assertNotEqual(structural_digest(original, artifact=FEATURE_INDEX),
                            structural_digest(changed, artifact=FEATURE_INDEX))

    def test_authored_text_cannot_impersonate_the_progress_marker(self):
        original = self.index.read_text(encoding='utf-8')
        changed = original.replace('| pending |', '| <managed-progress> |')
        self.assertNotEqual(structural_digest(original, artifact=FEATURE_INDEX),
                            structural_digest(changed, artifact=FEATURE_INDEX))

    def test_managed_progress_block_keeps_its_narrow_line_whitelist(self):
        for value in ('status: passed', 'owner: service', '| F001 | passed |',
                      'generation: passed; Counter.reset clears storage'):
            with self.subTest(value=value):
                with self.assertRaises(MigrationError):
                    structural_digest('<!-- hmigbot-progress:begin -->\n' + value + '\n<!-- hmigbot-progress:end -->', artifact=FEATURE_INDEX)


if __name__ == '__main__':
    unittest.main()
