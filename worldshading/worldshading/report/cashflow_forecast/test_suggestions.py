"""Suggested dates preserve whole purchases and check every later daily balance."""
import unittest
from datetime import date, timedelta
from worldshading.worldshading.report.cashflow_forecast.engine import build_forecast, as_date, money
from worldshading.worldshading.report.cashflow_forecast import suggestions


class SuggestedDatesTests(unittest.TestCase):
    def run_search(self, events, opening=100, end='2027-01-30', tolerance=0, fixed=None, vat=0):
        def evaluate(extra):
            return build_forecast('2026-12-28', end, opening, (fixed or [])+extra, {}, vat_opening=vat)
        return suggestions.suggest_dates('2026-12-28', end, events, evaluate, tolerance), evaluate

    def payment(self, due, amount, number=1, category='proposed_purchase'):
        return dict(date=as_date(due), amount=money(amount), category=category, scenario=True, purchase_number=number)

    def test_delays_until_funding_and_preserves_split_gaps(self):
        events=[self.payment('2026-12-28',60), self.payment('2026-12-30',60)]
        original=[dict(e) for e in events]
        result,_=self.run_search(events, fixed=[dict(date='2027-01-02',category='other_receipts',amount=50)])
        self.assertEqual(result[0]['first_cost_date'],'2026-12-31')
        self.assertEqual(result[0]['shift_days'],3)
        self.assertEqual(events,original)

    def test_tolerance_inclusive_and_later_shortage_blocks(self):
        events=[self.payment('2026-12-28',110)]
        self.assertEqual(self.run_search(events,tolerance=10)[0][0]['first_cost_date'],'2026-12-28')
        self.assertIsNone(self.run_search(events,tolerance=9)[0][0]['first_cost_date'])
        result,_=self.run_search(events,fixed=[dict(date='2027-01-30',category='other_payments',amount=10)],tolerance=10)
        self.assertIsNone(result[0]['first_cost_date'])

    def test_customs_can_precede_supplier_and_all_costs_must_fit(self):
        events=[self.payment('2026-12-30',60),self.payment('2026-12-28',5,category='customs')]
        result,_=self.run_search(events)
        self.assertEqual(result[0]['supplier_date'],'2026-12-30')
        self.assertEqual(result[0]['first_cost_date'],'2026-12-28')
        result,_=self.run_search(events,end='2026-12-29')
        self.assertIsNone(result[0]['first_cost_date'])

    def test_each_purchase_checks_other_purchases_on_entered_dates(self):
        events=[self.payment('2026-12-28',60),self.payment('2026-12-29',60,2)]
        result,_=self.run_search(events)
        self.assertEqual(len(result),2)
        self.assertTrue(all(r['first_cost_date'] is None for r in result))

    def test_optimized_search_matches_exact_engine_across_quarters(self):
        events=[self.payment('2026-12-28',40),self.payment('2026-12-29',5,category='import_vat'),
                self.payment('2026-12-29',-5,category='vat_accrual')]
        fixed=[dict(date='2027-01-03',category='other_receipts',amount=50)]
        result,evaluate=self.run_search(events,opening=30,fixed=fixed,vat=20,end='2027-04-30')
        first=as_date('2026-12-28'); expected=None
        for offset in range((as_date('2027-04-30')-first).days):
            shifted=[dict(e,date=e['date']+timedelta(days=offset)) for e in events]
            rows=evaluate(shifted)
            if min(r['closing_cash'] for r in rows if r['date']>=first+timedelta(days=offset))>=0:
                expected=str(first+timedelta(days=offset));break
        self.assertEqual(result[0]['first_cost_date'],expected)

    def test_negative_or_nonfinite_tolerance_rejected(self):
        for value in [-1,'NaN','Infinity']:
            with self.assertRaises(ValueError):self.run_search([],tolerance=value)

    def test_report_tolerance_default_and_validation(self):
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
        with patch.object(report,'authorize'), patch.object(report,'resolve_accounts',return_value=['Bank']), patch.object(report,'nowdate',return_value='2026-12-28'):
            values=dict(company='Example',end_date='2027-01-30')
            self.assertEqual(report.validate(values)[0].maximum_shortage,1000)
            values['maximum_shortage']=-1
            with self.assertRaises(Exception):report.validate(values)

    def test_prepared_endpoint_reuses_inputs_and_tolerance_can_change_without_rebuild(self):
        import frappe
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report, prepared_access
        values=frappe._dict(company='Example',end_date='2027-01-30',maximum_shortage=10)
        source=dict(company='Example',currency='BHD',opening_balance=100,events=[],historical={},vat_opening=0,
                    accounts_breakdown=[],actual_sales_today=0,holidays=[])
        context=dict(today_policy='auto-v1',vat_policy='quarter-v4',forecast_date='2026-12-28',
                     base_filters=dict(company='Example',end_date='2027-01-30'),calculation_inputs=source)
        with patch.object(prepared_access,'run',return_value=dict(result=[dict(_cashflow_context=context)])), \
             patch.object(report,'validate',return_value=(values,date(2026,12,28),date(2027,1,30),['Bank'],[self.payment('2026-12-28',110)])), \
             patch.object(report,'Sources',side_effect=AssertionError('Must reuse the prepared inputs')):
            result=report.recalculate_purchase('SAVED',values,suggest_purchase_dates=1)
        self.assertEqual(result['suggestions'][0]['first_cost_date'],'2026-12-28')
        self.assertEqual(source['events'],[])

    def test_tax_quarter_cache_matches_daily_brute_force_with_scheduled_settlements(self):
        start,end=as_date('2026-12-28'),as_date('2027-04-30')
        for amount,credit,tolerance in [(40,5,0),(110,15,10),(200,30,50)]:
            events=[self.payment('2026-12-28',amount),self.payment('2026-12-30',credit,category='import_vat'),
                    self.payment('2026-12-30',-credit,category='vat_accrual')]
            fixed=[dict(date='2027-01-10',category='other_receipts',amount=100),
                   dict(date='2027-03-01',category='other_receipts',amount=100),
                   dict(date='2027-01-20',category='vat_settlement',amount=5),
                   dict(date='2027-02-01',category='vat_accrual',amount=20)]
            result,evaluate=self.run_search(events,opening=50,fixed=fixed,vat=40,end=str(end),tolerance=tolerance)
            expected=None
            for shift in range((end-start).days-1):
                rows=evaluate([dict(e,date=e['date']+timedelta(days=shift)) for e in events])
                first=start+timedelta(days=shift)
                if min(row['closing_cash'] for row in rows if row['date']>=first)>=-tolerance:
                    expected=str(first);break
            self.assertEqual(result[0]['first_cost_date'],expected)

    def test_never_suggests_before_entered_payment_dates(self):
        events=[self.payment('2027-01-10',20),self.payment('2027-01-05',5,category='customs')]
        result,_=self.run_search(events)
        self.assertEqual(result[0]['shift_days'],0)
        self.assertEqual(result[0]['supplier_date'],'2027-01-10')
        self.assertEqual(result[0]['first_cost_date'],'2027-01-05')
