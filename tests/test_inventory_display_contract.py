"""Audit the meaning of null/zero without changing business calculations."""
import unittest
from collections import Counter
from datetime import date, timedelta
from math import ceil
from pathlib import Path

from scai.analysis import analyze, forecast, inventory_risk
from scai.data import load


class InventoryDisplayContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables, cls.series, cls.asof = load(Path(__file__).resolve().parents[1] / 'data/demo')
        cls.result, _ = analyze(cls.tables, cls.series, cls.asof)

    def test_base_counts_and_four_state_distribution(self):
        rows = self.result['inventory']
        self.assertEqual(len(rows), 90)
        counts = Counter((x['first_shortage_day'] is not None, x['reorder_suggestion_units'] > 0) for x in rows)
        self.assertEqual(counts, {(True, True): 17, (False, True): 4, (False, False): 69})
        self.assertEqual(sum(x['first_shortage_day'] is not None for x in rows), 17)
        self.assertEqual(sum(x['reorder_suggestion_units'] > 0 for x in rows), 21)
        for x in rows:
            for name in ('first_shortage_day', 'peak_net_shortage_units', 'reorder_suggestion_units', 'reorder_cost_cny'):
                self.assertIn(name, x)
            if x['first_shortage_day'] is None:
                self.assertEqual(x['peak_net_shortage_units'], 0)
            if x['reorder_suggestion_units'] == 0:
                self.assertEqual(x['reorder_cost_cny'], 0)

    def test_all_base_indicators_against_raw_inputs(self):
        """Check all 90 entities against raw demand, inventory and order inputs."""
        inputs = {(x['sku'], x['warehouse']): x for x in self.tables['inventory']}
        for row in self.result['inventory']:
            key = row['sku'], row['warehouse']
            with self.subTest(entity=key):
                inv = inputs[key]
                daily = forecast([x['demand_units'] for x in self.series[key]], inv['lead_days'] + 7, row['model'])
                arrivals = [sum(o['qty'] for o in self.tables['orders']
                                if (o['sku'], o['warehouse']) == key and o['received_date'] is None
                                and o['expected_date'] == self.asof + timedelta(days=day))
                            for day in range(1, len(daily) + 1)]
                balances = [inv['on_hand'] - inv['backlog']]
                for arrival, demand in zip(arrivals, daily):
                    balances.append(balances[-1] + arrival - demand)
                expected_first = next((day for day, balance in enumerate(balances) if balance < 0), None)
                safety = sum(daily) / len(daily) * inv['safety_days']
                expected_qty = max(0, ceil(sum(daily) + safety - inv['on_hand'] + inv['backlog'] - sum(arrivals)))
                self.assertEqual(row['first_shortage_day'], expected_first)
                self.assertEqual(row['peak_net_shortage_units'], round(max(0, -min(balances)), 4))
                self.assertEqual(row['reorder_suggestion_units'], expected_qty)
                self.assertEqual(row['reorder_cost_cny'], round(expected_qty * inv['unit_cost_cny'], 2))
                self.assertEqual([p['balance'] for p in row['time_path']], [round(b, 4) for b in balances[1:]])

    def risk(self, on_hand, orders=(), backlog=0, cost=2):
        inv = {'sku': 'S', 'warehouse': 'W', 'source_row': 2, 'lead_days': 7,
               'on_hand': on_hand, 'backlog': backlog, 'safety_days': 3, 'unit_cost_cny': cost}
        return inventory_risk(inv, orders, [10] * 28, date(2026, 10, 17), 'naive')

    def test_four_states_with_hand_calculated_examples(self):
        late = [{'received_date': None, 'expected_date': date(2026, 10, 22), 'qty': 1000}]
        for on_hand, orders, first, peak, qty in [(10, [], 2, 130, 160), (10, late, 2, 30, 0),
                                                 (140, [], None, 0, 30), (170, [], None, 0, 0)]:
            with self.subTest(on_hand=on_hand, orders=orders):
                result = self.risk(on_hand, orders)
                self.assertEqual((result['first_shortage_day'], result['peak_net_shortage_units'],
                                  result['reorder_suggestion_units'], result['reorder_cost_cny']),
                                 (first, peak, qty, qty * 2))

    def test_day_zero_shortage_is_not_null_even_after_recovery(self):
        result = self.risk(0, [{'received_date': None, 'expected_date': date(2026, 10, 18), 'qty': 200}], backlog=10)
        self.assertEqual(result['first_shortage_day'], 0)
        self.assertEqual(result['peak_net_shortage_units'], 10)
        self.assertEqual(result['reorder_suggestion_units'], 0)
        self.assertGreater(result['time_path'][0]['balance'], 0)

    def test_zero_cost_does_not_imply_zero_reorder(self):
        result = self.risk(10, cost=0)
        self.assertEqual(result['reorder_suggestion_units'], 160)
        self.assertEqual(result['reorder_cost_cny'], 0)
