"""Reservations test supplied upper bounds, not predicted/model token usage."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios import usage_budget as budget


class UsageReservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root / 'usage.json'
        for name, value in [('_clock', (1000.0, 500.0)), ('_boot_id', 'reservation-test-boot')]:
            p = patch.object(budget, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        budget.start(self.ledger, 'run', project_root=self.root, token_limit=1000)

    def reserve(self, call='call', tokens=600, **changed):
        options = dict(run_id='run', project_root=self.root, stage='execute',
                       agent='worker', provider='synthetic', attempt=1)
        options.update(changed)
        return budget.reserve(self.ledger, call, tokens, **options)

    def record(self, call='call', tokens=250, **changed):
        options = dict(run_id='run', normalization_mode='openai_responses',
                       stage='execute', agent='worker', provider='synthetic', attempt=1)
        options.update(changed)
        raw = None if tokens is None else {'input_tokens': tokens, 'output_tokens': 0}
        return budget.record(self.ledger, call, raw, **options)

    def data(self):
        return json.loads(self.ledger.read_text(encoding='utf-8'))

    def test_inflight_is_counted_and_overlapping_dispatch_is_refused(self):
        report = self.reserve()
        self.assertEqual((report['reserved_tokens'], report['available_tokens']), (600, 400))
        before = self.data()
        with self.assertRaises(budget.BudgetError):
            self.reserve('parallel', 401)
        self.assertEqual(before['reservations'], self.data()['reservations'])
        self.assertEqual(before['calls'], self.data()['calls'])
        report = self.reserve('parallel', 400)
        self.assertEqual(report['active_reservation_count'], 2)
        self.assertFalse(budget.check_for_dispatch(self.ledger, run_id='run',
                         project_root=self.root)['can_continue'])

    def test_reserve_upgrades_schema_so_old_readers_cannot_ignore_inflight(self):
        self.assertEqual(self.data()['schema_version'], 1)
        self.reserve()
        self.assertEqual(self.data()['schema_version'], 2)
        data = self.data()
        data['schema_version'] = 1
        self.ledger.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(budget.BudgetError):
            budget.summary(self.ledger)

    def test_duplicate_is_idempotent_and_identity_or_bound_conflicts_refused(self):
        self.assertTrue(self.reserve()['reservation_created'])
        report = self.reserve()
        self.assertEqual((report['reservation_created'], report['reservation_status'],
                          report['reservation_call_id']), (False, 'active', 'call'))
        self.assertEqual(len(self.data()['reservations']), 1)
        for changed in [{'tokens': 601}, {'agent': 'other'}, {'attempt': 2},
                        {'run_id': 'other'}, {'project_root': self.root.parent}]:
            with self.subTest(changed=changed), self.assertRaises(budget.BudgetError):
                self.reserve(**changed)

    def test_released_reservation_cannot_be_reserved_again(self):
        self.reserve()
        budget.release(self.ledger, 'call', run_id='run', reason='not called')
        with self.assertRaises(budget.BudgetError):
            self.reserve()

    def test_settled_reservation_cannot_be_reserved_again(self):
        self.reserve()
        self.record()
        with self.assertRaises(budget.BudgetError):
            self.reserve()

    def test_unknown_reservation_cannot_be_reserved_again(self):
        self.reserve()
        self.record(tokens=None, normalization_mode='unreported')
        with self.assertRaises(budget.BudgetError):
            self.reserve()

    def test_active_replay_does_not_grant_expired_or_unverified_work(self):
        self.reserve()
        with patch.object(budget, '_clock', return_value=(8201.0, 7701.0)):
            with self.assertRaises(budget.BudgetError):
                self.reserve()
        self.assertFalse(self.data()['finished'])

    def test_rejected_reserve_persists_clock_reversal_after_clock_recovers(self):
        self.reserve()
        before = self.data()
        with patch.object(budget, '_clock', return_value=(999.0, 501.0)):
            with self.assertRaises(budget.BudgetError):
                self.reserve('another', 1)
        self.assertEqual(self.data()['reservations'], before['reservations'])
        self.assertEqual(self.data()['calls'], before['calls'])
        with patch.object(budget, '_clock', return_value=(1001.0, 502.0)):
            report = budget.summary(self.ledger)
        self.assertIn('wall_clock_reversed', report['clock_anomalies'])
        self.assertFalse(report['can_continue'])

    def test_actual_usage_settles_without_double_counting(self):
        self.reserve()
        report = self.record()
        self.assertEqual((report['total_tokens'], report['reserved_tokens'],
                          report['active_reservation_count']), (250, 0, 0))
        self.assertEqual(self.data()['reservations'][0]['state'], 'settled')
        self.record()
        self.assertEqual(budget.finish(self.ledger, run_id='run')['status'], 'PASS')

    def test_actual_over_bound_is_retained_and_reported(self):
        self.reserve(tokens=100)
        report = self.record(tokens=1100)
        self.assertEqual(report['total_tokens'], 1100)
        self.assertEqual(report['reservation_overrun_count'], 1)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(self.data()['calls'][0]['raw_usage']['input_tokens'], 1100)

    def test_unknown_usage_keeps_unspent_bound_and_cannot_release_or_finish(self):
        self.reserve()
        report = self.record(tokens=None, normalization_mode='unreported')
        self.assertEqual(report['reserved_tokens'], 600)
        self.assertFalse(report['can_continue'])
        for action in [lambda: budget.release(self.ledger, 'call', run_id='run', reason='cancel'),
                       lambda: budget.finish(self.ledger, run_id='run')]:
            with self.assertRaises(budget.BudgetError):
                action()
        self.assertFalse(self.data()['finished'])

    def test_active_prevents_finishing_until_settled_or_audited_release(self):
        self.reserve()
        with self.assertRaises(budget.BudgetError):
            budget.finish(self.ledger, run_id='run')
        report = budget.release(self.ledger, 'call', run_id='run', reason='cancelled before provider invocation')
        self.assertEqual(report['reserved_tokens'], 0)
        self.assertEqual(self.data()['reservations'][0]['release_reason'], 'cancelled before provider invocation')
        self.assertEqual(budget.finish(self.ledger, run_id='run')['status'], 'PASS')

    def test_release_does_not_erase_late_actual_usage(self):
        self.reserve()
        budget.release(self.ledger, 'call', run_id='run', reason='thought not invoked')
        report = self.record(tokens=250)
        self.assertEqual(report['total_tokens'], 250)
        self.assertIn('released_reservation_was_used', report['reasons'])
        self.assertEqual(report['status'], 'FAIL')

    def test_release_idempotence_and_identity_guards(self):
        self.reserve()
        for run, reason in [('other', 'cancel'), ('run', '')]:
            with self.assertRaises(budget.BudgetError):
                budget.release(self.ledger, 'call', run_id=run, reason=reason)
        budget.release(self.ledger, 'call', run_id='run', reason='not called')
        budget.release(self.ledger, 'call', run_id='run', reason='not called')
        with self.assertRaises(budget.BudgetError):
            budget.release(self.ledger, 'call', run_id='run', reason='different reason')

    def test_record_identity_must_match_reservation(self):
        self.reserve()
        with self.assertRaises(budget.BudgetError):
            self.record(agent='other')
        self.assertEqual(self.data()['calls'], [])

    def test_atomic_competing_reservations_never_overbook(self):
        def attempt(number):
            try:
                self.reserve(str(number), 600)
                return True
            except budget.BudgetError:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(budget.summary(self.ledger)['reserved_tokens'], 600)

    def test_legacy_schema_without_reservations_still_replays(self):
        data = self.data()
        data.pop('reservations', None)
        self.ledger.write_text(json.dumps(data), encoding='utf-8')
        self.assertEqual(budget.summary(self.ledger)['reserved_tokens'], 0)
        self.assertEqual(self.record()['total_tokens'], 250)

    def test_partial_usage_only_holds_the_unspent_bound_but_stays_unknown(self):
        self.reserve()
        report = budget.record(self.ledger, 'call', {'input_tokens': 100}, run_id='run',
                               normalization_mode='openai_responses', stage='execute',
                               agent='worker', provider='synthetic')
        self.assertEqual((report['total_tokens'], report['reserved_tokens']), (100, 500))
        self.assertFalse(report['can_continue'])

    def test_invalid_bounds_and_retrospective_reservations_are_refused(self):
        for bound in [0, -1, True, 1.5]:
            with self.subTest(bound=bound), self.assertRaises(budget.BudgetError):
                self.reserve(tokens=bound)
        self.record()
        with self.assertRaises(budget.BudgetError):
            self.reserve()

    def test_process_reservations_share_atomic_capacity(self):
        ledger = self.root / 'process-reservations.json'
        with patch.object(budget, '_clock', side_effect=lambda: (time.time(), time.monotonic())):
            budget.start(ledger, 'run', project_root=self.root, token_limit=1000)
        code = ("from hmigbot_ios import usage_budget as b; import sys; "
                "b._boot_id=lambda:'reservation-test-boot'; "
                "b.reserve(sys.argv[1],sys.argv[2],600,run_id='run',project_root=sys.argv[3],"
                "stage='execute',agent='worker',provider='synthetic')")
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1')
        processes = [subprocess.Popen([sys.executable, '-c', code, str(ledger), str(i), str(self.root)],
                                     env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for i in range(4)]
        outcomes = [p.communicate(timeout=30) or None for p in processes]
        self.assertEqual(sum(p.returncode == 0 for p in processes), 1, outcomes)
        data = json.loads(ledger.read_text(encoding='utf-8'))
        self.assertEqual(len(data['reservations']), 1)
        self.assertEqual(data['reservations'][0]['token_upper_bound'], 600)

    def test_tampered_reservation_state_is_rejected(self):
        self.reserve()
        data = self.data()
        data['reservations'][0]['state'] = 'settled'
        self.ledger.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(budget.BudgetError):
            budget.summary(self.ledger)


if __name__ == '__main__':
    unittest.main()
