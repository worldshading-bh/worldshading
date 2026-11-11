import unittest
from datetime import date
from worldshading.worldshading.report.cashflow_forecast.engine import build_forecast
from worldshading.worldshading.report.cashflow_forecast.vat import due_date
from worldshading.worldshading.report.cashflow_forecast.scenarios import purchase_events

class ForecastUpdatesTests(unittest.TestCase):
    def test_vat_due_25th(self):
        self.assertEqual(due_date('2026-01-01'), date(2026,4,25))
        self.assertEqual(due_date('2026-12-31'), date(2027,1,25))
        rows=build_forecast('2026-12-31','2027-01-25',1000,[],{},vat_opening=100)
        self.assertEqual(sum(r['quarterly_vat'] for r in rows[:-1]),0)
        self.assertEqual(rows[-1]['quarterly_vat'],100)

    def test_manual_sales_holidays_and_today(self):
        rows=build_forecast('2026-11-10','2026-11-13',1000,[],{'2026-11-11':900},
            adjustment=50,today_receipts=12,manual_daily_sales=100,holidays=['2026-11-12'])
        self.assertEqual([r['expected_receipts'] for r in rows],[12,100,0,100])

    def test_split_payment_eta_before_supplier(self):
        purchase=dict(schema=3,amount=15000,date='2026-12-01',international=1,eta_date='2026-11-20',
            split_payments=1,payments=[dict(date='2026-12-01',amount=10000),dict(date='2027-01-10',amount=5000)])
        template=[dict(account_head='Custom Duty - WS',charge_type='On Net Total',rate=5),
            dict(account_head='Input VAT – Import - WS',charge_type='On Net Total',rate=10)]
        events=purchase_events(purchase,'2026-11-10','2027-02-10',template)
        self.assertEqual([e['amount'] for e in events if e['category']=='proposed_purchase'],[10000,5000])
        self.assertEqual({e['date'] for e in events if e['category'] in ('customs','import_vat')},{date(2026,11,20)})
        purchase['payments'][1]['amount']=4000
        with self.assertRaises(ValueError):purchase_events(purchase,'2026-11-10','2027-02-10',template)

