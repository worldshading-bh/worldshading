"""Read-only source adapter fixtures; no site initialization or business data."""
import unittest
from collections import defaultdict
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import frappe
from worldshading.worldshading.report.cashflow_forecast.sources import Sources


class PoInvoicePayments(unittest.TestCase):
    def invoice(self, name='PI', outstanding=500, total=1000):
        pi=frappe._dict(name=name,supplier='Supplier',base_grand_total=total,base_net_total=total,
            outstanding_amount=outstanding,conversion_rate=1,party_account_currency='BHD',currency='BHD',
            posting_date=date(2026,5,1),due_date=date(2026,8,1),status='Overdue')
        pi.check_permission=lambda *args:None
        pi.payment_schedule=[frappe._dict(due_date=date(2026,5,1),payment_amount=total/2,payment_term='First'),
                             frappe._dict(due_date=date(2026,8,1),payment_amount=total/2,payment_term='Second')]
        return pi

    def payment(self,name='PE',amount=500,doctype='Purchase Order',reference='PO',supplier='Supplier',term=None):
        return frappe._dict(name=name,company='Example',party_type='Supplier',party=supplier,docstatus=0,
            payment_type='Pay',posting_date=date(2026,12,24),workflow_state='Scheduled',
            base_paid_amount=amount,target_exchange_rate=1,
            references=[frappe._dict(reference_doctype=doctype,reference_name=reference,
                                    allocated_amount=amount,payment_term=term)])

    def collect(self,invoices,payments,links=None):
        s=Sources.__new__(Sources)
        s.company,s.currency='Example','BHD'
        s.start,s.end=date(2026,11,15),date(2027,2,15)
        s.events,s.overdue,s.warnings=[],[],[]
        s.include_overdue=False
        s.invoiced,s.import_credited,s.applied_advances=[defaultdict(Decimal) for _ in range(3)]
        s.handled_pe,s.handled_glp=set(),set()
        s.names=lambda *args:[]
        s.journals=lambda:SimpleNamespace(reserve=lambda *args:Decimal(0),emit=lambda:None)
        s.documents=lambda dt,filters=None:iter([pe for pe in payments if not filters or pe.docstatus==filters.get('docstatus',pe.docstatus)])
        links=links if links is not None else [frappe._dict(parent=pi.name,purchase_order='PO',amount=pi.base_net_total) for pi in invoices]
        def sql(query,*args,**kwargs):
            if 'select i.parent,i.purchase_order' in query:return links
            if 'select r.parent,r.reference_name' in query:
                return [frappe._dict(parent=pe.name,reference_name=r.reference_name,allocated_amount=r.allocated_amount,
                                     payment_term=r.get('payment_term')) for pe in payments if pe.docstatus==1
                        for r in pe.references if r.reference_doctype=='Purchase Order']
            return []
        with patch.object(frappe,'has_permission',return_value=True), \
             patch.object(frappe,'get_list',side_effect=lambda dt,**kwargs: invoices if dt=='Purchase Invoice' else [pe for pe in payments if pe.docstatus==1]), \
             patch.object(frappe,'get_doc',side_effect=lambda dt,name:next(pi for pi in invoices if pi.name==name)), \
             patch.object(frappe,'db',SimpleNamespace(sql=sql)):
            s.supplier_invoices()
        return s

    def test_po_scheduled_payment_replaces_invoice_due_date_and_is_not_added_again(self):
        pe=self.payment()
        s=self.collect([self.invoice()],[pe])
        self.assertEqual(s.overdue,[])
        self.assertEqual([(e['name'],e['date'],e['amount']) for e in s.events],[('PE',date(2026,12,24),500)])
        refs=s.events[0].get('related_documents',[])
        self.assertIn(dict(doctype='Purchase Order',name='PO'),refs)
        self.assertEqual(s.events[0]['related_name'],'PI')
        s.pending_documents=lambda dt:iter([pe] if dt=='Payment Entry' else [])
        s.other_payments()
        self.assertEqual(sum(e['amount'] for e in s.events),500)
        self.assertEqual(s.pending_reference_payments('Purchase Order','PO'),[])

    def test_same_po_payment_cannot_replace_two_invoice_balances_twice(self):
        s=self.collect([self.invoice('PI-1',300),self.invoice('PI-2',300)],[self.payment()])
        self.assertEqual(sum(e['amount'] for e in s.events),500)
        self.assertEqual(sum(e['amount'] for e in s.overdue),100)

    def test_direct_invoice_reference_precedes_po_fallback(self):
        s=self.collect([self.invoice()],[self.payment('PE-PO',500),
            self.payment('PE-PI',200,'Purchase Invoice','PI')])
        self.assertEqual([(e['name'],e['amount']) for e in s.events],[('PE-PI',200),('PE-PO',300)])
        self.assertEqual(s.overdue,[])
        self.assertEqual(s.pending_reference_payments('Purchase Order','PO')[0][1],200)

    def test_partial_po_payment_preserves_uncovered_invoice_overdue(self):
        s=self.collect([self.invoice()],[self.payment(amount=200)])
        self.assertEqual(sum(e['amount'] for e in s.events),200)
        self.assertEqual(sum(e['amount'] for e in s.overdue),300)

    def test_wrong_supplier_and_draft_do_not_reschedule_invoice(self):
        draft=self.payment('PE-DRAFT');draft.workflow_state='Draft'
        s=self.collect([self.invoice()],[self.payment(supplier='Another Supplier'),draft])
        self.assertEqual(s.events,[])
        self.assertEqual(sum(e['amount'] for e in s.overdue),500)

    def test_po_reference_term_preserves_earlier_invoice_overdue(self):
        s=self.collect([self.invoice(outstanding=1000)],[self.payment(term='Second')])
        self.assertEqual([(e['name'],e['amount']) for e in s.events],[('PE',500)])
        self.assertEqual([(e['date'],e['amount']) for e in s.overdue],[(date(2026,5,1),500)])

    def test_multiple_po_invoice_requires_explicit_invoice_reference(self):
        pi=self.invoice()
        links=[frappe._dict(parent='PI',purchase_order=po,amount=500) for po in ('PO','PO-2')]
        s=self.collect([pi],[self.payment()],links)
        self.assertEqual(s.events,[])
        self.assertEqual(sum(e['amount'] for e in s.overdue),500)
        self.assertTrue(any('multiple POs' in w for w in s.warnings))

    def test_invoice_and_unbilled_po_share_remaining_payment_budget(self):
        s=self.collect([self.invoice(total=600,outstanding=300)],[self.payment()])
        po=frappe._dict(name='PO',supplier='Supplier',docstatus=1,workflow_state='Pending Payment',
            base_grand_total=1000,advance_paid=0,conversion_rate=1,currency='BHD',
            eta_date=date(2026,12,1),taxes=[],payment_schedule=[frappe._dict(
                due_date=date(2026,12,1),payment_amount=1000)],supplier_country='Bahrain')
        s._supplier_horizon_only=True
        s.documents=lambda *args:iter([po])
        s.purchase_orders()
        self.assertEqual(sum(e['amount'] for e in s.events if e['doctype']=='Payment Entry'),500)
        self.assertEqual(sum(e['amount'] for e in s.events if e['doctype']=='Purchase Order'),200)
        self.assertEqual(sum(e['amount'] for e in s.events),700)
        self.assertEqual(s.pending_reference_payments('Purchase Order','PO'),[])

    def test_shared_payment_keeps_each_reference_terms_remaining_budget(self):
        first=self.invoice('PI-1',300,total=300)
        first.payment_schedule=[frappe._dict(due_date=date(2026,5,1),payment_amount=300,payment_term='First')]
        second=self.invoice('PI-2',1000)
        pe=self.payment(amount=800)
        pe.references=[frappe._dict(reference_doctype='Purchase Order',reference_name='PO',allocated_amount=amount,
                                   payment_term=term) for term,amount in [('First',300),('Second',500)]]
        s=self.collect([first,second],[pe])
        self.assertEqual(sum(e['amount'] for e in s.events),800)
        self.assertEqual([(e['name'],e['date'],e['amount']) for e in s.overdue],
                         [('PI-2',date(2026,5,1),500)])

    def test_foreign_currency_reference_is_capped_in_company_currency(self):
        pi=self.invoice(total=400,outstanding=200)
        pi.currency='USD';pi.conversion_rate=0.4
        for row in pi.payment_schedule:row.payment_amount=500
        pe=self.payment(amount=200)
        pe.target_exchange_rate=0.4;pe.references[0].allocated_amount=500
        s=self.collect([pi],[pe])
        self.assertEqual(s.overdue,[])
        self.assertEqual(sum(e['amount'] for e in s.events),200)

    def completed(self, amount=500, reference='PO', doctype='Purchase Order'):
        pe=self.payment('PE-PAID',amount,doctype,reference)
        pe.docstatus=1;pe.workflow_state='Completed';pe.posting_date=date(2026,5,1)
        return pe

    def test_completed_po_advance_and_scheduled_balance_leave_no_overdue(self):
        s=self.collect([self.invoice(outstanding=1000)],[self.completed(),self.payment()])
        self.assertEqual(s.overdue,[])
        self.assertEqual([(e['name'],e['date'],e['amount']) for e in s.events],[('PE',date(2026,12,24),500)])
        self.assertEqual(s.applied_advances['PO'],500)

    def test_reconciled_advance_is_not_deducted_from_invoice_twice(self):
        s=self.collect([self.invoice(outstanding=500)],[self.completed(reference='PI',doctype='Purchase Invoice'),self.payment()])
        self.assertEqual(s.overdue,[])
        self.assertEqual(sum(e['amount'] for e in s.events),500)

    def test_partly_reconciled_advance_uses_only_remaining_po_reference(self):
        paid=self.completed()
        paid.references=[frappe._dict(reference_doctype=dt,reference_name=name,allocated_amount=amount)
                         for dt,name,amount in [('Purchase Invoice','PI',300),('Purchase Order','PO',200)]]
        s=self.collect([self.invoice(outstanding=700)],[paid,self.payment()])
        self.assertEqual(s.overdue,[])
        self.assertEqual(sum(e['amount'] for e in s.events),500)
        self.assertEqual(s.applied_advances['PO'],200)

    def test_fully_paid_po_advance_creates_no_future_cash_payment(self):
        s=self.collect([self.invoice(outstanding=1000)],[self.completed(amount=1000)])
        self.assertEqual(s.events,[])
        self.assertEqual(s.overdue,[])

    def test_completed_advance_is_shared_once_across_invoices(self):
        s=self.collect([self.invoice('PI-1',400,400),self.invoice('PI-2',400,400)],[self.completed()])
        self.assertEqual(s.events,[])
        self.assertEqual(sum(e['amount'] for e in s.overdue),300)
        self.assertEqual(s.applied_advances['PO'],500)

    def test_posted_future_cancelled_and_other_supplier_are_not_paid_offsets(self):
        for change in ({'posting_date':date(2026,12,1)},{'docstatus':2},{'party':'Another Supplier'}):
            paid=self.completed()
            paid.update(change)
            s=self.collect([self.invoice(outstanding=1000)],[paid,self.payment()])
            self.assertEqual(sum(e['amount'] for e in s.overdue),500)
            self.assertEqual(sum(e['amount'] for e in s.events),500)

    def test_paid_advance_does_not_also_erase_unbilled_po_balance(self):
        s=self.collect([self.invoice(total=600,outstanding=600)],[self.completed()])
        po=frappe._dict(name='PO',supplier='Supplier',docstatus=1,workflow_state='Pending Payment',
            base_grand_total=1000,advance_paid=500,conversion_rate=1,currency='BHD',
            eta_date=date(2026,12,1),taxes=[],payment_schedule=[frappe._dict(
                due_date=date(2026,12,1),payment_amount=1000)],supplier_country='Bahrain')
        s._supplier_horizon_only=True;s.documents=lambda *args:iter([po])
        s.purchase_orders()
        self.assertEqual(sum(e['amount'] for e in s.overdue),100)
        self.assertEqual(sum(e['amount'] for e in s.events),400)

    def test_paid_later_term_does_not_hide_earlier_overdue_term(self):
        pe=self.completed();pe.references[0].payment_term='Second'
        s=self.collect([self.invoice(outstanding=1000)],[pe])
        self.assertEqual([(e['date'],e['amount']) for e in s.overdue],[(date(2026,5,1),500)])
        self.assertEqual(s.events,[])
