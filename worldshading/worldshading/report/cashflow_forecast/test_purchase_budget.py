"""Standalone purchase and budget fixtures; no site or accounting writes."""
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import frappe
from worldshading.worldshading.report.cashflow_forecast.scenarios import arrival_date, purchase_events
from worldshading.worldshading.report.cashflow_forecast.budgets import daily_budget, Budgets
from worldshading.worldshading.report.cashflow_forecast.engine import build_forecast, monthly_rows


class PurchaseTests(unittest.TestCase):
    def values(self):
        return dict(description='New goods',purchase_value=1000,order_date='2026-11-10',international=1,
                    eta_mode='Lead Time',lead_time=1,lead_unit='Months',
                    payments=[dict(date='2026-11-10',amount=300),dict(date='2026-12-15',amount=700)],
                    charges=[dict(account='Freight',amount=100)])

    def taxes(self):
        return [dict(account_head='Freight',charge_type='Actual',category='Valuation and Total'),
                dict(account_head='Custom Duty - WS',charge_type='On Previous Row Total',row_id=1,rate=5,category='Valuation'),
                dict(account_head='Input VAT – Import - WS',charge_type='On Previous Row Total',row_id=2,rate=10,category='Total')]

    def test_template_basis_and_eta_are_independent_of_advance(self):
        events=purchase_events(self.values(),'2026-11-10','2026-12-31',self.taxes())
        customs=[r for r in events if r['category']=='customs'][0]
        vat=[r for r in events if r['category']=='import_vat'][0]
        self.assertEqual((customs['date'],customs['amount']),(date(2026,12,10),55))
        # Import VAT includes customs even when customs is Valuation-only.
        self.assertEqual(vat['amount'],Decimal('115.500'))
        rows=build_forecast('2026-11-10','2027-01-25',2000,events,{},vat_opening=500)
        baseline=build_forecast('2026-11-10','2027-01-25',2000,[],{},vat_opening=500)
        self.assertEqual(rows[0]['closing_cash'],1700)
        self.assertEqual(rows[-1]['closing_cash']-baseline[-1]['closing_cash'],-1155)
        monthly=monthly_rows(rows)
        self.assertEqual(sum(r['proposed_purchase'] for r in monthly),1100)

    def test_customs_already_in_total_is_not_added_twice(self):
        taxes=self.taxes()
        taxes[1]['category']='Valuation and Total'
        events=purchase_events(self.values(),'2026-11-10','2026-12-31',taxes)
        self.assertEqual([e['amount'] for e in events if e['category']=='import_vat'],[Decimal('115.500')])

    def test_stored_po_tax_adjustment_preserves_source_rows(self):
        from worldshading.worldshading.report.cashflow_forecast.engine import import_cash_taxes
        rows=self.taxes()
        self.assertEqual(import_cash_taxes(rows,[100,55,110]),[100,55,Decimal('115.500')])
        self.assertEqual(rows[1]['category'],'Valuation')

    def test_simple_purchase_and_forty_day_import_option(self):
        values=dict(schema=2,amount=1000,date='2026-11-10',include_customs_vat=1,interval=40,interval_unit='Days')
        events=purchase_events(values,'2026-11-10','2026-12-31',self.taxes())
        self.assertEqual(events[0]['category'],'proposed_purchase')
        self.assertEqual(events[0]['amount'],1000)
        self.assertEqual([(e['date'],e['amount']) for e in events if e['category']=='customs'],[(date(2026,12,20),50)])
        self.assertEqual([(e['date'],e['amount']) for e in events if e['category']=='import_vat'],[(date(2026,12,20),105)])
        values['include_customs_vat']=0
        self.assertEqual(len(purchase_events(values,'2026-11-10','2026-12-31')),1)

    def test_simple_purchase_validates_amount_date_and_interval(self):
        for updates in [dict(amount=0),dict(date='2026-11-01'),dict(interval=-1),dict(interval=2,interval_unit='Months')]:
            values=dict(schema=2,amount=1000,date='2026-11-10',include_customs_vat=1,interval=40,interval_unit='Days')
            values.update(updates)
            with self.assertRaises(ValueError):purchase_events(values,'2026-11-10','2026-12-31',self.taxes())

    def test_import_defaults_ignore_local_default_template(self):
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
        listing=[frappe._dict(name='Local',is_default=1),frappe._dict(name='Import',is_default=0)]
        docs={'Local':frappe._dict(taxes=[frappe._dict(account_head='Input VAT – Local - WS')]),
              'Import':frappe._dict(taxes=[frappe._dict(account_head='Custom Duty - WS'),frappe._dict(account_head='Input VAT – Import - WS')])}
        for doc in docs.values():doc.check_permission=lambda *args:None
        with patch.object(frappe,'get_list',return_value=listing),patch.object(frappe,'get_doc',side_effect=lambda dt,name:docs[name]), \
             patch.object(report,'get_purchase_template',return_value={'rows':self.taxes()}) as loader:
            rows=report.get_company_import_rows('Example')
        loader.assert_called_once_with('Example','Import')
        self.assertEqual(len(rows),3)

    def test_leap_month_and_days(self):
        self.assertEqual(arrival_date('2028-01-31','Lead Time',lead=1,unit='Months'),date(2028,2,29))
        self.assertEqual(arrival_date('2026-11-10','Lead Time',lead=45,unit='Days'),date(2026,12,25))

    def test_local_cash_does_not_create_import_tax(self):
        values=self.values();values['international']=0
        self.assertEqual(len(purchase_events(values,'2026-11-10','2026-12-31')),2)

    def test_installments_must_cover_purchase_and_eta_must_be_in_horizon(self):
        values=self.values();values['payments'][1]['amount']=600
        with self.assertRaises(ValueError):purchase_events(values,'2026-11-10','2026-12-31',self.taxes())
        values=self.values();values['lead_time']=3
        with self.assertRaises(ValueError):purchase_events(values,'2026-11-10','2026-12-31',self.taxes())

    def test_unmapped_duplicate_or_negative_charges_rejected(self):
        for charges in [[dict(account='Other',amount=10)], [dict(account='Freight',amount=-1)],
                        [dict(account='Freight',amount=1),dict(account='Freight',amount=2)]]:
            values=self.values();values['charges']=charges
            with self.assertRaises(ValueError):purchase_events(values,'2026-11-10','2026-12-31',self.taxes())


