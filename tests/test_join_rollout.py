"""Modern scoped tool observations must never become an empty successful join."""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
WRAPPER = ROOT / 'skills/a2h-join/scripts/join_gate.py'


class JoinRolloutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='join-rollout-test-')
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.rollout = self.project / 'actual-schema.jsonl'
        self.rows = [{'type': 'session_meta', 'payload': {'id': 'synthetic-session',
            'cwd': str(self.project), 'agent_path': '/root/parent',
            'source': {'subagent': {'thread_spawn': {'agent_path': '/root/parent', 'depth': 1}}}}}]
        self.counter = 0
        self.started = datetime.now(timezone.utc)
        self.expected(['worker'])
        (self.project / 'artifact.txt').write_text('complete unit-test artifact', encoding='utf-8')

    def expected(self, names):
        path = self.project / 'spec/a2h/_work/expected_probe.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'join_point': 'probe', 'task_names': names,
            'artifacts': [{'path': 'artifact.txt', 'min_count': 1, 'min_bytes': 10}]}), encoding='utf-8')

    def tool(self, name, arguments, output):
        self.counter += 1
        call = f'unit-call-{self.counter}'
        self.rows += [
            {'type': 'response_item', 'payload': {'type': 'function_call', 'name': name,
                'call_id': call, 'arguments': json.dumps(arguments)}},
            {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': call,
                'output': json.dumps(output) if not isinstance(output, str) else output}}]
        return call

    def spawn(self, name='worker', parent='/root/parent'):
        return self.tool('spawn_agent', {'task_name': name, 'agent_type': 'worker',
            'message': 'PRIVATE_UNIT_TEST_MESSAGE_DO_NOT_PRINT'}, {'task_name': parent + '/' + name})

    def observe(self, values):
        return self.tool('list_agents', {}, {'agents': [
            {'agent_name': name, 'agent_status': status} for name, status in values.items()]})

    def run_gate(self, no_ledger=True):
        for index, row in enumerate(self.rows):
            row.setdefault('timestamp', (self.started + timedelta(milliseconds=index)).isoformat())
        raw = b''.join((json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8') for row in self.rows)
        self.rollout.write_bytes(raw)
        args = [sys.executable, str(WRAPPER), '--project', str(self.project),
                '--join-point', 'probe', '--rollout', str(self.rollout)]
        if no_ledger:
            args.append('--no-ledger')
        result = subprocess.run(args, capture_output=True, env={**os.environ, 'PYTHONUTF8': '1'}, timeout=30)
        self.assertNotIn(b'PRIVATE_UNIT_TEST_MESSAGE_DO_NOT_PRINT', result.stdout + result.stderr)
        return result, hashlib.sha256(raw).hexdigest()

    def manifest(self, source_sha):
        path = self.project / f'spec/reports/derived/a2h-join/probe/{source_sha}.json'
        self.assertTrue(path.is_file(), 'A verified adapter must publish auditable derivation evidence')
        return json.loads(path.read_text(encoding='utf-8'))

    def test_deep_completed_handles_use_original_artifact_validation_and_source_provenance(self):
        spawn = self.spawn()
        observation = self.observe({'/root/parent/worker': {'completed': 'synthetic observed completion'}})
        result, sha = self.run_gate(no_ledger=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = self.manifest(sha)
        self.assertEqual(manifest['source_sha256'], sha)
        self.assertEqual(manifest['source_bytes'], len(self.rollout.read_bytes()))
        self.assertEqual(manifest['writer']['agent_path'], '/root/parent')
        self.assertEqual(manifest['handles'][0]['source_name'], '/root/parent/worker')
        self.assertEqual(manifest['handles'][0]['projected_name'], '/root/worker')
        self.assertEqual(manifest['handles'][0]['spawn_call_id'], spawn)
        self.assertEqual(manifest['handles'][0]['observation_call_id'], observation)
        self.assertEqual(manifest['original_gate']['exit_code'], 0)
        self.assertEqual(manifest['original_gate']['recognized_handles'], 1)
        self.assertTrue((self.project / 'spec/a2h/_work/join-ledger.jsonl').is_file())
        projection = Path(manifest['projection_path']).read_bytes()
        self.assertEqual(hashlib.sha256(projection).hexdigest(), manifest['projection_sha256'])
        projected = [json.loads(line) for line in projection.splitlines()]
        self.assertEqual(projected[0]['type'], 'hmigbot_join_projection')
        self.assertEqual({row['payload']['call_id'] for row in projected[1:]}, {spawn, observation})
        raw_lines = self.rollout.read_bytes().splitlines()
        for row, raw_line, record in zip(projected[1:], projection.splitlines()[1:], manifest['records']):
            self.assertEqual(hashlib.sha256(raw_line).hexdigest(), record['projected_record_sha256'])
            self.assertEqual(hashlib.sha256(raw_lines[record['source_line'] - 1]).hexdigest(), record['source_line_sha256'])
            self.assertEqual(row['hmigbot_join_source']['line'], record['source_line'])
        observed_output = json.loads(projected[-1]['payload']['output'])
        self.assertEqual(observed_output['agents'][0]['agent_status'], {'completed': 'synthetic observed completion'})
        (self.project / 'artifact.txt').unlink()
        rejected, sha = self.run_gate()
        self.assertEqual(rejected.returncode, 1, rejected.stdout + rejected.stderr)
        self.assertNotEqual(self.manifest(sha)['original_gate']['exit_code'], 0)

    def test_missing_unknown_and_noncompleted_observations_never_pass_empty_handles(self):
        self.spawn()
        result, _ = self.run_gate()
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        for status in ('running', 'unknown', 'failed', 'dead', {'failed': 'synthetic failure'}):
            with self.subTest(status=status):
                self.observe({'/root/parent/worker': status})
                result, _ = self.run_gate()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_live_list_absence_keeps_completion_but_actual_followup_and_running_reopen_it(self):
        self.spawn()
        self.observe({'/root/parent/worker': {'completed': 'first observed completion'}})
        self.observe({})  # The live API may release a completed agent slot.
        self.assertEqual(self.run_gate()[0].returncode, 0)
        self.tool('followup_task', {'target': 'worker', 'message': 'private synthetic followup'}, '')
        self.assertNotEqual(self.run_gate()[0].returncode, 0)
        self.observe({'/root/parent/worker': {'completed': 'second observed completion'}})
        self.assertEqual(self.run_gate()[0].returncode, 0)
        self.observe({'/root/parent/worker': 'running'})
        self.assertNotEqual(self.run_gate()[0].returncode, 0)

    def test_only_expected_direct_children_are_projected_and_siblings_are_not_claimed_joined(self):
        self.spawn('sibling')
        self.spawn('worker')
        self.observe({'/root/parent/sibling': 'running',
                      '/root/parent/worker': {'completed': 'observed completion'}})
        result, sha = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = self.manifest(sha)
        self.assertEqual([row['task_name'] for row in manifest['handles']], ['worker'])
        self.assertNotIn(b'sibling', result.stdout + result.stderr)

    def test_expected_names_without_real_spawn_and_wrong_writer_are_rejected(self):
        self.expected(['worker', 'missing'])
        self.spawn()
        self.observe({'/root/parent/worker': {'completed': 'observed completion'}})
        self.assertEqual(self.run_gate()[0].returncode, 3)
        self.expected(['worker'])
        self.rows = self.rows[:1]
        self.spawn(parent='/root/unrelated')
        self.observe({'/root/unrelated/worker': {'completed': 'unrelated observation'}})
        self.assertEqual(self.run_gate()[0].returncode, 3)

    def test_agent_message_final_answer_prose_is_not_a_completion_oracle(self):
        self.spawn()
        self.rows.append({'type': 'response_item', 'payload': {'type': 'agent_message',
            'author': '/root/parent/worker', 'recipient': '/root/parent',
            'content': [{'type': 'text', 'text': 'FINAL_ANSWER completed all work'}],
            'internal_chat_message_metadata_passthrough': {'turn_id': 'unit-turn', 'create_time': 1}}})
        self.assertEqual(self.run_gate()[0].returncode, 3)

    def test_pending_followup_reopens_completion_before_its_tool_output_exists(self):
        self.spawn()
        self.observe({'/root/parent/worker': {'completed': 'observed completion'}})
        self.rows.append({'type': 'response_item', 'payload': {'type': 'function_call',
            'name': 'followup_task', 'call_id': 'pending-followup',
            'arguments': json.dumps({'target': 'worker', 'message': 'private synthetic followup'})}})
        result, sha = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.manifest(sha)['original_gate']['invoked'])

    def test_duplicate_calls_and_ambiguous_completed_status_are_rejected(self):
        self.spawn()
        self.observe({'/root/parent/worker': {'completed': 'done', 'running': 'reopened'}})
        self.assertEqual(self.run_gate()[0].returncode, 3)
        self.rows.append(self.rows[1].copy())
        self.assertEqual(self.run_gate()[0].returncode, 3)

    def test_projection_cannot_be_reused_as_an_original_rollout(self):
        self.spawn()
        self.observe({'/root/parent/worker': {'completed': 'observed completion'}})
        result, sha = self.run_gate()
        self.assertEqual(result.returncode, 0)
        projected = Path(self.manifest(sha)['projection_path'])
        result = subprocess.run([sys.executable, str(WRAPPER), '--project', str(self.project),
            '--join-point', 'probe', '--rollout', str(projected), '--no-ledger'], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 3)

    def test_inherited_session_metadata_cannot_replace_the_actual_writer(self):
        self.rows.append({'type': 'session_meta', 'payload': {'id': 'copied-ancestor', 'agent_path': '/root'}})
        self.spawn()
        self.observe({'/root/parent/worker': {'completed': 'observed completion'}})
        result, sha = self.run_gate()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.manifest(sha)['writer']['agent_path'], '/root/parent')
        del self.rows[0]['payload']['agent_path']
        del self.rows[0]['payload']['source']['subagent']['thread_spawn']['agent_path']
        self.assertEqual(self.run_gate()[0].returncode, 3)

    def test_explicit_rollout_is_required_without_scanning_other_sessions(self):
        result = subprocess.run([sys.executable, str(WRAPPER), '--project', str(self.project),
            '--join-point', 'probe', '--no-ledger'], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 3)

    def test_even_original_exit_zero_with_no_recognized_handles_is_not_success(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from types import SimpleNamespace
        from unittest.mock import patch
        sys.path.insert(0, str(ROOT / 'src'))
        from hmigbot_ios.join_rollout import main
        self.spawn()
        self.observe({'/root/parent/worker': {'completed': 'observed completion'}})
        self.run_gate()

        def invoke(argv, **kwargs):
            if argv[0] == 'git':
                return SimpleNamespace(returncode=0, stdout=b'unit-commit\n' if 'rev-parse' in argv else b'', stderr=b'')
            return SimpleNamespace(returncode=0, stdout='句柄=0'.encode(), stderr=b'')

        with patch('hmigbot_ios.join_rollout.subprocess.run', side_effect=invoke), redirect_stdout(StringIO()):
            code = main(['--project', str(self.project), '--join-point', 'probe',
                '--rollout', str(self.rollout), '--no-ledger'], root=ROOT)
        self.assertEqual(code, 3)


if __name__ == '__main__':
    unittest.main()
