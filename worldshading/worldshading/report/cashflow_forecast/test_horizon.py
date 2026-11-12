"""Standalone horizon rules and generation boundary checks; no site initialization."""
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
import frappe
from worldshading.worldshading.report.cashflow_forecast import horizon


class HorizonTests(unittest.TestCase):
    def test_earlier_equal_later_and_no_commitment(self):
        for requested,expected in [('2027-02-01','2027-03-15'),('2027-03-15','2027-03-15'),('2027-04-01','2027-04-01')]:
            self.assertEqual(str(horizon.adjust_end_date(requested,'2026-11-12','2027-03-15')),expected)
        self.assertEqual(str(horizon.adjust_end_date('2027-02-01','2026-11-12',None)),'2027-02-01')
        with self.assertRaises(ValueError):horizon.adjust_end_date('2027-02-01','2026-11-12','2029-01-01')

    def test_only_outstanding_po_related_supplier_dates_set_minimum(self):
        rows=[dict(date='2027-03-15',category='supplier_payments',amount=5,doctype='Purchase Order',name='PO'),
              dict(date='2027-03-20',category='supplier_payments',amount=2,doctype='Purchase Invoice',name='PI-LINKED'),
              dict(date='2028-01-01',category='supplier_payments',amount=2,doctype='Purchase Invoice',name='PI-UNLINKED'),
              dict(date='2028-02-01',category='customs',amount=3,doctype='Purchase Order',name='PO'),
              dict(date='2028-03-01',category='supplier_payments',amount=0,doctype='Purchase Order',name='PO-PAID')]
        self.assertEqual(horizon.latest_supplier_payment(rows,{'PI-LINKED':{'PO'}},'2026-11-12')['date'],date(2027,3,20))
        rows.append(dict(date='2027-04-01',category='supplier_payments',amount=2,doctype='Payment Entry',name='PE',related_doctype='Purchase Invoice',related_name='PI-LINKED'))
        self.assertEqual(horizon.latest_supplier_payment(rows,{'PI-LINKED':{'PO'}},'2026-11-12')['name'],'PE')

    def test_reconciled_po_exclusions_and_tolerance_do_not_set_minimum(self):
        from worldshading.worldshading.report.cashflow_forecast.test_sources import PoObligationFixtureTests
        fixture=PoObligationFixtureTests()
        schedule=[(date(2027,3,15),100)]
        for amount,state in [(0,'Completed'),('0.200','Completed'),(100,'Legal Dispute')]:
            source=fixture.collect(amount,state=state,installments=schedule,horizon=True)
            self.assertIsNone(horizon.latest_supplier_payment(source.events,{},source.start))
        source=fixture.collect(1,installments=schedule,horizon=True)
        self.assertEqual(horizon.latest_supplier_payment(source.events,{},source.start)['date'],date(2027,3,15))
        self.assertFalse([r for r in source.events if r['category']=='customs'])

    def test_source_pass_includes_future_posted_pe_and_skips_unrelated_payments(self):
        source=SimpleNamespace(events=[dict(date='2027-03-15',category='supplier_payments',amount=1,doctype='Purchase Order',name='PO')],
            invoice_purchase_orders={'PI':{'PO'}},supplier_invoices=lambda:None,purchase_orders=lambda:None)
        payments=[frappe._dict(name='PE-FUTURE',docstatus=1,payment_type='Pay',posting_date='2027-04-01',base_paid_amount=5,
            references=[frappe._dict(reference_doctype='Purchase Invoice',reference_name='PI',allocated_amount=5)]),
            frappe._dict(name='PE-DRAFT',docstatus=0,workflow_state='Draft',payment_type='Pay',posting_date='2028-01-01',base_paid_amount=5,
            references=[frappe._dict(reference_doctype='Purchase Order',reference_name='PO',allocated_amount=5)])]
        source.pending_documents=lambda dt:iter(payments)
        source.journals=lambda:SimpleNamespace(load=lambda:None,entries=[])
        with patch('worldshading.worldshading.report.cashflow_forecast.sources.Sources',return_value=source), \
             patch.object(frappe,'has_permission',return_value=True):
            latest=horizon.minimum_purchase_end('Example',['Bank'],'2026-11-12')
        self.assertEqual(latest['date'],date(2027,4,1))
        self.assertEqual(latest['name'],'PE-FUTURE')
        self.assertTrue(source._supplier_horizon_only)

    def test_other_reports_queue_without_purchase_scan(self):
        from worldshading.worldshading.report.cashflow_forecast import prepared_access
        with patch.object(prepared_access,'guard_request',return_value=False), \
             patch.object(prepared_access,'normalize_generation_filters') as scan, \
             patch('frappe.desk.query_report.background_enqueue_run',return_value={'name':'OTHER'}):
            self.assertEqual(prepared_access.background_enqueue_run('Other Report','{}')['name'],'OTHER')
        scan.assert_not_called()

    def test_generation_corrects_only_end_date_and_does_not_mutate_input(self):
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
        values=dict(company='Example',end_date='2027-02-01',support_amount=10)
        with patch.object(report,'authorize'),patch.object(report,'resolve_accounts',return_value=['Bank']), \
             patch.object(report,'nowdate',return_value='2026-11-12'), \
             patch.object(report,'minimum_purchase_end',return_value=dict(date=date(2027,3,15),doctype='Purchase Order',name='PO')):
            normalized,change=report.normalize_generation_filters(values)
        self.assertEqual(values['end_date'],'2027-02-01')
        self.assertEqual(normalized['end_date'],'2027-03-15')
        self.assertEqual(normalized['support_amount'],10)
        self.assertEqual(change['previous_end_date'],'2027-02-01')
        self.assertEqual(change['end_date'],'2027-03-15')

    def test_queue_saves_corrected_filters_and_returns_notice(self):
        from worldshading.worldshading.report.cashflow_forecast import prepared_access
        change=dict(previous_end_date='2027-02-01',end_date='2027-03-15')
        with patch.object(prepared_access,'guard_request',return_value=True), \
             patch.object(prepared_access,'normalize_generation_filters',return_value=({'company':'Example','end_date':'2027-03-15'},change)), \
             patch.object(prepared_access,'get_overdue_commitments',return_value={'items':[]}), \
             patch('frappe.desk.query_report.background_enqueue_run',return_value={'name':'PREPARED'}) as original:
            result=prepared_access.background_enqueue_run('Cashflow Forecast','{}')
        self.assertEqual(frappe.parse_json(original.call_args[0][1])['end_date'],'2027-03-15')
        self.assertEqual(result['end_date_adjustment'],change)
        self.assertEqual(result['name'],'PREPARED')
