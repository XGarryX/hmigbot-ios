import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.ios_scheduler import _execution_evidence


class UsageCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)

    def invoke(self, command, *args):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/a2h_ios.py'), command,
                                 '--project', str(self.project), *args],
                                capture_output=True, encoding='utf-8', timeout=20,
                                env={**os.environ, 'PYTHONIOENCODING': 'gbk', 'PYTHONDONTWRITEBYTECODE': '1'})
        return result.returncode, json.loads(result.stdout)

    def record(self, *, usage, mode):
        request = self.project / 'request.json'
        request.write_text(json.dumps({'call_id': 'call-1', 'raw_usage': usage,
                          'run_id': 'cuike', 'normalization_mode': mode, 'stage': 'convert',
                          'agent': 'remote-codex', 'provider': 'openai'}), encoding='utf-8')
        return self.invoke('usage-record', '--input', str(request))

    def test_end_to_end_budget_and_cached_input(self):
        self.assertEqual(self.invoke('usage-start', '--run-id', 'cuike')[0], 0)
        self.assertEqual(self.invoke('usage-check')[0], 3)  # unfinished is unknown
        code, report = self.record(usage={'input_tokens': 100, 'output_tokens': 20,
                                         'input_tokens_details': {'cached_tokens': 40}}, mode='openai_responses')
        self.assertEqual(code, 0, report)
        self.assertEqual(report['total_tokens'], 120)
        code, report = self.invoke('usage-finish', '--run-id', 'cuike')
        self.assertEqual((code, report['status'], report['total_tokens']), (0, 'PASS', 120))
        self.assertEqual(self.invoke('usage-start', '--run-id', 'reset')[0], 2)

    def test_missing_usage_never_passes(self):
        self.invoke('usage-start', '--run-id', 'cuike')
        self.assertEqual(self.record(usage=None, mode='unreported')[0], 3)
        code, report = self.invoke('usage-finish', '--run-id', 'cuike')
        self.assertEqual((code, report['status']), (3, 'UNKNOWN'))

    def test_ledger_paths_cannot_replace_other_evidence(self):
        for path in ['spec/baseline/usage-budget.json', 'entry/usage-budget.json',
                     'spec/reports/derived/ios-facts.json']:
            code, _ = self.invoke('usage-start', '--run-id', 'cuike', '--ledger', str(self.project / path))
            self.assertEqual(code, 2)
            self.assertFalse((self.project / path).exists())

    def test_lock_is_execution_evidence_without_exempting_product_files(self):
        self.assertTrue(_execution_evidence('spec/reports/derived/usage-budget.json.lock'))
        self.assertTrue(_execution_evidence('spec/reports/derived/run1/usage-budget.json.lock'))
        self.assertFalse(_execution_evidence('entry/usage-budget.json.lock'))
        self.assertFalse(_execution_evidence('spec/baseline/usage-budget.json.lock'))


if __name__ == '__main__':
    unittest.main()
