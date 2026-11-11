import unittest
from decimal import Decimal
from worldshading.worldshading.report.cashflow_forecast.engine import build_forecast,monthly_rows

class AutomaticTodayTests(unittest.TestCase):
    def test_actual_plus_remaining_is_displayed_but_actual_not_added_twice(self):
        rows=build_forecast('2026-11-11','2026-11-12',1000,[],{'2026-11-11':1000,'2026-11-12':200},actual_sales_today=400)
        first=rows[0]
        self.assertEqual(first['expected_receipts'],1000)
        self.assertEqual(first['remaining_sales_today'],600)
        self.assertEqual(first['total_receipts'],600)
        self.assertEqual(first['closing_cash'],1600)
        self.assertEqual(rows[1]['closing_cash'],1800)

    def test_manual_average_actual_above_target_and_holiday(self):
        for actual,holiday,expected,remaining in [(400,[],1000,600),(1200,[],1200,0),(400,['2026-11-11'],400,0)]:
            row=build_forecast('2026-11-11','2026-11-11',1000,[],{},manual_daily_sales=1000,holidays=holiday,actual_sales_today=actual)[0]
            self.assertEqual(row['expected_receipts'],expected)
            self.assertEqual(row['sales_cash_inflow'],remaining)
            self.assertEqual(row['closing_cash'],1000+remaining)

    def test_percentage_and_monthly_cash_remain_consistent(self):
        rows=build_forecast('2026-11-11','2026-11-12',1000,[],{'2026-11-11':1000,'2026-11-12':1000},adjustment=-30,actual_sales_today=400)
        self.assertEqual(rows[0]['expected_receipts'],700)
        self.assertEqual(rows[0]['sales_cash_inflow'],300)
        month=monthly_rows(rows)[0]
        self.assertEqual(month['expected_receipts'],1400)
        self.assertEqual(month['total_receipts'],1000)
        self.assertEqual(month['closing_cash'],2000)

    def test_report_projects_only_remaining_vat_in_both_sales_modes(self):
        import frappe
        from types import SimpleNamespace
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
        from worldshading.worldshading.report.cashflow_forecast.sources import Sources
        from datetime import date
        for manual in (0,1):
            source=Sources.__new__(Sources);source.start=date(2026,11,11);source.end=source.start
            source.company='Example';source.currency='BHD';source.opening_balance=1000;source.actual_sales_today=550
            source.historical={'2026-11-11':1100};source.sales_tax={'2026-11-11':100};source.events=[];source.overdue=[]
            source.warnings=[];source.accounts_breakdown=[];source.include_overdue=True;source.vat_opening=50
            source.holidays=[];source.manual_vat_rate=Decimal(10);source.collect=lambda:source
            values=frappe._dict(company='Example',manual_sales=manual,average_daily_sales=1100,sales_adjustment=0,today_receipts=99999)
            with patch.object(report,'validate',return_value=(values,source.start,source.end,[],[])),patch.object(report,'Sources',return_value=source):
                rows=report.execute(values)[1]
            self.assertEqual(rows[0]['expected_receipts'],1100)
            self.assertEqual(rows[0]['total_receipts'],550)
            self.assertEqual(rows[0]['closing_cash'],1550)
            self.assertEqual(rows[0]['vat_position'],100)
            self.assertEqual(rows[0]['_cashflow_context']['today_policy'],'auto-v1')

    def test_returns_and_actual_above_target_do_not_change_tomorrow(self):
        row=build_forecast('2026-11-11','2026-11-11',1000,[],{'2026-11-11':100},actual_sales_today=-50)[0]
        self.assertEqual(row['remaining_sales_today'],150);self.assertEqual(row['expected_receipts'],100)
        rows=build_forecast('2026-11-11','2026-11-12',1000,[],{},manual_daily_sales=100,actual_sales_today=200)
        self.assertEqual(rows[0]['sales_cash_inflow'],0)
        self.assertEqual(rows[1]['expected_receipts'],100)

    def test_missing_today_sales_access_does_not_guess_remaining_cash(self):
        import frappe
        from types import SimpleNamespace
        from unittest.mock import patch
        from datetime import date
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
        source=SimpleNamespace(actual_sales_today=None,collect=lambda:source)
        values=frappe._dict(company='Example',include_overdue=1)
        with patch.object(report,'validate',return_value=(values,date(2026,11,11),date(2026,11,12),[],[])),patch.object(report,'Sources',return_value=source),patch.object(frappe,'throw',side_effect=PermissionError):
            with self.assertRaises(PermissionError):report.execute(values)
