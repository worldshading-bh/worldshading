"""Draft security cheques are guarantees, not forecast cash or payment coverage."""
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch,Mock
import frappe
from worldshading.worldshading.report.cashflow_forecast.sources import Sources
from worldshading.worldshading.report.cashflow_forecast import test_po_invoice_payments as invoice_fixture
from worldshading.worldshading.report.cashflow_forecast import horizon

class SecurityChequeTests(unittest.TestCase):
    def payment(self,flag=1,status=0,day='2026-12-01'):
        return frappe._dict(name='PE-SECURITY',company='Example',docstatus=status,payment_type='Pay',
            party_type='Supplier',party='Supplier',posting_date=day,base_paid_amount=100,
            workflow_state='Scheduled',is_security_cheque=flag,references=[])

    def collect(self,payment):
        source=Sources.__new__(Sources);source.company='Example';source.accounts=['Bank']
        source.start=date(2026,11,17);source.end=date(2027,12,31);source.include_overdue=True
        source.events=[];source.overdue=[];source.warnings=[];source.handled_pe=set();source.handled_glp=set()
        source.pending_documents=lambda dt:iter([payment] if dt=='Payment Entry' else [])
        source.journals=lambda:SimpleNamespace(emit=lambda:None)
        source.other_payments();return source

    def test_draft_security_cheque_without_reference_is_not_cash_or_overdue(self):
        for day in ['2026-10-01','2026-12-01']:
            source=self.collect(self.payment(day=day))
            self.assertEqual(source.events,[]);self.assertEqual(source.overdue,[])

    def test_missing_field_and_unchecked_flag_keep_regular_payments(self):
        for payment in [self.payment(flag=0),self.payment(flag=None)]:
            self.assertEqual(sum(row['amount'] for row in self.collect(payment).events),100)

    def test_submitted_cash_entry_is_not_hidden_by_a_security_flag(self):
        self.assertEqual(sum(row['amount'] for row in self.collect(self.payment(status=1)).events),100)

    def test_security_reference_cannot_replace_a_real_invoice_obligation(self):
        fixture=invoice_fixture.PoInvoicePayments();payment=fixture.payment(amount=500);payment.is_security_cheque=1
        source=fixture.collect([fixture.invoice()],[payment])
        self.assertEqual(source.events,[])
        self.assertEqual(sum(row['amount'] for row in source.overdue),500)

    def test_security_cheque_does_not_extend_forecast_horizon(self):
        source=SimpleNamespace(events=[],invoice_purchase_orders={},supplier_invoices=lambda:None,purchase_orders=lambda:None)
        payment=self.payment(day='2031-01-01');payment.references=[frappe._dict(reference_doctype='Purchase Order',reference_name='PO',allocated_amount=100)]
        source.pending_documents=lambda dt:iter([payment]);source.journals=lambda:SimpleNamespace(load=lambda:None,entries=[])
        with patch('worldshading.worldshading.report.cashflow_forecast.sources.Sources',return_value=source),patch.object(frappe,'has_permission',return_value=True):
            self.assertIsNone(horizon.minimum_purchase_end('Example',['Bank'],'2026-11-17'))

    def test_direct_po_schedule_link_uses_flag_only_when_field_exists(self):
        for field_exists in [False,True]:
            fixture=invoice_fixture.PoInvoicePayments();source=fixture.collect([],[])
            source._supplier_horizon_only=True
            po=frappe._dict(name='PO',supplier='Supplier',docstatus=1,workflow_state='Pending Payment',
                base_grand_total=100,advance_paid=0,conversion_rate=1,currency='BHD',taxes=[],
                payment_schedule=[frappe._dict(due_date='2026-10-01',payment_amount=100,payment_entry='PE-SECURITY')])
            source.documents=lambda dt,filters=None:iter([po] if dt=='Purchase Order' else [])
            pe=frappe._dict(company='Example',docstatus=0,posting_date='2027-01-01')
            if field_exists:pe.is_security_cheque=1
            get_value=Mock(return_value=pe)
            with patch.object(frappe,'get_meta',return_value=SimpleNamespace(has_field=lambda name:field_exists)), \
                 patch.object(frappe,'db',SimpleNamespace(get_value=get_value)):
                source.purchase_orders()
            fields=get_value.call_args[0][2]
            self.assertEqual('is_security_cheque' in fields,field_exists)
            if field_exists:
                self.assertEqual(source.events,[])
                self.assertEqual(source.overdue[0]['date'],date(2026,10,1))
            else:self.assertEqual(source.events[0]['date'],date(2027,1,1))
