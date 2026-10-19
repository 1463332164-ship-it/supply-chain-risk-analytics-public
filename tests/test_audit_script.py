"""Actual subprocess experiments plus small boundary checks; no personal reviews."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from scripts import audit_scenarios as audit
from scripts import verify
from unittest.mock import patch
from scai.data import generate, fingerprint, write_csv, SCHEMAS
import csv

ROOT = Path(__file__).resolve().parents[1]


class AuditScriptTests(unittest.TestCase):
    def setUp(self):
        # Own setup creates its parent; no dependency on another test's ordering.
        (ROOT / 'runs').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'runs', prefix='test-script-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def invoke(self, *args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return audit.main(list(args))

    def test_none_and_zero_metric_deltas(self):
        for value, base in ((None, 1), (1, None), (None, None)):
            self.assertEqual(audit.metric_delta(value, base), {'absolute': None, 'percent': None})
        self.assertEqual(audit.metric_delta(4, 0), {'absolute': 4, 'percent': None})
        self.assertEqual(audit.metric_delta(0, 4), {'absolute': -4, 'percent': -100})
        self.assertEqual(audit.metric_delta(5, 4), {'absolute': 1, 'percent': 25})

    def test_existing_output_refused_without_changes(self):
        sentinel = self.root / 'sentinel'
        sentinel.write_bytes(b'EXISTING')
        with self.assertRaises(SystemExit) as exc: self.invoke('--out', str(self.root))
        self.assertEqual(exc.exception.code, 2)
        self.assertEqual(sentinel.read_bytes(), b'EXISTING')
        self.assertEqual(list(self.root.iterdir()), [sentinel])

    def test_verification_entrypoint_refuses_existing_output_before_running(self):
        with patch.object(verify, 'command') as command:
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                verify.main(['--out', str(self.root)])
            self.assertEqual(exc.exception.code, 2)
            command.assert_not_called()

    def test_verification_failed_tests_stop_and_preserve_historical_record(self):
        before = (ROOT / 'examples/verification.json').read_bytes()
        out = self.root / 'verification-failure'
        with patch.object(verify, 'command', return_value={'returncode': 1, 'stderr': 'injected failure'}) as command:
            self.assertEqual(verify.main(['--out', str(out)]), 1)
            self.assertEqual(command.call_count, 1)
        self.assertFalse(audit.read(out / 'verification.json')['all_commands_passed'])
        self.assertEqual((ROOT / 'examples/verification.json').read_bytes(), before)

    def test_input_output_overlap_and_outside_runs_are_refused(self):
        for out, data in [(self.root / 'data/new', self.root / 'data'),
                          (self.root / 'future', self.root / 'future/data'),
                          (self.root / 'same', self.root / 'same'),
                          (ROOT / 'new-outside-runs', ROOT / 'data/demo')]:
            with self.subTest(out=out), self.assertRaises(SystemExit) as exc:
                self.invoke('--out', str(out), '--data', str(data))
            self.assertEqual(exc.exception.code, 2)
            self.assertFalse(out.exists())

    def test_response_inside_output_is_refused(self):
        out = self.root / 'new'
        with self.assertRaises(SystemExit):
            self.invoke('--out', str(out), '--response', str(out / 'response.json'))
        self.assertFalse(out.exists())

    def test_invalid_input_has_failure_record_not_success_summary(self):
        out = self.root / 'failed'
        code = self.invoke('--out', str(out), '--data', str(self.root / 'missing-data'))
        self.assertEqual(code, 2)
        self.assertEqual(audit.read(out / 'failure.json')['status'], 'failed')
        self.assertFalse((out / 'experiment_summary.json').exists())
        self.assertFalse((out / 'scenario_metrics.csv').exists())
        self.assertNotEqual(audit.read(out / 'commands.json')[0]['returncode'], 0)

    def make_alternate_data(self):
        data = self.root / 'data'
        generate(data, seed=9)
        return data

    def test_alternate_input_runs_without_implicit_fixed_ai_response(self):
        data = self.make_alternate_data()
        before = fingerprint(data)
        out = self.root / 'experiment'
        self.assertEqual(self.invoke('--out', str(out), '--data', str(data)), 0)
        result = audit.read(out / 'experiment_summary.json')
        self.assertTrue(result['repeat_results_identical'])
        self.assertEqual(result['ai_validation']['status'], 'not_requested')
        self.assertEqual(fingerprint(data), before)
        self.assertEqual(len(result['scenarios']), 4)
        self.assertEqual(len(audit.read(out / 'commands.json')), 5)

    def test_wrong_optional_ai_response_preserves_completed_analysis(self):
        data = self.make_alternate_data()
        out = self.root / 'wrong-response'
        self.assertEqual(self.invoke('--out', str(out), '--data', str(data),
                                    '--response', str(ROOT / 'examples/ai_response_codex.json')), 2)
        result = audit.read(out / 'experiment_summary.json')
        self.assertEqual(result['analysis_status'], 'passed')
        self.assertEqual(result['ai_validation']['status'], 'failed')
        self.assertTrue(result['repeat_results_identical'])
        self.assertTrue((out / 'scenario_metrics.csv').is_file())
        self.assertFalse((out / 'base_ai').exists())
        self.assertIn('different packet', audit.read(out / 'commands.json')[-1]['stderr'])

    def test_no_due_orders_yields_null_otd_and_null_deltas(self):
        data = self.make_alternate_data()
        # Move every promise beyond the snapshot, maintaining valid date contracts.
        with (data / 'orders.csv').open(encoding='utf-8-sig', newline='') as stream:
            orders = list(csv.DictReader(stream))
        for order in orders:
            order['promised_date'] = '2026-10-18'
        write_csv(data / 'orders.csv', orders, SCHEMAS['orders'])
        before = fingerprint(data)
        out = self.root / 'no-due'
        self.assertEqual(self.invoke('--out', str(out), '--data', str(data)), 0)
        summary = audit.read(out / 'experiment_summary.json')
        for scenario in summary['scenarios']:
            self.assertIsNone(summary['scenarios'][scenario]['otd'])
            self.assertEqual(summary['delta_from_base'][scenario]['otd'], {'absolute': None, 'percent': None})
        self.assertEqual(fingerprint(data), before)
