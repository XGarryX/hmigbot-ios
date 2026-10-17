"""E172（AIPPT_930 移植）：冷启探针证据落盘、只数本应用进程的网络栈日志、hilog 远端报错（rc=0）按 EVIDENCE_LOST 判 FAIL。"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROBE = Path(__file__).parents[1] / 'cold_start_probe.sh'
MOCK = '''#!SHEBANG
import os, sys
args = sys.argv[1:]
scenario = os.environ['TEST_SCENARIO']
if args == ['list', 'targets']:
 print('device')
elif args[0:2] == ['shell', 'ps']:
 print('root 123 1 0 00:00 ? 00:00:01 com.demo')
elif args[0:3] == ['shell', 'hilog', '-x']:
 if scenario == 'error':
  print('Invalid log type [CODE:-3]')
 elif '-P' in args:
  if scenario in ('success', 'noisy'): print('09-18 00:08:33.910  123  123 I A00100/httpclient: request POST dispatched')
  else: print('09-18 00:08:33.910  123  123 I A00100/App: waiting privacy consent')
 else:
  if scenario == 'noisy':
   print('09-18 00:08:33.800  789  789 W C01F00/Settings: Invalid log type in legacy config, fallback to default')
   print('09-18 00:08:33.801  789  789 I C01F00/Shell: Usage: shown for unknown flag')
  print('09-18 00:08:33.910  456  456 I C00100/httpclient: request POST other app')
elif args[0:2] == ['shell', 'cat']:
 print('{}')
'''


class ColdEvidenceTests(unittest.TestCase):
    def run_probe(self, scenario):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            hdc = root / 'hdc'
            hdc.write_text(MOCK.replace('SHEBANG', sys.executable))
            hdc.chmod(0o755)
            evidence = root / 'evidence'
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                       TEST_SCENARIO=scenario, A2H_COLD_EVIDENCE_DIR=str(evidence))
            result = subprocess.run(['bash', str(PROBE), 'com.demo', 'EntryAbility', '0'],
                                    env=env, capture_output=True, text=True, timeout=20)
            return result, {p.name: p.read_text() for p in evidence.iterdir()}

    def test_other_app_network_cannot_pass(self):
        result, evidence = self.run_probe('other')
        self.assertEqual(result.returncode, 1)
        self.assertIn('零网络请求出网', result.stdout)
        self.assertIn('other app', evidence['hilog-all.txt'])
        self.assertIn('waiting privacy consent', evidence['hilog-app.txt'])

    def test_remote_error_rc_zero_is_evidence_failure(self):
        result, evidence = self.run_probe('error')
        self.assertEqual(result.returncode, 1)
        self.assertIn('EVIDENCE_LOST', result.stdout)
        self.assertNotIn('零网络请求出网', result.stdout)

    def test_error_words_inside_log_lines_are_not_evidence_loss(self):
        # E254：日志正文里带 Invalid log type / Usage: 不是命令失败（ds closeout 三次冷启 FAIL 之一即此）
        result, evidence = self.run_probe('noisy')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('EVIDENCE_LOST', result.stdout)
        self.assertIn('Usage: shown for unknown flag', evidence['hilog-all.txt'])

    def test_app_scoped_outbound_trace_retained(self):
        result, evidence = self.run_probe('success')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS', result.stdout)
        self.assertIn('123', evidence['processes.txt'])
        self.assertIn('request POST dispatched', evidence['hilog-app.txt'])


if __name__ == '__main__':
    unittest.main()