class BudgetTests(unittest.TestCase):
    def test_full_month_and_partial_month_rounding_no_past_catchup(self):
        percentages={m:Decimal(100)/12 for m in range(1,13)}
        rows=list(daily_budget(1200,percentages,'2026-11-01','2026-11-30'))
        self.assertEqual(sum(v for d,v in rows),100)
        future=list(daily_budget(1200,percentages,'2026-11-11','2026-11-30'))
        self.assertEqual(sum(v for d,v in future),Decimal('66.670'))

    def test_daily_amount_is_constant_until_last_day(self):
        percentages={m:Decimal(100)/12 for m in range(1,13)}
        rows=list(daily_budget(7700,percentages,'2026-12-01','2026-12-31'))
        self.assertEqual(len({v for d,v in rows[:-1]}),1)
        self.assertEqual(sum(v for d,v in rows),Decimal('641.667'))
        partial=list(daily_budget(7700,percentages,'2026-12-10','2026-12-21'))
        self.assertEqual(len({v for d,v in partial}),1)

    def test_small_monthly_amount_never_has_negative_balancing_day(self):
        percentages={m:Decimal(100)/12 for m in range(1,13)}
        rows=list(daily_budget(1,percentages,'2026-12-01','2026-12-31'))
        self.assertTrue(all(v>=0 for d,v in rows))
        self.assertEqual(len({v for d,v in rows[:-1]}),1)

    def test_annual_rounding_preserves_annual_budget(self):
        percentages={m:Decimal(100)/12 for m in range(1,13)}
        self.assertEqual(sum(v for d,v in daily_budget(1,percentages,'2028-01-01','2028-12-31')),1)

    def test_invalid_distribution_rejected(self):
        with self.assertRaises(ValueError):list(daily_budget(1200,{1:50},'2026-01-01','2026-01-31'))

    def test_source_uses_only_submitted_budgets_and_starts_tomorrow(self):
        events,warnings=[],[]
        budget=frappe._dict(name='BUDGET',fiscal_year='2026',monthly_distribution='Monthly',budget_against='Cost Center',
                           cost_center='Leaf',accounts=[frappe._dict(account='Marketing',budget_amount=1200)])
        year=frappe._dict(year_start_date='2026-01-01',year_end_date='2026-12-31')
        distribution=frappe._dict(fiscal_year='2026',percentages=[frappe._dict(month='November',percentage_allocation=100)])
        account=frappe._dict(company='Example',is_group=0,root_type='Expense')
        for doc in [year,distribution,account]:doc.check_permission=lambda *args:None
        docs={'Fiscal Year':year,'Monthly Distribution':distribution,'Account':account}
        def documents(dt,filters):
            self.assertEqual(filters,{'docstatus':1})
            return iter([budget])
        source=SimpleNamespace(start=date(2026,11,10),end=date(2026,11,30),company='Example',events=[],documents=documents,
                               event=lambda day,category,amount,*args,**kwargs:events.append((day,category,amount)),warn=warnings.append)
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_doc',side_effect=lambda dt,name:docs[dt]):
            Budgets(source).collect()
        self.assertEqual(events[0][0],date(2026,11,11))
        self.assertEqual(sum(r[2] for r in events),800)
        self.assertEqual(events[0][1],'budget_expenses')
        source._fixed_expense_accounts={'Marketing':{'Historical closed expense'}};events[:]=[]
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_doc',side_effect=lambda dt,name:docs[dt]):
            Budgets(source).collect()
        self.assertTrue(events, 'Historical closed expenses must not suppress future budgets')
        source._future_fixed_expense_accounts={'Marketing'};events[:]=[]
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_doc',side_effect=lambda dt,name:docs[dt]):
            Budgets(source).collect()
        self.assertFalse(events)
        self.assertTrue(any('Fixed Expense' in w for w in warnings))
