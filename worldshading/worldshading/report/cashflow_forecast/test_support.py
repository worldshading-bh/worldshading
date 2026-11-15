"""Dated manual funding has no accounting or VAT side effects."""
import unittest
from datetime import date
from worldshading.worldshading.report.cashflow_forecast.scenarios import support_events
from worldshading.worldshading.report.cashflow_forecast.engine import build_forecast, monthly_rows

class SupportTests(unittest.TestCase):
    def test_support_changes_cash_on_each_date_not_opening(self):
        events=support_events([dict(date='2026-11-17',amount=100),dict(date='2026-11-19',amount=50,description='Owner funding')],
                              date(2026,11,15),date(2026,11,20))
        rows=build_forecast('2026-11-15','2026-11-20',10,events,{})
        self.assertEqual(rows[0]['opening_cash'],10)
        self.assertEqual([r['closing_cash'] for r in rows],[10,10,110,110,160,160])
        self.assertEqual(sum(r['total_payments'] for r in rows),0)
        self.assertEqual(events[0]['description'],'Support')
        self.assertEqual(monthly_rows(rows)[0]['other_receipts'],150)
        self.assertTrue(all(e['category']=='other_receipts' for e in events))
        self.assertTrue(all(r['vat_position']==0 for r in rows))

    def test_support_rows_require_in_range_date_and_positive_finite_amount(self):
        for row in [dict(date='2026-11-14',amount=1),dict(date='2026-11-21',amount=1),
                    dict(date='2026-11-17',amount=0),dict(date='2026-11-17',amount=-1),
                    dict(date='2026-11-17',amount='NaN'),dict(amount=1),[],
                    dict(date='2026-11-17',amount=1,description='x'*501)]:
            with self.assertRaises((ValueError,TypeError)):
                support_events([row],'2026-11-15','2026-11-20')
        with self.assertRaises(ValueError):support_events([{}]*501,'2026-11-15','2026-11-20')
        self.assertEqual(support_events([],'2026-11-15','2026-11-20'),[])

    def test_report_validation_turns_saved_support_table_into_incoming_events(self):
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
        values=dict(company='Example',end_date='2026-11-20',support_amount=0,
                    support_payments='[{"date":"2026-11-17","amount":100},{"date":"2026-11-19","amount":50}]')
        with patch.object(report,'authorize'),patch.object(report,'resolve_accounts',return_value=['Bank']), \
             patch.object(report,'nowdate',return_value='2026-11-15'):
            filters,start,end,accounts,events=report.validate(values)
        self.assertEqual([(e['date'],e['amount']) for e in events],[(date(2026,11,17),100),(date(2026,11,19),50)])
        self.assertEqual(filters.support_amount,0)
        self.assertTrue(all(e['manual_support'] for e in events))
