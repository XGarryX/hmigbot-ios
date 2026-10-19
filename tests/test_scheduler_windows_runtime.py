"""Original compiled landing, lint equivalence, and owned Windows process trees."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios import ios_scheduler as scheduler
from hmigbot_ios.core import MigrationError, digest, json_bytes, read_json, write_json
from hmigbot_ios.native_static_runtime import LinearTopDeclaration, original_runtime
from hmigbot_ios import windows_scheduler_runtime as adapter
from hmigbot_ios.scheduler_windows_runtime import run as owned_run
import test_ios_harness as harness_fixture


def load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeclarationEquivalenceTests(unittest.TestCase):
    def test_differential_captures_for_valid_invalid_and_unicode_declarations(self):
        original = load_source('raw_runtime_match_tests', scheduler.UPSTREAM / '_static_runtime.py')._TOP_DECL_RE
        linear = LinearTopDeclaration()
        prefixes = ['const x', 'export const π_变量', 'let $x: string', 'var x: A | B',
                    'const x: Map<string, number>', 'const x?: string', 'static x', 'const',
                    'const x: A = B', 'export let x', '  const x : (() => void)']
        tails = ['', ' ', ';', ' ; ', '1', '1 ; ', 'new X()', 'new X();', 'x = y;',
                 '"  " ;', '\t;\t', '   ', '1\n', '1\n  ', '1\n2', '";";', ';;;;']
        for prefix in prefixes:
            for whitespace in ['', ' ', '\t', '    ']:
                for tail in tails:
                    text = prefix + whitespace + '=' + whitespace + tail
                    with self.subTest(text=text):
                        expected, actual = original.match(text), linear.match(text)
                        self.assertEqual(expected.groups() if expected else None,
                                         actual.groups() if actual else None)

    def test_long_erased_string_has_exact_rhs_and_finishes_without_backtracking(self):
        value = '"' + ' ' * 16422 + '"'
        started = time.monotonic()
        result = LinearTopDeclaration().match('const UNICODE15_FULL_CASE_FOLD: string = ' + value + ';')
        self.assertEqual(result.groups(), ('UNICODE15_FULL_CASE_FOLD', value))
        self.assertIsNone(LinearTopDeclaration().match('let x: A' + ' ' * 20000 + '| B;'))
        self.assertEqual(LinearTopDeclaration().match('let x: A' + ' ' * 20000 + '| B = 1;').groups(), ('x', '1'))
        self.assertLess(time.monotonic() - started, 1)

    def test_original_four_lint_rules_and_safe_fixes_are_retained(self):
        raw = load_source('raw_runtime_rule_tests', scheduler.UPSTREAM / '_static_runtime.py')
        safe = original_runtime(scheduler.UPSTREAM)
        vendor_fixture = load_source('original_static_runtime_fixture',
            scheduler.UPSTREAM / 'tests/test_static_runtime_lint.py')
        with tempfile.TemporaryDirectory(prefix='runtime-rules-') as temp:
            first, second = Path(temp) / 'original', Path(temp) / 'adapted'
            for folder in (first, second):
                folder.mkdir()
                vendor_fixture.make_project(folder)
                ets = folder / 'entry/src/main/ets'
                (ets / 'CycleA.ets').write_text(
                    "import { B } from './CycleB';\nexport const a = B;\n", encoding='utf-8')
                (ets / 'CycleB.ets').write_text(
                    "import { a } from './CycleA';\nexport class B { static v: number = a; }\n", encoding='utf-8')
            for fix in (False, True):
                expected, actual = raw.run_lint(first, fix=fix), safe.run_lint(second, fix=fix)
                self.assertEqual(expected, actual)
                if not fix:
                    self.assertEqual(set(actual['counts']), {'module-init-runtime-dependency',
                        'module-init-cycle-tdz', 'avoid-area-px-as-vp', 'dimen-binding-literal-drift'})
                else:
                    self.assertTrue(actual['fixed'])
                    self.assertNotIn('avoid-area-px-as-vp', actual['counts'])
                self.assertEqual({p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob('*') if p.is_file()},
                                 {p.relative_to(second).as_posix(): p.read_bytes() for p in second.rglob('*') if p.is_file()})


@unittest.skipUnless(os.name == 'nt', 'Windows original compiled scheduler runtime')
class WindowsSchedulerRuntimeTests(unittest.TestCase):
    def setUp(self):
        prior = scheduler.invoke
        adapter.install()
        self.addCleanup(setattr, scheduler, 'invoke', prior)

    def landing_fixture(self, bad=False):
        temp = tempfile.TemporaryDirectory(prefix='compiled-runtime-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        _, project, graph = harness_fixture.fixture(root)
        output = 'entry/src/main/ets/Counter.ets'
        request = root / 'request.json'
        write_json(request, {'schema_version': 2, 'wave': 'domains',
            'graph_sha256': digest(json_bytes(graph)), 'tasks': [{
                'id': 'counter', 'role': 'a2h-ios-converter', 'goal': 'Implement source counter',
                'ownership': [output], 'ac_ids': ['F001-AC01'],
                'fact_ids': [fact['id'] for fact in graph['facts']], 'parents': []}]})
        scheduler.generate(project, request)
        action, code = scheduler.step(project, 'domains')
        self.assertEqual((action['action'], code), ('dispatch', 0))
        path = project / output
        path.parent.mkdir(parents=True)
        source = ('const UNICODE15_FULL_CASE_FOLD: string = "' + 'a' * 16422 + '";\n'
                  'export class Counter { count: number = 0; }\n')
        if bad:
            source += ('class Runtime { constructor() { const ctx = getContext(); } }\n'
                       'export const boot = new Runtime();\n')
        path.write_text(source, encoding='utf-8')
        write_json(project / action['batch'][0]['result_path'], {
            'ios_receipt_version': 2, 'source_sha256': graph['source_sha256'],
            'plan_sha256': digest((project / 'spec/waves/plan-domains.json').read_bytes()),
            'task_id': 'counter', 'status': 'generated', 'behavior_verified': False,
            'file_hashes': {output: digest(path.read_bytes())}, 'ac_ids': ['F001-AC01'],
            'findings': [], 'final_state': 'PASS', 'task': 'counter', 'files_touched': [output],
            'files': [output], 'fixed': [], 'unresolved': [], 'domain': 'counter', 'skipped': []})
        return project, path

    def test_real_compiled_landing_consumes_shim_and_keeps_original_writer(self):
        project, path = self.landing_fixture()
        before = path.read_bytes()
        process = subprocess.run([sys.executable, str(ROOT / 'scripts/a2h_ios.py'),
                                  'land-results', '--project', str(project), '--wave', 'domains'],
                                 capture_output=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr.decode('utf-8', errors='replace'))
        action = json.loads(process.stdout)
        self.assertFalse(action.get('fence_breach'), action)
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue((project / 'spec/state/journal.json').is_file())
        lint = read_json(project / 'spec/reports/static-runtime/land-counter.json')
        self.assertEqual((lint['ok'], lint['scanned'], lint['findings'], lint['fixed']), (True, 1, [], []))
        self.assertEqual(scheduler.step(project, 'domains')[0]['action'], 'done')

    def test_real_compiled_landing_still_rejects_runtime_initialization_fault(self):
        project, _ = self.landing_fixture(bad=True)
        action, _ = scheduler.step(project, 'domains', landing=True)
        lint = read_json(project / 'spec/reports/static-runtime/land-counter.json')
        self.assertFalse(lint['ok'])
        self.assertIn('module-init-runtime-dependency', lint['counts'])
        self.assertNotEqual(scheduler.step(project, 'domains')[0]['action'], 'done', action)

    def test_timeout_terminates_only_owned_tree_and_returns_partial_output(self):
        code = ('import subprocess,sys,time; '
                'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
                'print("owned-child="+str(p.pid),flush=True); '
                'print("partial stderr",file=sys.stderr,flush=True); time.sleep(30)')
        with tempfile.TemporaryDirectory(prefix='owned-timeout-') as temp:
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                owned_run([sys.executable, '-c', code], cwd=temp, env=os.environ.copy(), timeout=1)
        error = raised.exception
        self.assertIn(b'owned-child=', error.output)
        self.assertIn(b'partial stderr', error.stderr)
        self.assertTrue(error.ios_process_tree['job_terminated'])
        child = int(error.output.split(b'owned-child=')[1].splitlines()[0])
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x00100000, False, child)
        if handle:
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            try:
                self.assertEqual(kernel.WaitForSingleObject(handle, 3000), 0)
            finally:
                kernel.CloseHandle(handle)

    def test_job_assignment_failure_never_runs_the_suspended_process_and_closes_handles(self):
        import ctypes
        real_kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        class RefuseAssignment:
            def __call__(self, *args):
                ctypes.set_last_error(5)
                return 0
        class Kernel:
            AssignProcessToJobObject = RefuseAssignment()
            def __getattr__(self, name):
                return getattr(real_kernel, name)
        launched = []
        original_popen = subprocess.Popen
        def capture(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            launched.append(process)
            return process
        with tempfile.TemporaryDirectory(prefix='refused-job-') as temp:
            marker = Path(temp) / 'must-not-run.txt'
            code = f'from pathlib import Path; Path({str(marker)!r}).write_text("ran")'
            with patch('hmigbot_ios.scheduler_windows_runtime.ctypes.WinDLL', return_value=Kernel()), \
                 patch('hmigbot_ios.scheduler_windows_runtime.subprocess.Popen', side_effect=capture):
                with self.assertRaises(OSError):
                    owned_run([sys.executable, '-c', code], cwd=temp, env=os.environ.copy(), timeout=1)
            self.assertFalse(marker.exists())
        self.assertEqual(len(launched), 1)
        self.assertIsNotNone(launched[0].returncode)
        self.assertTrue(launched[0].stdout.closed)
        self.assertTrue(launched[0].stderr.closed)
        self.assertTrue(launched[0]._handle.closed)

    def test_failed_run_replaces_stale_logs_with_its_real_partial_output(self):
        with tempfile.TemporaryDirectory(prefix='runtime-partial-') as temp:
            project = Path(temp)
            logs = project / 'spec/reports/scheduler'
            logs.mkdir(parents=True)
            (logs / 'land_results.stdout.log').write_bytes(b'OLD missing-result')
            failure = subprocess.TimeoutExpired(['original'], 60, output=b'NEW partial', stderr=b'NEW error')
            failure.ios_process_tree = {'root_pid': 123, 'job_terminated': True}
            with patch.object(adapter, 'run_owned_process', side_effect=failure):
                with self.assertRaisesRegex(MigrationError, 'Original scheduler failed'):
                    adapter.invoke(project, 'land_results', [])
            self.assertEqual((logs / 'land_results.stdout.log').read_bytes(), b'NEW partial')
            self.assertEqual((logs / 'land_results.stderr.log').read_bytes(), b'NEW error')
            self.assertTrue(read_json(logs / 'land_results.failure.json')['process_tree']['job_terminated'])


if __name__ == '__main__':
    unittest.main()
