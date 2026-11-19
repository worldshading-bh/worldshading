import copy
import unittest
from unittest.mock import patch, Mock
import frappe
from worldshading.api import bank_loan_payments as api


class Row(frappe._dict):
    def set(self,key,value):self[key]=value
    def as_dict(self):return dict(self)


class TestPaymentAPI(unittest.TestCase):
    def setUp(self):
        self.source=Row(name='LOAN-1',workflow_state='Approved',status='Active',company='WS',currency='BHD')
        self.source.precision=lambda field:3
        self.terms=dict(company='WS',currency='BHD',opening_principal=1000,tracking_start_date='2026-01-01',
            schedule=[dict(name='row-1',due_date='2026-12-19',principal_amount=100,interest_amount=10,charges_amount=0)])
        self.mapping=dict(company='WS',currency='BHD',loan_account='Loan',interest_account='Interest',charges_account='Fees',payment_account='Bank')
        for name,value in [('throw',Mock(side_effect=ValueError)),('session',Row(user='maker@example.com')),
                           ('get_roles',Mock(return_value=['Maker - ACC (Workflow)']))]:
            p=patch.object(frappe,name,value,create=True);p.start();self.addCleanup(p.stop)
        p=patch.object(api,'nowdate',return_value='2026-12-19');p.start();self.addCleanup(p.stop)
        for name,value in [('_source',self.source),('approved_terms',self.terms),('_mapping',self.mapping),('payment_documents',[]),('_payment_record',None)]:
            p=patch.object(api,name,return_value=value);p.start();self.addCleanup(p.stop)

    def document(self,old=None):
        d=Row(name='JV-new',docstatus=0,company='WS',transaction_type='Other Expenses',posting_date='2026-12-19',
              custom_bank_loan='LOAN-1',payment_bank='Bank',request_id='a'*32,
              allocations=[Row(installment='row-1',principal_amount=100,interest_amount=10,charges_amount=0,booked_interest=0,booked_charges=0)],
              accounts=[Row(account='Loan',debit=100,credit=0),Row(account='Interest',debit=10,credit=0),Row(account='Bank',debit=0,credit=110)])
        d.get_doc_before_save=lambda:old
        return d

    def test_valid_new_payment_uses_server_snapshot(self):
        d=self.document();d.snapshot='forged'
        api._validate_payment(d)
        self.assertIn('Loan',d.snapshot)
        self.assertEqual(d.allocations[0].currency,'BHD')

    def test_unchanged_amounts_on_another_payment_date_need_no_reason(self):
        d=self.document();d.posting_date='2026-11-19'
        api._validate_payment(d)
        self.assertFalse(d.get('reason'))

    def test_partial_and_additional_charges_require_reason(self):
        d=self.document();d.allocations[0].principal_amount=40
        d.accounts[0].debit=40;d.accounts[2].credit=50
        with self.assertRaises(ValueError):api._validate_payment(d)
        d.reason='Agreed partial payment';api._validate_payment(d)
        d.allocations[0].charges_amount=5;d.accounts.append(Row(account='Fees',debit=5,credit=0));d.accounts[2].credit=55
        api._validate_payment(d)

    def test_pending_duplicate_is_blocked_but_completed_partial_is_allowed(self):
        d=self.document()
        prior=dict(name='JV-existing',docstatus=0,request_id='b'*32,before_tracking=False,
            allocations=[dict(installment='row-1',principal_amount=40,interest_amount=0,charges_amount=0)])
        with patch.object(api,'payment_documents',return_value=[prior]):
            with self.assertRaises(ValueError):api._validate_payment(d)
        prior['docstatus']=1;d.allocations[0].principal_amount=60;d.accounts[0].debit=60;d.accounts[2].credit=70
        with patch.object(api,'payment_documents',return_value=[prior]):api._validate_payment(d)

    def test_new_link_needs_approved_master_and_existing_posted_link_is_immutable(self):
        self.source.workflow_state='Draft'
        with self.assertRaises(ValueError):api._validate_payment(self.document())
        self.source.workflow_state='Approved'
        old=self.document();old.docstatus=1;old.snapshot='snapshot'
        current=self.document(old);current.docstatus=1;current.snapshot='snapshot'
        api._validate_payment(current)
        current.allocations[0].principal_amount=90
        with self.assertRaises(ValueError):api._validate_payment(current)

    def test_submitted_allocation_date_and_currency_cannot_be_relabelled(self):
        from datetime import date
        old=self.document();old.docstatus=1;old.snapshot='snapshot'
        old.allocations[0].installment_date=date(2026,12,19)
        old.allocations[0].currency='BHD'
        d=self.document(old);d.docstatus=1;d.snapshot='snapshot'
        d.allocations[0].installment_date='2026-12-19';d.allocations[0].currency='BHD'
        api._validate_payment(d)
        d.allocations[0].currency='USD'
        with self.assertRaises(ValueError):api._validate_payment(d)
        d.allocations[0].currency='BHD';d.allocations[0].installment_date='2027-01-19'
        with self.assertRaises(ValueError):api._validate_payment(d)

    def test_linking_older_submitted_jv_keeps_its_original_transaction_type(self):
        old=self.document();old.custom_bank_loan=None;old.docstatus=1
        d=self.document(old);d.docstatus=1;d.transaction_type=None
        d.reason='Reviewed existing bank repayment'
        api._validate_payment(d)
        self.assertIsNone(d.transaction_type)
        d.before_tracking=1;d.posting_date='2025-12-19';d.allocations[0].installment=None
        api._validate_payment(d)

    def test_future_payment_can_be_prepared_but_not_counted_as_posted_today(self):
        old=self.document();old.custom_bank_loan=None;old.docstatus=1
        d=self.document(old);d.docstatus=1;d.reason='Historical link'
        with patch.object(api,'nowdate',return_value='2026-11-19'):
            with self.assertRaises(ValueError):api._validate_payment(d)

    def test_cancelled_historical_payment_can_be_amended_with_fresh_reference(self):
        d=self.document();d.before_tracking=1;d.posting_date='2025-12-19'
        d.allocations[0].installment=None;d.amended_from='JV-old'
        d.reason='Native amendment of historical bank payment'
        db=Mock();db.get_value.return_value=Row(docstatus=2,custom_bank_loan='LOAN-1',before_tracking=1)
        with patch.object(frappe,'db',db,create=True), patch.object(api,'_payment_record',return_value={'before_tracking':1}):api._validate_payment(d)

    def test_cancel_cannot_rewrite_linked_allocations_and_posted_history_is_retained(self):
        old=self.document();old.docstatus=1;old.snapshot='snapshot'
        d=self.document(old);d.docstatus=2;d.snapshot='snapshot'
        api._validate_payment(d)
        d.allocations[0].principal_amount=90
        with self.assertRaises(ValueError):api._validate_payment(d)
        with self.assertRaises(ValueError):api.protect_journal_delete(d)
        d.docstatus=0;api.protect_journal_delete(d)

    def test_before_tracking_never_accepts_new_or_current_period_payment(self):
        d=self.document();d.before_tracking=1
        with self.assertRaises(ValueError):api._validate_payment(d)


if __name__=='__main__':unittest.main()