class ForecastAdapterUpdatesTests(unittest.TestCase):
    def test_manual_source_uses_today_only_and_configured_holidays_tax(self):
        import frappe
        from unittest.mock import patch
        from types import SimpleNamespace
        from worldshading.worldshading.report.cashflow_forecast.sources import Sources
        source=Sources.__new__(Sources)
        source.company='Example';source.start=date(2026,11,10);source.end=date(2026,11,13)
        source.holiday_list='Calendar';source.historical={};source.sales_tax={}
        holiday=SimpleNamespace(from_date=date(2026,1,1),to_date=date(2026,12,31),
            holidays=[SimpleNamespace(holiday_date=date(2026,11,12))],check_permission=lambda *args:None)
        template=SimpleNamespace(taxes=[SimpleNamespace(account_head='Output VAT – Sales - WS',charge_type='On Net Total',rate=10)],check_permission=lambda *args:None)
        def listing(dt,filters=None,**kwargs):
            if dt=='Sales Invoice':
                self.assertEqual(filters['posting_date'],source.start)
                return [frappe._dict(amount=22)]
            if dt=='Holiday List':return [frappe._dict(name='Calendar')]
            return [frappe._dict(name='Default VAT')]
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_list',side_effect=listing), \
            patch.object(frappe,'get_doc',side_effect=lambda dt,name:holiday if dt=='Holiday List' else template):
            source.manual_sales()
        self.assertEqual(source.actual_sales_today,22)
        self.assertEqual(source.holidays,['2026-11-12'])
        self.assertEqual(source.manual_vat_rate,10)
        self.assertFalse(source.historical)

    def test_only_latest_completed_quarter_is_forecast_not_older_unpaid(self):
        import frappe
        from unittest.mock import patch,Mock
        from types import SimpleNamespace
        from worldshading.worldshading.report.cashflow_forecast.sources import Sources
        source=Sources.__new__(Sources)
        source.company='Example';source.accounts=['Bank'];source.start=date(2026,11,10);source.end=date(2027,1,25)
        source.events=[];source.overdue=[];source.warnings=[];source.include_overdue=True
        periods=[frappe._dict(year=2026,period=2,amount=400),frappe._dict(year=2026,period=3,amount=100),frappe._dict(year=2026,period=4,amount=50)]
        with patch.object(frappe,'db',SimpleNamespace(exists=lambda *args:True,sql=Mock(side_effect=[[],periods]))), \
            patch.object(frappe,'get_doc',return_value=SimpleNamespace(check_permission=lambda *args:None)):
            source.tax_position();source._vat_data.finalize()
        self.assertEqual(source.vat_ledger_balance,550)
        self.assertEqual(source.vat_opening['balances'],{'2026-04-01':'400.000','2026-07-01':'100.000','2026-10-01':'50.000'})
        self.assertEqual(len(source.events),1)
        self.assertEqual(source.events[0]['amount'],100)
        self.assertEqual(source.events[0]['vat_quarter'],'2026-07-01')
        rows=build_forecast(source.start,source.end,1000,source.events,{},vat_opening=source.vat_opening)
        self.assertEqual(sum(row['quarterly_vat'] for row in rows),150)

    def test_quick_purchase_replaces_not_accumulates_and_does_not_collect_sources(self):
        import frappe
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report,prepared_access
        values=frappe._dict(company='Example',end_date='2026-12-31',manual_sales=0,include_overdue=1)
        source=frappe._dict(company='Example',currency='BHD',opening_balance=1000,events=[],historical={},vat_opening=0,
            accounts_breakdown=[],warnings=[],actual_sales_today=0,vat_reconciliation=[],vat_ledger_balance=0,overdue=[],journal_stats={},holidays=[])
        context=dict(today_policy='auto-v1',vat_policy='quarter-v4',forecast_date='2026-11-10',base_filters=dict(values),calculation_inputs=dict(source))
        saved={'result':[{'_cashflow_context':context}]}
        events=[dict(date=date(2026,11,15),category='proposed_purchase',amount=100,scenario=True,scenario_kind='supplier',description='Purchase')]
        with patch.object(prepared_access,'run',return_value=saved) as authorized, \
             patch.object(report,'validate',return_value=(values,date(2026,11,10),date(2026,12,31),['Bank'],events)), \
             patch.object(report,'_',side_effect=lambda value:value),patch.object(report,'Sources') as collector:
            first=report.recalculate_purchase('SNAPSHOT',values)
            events[0]['amount']=200
            second=report.recalculate_purchase('SNAPSHOT',values)
        self.assertEqual(first['result'][-1]['closing_cash'],900)
        self.assertEqual(second['result'][-1]['closing_cash'],800)
        collector.assert_not_called()
        self.assertEqual(authorized.call_count,2)
        self.assertEqual(source.events,[])

    def test_quick_purchase_rejects_changed_base_filters(self):
        import frappe
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report,prepared_access
        values=frappe._dict(company='Other',end_date='2026-12-31',manual_sales=0)
        context=dict(today_policy='auto-v1',vat_policy='quarter-v4',forecast_date='2026-11-10',base_filters={'company':'Example'},calculation_inputs={'events':[]})
        with patch.object(prepared_access,'run',return_value={'result':[{'_cashflow_context':context}]}), \
            patch.object(report,'validate',return_value=(values,date(2026,11,10),date(2026,12,31),[],[])), \
            patch.object(frappe,'throw',side_effect=ValueError):
            with self.assertRaises(ValueError):report.recalculate_purchase('SNAPSHOT',values)

    def test_old_known_payment_does_not_create_credit_in_latest_quarter(self):
        from worldshading.worldshading.report.cashflow_forecast.engine import build_forecast
        opening={'balances':{'2026-04-01':100,'2026-07-01':200,'2026-10-01':50}}
        events=[dict(date='2026-11-10',category='vat_settlement',amount=200,vat_quarter='2026-07-01'),
                dict(date='2026-11-20',category='vat_settlement',amount=100,vat_quarter='2026-04-01')]
        rows=build_forecast('2026-11-10','2027-01-25',1000,events,{},vat_opening=opening)
        self.assertEqual(rows[0]['quarterly_vat'],200)
        self.assertEqual(rows[-1]['quarterly_vat'],50)
        self.assertEqual(sum(row['quarterly_vat'] for row in rows),350)
        self.assertEqual(rows[-1]['vat_position'],0)

    def test_automatic_holidays_span_years_and_deduplicate(self):
        import frappe
        from types import SimpleNamespace
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast.sources import Sources
        source=Sources.__new__(Sources);source.start=date(2026,12,30);source.end=date(2027,1,3)
        calendars={name:SimpleNamespace(from_date=date(int(name),1,1),to_date=date(int(name),12,31),check_permission=lambda *args:None,
            holidays=[SimpleNamespace(holiday_date=day) for day in dates])
            for name,dates in [('2026',[date(2026,12,31)]),('2027',[date(2027,1,1),date(2027,1,1),date(2027,2,1)])]}
        with patch.object(frappe,'get_list',return_value=[frappe._dict(name=name) for name in calendars]) as lookup, \
             patch.object(frappe,'get_doc',side_effect=lambda dt,name:calendars[name]):
            source.forecast_holidays()
        self.assertEqual(source.holidays,['2026-12-31','2027-01-01'])
        self.assertEqual(lookup.call_args[1]['filters'],{'from_date':['<=',source.end],'to_date':['>=',source.start]})

    def test_missing_holiday_list_keeps_regular_sales(self):
        import frappe
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast.sources import Sources
        source=Sources.__new__(Sources);source.start=date(2027,1,1);source.end=date(2027,1,3)
        with patch.object(frappe,'get_list',return_value=[]):source.forecast_holidays()
        rows=build_forecast(source.start,source.end,1000,[],{},manual_daily_sales=100,holidays=source.holidays)
        self.assertEqual([row['expected_receipts'] for row in rows],[0,100,100])

    def test_multiple_purchase_totals_come_from_each_payment_table(self):
        values={'schema':4,'purchases':[
            {'payments':[{'date':'2026-11-15','amount':10000},{'date':'2026-12-10','amount':5000}],
             'international':1,'eta_date':'2026-11-20'},
            {'payments':[{'date':'2026-12-01','amount':2000}],
             'international':1,'eta_date':'2026-12-05'}]}
        template=[dict(account_head='Custom Duty - WS',charge_type='On Net Total',rate=5),
            dict(account_head='Input VAT – Import - WS',charge_type='On Net Total',rate=10)]
        events=purchase_events(values,'2026-11-10','2027-02-10',template)
        self.assertEqual(sum(e['amount'] for e in events if e['category']=='proposed_purchase'),17000)
        self.assertEqual([(str(e['date']),e['amount']) for e in events if e['category']=='import_vat'],[('2026-11-20',1500),('2026-12-05',200)])
        self.assertEqual({e['purchase_number'] for e in events},{1,2})
        self.assertTrue(any('Purchase 2' in e['description'] for e in events))
        values['purchases'][1]['payments'][0]['amount']=-1
        with self.assertRaises(ValueError):purchase_events(values,'2026-11-10','2027-02-10',template)
