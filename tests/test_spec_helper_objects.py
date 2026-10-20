"""Unicode discovery and zero-object gates around the bundled spec helpers.

The compiled helpers historically accepted only ASCII feature file names, so
the same document body passed with seven ACs under ``F001-account.md`` and
with zero ACs under ``F001-账号与引导.md``.  These tests pin the source-visible
contract that closes that gap: Chinese and English names are the same
document, main documents and addenda are distinct, duplicate identities are
rejected, and a non-empty expectation with zero discovered objects exits
nonzero.  The original helper stays the implementation of its own divergence
and decision-ledger rules; tests assert those rules still decide PASS/FAIL.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios import spec_discovery, spec_helpers

SCRIPTS = ROOT / 'skills/a2h-spec/scripts'
FIXTURE_DOC = ROOT / 'tests/fixtures/a2h-native-spec/spec/baseline/features/F001-counter.md'
TEMP_BASE = Path('D:/Temp') if os.name == 'nt' and Path('D:/Temp').is_dir() else Path(tempfile.gettempdir())

DOC_HEADER = FIXTURE_DOC.read_text(encoding='utf-8').split('## 验收标准')[0]

LEDGER_FEATURE = """# F001: 账号

## 数据流
登录 → 校验 → 主界面。PD-001 替代路径：使用系统账号选择器替代原登录页。

## 实现映射
| 源 | ArkTS目标 | 契约 | 难度 | 决策 |
| --- | --- | --- | --- | --- |
| UIKit login | ArkUI picker | HARD-DIV PD-001 | 低 | PD-001 supersedes: [F001-AC01] |

## 验收标准
- [ ] F001-AC01 主体登录　`源:A.b → 标:B.c`　`判:unit | x`　`真:src:A.swift:1`　〔superseded by F001-AC02〕
- [ ] F001-AC02 差异断言　`决:PD-001 → 标:B.c`　`判:unit | y`　`真:decision:PD-001`
"""

LEDGER = """# Migration Decisions

## 待批决策（PD-*）

