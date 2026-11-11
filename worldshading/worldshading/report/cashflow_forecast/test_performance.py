"""Query-shape and permission fixtures; no site initialization or business DB."""
import unittest
from datetime import date
from decimal import Decimal
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import patch, Mock
import frappe
from worldshading.worldshading.report.cashflow_forecast.sources import Sources


class PerformanceTests(unittest.TestCase):
    def source(self):
        s=Sources.__new__(Sources)
        s.company,s.currency='Example','BHD'
        s.start,s.end=date(2026,11,10),date(2026,11,11)
        s.warnings,s.accounts_breakdown=[],[]
        s.historical,s.sales_tax={},{}
        s.invoiced,s.applied_advances=defaultdict(Decimal),defaultdict(Decimal)
        return s

    def test_opening_balances_use_one_query_and_preserve_zero_negative_and_order(self):
        s=self.source();s.accounts=['Zero','Bank','Overdraft']
        sql=Mock(return_value=[frappe._dict(account='Bank',balance='123.4567'),frappe._dict(account='Overdraft',balance=-10)])
        with patch.object(frappe,'db',SimpleNamespace(sql=sql)):
            s.opening()
        self.assertEqual(sql.call_count,1)
        self.assertEqual(s.opening_balance,Decimal('113.457'))
        self.assertEqual([r['account'] for r in s.accounts_breakdown],s.accounts)
        self.assertEqual(s.accounts_breakdown[0]['amount'],0)
        self.assertEqual(sql.call_args[0][1],tuple(v for a in s.accounts for v in ('Example',a,s.start)))
        self.assertEqual(sql.call_args[0][0].count('union all'),2)

    def test_document_cache_is_per_execution_and_rechecks_permission(self):
        s=self.source();doc=SimpleNamespace(check_permission=Mock())
        with patch.object(frappe,'get_doc',return_value=doc) as loader:
            self.assertIs(s.read_document('Payment Entry','PE'),s.read_document('Payment Entry','PE'))
            self.assertEqual(loader.call_count,1)
            self.assertEqual(doc.check_permission.call_count,2)
            self.source().read_document('Payment Entry','PE')
            self.assertEqual(loader.call_count,2)

    def test_bounded_sales_keep_actual_today_and_permission_filtered_tax(self):
        s=self.source()
        prior=frappe._dict(name='VISIBLE',posting_date=date(2025,11,11),base_grand_total=150)
        today=frappe._dict(name='TODAY',posting_date=s.start,base_grand_total=20)
        sql=Mock(return_value=[frappe._dict(parent='VISIBLE',amount=15),frappe._dict(parent='HIDDEN',amount=99)])
        with patch.object(frappe,'has_permission',return_value=True), \
             patch.object(frappe,'get_list',side_effect=[[prior],[today],[frappe._dict(posting_date='2025-01-01')]]) as listings, \
             patch.object(frappe,'db',SimpleNamespace(sql=sql)):
            s.historical_sales()
        self.assertEqual(s.actual_sales_today,20)
        self.assertEqual(s.historical,{'2026-11-10':0,'2026-11-11':150})
        self.assertEqual(s.sales_tax['2026-11-11'],15)
        self.assertFalse(s.warnings)
        queries=listings.call_args_list
        self.assertEqual(queries[0][1]['filters']['posting_date'],['between',[date(2025,11,10),date(2025,11,11)]])
        self.assertEqual(queries[1][1]['filters']['posting_date'],s.start)
        self.assertEqual(queries[2][1]['limit_page_length'],1)

    def test_completed_po_header_screen_matches_existing_skip_condition(self):
        s=self.source()
        r=frappe._dict(name='PO',base_grand_total=1000,advance_paid=0,currency='BHD',conversion_rate=1,
                      workflow_state='Completed',eta_date=date(2026,10,1))
        s.invoiced['PO']=1000
        self.assertFalse(s.purchase_order_relevant(r,0))
        r.eta_date=s.start
        self.assertTrue(s.purchase_order_relevant(r,0))
        r.eta_date=None;s.invoiced['PO']=900
        self.assertTrue(s.purchase_order_relevant(r,0))
        s.invoiced['PO']=1000;r.workflow_state='On Hold'
        self.assertTrue(s.purchase_order_relevant(r,0))

    def test_po_header_import_screen_rounds_individual_tax_rows(self):
        s=self.source();s.invoiced['PO']=Decimal('.999')
        record=frappe._dict(name='PO',base_grand_total=1,advance_paid=0,currency='BHD',conversion_rate=1,
                           workflow_state='Completed',eta_date=None)
        db=SimpleNamespace(exists=lambda *args:True,sql=Mock(return_value=[
            frappe._dict(parent='PO',amount=Decimal('.0004')),frappe._dict(parent='PO',amount=Decimal('.0004'))]))
        with patch.object(frappe,'db',db),patch.object(frappe,'has_permission',return_value=True), \
             patch.object(frappe,'get_list',return_value=[record]):
            self.assertEqual(s.names('Purchase Order',{'docstatus':1}),['PO'])
