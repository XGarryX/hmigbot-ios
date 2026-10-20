"""Real original-writer recovery; optional exact old runtime tests an upgrade."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
from hmigbot_ios.core import digest, json_bytes, read_json, write_json


def prepare(root, managed_install=False):
    from test_ios_harness import fixture
    from spec_contract_fixture import strict_contract
    from test_plan_contract import PlanContractTests
    from hmigbot_ios.ios_scheduler import generate, step
    source, target, graph = fixture(root)
    strict_contract(target)
    index = target / 'spec/baseline/feature-index.md'
    index.write_text(index.read_text(encoding='utf-8').replace('| base | base |', '| base | 无 |'), encoding='utf-8')
    template = PlanContractTests()
    template.setUp()
    try:
        template.items[1]['ownership'] = ['entry/src/main/ets/pages/CounterPage.ets']
        template.write_plans()
        shutil.copytree(template.base / 'plans', target / 'spec/baseline/plans', dirs_exist_ok=True)
        request = copy.deepcopy(template.request)
        request['tasks'][1] = template.task('counter', template.items[1:3], parents=['base'], mapping_reason='UI and service share one owner')
    finally:
        template.tearDown()
    request['graph_sha256'] = digest(json_bytes(graph))
    for task in request['tasks']:
        task['fact_ids'] = [fact['id'] for fact in graph['facts']]
    path = root / 'request.json'
    write_json(path, request)
    from hmigbot_ios.native_authoring import prepare as authoring_prepare
    authoring_path = target / 'spec/ref/native-authoring-reviewed-input.json'
    authoring = authoring_prepare(target)['input_template']
    write_json(authoring_path, authoring)
    (root / 'authoring-before.json').write_bytes(authoring_path.read_bytes())
    if managed_install:
        subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/manage_install.py'), 'install', '--workspace', str(target)], check=True)
    generate(target, path)
    action, code = step(target, 'domains')
    assert code == 0 and action['batch'][0]['id'] == 'base', action
    partial = target / 'entry/Base.ets'
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_text('export const reviewedPartial: number = 1;\n', encoding='utf-8')
    receipt = {'ios_receipt_version': 2, 'task_id': 'base', 'domain': 'base',
               'source_sha256': graph['source_sha256'], 'plan_sha256': digest((target / 'spec/waves/plan-domains.json').read_bytes()),
               'status': 'blocked', 'final_state': 'BLOCKED', 'behavior_verified': False,
               'file_hashes': {'entry/Base.ets': digest(partial.read_bytes())}, 'files_touched': ['entry/Base.ets'], 'files': ['entry/Base.ets'], 'fixed': [], 'skipped': [], 'ac_ids': [],
               'findings': [{'id': 'SPEC.CONFLICT', 'message': 'Reviewed counter wording correction'}]}
    write_json(target / 'spec/waves/results/domains/base.json', receipt)
    page = target / 'spec/baseline/ui/page_0001_Counter.md'
    page.write_text(page.read_text(encoding='utf-8') + '\nReviewed state wording correction.\n', encoding='utf-8')
    authoring['inventory_sha256'] = authoring_prepare(target)['input_template']['inventory_sha256']
    write_json(authoring_path, authoring)
    request['replan_review'] = {'reviewer': 'independent-source-reviewer', 'reason': 'Reviewed wording correction, original source/AC preserved'}
    write_json(target / 'spec/ref/replan-request.json', request)
    from hmigbot_ios.native_pipeline import main
    assert main(['land-results', '--project', str(target)]) == 2
    assert main(['replan', '--project', str(target), '--input', str(target / 'spec/ref/replan-request.json')]) == 2
    print(json.dumps({'status': 'old_attempt_prepared', 'contract_revision': read_json(target / 'spec/blueprint/contracts.json')['contract_revision']}))


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = None if os.environ.get('HMIGBOT_RECOVERY_FIXTURE_PATH') else tempfile.TemporaryDirectory(prefix='reviewed-replan-')
        cls.root = Path(os.environ['HMIGBOT_RECOVERY_FIXTURE_PATH']) if cls.temp is None else Path(cls.temp.name)
        cls.root.mkdir(parents=True, exist_ok=True)
        old = Path(os.environ.get('HMIGBOT_RECOVERY_OLD_RUNTIME', ROOT))
        env = {**os.environ, 'HMIGBOT_TEST_RUNTIME': str(old), 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8'}
        proc = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--prepare', str(cls.root)], env=env, capture_output=True)
        print('OLD_PREPARE', proc.returncode, proc.stdout.decode('utf-8'), proc.stderr.decode('utf-8'))
        if proc.returncode:
            raise AssertionError('Old runtime fixture preparation failed')
        cls.project = cls.root / 'target'
        from hmigbot_ios.ios_scheduler import baseline_inputs
        from hmigbot_ios.plan_contract import contract_revision
        c = read_json(cls.project / 'spec/blueprint/contracts.json')
        binding = {name + '_sha256': digest((cls.project / path).read_bytes()) for name, path in [
            ('plan', 'spec/waves/plan-domains.json'), ('contract', 'spec/blueprint/contracts.json'),
            ('dispatch', 'spec/state/dispatch.json'), ('dispatch_evidence', 'spec/reports/ios-dispatch-domains.json'),
            ('receipt', 'spec/waves/results/domains/base.json')]}
        binding.update(source_sha256=c['source_sha256'], graph_sha256=c['graph_sha256'],
                       baseline_inputs_sha256=digest(json_bytes(c['input_hashes'])), contract_revision=c['contract_revision'])
        current = baseline_inputs(cls.project, 'domains')
        changes = [{'path': p, 'old_sha256': old_hash, 'new_sha256': current[p]} for p, old_hash in c['input_hashes'].items() if current.get(p) != old_hash]
        cls.review = {'version': 1, 'wave': 'domains', 'task_id': 'base', 'attempt': 1,
                      'reviewer': 'independent-source-reviewer', 'reason': 'Accepted precise Spec wording correction', 'workers_stopped': True,
                      'old': binding, 'new': {'contract_revision': contract_revision(cls.project), 'baseline_inputs_sha256': digest(json_bytes(current))},
                      'changes': changes, 'replan_request': {'path': 'spec/ref/replan-request.json', 'sha256': digest((cls.project / 'spec/ref/replan-request.json').read_bytes())}}
        cls.review['authoring_rebind'] = {'path': 'spec/ref/native-authoring-reviewed-input.json', 'previous_copy': str(cls.root / 'authoring-before.json'), 'old_sha256': digest((cls.root / 'authoring-before.json').read_bytes()), 'new_sha256': digest((cls.project / 'spec/ref/native-authoring-reviewed-input.json').read_bytes())}
        print('REVISION_BINDINGS', json.dumps(cls.review['old']), json.dumps(cls.review['new']))
        if 'HMIGBOT_RECOVERY_OLD_RUNTIME' in os.environ:
            assert binding['contract_revision'] != cls.review['new']['contract_revision'], 'upgrade must change actual revision'

    @classmethod
    def tearDownClass(cls):
        if cls.temp is not None: cls.temp.cleanup()

    def cli(self, *args):
        proc = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/a2h_ios.py'), *args], capture_output=True,
                              env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8'})
        print('CLI', json.dumps(args), 'RC', proc.returncode, proc.stdout.decode('utf-8'), proc.stderr.decode('utf-8'))
        return proc.returncode, json.loads(proc.stdout)

    def recover(self, value):
        path = self.root / 'review.json'; write_json(path, value)
        return self.cli('recover-blocked', '--project', str(self.project), '--review', str(path))

    def test_01_ordinary_deadlock_and_negative_bindings(self):
        self.assertEqual(self.cli('land-results', '--project', str(self.project))[0], 2)
        self.assertEqual(self.cli('replan', '--project', str(self.project), '--input', str(self.project / 'spec/ref/replan-request.json'))[0], 2)
        state = {p: (self.project / f'spec/state/{p}.json').read_bytes() for p in ('state', 'dispatch')}
        for mutate in [lambda r: r.update(workers_stopped=False), lambda r: r.update(attempt=2),
                       lambda r: r.update(task_id='counter'), lambda r: r.update(reviewer=''),
                       lambda r: r['old'].update(receipt_sha256='0' * 64),
                       lambda r: r['new'].update(contract_revision='0' * 64),
                       lambda r: r['changes'][0].update(path='../escape.md')]:
            value = copy.deepcopy(self.review); mutate(value)
            self.assertEqual(self.recover(value)[0], 2)
        for relative in ['spec/waves/prompts/domains/base.txt', 'spec/state/fence-snapshot/.manifest.json', 'entry/Unowned.ets']:
            path = self.project / relative; existed = path.exists(); original = path.read_bytes() if existed else b''
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(original + b'\ntamper\n')
            try: self.assertEqual(self.recover(self.review)[0], 2)
            finally:
                if existed: path.write_bytes(original)
                else: path.unlink()
        # Pin altered bytes in the review too: these must fail on semantic
        # protections, not merely on a stale outer receipt digest.
        receipt_path = self.project / 'spec/waves/results/domains/base.json'
        original_receipt = receipt_path.read_bytes()
        for mutate in [lambda r: r.update(status='generated', final_state='PASS', findings=[]),
                       lambda r: r.update(task_id='counter'),
                       lambda r: r['file_hashes'].update({'entry/Escape.ets': '0' * 64}),
                       lambda r: r['file_hashes'].update({'entry/Base.ets': '0' * 64})]:
            receipt = json.loads(original_receipt); mutate(receipt); write_json(receipt_path, receipt)
            value = copy.deepcopy(self.review); value['old']['receipt_sha256'] = digest(receipt_path.read_bytes())
            try: self.assertEqual(self.recover(value)[0], 2)
            finally: receipt_path.write_bytes(original_receipt)
        for relative in ['source/Counter.swift', 'target/spec/ref/native-authoring-reviewed-input.json']:
            path = self.root / relative; original = path.read_bytes()
            if relative.startswith('source'):
                path.write_bytes(original + b'\nstruct ChangedSource {}\n')
                value = self.review
            else:
                data = json.loads(original); data['documents'][0]['languages'] = ['objc']
                write_json(path, data)
                value = copy.deepcopy(self.review); value['authoring_rebind']['new_sha256'] = digest(path.read_bytes())
            try: self.assertEqual(self.recover(value)[0], 2)
            finally: path.write_bytes(original)
        for relative, field in [('spec/waves/plan-domains.json', 'plan_sha256'), ('spec/blueprint/contracts.json', 'contract_sha256')]:
            path = self.project / relative; original = path.read_bytes(); data = json.loads(original)
            data['unexpected_tamper'] = True; write_json(path, data)
            value = copy.deepcopy(self.review); value['old'][field] = digest(path.read_bytes())
            try: self.assertEqual(self.recover(value)[0], 2)
            finally: path.write_bytes(original)
        authoring = self.project / 'spec/ref/native-authoring-reviewed-input.json'
        original = authoring.read_bytes(); data = json.loads(original); data['inventory_sha256'] = '0' * 64; write_json(authoring, data)
        value = copy.deepcopy(self.review); value['authoring_rebind']['new_sha256'] = digest(authoring.read_bytes())
        try: self.assertEqual(self.recover(value)[0], 2)
        finally: authoring.write_bytes(original)
        for p, data in state.items(): self.assertEqual((self.project / f'spec/state/{p}.json').read_bytes(), data)

    def test_02_original_writer_then_replan_and_new_dispatch(self):
        code, result = self.recover(self.review)
        self.assertEqual(code, 0, result)
        self.assertEqual(result['status'], 'blocked_attempt_terminated')
        self.assertFalse(result['prior_success_inherited'])
        self.assertEqual(self.recover(self.review), (0, result))
        code, result = self.cli('replan', '--project', str(self.project), '--input', str(self.project / 'spec/ref/replan-request.json'))
        self.assertEqual(code, 0, result)
        self.assertFalse(result['prior_success_inherited'])
        code, result = self.cli('next-batch', '--project', str(self.project))
        self.assertEqual(code, 0, result)
        self.assertEqual([row['id'] for row in result['batch']], ['base'])


class CacheResultTests(unittest.TestCase):
    """Portable cache-only metadata tests; no source gate or kernel rerun."""
    def setUp(self):
        from hmigbot_ios.replan_recovery import _seal_archive
        self.temp = tempfile.TemporaryDirectory(prefix='blocked-cache-')
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        objects = {'plan.json': {}, 'contract.json': {}, 'dispatch.json': {}, 'dispatch-evidence.json': {},
                   'receipt.json': {'task_id': 'base', 'plan_sha256': digest(json_bytes({})), 'source_sha256': 'a' * 64,
                                    'status': 'blocked', 'final_state': 'BLOCKED', 'behavior_verified': False},
                   'replan-request.json': {}, 'state-before.json': {}, 'control-presence.json': {'journal_before_present': False},
                   'inputs.json': {'old': {}, 'new': {}},
                   'state-after.json': {'waves': {'domains': {'tasks': [{'id': 'base', 'status': 'failed'}]}}},
                   'dispatch-after.json': {}, 'journal-after.json': {'operation_outputs': [
                       {'workflow_id': 'domains', 'task_id': 'base', 'attempt': 1, 'status': 'RETRY_NEEDED'}]}}
        old = {field: digest(json_bytes(objects[name])) for name, field in [
            ('plan.json','plan_sha256'), ('contract.json','contract_sha256'), ('dispatch.json','dispatch_sha256'),
            ('dispatch-evidence.json','dispatch_evidence_sha256'), ('receipt.json','receipt_sha256')]}
        old.update(source_sha256='a' * 64, graph_sha256='b' * 64, baseline_inputs_sha256=digest(json_bytes({})), contract_revision='c' * 64)
        self.review = {'version': 1, 'wave': 'domains', 'task_id': 'base', 'attempt': 1, 'reviewer': 'cache-unit',
                       'reason': 'Cache-only fixture; does not claim original kernel execution', 'workers_stopped': True,
                       'old': old, 'new': {'contract_revision': 'd' * 64, 'baseline_inputs_sha256': digest(json_bytes({}))},
                       'changes': [{'path': 'spec/baseline/ui/example.md', 'old_sha256': 'e' * 64, 'new_sha256': 'f' * 64}],
                       'replan_request': {'path': 'spec/ref/request.json', 'sha256': digest(json_bytes({}))}}
        self.key = digest(json_bytes(self.review))
        self.archive = self.project / 'spec/reports/ios-blocked-recovery' / self.key
        self.action = {'ok': False, 'wave': 'domains', 'landed': [{'id': 'base', 'attempt': 1, 'status': 'RETRY_NEEDED'}],
                       'ios_blocked_receipts': [{'id': 'base', 'archive': 'spec/reports/ios-blocked-receipts/domains/base/' + old['receipt_sha256'] + '.json',
                           'sha256': old['receipt_sha256'], 'native_status': 'blocked', 'original_disposition': 'missing-as-failed'}]}
        self.result = {'status': 'blocked_attempt_terminated', 'task_id': 'base', 'attempt': 1,
                       'archive': self.archive.relative_to(self.project).as_posix(), 'review_sha256': self.key,
                       'state_writer': 'original land_results --missing-as-failed', 'action': self.action,
                       'prior_success_inherited': False, 'behavior_verified': False}
        for name, value in {**objects, 'review.json': self.review, 'result.json': self.result}.items():
            write_json(self.archive / name, value)
        _seal_archive(self.archive, self.review)

    def cached(self):
        from hmigbot_ios.replan_recovery import _cached_result
        return _cached_result(self.project, self.archive, self.review, self.key)

    def rewrite_bound(self, name, value):
        write_json(self.archive / name, value)
        seal = read_json(self.archive / 'seal.json')
        seal['files'][name] = digest((self.archive / name).read_bytes())
        write_json(self.archive / 'seal.json', seal)

    def test_cache_legal_repeat_is_readonly_independent_of_current_run(self):
        before = {p.name: p.read_bytes() for p in self.archive.iterdir()}
        self.assertEqual(self.cached(), self.result)
        write_json(self.project / 'spec/state/state.json', {'run': 'new replan state, not cache authority'})
        self.assertEqual(self.cached(), self.result)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.archive.iterdir()})

    def test_cache_rr01_result_changed_without_seal_is_rejected(self):
        from hmigbot_ios.core import MigrationError
        bad = copy.deepcopy(self.result); bad.update(status='generated', behavior_verified=True, prior_success_inherited=True)
        write_json(self.archive / 'result.json', bad)
        with self.assertRaisesRegex(MigrationError, 'cache evidence digest'): self.cached()

    def test_cache_rr01_even_resealed_success_identity_types_are_rejected(self):
        from hmigbot_ios.core import MigrationError
        for mutate in [lambda r: r.update(status='generated', behavior_verified=True, prior_success_inherited=True),
                       lambda r: r.update(task_id='other'), lambda r: r.update(attempt=True),
                       lambda r: r.update(behavior_verified=0), lambda r: r['action'].update(ok=True),
                       lambda r: r['action']['landed'][0].update(status='OK'),
                       lambda r: r['action'].update(workflow_status='SUCCESS')]:
            bad = copy.deepcopy(self.result); mutate(bad); self.rewrite_bound('result.json', bad)
            with self.assertRaises(MigrationError): self.cached()
        self.rewrite_bound('result.json', self.result)
        self.rewrite_bound('state-after.json', {'waves': {'domains': {'tasks': [{'id': 'base', 'status': 'done'}]}}})
        with self.assertRaisesRegex(MigrationError, 'failed state'): self.cached()

    def test_cache_missing_seal_or_first_evidence_is_rejected(self):
        from hmigbot_ios.core import MigrationError
        seal = (self.archive / 'seal.json').read_bytes(); (self.archive / 'seal.json').unlink()
        with self.assertRaises(MigrationError): self.cached()
        (self.archive / 'seal.json').write_bytes(seal)
        (self.archive / 'receipt.json').unlink()
        with self.assertRaises(MigrationError): self.cached()


class ManagedUpgradeBindingTests(unittest.TestCase):
    """Portable proof-byte checks; real manager integration is separate evidence."""
    def test_managed_exact_paths_and_manifest_public_package_bytes(self):
        import base64
        from hmigbot_ios.replan_recovery import _managed_binding
        from hmigbot_ios.core import MigrationError
        path = '.agents/skills/ios-source-analysis/SKILL.md'
        old, new = b'# original public skill\n', b'# reviewed public skill\n'
        proof = {'install_manifest_sha256': 'a' * 64, 'old_runtime_revision': 'b' * 64,
                 'current_runtime_revision': 'c' * 64, 'files': [
                     {'path': path, 'old_sha256': digest(old), 'new_sha256': digest(new), 'old_copy': '/saved/original.md'}]}
        review = {'old': {'contract_revision': 'b' * 64}, 'new': {'contract_revision': 'c' * 64}, 'managed_upgrade': proof}
        manifest = {'owner': 'hmigbot-ios', 'schema_version': 1, 'files': {
            path: digest(new), '.hmigbot-ios/plugin/skills/ios-source-analysis/SKILL.md': digest(new)}}
        record = {'proof': proof, 'files': [{'path': path, 'old_base64': base64.b64encode(old).decode(),
                  'public_base64': base64.b64encode(new).decode(), 'package_base64': base64.b64encode(new).decode()}]}
        self.assertEqual(_managed_binding(review, manifest, record), {path})
        for field in ['old_base64', 'public_base64', 'package_base64']:
            bad = copy.deepcopy(record); bad['files'][0][field] = base64.b64encode(b'tampered').decode()
            with self.assertRaises(MigrationError): _managed_binding(review, manifest, bad)
        bad = copy.deepcopy(manifest); bad['files'][path] = '0' * 64
        with self.assertRaises(MigrationError): _managed_binding(review, bad, record)
        for path in ['.agents/skills/other/SKILL.md', '.migbot/config.json', 'entry/Counter.ets']:
            bad = copy.deepcopy(review); bad['managed_upgrade']['files'][0]['path'] = path
            saved = copy.deepcopy(record); saved['proof'] = bad['managed_upgrade']; saved['files'][0]['path'] = path
            with self.assertRaises(MigrationError): _managed_binding(bad, manifest, saved)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in {'--prepare', '--prepare-managed'}:
        prepare(Path(sys.argv[2]), managed_install=sys.argv[1] == '--prepare-managed')
    else:
        unittest.main()
