"""Standalone tests: run this file directly, never bench run-tests."""
import importlib.util
import os
import unittest
from datetime import date
from decimal import Decimal

spec = importlib.util.spec_from_file_location('cashflow_engine', os.path.join(os.path.dirname(__file__), 'engine.py'))
engine = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(engine)
except FileNotFoundError:
    pass


class ForecastTests(unittest.TestCase):
    def test_workbook_and_purchase_propagation(self):
        args = dict(start='2026-11-08', end='2026-11-10', opening='13399.997',
                    historical={'2026-11-08': 2000, '2026-11-09': 2000, '2026-11-10': 2000},
                    today_receipts=2000, events=[{'date': '2026-11-09', 'category': 'fixed_expenses', 'amount': 52},
                    {'date': '2026-11-10', 'category': 'fixed_expenses', 'amount': 3735},
                    {'date': '2026-11-10', 'category': 'supplier_payments', 'amount': '9747.983'}])
        rows = engine.build_forecast(**args)
        self.assertEqual([r['closing_cash'] for r in rows], [Decimal('15399.997'), Decimal('17347.997'), Decimal('5865.014')])
        args['events'].append({'date': '2026-11-09', 'category': 'extra_expenses', 'amount': 500})
        changed = engine.build_forecast(**args)
        self.assertEqual([r['closing_cash'] for r in changed], [Decimal('15399.997'), Decimal('16847.997'), Decimal('5365.014')])

    def test_adjustment_support_today_and_refunds(self):
        rows = engine.build_forecast('2026-11-08', '2026-11-10', 100, [],
            {'2026-11-08': 2000, '2026-11-09': 2000, '2026-11-10': -100},
            adjustment=-30, support=500, today_receipts=0)
        self.assertEqual([r['expected_receipts'] for r in rows], [Decimal('0'), Decimal('1400'), Decimal('-70')])
        self.assertEqual(rows[-1]['closing_cash'], Decimal('1930'))

    def test_month_anchor_and_leap_dates(self):
        self.assertEqual(list(engine.occurrences('2026-01-31', '2026-02-01', '2026-04-30', 1)),
                         [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)])
        self.assertEqual(list(engine.occurrences('2024-02-29', '2025-01-01', '2028-12-31', 12)),
                         [date(2025, 2, 28), date(2026, 2, 28), date(2027, 2, 28), date(2028, 2, 29)])

    def test_customs_template_chain_and_valuation(self):
        rows = [{'charge_type': 'Actual', 'tax_amount': 100, 'category': 'Valuation and Total'},
                {'charge_type': 'On Previous Row Total', 'row_id': 1, 'rate': 5, 'category': 'Valuation'},
                {'charge_type': 'On Previous Row Total', 'row_id': 2, 'rate': 10, 'category': 'Total'}]
        self.assertEqual(engine.template_taxes(1000, rows, 1), [Decimal('100'), Decimal('55'), Decimal('110')])

    def test_quarter_settlement_and_credit_carry(self):
        events = [{'date': '2026-12-30', 'category': 'vat_accrual', 'amount': -50},
                  {'date': '2026-12-31', 'category': 'vat_accrual', 'amount': 70}]
        rows = engine.build_forecast('2026-12-30', '2027-04-25', 1000, events, {}, vat_opening=-100)
        self.assertEqual(rows[1]['quarterly_vat'], Decimal('0'))
        self.assertEqual(rows[-1]['quarterly_vat'], Decimal('0'))
        events.append({'date': '2027-03-30', 'category': 'vat_accrual', 'amount': 200})
        rows = engine.build_forecast('2026-12-30', '2027-04-25', 1000, events, {}, vat_opening=-100)
        self.assertEqual(rows[-1]['quarterly_vat'], Decimal('120'))
        self.assertEqual(rows[-1]['closing_cash'], Decimal('880'))

    def test_paid_installments_and_invoice_replacement(self):
        schedule = [{'date': '2026-12-01', 'amount': 40}, {'date': '2027-01-01', 'amount': 60}]
        self.assertEqual(engine.reconcile_installments(schedule, 20, 30),
                         [{'date': '2027-01-01', 'amount': Decimal('50')}])
        self.assertEqual(engine.reconcile_installments(schedule, 100, 0), [])

    def test_known_vat_settlement_does_not_pay_same_liability_twice(self):
        rows = engine.build_forecast('2026-12-30', '2027-01-25', 1000,
            [{'date': '2026-12-30', 'category': 'vat_settlement', 'amount': 100}], {}, vat_opening=150)
        self.assertEqual(rows[0]['quarterly_vat'], Decimal('100'))
        self.assertEqual(rows[1]['quarterly_vat'], Decimal('0'))
        self.assertEqual(rows[-1]['quarterly_vat'], Decimal('50'))
        self.assertEqual(rows[-1]['closing_cash'], Decimal('850'))

    def test_validation_and_first_shortfall(self):
        for invalid in ['NaN', 'Infinity', '-Infinity']:
            with self.assertRaises(ValueError): engine.money(invalid)
        with self.assertRaises(ValueError): engine.build_forecast('2026-01-02', '2026-01-01', 0, [], {})
        with self.assertRaises(ValueError): engine.build_forecast('2026-01-01', '2026-01-02', 0, [], {}, adjustment=-101)
        rows = engine.build_forecast('2026-11-08', '2026-11-09', 100,
            [{'date': '2026-11-08', 'category': 'extra_expenses', 'amount': 200}], {})
        summary = engine.summarize(rows, 10)
        self.assertEqual(summary['first_shortfall_date'], date(2026, 11, 8))
        self.assertEqual(summary['lowest_balance'], Decimal('-100'))


if __name__ == '__main__':
    unittest.main()
