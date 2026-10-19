"""Regression contracts for the audited defects and unchanged business rules."""
import copy
import io
import json
import tempfile
import shutil
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date, timedelta
from pathlib import Path

from scai.ai import read_json, review, validate_response, make_packet, review_template
from scai.artifacts import verify_run
from scai.analysis import analyze, inventory_risk, delivery, forecast
from scai.data import load, dump
from scai.__main__ import main, run

ROOT = Path(__file__).resolve().parents[1]


class ReviewAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = read_json(ROOT / 'examples/base/ai_packet.json')
        cls.response = read_json(ROOT / 'examples/ai_response_codex.json')
        cls.result = read_json(ROOT / 'examples/base/results.json')

    def decisions(self):
        # Deliberately do not read the user's in-progress review_decisions.json.
        return review_template(self.packet, self.response)

    def test_all_pending_legal_and_inputs_unchanged(self):
        decisions = self.decisions()
        before = copy.deepcopy((self.packet, self.response, decisions))
        output = review(self.packet, self.response, decisions)
        self.assertEqual(output['approved_count'], 0)
        self.assertEqual(len(output['decisions']), 4)
        self.assertEqual((self.packet, self.response, decisions), before)

    def test_review_missing_duplicate_foreign_ids_rejected(self):
        for mode in ('missing', 'duplicate', 'foreign'):
            with self.subTest(mode=mode):
                decisions = self.decisions()
                if mode == 'missing': decisions['decisions'].pop()
                elif mode == 'duplicate': decisions['decisions'].append(decisions['decisions'][0])
                else: decisions['decisions'][0]['evidence_id'] = 'UNKNOWN'
                with self.assertRaises(ValueError): review(self.packet, self.response, decisions)

    def test_review_hash_and_invalid_decision_rejected(self):
        for mode in ('hash', 'decision'):
            decisions = self.decisions()
            if mode == 'hash': decisions['packet_sha256'] = 'other'
            else: decisions['decisions'][0]['decision'] = 'execute_purchase'
            with self.assertRaises(ValueError): review(self.packet, self.response, decisions)

    def test_cli_pending_output_is_isolated_and_not_execution(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='.test-review-') as folder:
            folder = Path(folder)
            shutil.copytree(ROOT / 'examples/base', folder / 'input')
            dump(folder / 'response.json', self.response)
            dump(folder / 'decisions.json', self.decisions())
            # Windows editors may save BOM; reader explicitly supports UTF-8 BOM.
            (folder / 'decisions.json').write_text(json.dumps(self.decisions()), encoding='utf-8-sig')
            with redirect_stdout(io.StringIO()):
                code = main(['review', '--run', str(folder / 'input'), '--response', str(folder / 'response.json'),
                             '--data', str(ROOT / 'data/demo'), '--out', str(folder / 'output'),
                             '--decisions', str(folder / 'decisions.json')])
            self.assertEqual(code, 0)
            output = read_json(folder / 'output/human_review.json')
            self.assertEqual(output['approved_count'], 0)
            self.assertIn('not authenticated identity or proof of execution', output['notice'])
            self.assertFalse((folder / 'output/dashboard_ai.html').exists())

    def test_nonpending_identity_requires_real_strings(self):
        decisions = self.decisions()
        decisions['decisions'][0].update(decision='approve', reviewer=None, reason=None)
        with self.assertRaisesRegex(ValueError, 'reviewer must be a string'): review(self.packet, self.response, decisions)

    def test_review_binds_exact_response(self):
        decisions = self.decisions()
        self.assertEqual(review(self.packet, self.response, decisions)['binding_status'], 'response_bound')
        response = copy.deepcopy(self.response)
        response['items'][0]['action'] = 'A different recommendation for an isolated test'
        with self.assertRaisesRegex(ValueError, 'response_sha256 mismatch'): review(self.packet, response, decisions)

    def test_validate_rejects_mixed_run_artifacts(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='.test-mixed-') as folder:
            folder = Path(folder)
            shutil.copytree(ROOT / 'examples/base', folder / 'input')
            verify_run(folder / 'input', ROOT / 'data/demo')  # valid full fixture first
            result = copy.deepcopy(self.result)
            result['summary']['demand_factor'] = 1.25
            dump(folder / 'input/results.json', result)
            dump(folder / 'response.json', self.response)
            error = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(error):
                code = main(['validate-ai', '--run', str(folder / 'input'), '--response', str(folder / 'response.json'),
                             '--data', str(ROOT / 'data/demo'), '--out', str(folder / 'output')])
            self.assertEqual(code, 2)
            self.assertIn('run hash mismatch: results.json', error.getvalue())
            self.assertFalse((folder / 'output').exists())

    def test_default_equivalent_factor_preserves_results_and_packet(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='.test-factor-') as folder:
            folder = Path(folder)
            run(ROOT / 'data/demo', folder / 'direct')
            for name, flags in [('default', []), ('int', ['--demand-factor', '1']), ('float', ['--demand-factor', '1.0'])]:
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['analyze', '--data', str(ROOT / 'data/demo'), '--out', str(folder / name), *flags]), 0)
                for filename in ('results.json', 'ai_packet.json'):
                    self.assertEqual((folder / name / filename).read_bytes(), (folder / 'direct' / filename).read_bytes())
            self.assertEqual(read_json(folder / 'direct/ai_packet.json'), self.packet)
            self.assertEqual(read_json(folder / 'direct/results.json'), self.result)


class BusinessAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables, cls.series, cls.asof = load(ROOT / 'data/demo')
        cls.results = {(factor, delay): analyze(cls.tables, cls.series, cls.asof, factor, delay)[0]
                       for factor, delay in ((1, 0), (1.25, 0), (1, 7), (1.25, 7))}

    def test_all_scenarios_entities_historical_metrics_and_source_isolation(self):
        base = self.results[(1, 0)]
        expected = {(1, 0): (17, 21), (1.25, 0): (29, 35), (1, 7): (42, 45), (1.25, 7): (69, 74)}
        for params, result in self.results.items():
            with self.subTest(params=params):
                keys = {(x['sku'], x['warehouse']) for x in result['inventory']}
                self.assertEqual(len(keys), 90)
                self.assertEqual(result['metrics'], base['metrics'])
                self.assertEqual(result['suppliers'], base['suppliers'])
                self.assertEqual((result['summary']['shortage_entities'], sum(x['reorder_suggestion_units'] > 0 for x in result['inventory'])), expected[params])
        changed = copy.deepcopy(self.tables)
        changed['inventory'][0]['on_hand'] += 10000
        altered, _ = analyze(changed, self.series, self.asof)
        self.assertEqual(altered['inventory'][1:], base['inventory'][1:])

    def test_all_scenario_paths_conserve_stock_and_do_not_double_count_arrivals(self):
        inputs = {(x['sku'], x['warehouse']): x for x in self.tables['inventory']}
        for (factor, delay), result in self.results.items():
            for row in result['inventory']:
                key = row['sku'], row['warehouse']
                inv = inputs[key]
                with self.subTest(params=(factor, delay), key=key):
                    self.assertEqual(row['horizon_days'], inv['lead_days'] + delay + 7)
                    daily = [x * factor for x in forecast([d['demand_units'] for d in self.series[key]], row['horizon_days'], row['model'])]
                    self.assertEqual(len(row['time_path']), row['horizon_days'])
                    self.assertEqual(len(daily), row['horizon_days'])
                    self.assertEqual([p['day'] for p in row['time_path']], list(range(1, row['horizon_days'] + 1)))
                    dates = [date.fromisoformat(result['summary']['as_of']) + timedelta(days=p['day']) for p in row['time_path']]
                    self.assertEqual(dates, [self.asof + timedelta(days=d) for d in range(1, row['horizon_days'] + 1)])
                    balance = inv['on_hand'] - inv['backlog']
                    for point, units in zip(row['time_path'], daily):
                        arrival = sum(o['qty'] for o in self.tables['orders']
                                      if (o['sku'], o['warehouse']) == key and o['received_date'] is None
                                      and o['expected_date'] > self.asof
                                      and (o['expected_date'] - self.asof).days + delay == point['day'])
                        self.assertEqual(point['arrival'], arrival)
                        self.assertEqual(point['demand'], round(units, 4))
                        balance += arrival - units
                        self.assertEqual(point['balance'], round(balance, 4))

    def test_arrival_window_boundaries_received_and_stale_eta(self):
        inv = dict(sku='S', warehouse='W', source_row=2, lead_days=1, on_hand=0, backlog=0, safety_days=0, unit_cost_cny=1)
        orders = [{'received_date': None, 'expected_date': self.asof + timedelta(days=day), 'qty': qty}
                  for day, qty in [(0, 999), (1, 8), (1, 12), (8, 30), (9, 999)]]
        orders.append({'received_date': self.asof, 'expected_date': self.asof + timedelta(days=1), 'qty': 999})
        result = inventory_risk(inv, orders, [10] * 28, self.asof, 'naive')
        self.assertEqual(result['first_shortage_day'], 3)
        self.assertEqual(result['peak_net_shortage_units'], 50)
        self.assertEqual(result['reorder_suggestion_units'], 30)
        self.assertEqual(sum(p['arrival'] for p in result['time_path']), 50)

    def test_delivery_cohort_includes_day_27_and_today_only(self):
        orders = [{'promised_date': self.asof + timedelta(days=day), 'received_date': receipt}
                  for day, receipt in [(-28, self.asof - timedelta(days=28)),
                                       (-27, self.asof - timedelta(days=27)), (0, None), (1, None)]]
        self.assertEqual(delivery(orders, self.asof), {'due_orders': 2, 'on_time_orders': 1, 'otd': .5})

    def test_forecast_and_zero_demand_backlog_semantics(self):
        self.assertEqual(forecast([10, 20, 30], 2, 'naive'), [30., 30.])
        self.assertEqual(forecast([999] + [10] * 28, 2, 'ma28'), [10., 10.])
        inv = dict(sku='S', warehouse='W', source_row=2, lead_days=1, on_hand=0, backlog=5, safety_days=3, unit_cost_cny=1)
        result = inventory_risk(inv, [], [0] * 28, self.asof, 'naive')
        self.assertIsNone(result['coverage_days'])
        self.assertEqual(result['first_shortage_day'], 0)
        self.assertEqual(result['reorder_suggestion_units'], 5)

    def test_scenario_bounds_rejected_before_calculation(self):
        for factor, delay in [(0, 0), (5.01, 0), (float('nan'), 0), (1, -1), (1, 61)]:
            with self.subTest(factor=factor, delay=delay), self.assertRaises(ValueError):
                analyze(self.tables, self.series, self.asof, factor, delay)
