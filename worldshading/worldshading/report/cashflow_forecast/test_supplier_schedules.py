import unittest
from datetime import date
from worldshading.worldshading.report.cashflow_forecast.rules import invoice_installments, reserve_installment


class SupplierSchedules(unittest.TestCase):
    def schedule(self):
        return [dict(date=date(2026,10,1),amount=500,payment_term='First'),
                dict(date=date(2026,12,1),amount=500,payment_term='Second',payment_entry='PE-LATER')]

    def test_paid_later_term_does_not_hide_overdue_earlier_term(self):
        schedule=self.schedule()
        schedule[1]['paid_amount']=500
        rows,gap=invoice_installments(schedule,1000,500)
        self.assertEqual([(r['payment_term'],r['amount']) for r in rows],[('First',500)])
        self.assertEqual(gap,0)

    def test_stale_term_paid_amount_cannot_erase_invoice_outstanding(self):
        schedule=self.schedule()
        schedule[1]['paid_amount']=500
        rows,gap=invoice_installments(schedule,1000,1000)
        self.assertEqual(sum(r['amount'] for r in rows),1000)

    def test_pending_later_term_or_custom_link_preserves_overdue_first(self):
        for kwargs in [dict(payment_term='Second'),dict(payment_name='PE-LATER')]:
            rows,used,ambiguous=reserve_installment(self.schedule(),500,**kwargs)
            self.assertEqual([(r['payment_term'],r['amount']) for r in rows],[('First',500)])
            self.assertEqual(used,500)
            self.assertFalse(ambiguous)

    def test_unknown_term_requires_review_instead_of_guessing(self):
        rows,used,ambiguous=reserve_installment(self.schedule(),500,payment_term='Missing')
        self.assertTrue(ambiguous)
        self.assertEqual(used,0)

    def test_shared_payment_link_still_honors_explicit_later_term(self):
        schedule=self.schedule()
        schedule[0]['payment_entry']='PE-LATER'
        rows,used,ambiguous=reserve_installment(schedule,500,payment_name='PE-LATER',payment_term='Second')
        self.assertEqual([(r['payment_term'],r['amount']) for r in rows],[('First',500)])
        self.assertEqual(used,500)
        self.assertFalse(ambiguous)

    def test_conflicting_payment_link_and_term_are_flagged(self):
        rows,used,ambiguous=reserve_installment(self.schedule(),500,payment_name='PE-LATER',payment_term='First')
        self.assertTrue(ambiguous)
        self.assertEqual(used,0)

    def test_schedule_already_reduced_to_residual_is_not_paid_twice(self):
        rows,gap=invoice_installments([dict(date=date(2026,10,1),amount=500)],1000,500)
        self.assertEqual(sum(r['amount'] for r in rows),500)
        self.assertEqual(gap,0)

    def test_short_schedule_reports_unscheduled_debt(self):
        rows,gap=invoice_installments(self.schedule()[:1],1000,1000)
        self.assertEqual(gap,500)

    def test_aggregate_paid_fifo_and_outstanding_cap(self):
        rows,gap=invoice_installments(self.schedule(),1000,300)
        self.assertEqual([(r['payment_term'],r['amount']) for r in rows],[('Second',300)])
        self.assertEqual(gap,0)


class SupplierSourceFixtures(unittest.TestCase):
    def test_invoice_later_prepared_payment_preserves_earlier_overdue(self):
        import frappe
        from collections import defaultdict
        from decimal import Decimal
        from types import SimpleNamespace
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast.sources import Sources
        source=Sources.__new__(Sources)
        source.company,source.currency='Example','BHD'
        source.start,source.end=date(2026,11,10),date(2026,12,31)
        source.events,source.overdue,source.warnings=[],[],[]
        source.include_overdue=False
        source.invoiced,source.import_credited,source.applied_advances=[defaultdict(Decimal) for _ in range(3)]
        source.handled_pe=set()
        source.names=lambda *args: []
        source.journals=lambda: SimpleNamespace(reserve=lambda *args: Decimal(0))
        pi=frappe._dict(name='PI-TEST',supplier='Supplier',base_grand_total=1000,base_net_total=1000,
                       outstanding_amount=1000,conversion_rate=1,party_account_currency='BHD',currency='BHD',
                       due_date=date(2026,12,1),status='Unpaid')
        pi.check_permission=lambda *args: None
        pi.payment_schedule=[frappe._dict(due_date=r['date'],payment_amount=r['amount'],payment_term=r['payment_term'],payment_entry=r.get('payment_entry')) for r in SupplierSchedules().schedule()]
        pe=frappe._dict(name='PE-LATER',posting_date=date(2026,12,2),workflow_state='Scheduled',
                       base_paid_amount=500,target_exchange_rate=1,
                       references=[frappe._dict(reference_doctype='Purchase Invoice',reference_name='PI-TEST',
                                               allocated_amount=500,payment_term='Second')])
        source.documents=lambda *args: iter([pe])
        with patch.object(frappe,'has_permission',return_value=True), \
             patch.object(frappe,'get_list',return_value=[pi]), \
             patch.object(frappe,'get_doc',return_value=pi), \
             patch.object(frappe,'db',SimpleNamespace(sql=lambda *args,**kwargs: [])):
            source.supplier_invoices()
        self.assertEqual([(r['name'],r['amount']) for r in source.overdue],[('PI-TEST',500)])
        self.assertEqual([(r['name'],r['date'],r['amount']) for r in source.events],
                         [('PE-LATER',date(2026,12,2),500)])
        self.assertEqual(sum(r['amount'] for r in source.events+source.overdue),1000)

    def test_pending_reference_budget_is_shared_across_pi_and_po(self):
        import frappe
        from worldshading.worldshading.report.cashflow_forecast.sources import Sources
        source=Sources.__new__(Sources)
        source.warnings=[]
        pe=frappe._dict(name='PE-CAP',posting_date=date(2026,12,2),workflow_state='Scheduled',
                       base_paid_amount=500,target_exchange_rate=1,
                       references=[frappe._dict(reference_doctype=dt,reference_name=name,allocated_amount=400)
                                   for dt,name in [('Purchase Invoice','PI'),('Purchase Order','PO')]])
        source.documents=lambda *args: iter([pe])
        self.assertEqual(source.pending_reference_payments('Purchase Invoice','PI')[0][1],400)
        self.assertEqual(source.pending_reference_payments('Purchase Order','PO')[0][1],100)
        self.assertTrue(any('capped' in w for w in source.warnings))