### PD-001 登录差异
- **类目**：C1
- **平台约束**：无等价
- **提议替代**：替代行为
- **影响 AC**：supersedes: [F001-AC01]　emits: [F001-AC02]
- **status**：%s
"""


def account_doc(count=7, feature_id='F001'):
    header = DOC_HEADER.rstrip('\n')
    if feature_id != 'F001':
        header = header.replace('# F001:', '# %s:' % feature_id, 1)
    lines = [header, '## 验收标准']
    for number in range(1, count + 1):
        lines.append(
            '- [ ] %s-AC%02d 账号断言%d　`源:Account.swift:add%d → 标:AccountModel.add%d`'
            '　`判:unit | 断言%d`　`真:src:Account.swift:%d`'
            % (feature_id, number, number, number, number, number, number))
    return '\n'.join(lines) + '\n'


def run_wrapper(script, arguments, cwd=None):
    return subprocess.run(
        [sys.executable, '-X', 'utf8', str(SCRIPTS / script), *map(str, arguments)],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        cwd=str(cwd) if cwd is not None else None)


class WrapperTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hmigbot object gate 空格 ',
                                               dir=str(TEMP_BASE))
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)

    def project(self, name='project'):
        root = self.tmp / name
        (root / 'spec/baseline/features').mkdir(parents=True)
        return root

    def features(self, project):
        return project / 'spec/baseline/features'

    @staticmethod
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


class DivergenceWrapperTests(WrapperTestCase):
    script = 'lint_divergence.py'

    def test_english_and_chinese_same_body_report_the_same_counts(self):
        body = account_doc()
        for name, filename in (('english', 'F001-account.md'),
                               ('chinese', 'F001-账号与引导.md')):
            with self.subTest(name=name):
                project = self.project(name)
                self.write(self.features(project) / filename, body)
                result = run_wrapper(self.script, ['--spec-dir', self.features(project), '--gate'])
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, output)
                self.assertIn('mains=1  parity ACs=7  divergence ACs=0', result.stdout)
                self.assertIn('RESULT: PASS', result.stdout)
                self.assertNotIn('F001-doc-', output, 'ASCII alias must not leak to users')

    def test_mixed_english_and_chinese_document_set_is_one_expected_set(self):
        project = self.project('mixed')
        self.write(self.features(project) / 'F001-account.md', account_doc(3))
        self.write(self.features(project) / 'F002-账号.md', account_doc(3, 'F002'))
        result = run_wrapper(self.script, ['--spec-dir', self.features(project), '--gate'])
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn('mains=2  parity ACs=6  divergence ACs=0', result.stdout)
        self.assertIn('RESULT: PASS', result.stdout)
        self.assertNotIn('F002-doc-', output)

    def test_addendum_is_ignored_by_counts_and_never_replaced(self):
        project = self.project()
        self.write(self.features(project) / 'F001-账号与引导.md', account_doc())
        self.write(self.features(project) / 'F001-账号与引导.state.md',
                   '# 附加状态说明\n- [ ] F001-AC08 附加断言　`源:A.swift:9 → 标:B.ets:9`\n')
        result = run_wrapper(self.script, ['--spec-dir', self.features(project), '--gate'])
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn('mains=1  parity ACs=7  divergence ACs=0', result.stdout)
        self.assertIn('RESULT: PASS', result.stdout)

    def test_duplicate_feature_id_and_duplicate_ac_identities_fail_closed(self):
        duplicate_id = self.project('duplicate-id')
        self.write(self.features(duplicate_id) / 'F001-account.md', account_doc())
        self.write(self.features(duplicate_id) / 'F001-账号与引导.md', account_doc())
        result = run_wrapper(self.script, ['--spec-dir', self.features(duplicate_id), '--gate'])
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn('DUPLICATE_FEATURE_ID', output)
        self.assertNotIn('RESULT: PASS', output)

        duplicate_ac = self.project('duplicate-ac')
        self.write(self.features(duplicate_ac) / 'F001-账号.md',
                   account_doc(2) + '- [ ] F001-AC01 重复断言　`源:A.swift:1 → 标:B.ets:1`\n')
        result = run_wrapper(self.script, ['--spec-dir', self.features(duplicate_ac), '--gate'])
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn('DUPLICATE_AC_ID', output)
        self.assertNotIn('RESULT: PASS', output)

    def test_empty_missing_and_wrong_scope_exit_nonzero(self):
        empty = self.project('empty')
        result = run_wrapper(self.script, ['--spec-dir', self.features(empty), '--gate'])
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertIn('ZERO_OBJECTS', output)
        self.assertNotIn('RESULT: PASS', output)

        allowed = run_wrapper(self.script, ['--spec-dir', self.features(empty), '--gate',
                                           '--allow-empty'])
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        self.assertIn('mains=0  parity ACs=0  divergence ACs=0', allowed.stdout)

        wrong_scope = self.project('wrong-scope')
        self.write(wrong_scope / 'README.md', '# not a spec\n')
        result = run_wrapper(self.script, ['--spec-dir', wrong_scope, '--gate'])
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn('ZERO_OBJECTS', output)
        self.assertNotIn('RESULT: PASS', output)

        missing = run_wrapper(self.script, ['--spec-dir', self.tmp / 'does-not-exist', '--gate'])
        output = missing.stdout + missing.stderr
        self.assertEqual(missing.returncode, 2, output)
        self.assertIn('SPEC_DIR_MISSING', output)
        self.assertNotIn('RESULT: PASS', output)

    def test_decision_ledger_semantics_survive_the_unicode_bridge(self):
        project = self.project('ledger')
        features = self.features(project)
        self.write(features / 'F001-账号与引导.md', LEDGER_FEATURE)
        self.write(project / 'spec/decision-ledger.md', LEDGER % 'proposed')
        custom = self.tmp / 'approved-ledger.md'
        self.write(custom, LEDGER % 'approved')

        blocked = run_wrapper(self.script, ['--spec-dir', features, '--gate'])
        output = blocked.stdout + blocked.stderr
        self.assertEqual(blocked.returncode, 1, output)
        self.assertIn('R2', output)
        self.assertIn('F001-账号与引导.md', output, 'the real Unicode name, not an alias')
        self.assertNotIn('F001-doc-', output)
        self.assertNotIn('RESULT: PASS', output)

        allowed = run_wrapper(self.script, ['--spec-dir', features, '--gate',
                                           '--ledger', custom])
        output = allowed.stdout + allowed.stderr
        self.assertEqual(allowed.returncode, 0, output)
        self.assertIn('mains=1  parity ACs=1  divergence ACs=1', allowed.stdout)
        self.assertIn('RESULT: PASS', allowed.stdout)
        self.assertNotIn('F001-doc-', output)

    def test_help_is_delegated_to_the_bundled_helper(self):
        result = run_wrapper(self.script, ['--help'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('usage: lint_divergence.py', result.stdout)


class TraceabilityWrapperTests(WrapperTestCase):
    script = 'build_traceability_index.py'

    def index(self, project):
        return project / 'spec/.a2h/requirements-index.json'

    def test_english_and_chinese_same_body_index_all_seven_with_real_paths(self):
        body = account_doc()
        results = {}
        for name, filename in (('english', 'F001-account.md'),
                               ('chinese', 'F001-账号与引导.md')):
            with self.subTest(name=name):
                project = self.project(name)
                self.write(self.features(project) / filename, body)
                out = self.tmp / (name + '-index.json')
                result = run_wrapper(self.script, ['--project-root', project, '--out', out])
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, output)
                self.assertNotIn('F001-doc-', output)
                payload = json.loads(out.read_text(encoding='utf-8'))
                self.assertEqual(payload['_meta']['total'], 7)
                self.assertEqual([item['requirement_id'] for item in payload['requirements']],
                                 ['F001-AC%02d' % number for number in range(1, 8)])
                self.assertEqual({item['spec_uri'] for item in payload['requirements']},
                                 {'spec/baseline/features/' + filename})
                results[name] = payload
        self.assertEqual({item['requirement_id'] for item in results['english']['requirements']},
                         {item['requirement_id'] for item in results['chinese']['requirements']})

    def test_mixed_english_and_chinese_document_set_keeps_both_real_paths(self):
        project = self.project('mixed')
        self.write(self.features(project) / 'F001-account.md', account_doc(3))
        self.write(self.features(project) / 'F002-账号.md', account_doc(3, 'F002'))
        result = run_wrapper(self.script, ['--project-root', project])
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        payload = json.loads(self.index(project).read_text(encoding='utf-8'))
        self.assertEqual(payload['_meta']['total'], 6)
        self.assertEqual({item['spec_uri'] for item in payload['requirements']},
                         {'spec/baseline/features/F001-account.md',
                          'spec/baseline/features/F002-账号.md'})
        self.assertEqual({item['requirement_id'] for item in payload['requirements']},
                         {'F001-AC%02d' % number for number in range(1, 4)}
                         | {'F002-AC%02d' % number for number in range(1, 4)})

    def test_main_document_plus_addendum_indexes_the_main_document_only(self):
        project = self.project()
        self.write(self.features(project) / 'F001-账号与引导.md', account_doc())
        self.write(self.features(project) / 'F001-账号与引导.protocol.md',
                   '# 协议附加\n- [ ] F001-AC09 附加协议　`源:P.swift:1 → 标:Q.ets:1`'
                   '　`判:unit`　`真:src:P.swift:1`\n')
        result = run_wrapper(self.script, ['--project-root', project])
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        payload = json.loads(self.index(project).read_text(encoding='utf-8'))
        self.assertEqual(payload['_meta']['total'], 7)
        self.assertNotIn('F001-AC09',
                         [item['requirement_id'] for item in payload['requirements']])
        self.assertEqual({item['spec_uri'] for item in payload['requirements']},
                         {'spec/baseline/features/F001-账号与引导.md'})

    def test_duplicates_and_empty_scope_never_publish_an_index(self):
        duplicate_id = self.project('duplicate-id')
        self.write(self.features(duplicate_id) / 'F001-account.md', account_doc())
        self.write(self.features(duplicate_id) / 'F001-账号.md', account_doc())
        result = run_wrapper(self.script, ['--project-root', duplicate_id])
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn('DUPLICATE_FEATURE_ID', output)
        self.assertFalse(self.index(duplicate_id).exists())

        duplicate_ac = self.project('duplicate-ac')
        self.write(self.features(duplicate_ac) / 'F001-账号.md',
                   account_doc(2) + '- [ ] F001-AC01 重复断言　`源:A.swift:1 → 标:B.ets:1`\n')
        result = run_wrapper(self.script, ['--project-root', duplicate_ac])
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 3, output)
        self.assertIn('DUPLICATE_AC_ID', output)
        self.assertFalse(self.index(duplicate_ac).exists())

        empty = self.project('empty')
        result = run_wrapper(self.script, ['--project-root', empty])
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertIn('ZERO_OBJECTS', output)
        self.assertFalse(self.index(empty).exists())

        allowed = run_wrapper(self.script, ['--project-root', empty, '--allow-empty'])
        output = allowed.stdout + allowed.stderr
        self.assertEqual(allowed.returncode, 0, output)
        payload = json.loads(self.index(empty).read_text(encoding='utf-8'))
        self.assertEqual(payload['_meta']['total'], 0)
        self.assertEqual(payload['requirements'], [])

    def test_missing_scope_and_existing_index_are_left_alone(self):
        missing = run_wrapper(self.script, ['--project-root', self.tmp / 'no-project'])
        output = missing.stdout + missing.stderr
        self.assertEqual(missing.returncode, 2, output)
        self.assertIn('SPEC_DIR_MISSING', output)

        project = self.project('guard-failure')
        self.write(self.features(project) / 'F001-account.md', account_doc())
        self.write(self.features(project) / 'F001-账号.md', account_doc())
        sentinel = '{"sentinel": "unchanged"}\n'
        self.write(self.index(project), sentinel)
        result = run_wrapper(self.script, ['--project-root', project])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.index(project).read_text(encoding='utf-8'), sentinel)

    def test_relative_out_is_resolved_against_the_caller_directory(self):
        project = self.project()
        self.write(self.features(project) / 'F001-账号与引导.md', account_doc(3))
        result = run_wrapper(self.script, ['--project-root', project, '--out', 'relative-index.json'],
                             cwd=self.tmp)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        payload = json.loads((self.tmp / 'relative-index.json').read_text(encoding='utf-8'))
        self.assertEqual(payload['_meta']['total'], 3)

    def test_help_is_delegated_to_the_bundled_helper(self):
        result = run_wrapper(self.script, ['--help'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('usage: build_traceability_index.py', result.stdout)


class DiscoveryRuleTests(WrapperTestCase):
    def test_unicode_ascii_and_mixed_names_are_the_same_kind_of_document(self):
        for name in ('F001-counter.md', 'F001-账号与引导.md', 'F001-账号-counter.md',
                     'F001_Account.md'):
            with self.subTest(name=name):
                document = spec_discovery.classify_name(name)
                self.assertIsNotNone(document)
                self.assertEqual((document.feature_id, document.kind), ('F001', 'main'))
        for name in ('F001-账号与引导.state.md', 'F001-account.protocol.md'):
            with self.subTest(name=name):
                document = spec_discovery.classify_name(name)
                self.assertEqual((document.feature_id, document.kind), ('F001', 'addendum'))
        self.assertIsNone(spec_discovery.classify_name('README.md'))
        self.assertIsNone(spec_discovery.classify_name('page_0001.md'))
        self.assertIsNone(spec_discovery.classify_name('F001-账号.txt'))

    def test_main_and_addendum_sets_are_validated(self):
        project = self.project()
        features = self.features(project)
        self.write(features / 'F001-账号.md', account_doc(2))
        self.write(features / 'F001-账号.state.md', '# 状态\n')
        discovery = spec_discovery.discover(features)
        self.assertEqual([document.name for document in discovery.mains], ['F001-账号.md'])
        self.assertEqual([document.name for document in discovery.addenda],
                         ['F001-账号.state.md'])
        self.assertEqual(discovery.addenda_for('F001')[0].slug, 'state')

        orphan = self.project('orphan')
        self.write(self.features(orphan) / 'F009-孤儿.state.md', '# 状态\n')
        with self.assertRaises(spec_discovery.DiscoveryError) as raised:
            spec_discovery.discover(self.features(orphan))
        self.assertEqual(raised.exception.code, 'ORPHAN_ADDENDUM')

    def test_duplicate_and_mismatched_identities_are_errors(self):
        duplicated = self.project('duplicate')
        self.write(self.features(duplicated) / 'F001-a.md', account_doc(1))
        self.write(self.features(duplicated) / 'F001-账号.md', account_doc(1))
        with self.assertRaises(spec_discovery.DiscoveryError) as raised:
            spec_discovery.discover(self.features(duplicated))
        self.assertEqual(raised.exception.code, 'DUPLICATE_FEATURE_ID')

        mismatched = self.project('mismatched')
        self.write(self.features(mismatched) / 'F001-a.md',
                   '# F001\n- [ ] F002-AC01 别人的断言\n')
        discovery = spec_discovery.discover(self.features(mismatched))
        with self.assertRaises(spec_discovery.DiscoveryError) as raised:
            spec_discovery.acceptance_documents(discovery)
        self.assertEqual(raised.exception.code, 'MISMATCHED_AC_ID')

    def test_zero_documents_need_explicit_opt_in_and_missing_dir_never_passes(self):
        empty = self.tmp / 'empty-features'
        empty.mkdir()
        with self.assertRaises(spec_discovery.DiscoveryError) as raised:
            spec_discovery.discover(empty)
        self.assertEqual(raised.exception.code, 'ZERO_OBJECTS')
        discovery = spec_discovery.discover(empty, allow_empty=True)
        self.assertEqual(discovery.mains, ())
        with self.assertRaises(spec_discovery.DiscoveryError) as raised:
            spec_discovery.discover(self.tmp / 'missing', allow_empty=True)
        self.assertEqual(raised.exception.code, 'SPEC_DIR_MISSING')

    def test_ascii_alias_is_deterministic_and_accepted_by_both_helper_filters(self):
        document = spec_discovery.classify_name('F001-账号与引导.md')
        alias = spec_helpers.alias_name(document)
        self.assertEqual(alias, spec_helpers.alias_name(document))
        self.assertFalse(spec_helpers.helper_discovers(document.name, spec_helpers.DIVERGENCE))
        self.assertFalse(spec_helpers.helper_discovers(document.name, spec_helpers.TRACEABILITY))
        self.assertTrue(spec_helpers.helper_discovers(alias, spec_helpers.DIVERGENCE))
        self.assertTrue(spec_helpers.helper_discovers(alias, spec_helpers.TRACEABILITY))


class ObjectValidationTests(WrapperTestCase):
    def setUp(self):
        super().setUp()
        self.project_root = self.project('unit')
        self.write(self.features(self.project_root) / 'F001-账号.md', account_doc(2))
        self.discovery = spec_discovery.discover(self.features(self.project_root))
        self.ids = ['F001-AC01', 'F001-AC02']

    @staticmethod
    def payload(ids, uri='spec/baseline/features/F001-账号.md'):
        requirements = []
        for requirement_id in ids:
            requirements.append({
                'requirement_id': requirement_id,
                'kind': 'acceptance_criterion',
                'feature_id': requirement_id.split('-AC', 1)[0],
                'spec_uri': uri,
                'assertion': 'assertion',
                'assertion_digest': 'sha256:' + '0' * 16,
                'status': 'active',
                'oracle': None,
                'truth_source': None,
            })
        return {
            '_meta': {'total': len(requirements), 'active': len(requirements),
                      'with_oracle': 0, 'with_truth_source': 0, 'duplicate_ids': []},
            'requirements': requirements,
        }

    def rejected(self, payload, code):
        with self.assertRaises(spec_helpers.ObjectContractError) as raised:
            spec_helpers.validate_traceability_index(payload, self.discovery, {})
        self.assertEqual(raised.exception.code, code)

    def test_unicode_uri_is_normalized_and_alias_is_mapped_back(self):
        normalized, stats = spec_helpers.validate_traceability_index(
            self.payload(self.ids), self.discovery, {})
        self.assertEqual({item['spec_uri'] for item in normalized['requirements']},
                         {'spec/baseline/features/F001-账号.md'})
        self.assertEqual(stats.requirements, 2)

        aliased, _ = spec_helpers.validate_traceability_index(
            self.payload(self.ids, 'spec/baseline/features/F001-doc-abc123.md'),
            self.discovery, {'F001-doc-abc123.md': 'F001-账号.md'})
        self.assertEqual({item['spec_uri'] for item in aliased['requirements']},
                         {'spec/baseline/features/F001-账号.md'})

    def test_schema_identity_and_meta_tampering_fail_closed(self):
        missing = self.payload(self.ids)
        del missing['requirements'][0]['assertion_digest']
        self.rejected(missing, 'INDEX_SCHEMA')

        duplicate = self.payload(self.ids + ['F001-AC01'])
        self.rejected(duplicate, 'DUPLICATE_AC_ID')

        unexpected = self.payload(['F001-AC01', 'F001-AC02', 'F001-AC03'])
        self.rejected(unexpected, 'UNEXPECTED_OBJECT')

        unknown = self.payload(self.ids, 'spec/baseline/features/F001-unknown.md')
        self.rejected(unknown, 'UNKNOWN_OBJECT')

        wrong_parent = self.payload(self.ids, 'other/features/F001-账号.md')
        self.rejected(wrong_parent, 'OBJECT_MAPPING')

        wrong_meta = self.payload(self.ids)
        wrong_meta['_meta']['total'] = 5
        self.rejected(wrong_meta, 'INDEX_META')

        missing_id = self.payload(['F001-AC01'])
        self.rejected(missing_id, 'EXPECTED_COUNT_MISMATCH')

    def test_zero_actual_and_mismatched_divergence_counts_are_guarded(self):
        empty_dir = self.tmp / 'empty-unit'
        empty_dir.mkdir()
        empty = spec_discovery.discover(empty_dir, allow_empty=True)
        with self.assertRaises(spec_helpers.ObjectContractError) as raised:
            spec_helpers.verify_divergence_objects(empty, {'mains': 0, 'parity': 1,
                                                           'divergence': 0})
        self.assertEqual(raised.exception.code, 'ZERO_OBJECTS')

        with self.assertRaises(spec_helpers.ObjectContractError) as raised:
            spec_helpers.verify_divergence_objects(
                self.discovery, {'mains': 1, 'parity': 0, 'divergence': 0})
        self.assertEqual(raised.exception.code, 'EXPECTED_COUNT_MISMATCH')

        spec_helpers.verify_divergence_objects(
            self.discovery, {'mains': 1, 'parity': 2, 'divergence': 0})


class FollowupBoundaryTests(WrapperTestCase):
    def test_gbk_guard_reports_unicode_filename_as_utf8_without_traceback(self):
        project = self.project()
        self.write(self.features(project) / 'F001-account.md', account_doc(1))
        self.write(self.features(project) / 'F001-账号😀.md', account_doc(1))
        environment = dict(os.environ, PYTHONIOENCODING='gbk', PYTHONUTF8='0')
        for script, arguments in (
                ('lint_divergence.py', ['--spec-dir', self.features(project), '--gate']),
                ('build_traceability_index.py', ['--project-root', project])):
            result = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, arguments)],
                                    capture_output=True, env=environment)
            output = (result.stdout + result.stderr).decode('utf-8')
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn('DUPLICATE_FEATURE_ID', output)
            self.assertIn('F001-账号😀.md', output)
            self.assertNotIn('UnicodeEncodeError', output)
            self.assertNotIn('RESULT: PASS', output)

    def test_gbk_normal_output_and_real_index_paths_remain_utf8(self):
        project = self.project()
        filename = 'F001-账号😀.md'
        self.write(self.features(project) / filename, account_doc(1))
        environment = dict(os.environ, PYTHONIOENCODING='gbk', PYTHONUTF8='0')
        for script, arguments in (
                ('lint_divergence.py', ['--spec-dir', self.features(project), '--gate']),
                ('build_traceability_index.py', ['--project-root', project])):
            result = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, arguments)],
                                    capture_output=True, env=environment)
            output = (result.stdout + result.stderr).decode('utf-8')
            self.assertEqual(result.returncode, 0, output)
            self.assertNotIn('\ufffd', output, 'helper diagnostics must retain their Unicode text')
        payload = json.loads((project / 'spec/.a2h/requirements-index.json').read_text(encoding='utf-8'))
        self.assertEqual(payload['requirements'][0]['spec_uri'], 'spec/baseline/features/' + filename)

    def test_output_cannot_overwrite_main_baseline_ledger_or_hardlink(self):
        project = self.project()
        source = self.features(project) / 'F001-账号.md'
        self.write(source, account_doc(1))
        ledger = project / 'spec/decision-ledger.md'
        self.write(ledger, LEDGER % 'approved')
        baseline = project / 'spec/baseline/source.json'
        self.write(baseline, '{"source":true}')
        hardlink = self.tmp / 'hardlink-index.json'
        os.link(source, hardlink)
        ledger_hardlink = self.tmp / 'ledger-index.json'
        os.link(ledger, ledger_hardlink)
        for out in (source, ledger, baseline, hardlink, ledger_hardlink,
                    self.features(project) / 'new-index.json'):
            before = {path: path.read_bytes() for path in (source, ledger, baseline)}
            result = run_wrapper('build_traceability_index.py', ['--project-root', project, '--out', out])
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn('OUTPUT_CONFLICT', output)
            self.assertNotIn('RESULT: PASS', output)
            self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_existing_legal_json_index_can_be_updated_relative_to_cwd(self):
        project = self.project()
        self.write(self.features(project) / 'F001-账号.md', account_doc(1))
        out = self.tmp / 'existing.json'
        self.write(out, '{"old":true}')
        result = run_wrapper('build_traceability_index.py',
                             ['--project-root', project, '--out', out.name], cwd=self.tmp)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['_meta']['total'], 1)

    def test_nonempty_main_without_acs_is_rejected_even_with_allow_empty(self):
        project = self.project()
        self.write(self.features(project) / 'F001-账号.md', account_doc(0))
        for script, arguments in (
                ('lint_divergence.py', ['--spec-dir', self.features(project), '--gate']),
                ('build_traceability_index.py', ['--project-root', project])):
            for extra in ([], ['--allow-empty']):
                result = run_wrapper(script, arguments + extra)
                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn('ZERO_ACCEPTANCE_CRITERIA', output)
                self.assertNotIn('RESULT: PASS', output)
        self.assertFalse((project / 'spec/.a2h/requirements-index.json').exists())

    def test_link_and_junction_detection_requires_no_windows_privileges(self):
        project = self.project()
        source = self.features(project) / 'F001-账号.md'
        self.write(source, account_doc(1))
        original = Path.is_symlink
        def linked(path):
            return path == source.absolute() or original(path)
        with patch.object(Path, 'is_symlink', linked):
            with self.assertRaisesRegex(spec_discovery.DiscoveryError, 'INPUT_LINK'):
                spec_discovery.discover(self.features(project))
        with patch.object(Path, 'is_junction', lambda path: path == self.features(project).absolute(), create=True):
            with self.assertRaisesRegex(spec_discovery.DiscoveryError, 'INPUT_LINK'):
                spec_discovery.discover(self.features(project))
        discovery = spec_discovery.discover(self.features(project))
        with patch.object(Path, 'is_symlink', linked), patch('shutil.copyfile') as copied:
            with self.assertRaisesRegex(spec_discovery.DiscoveryError, 'INPUT_LINK'):
                with spec_helpers.shadow_features(self.features(project), discovery, spec_helpers.TRACEABILITY):
                    pass
            copied.assert_not_called()

    def test_output_link_alias_is_rejected_before_resolve(self):
        project = self.project()
        self.write(self.features(project) / 'F001-账号.md', account_doc(1))
        discovery = spec_discovery.discover(self.features(project))
        out = self.tmp / 'linked-index.json'
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', lambda path: path == out.absolute() or original(path)):
            with self.assertRaisesRegex(spec_discovery.DiscoveryError, 'INPUT_LINK'):
                spec_helpers.validate_output_path(out, project, discovery)


if __name__ == '__main__':
    unittest.main()
