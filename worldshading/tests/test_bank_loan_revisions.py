import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
import frappe
from worldshading.api.bank_loan_revisions import commercial_snapshot, validate_revision


class Loan(frappe._dict):
    def set(self,key,value):self[key]=value
    def append(self,key,value):self.setdefault(key,[]).append(frappe._dict(value))
    def precision(self,field):return 3


def loan(state='Draft',**kw):
    d=Loan(company='WS',currency='BHD',original_principal=1000,opening_principal=600,
        disbursement_date='2026-01-01',tracking_start_date='2026-11-01',maturity_date='2027-01-01',
        workflow_state=state,schedule=[frappe._dict(name='row-1',due_date='2026-12-01',principal_amount=600,interest_amount=10)],revisions=[])
    d.update(kw);return d


class TestLoanRevisions(unittest.TestCase):
    def setUp(self):
        for name,value in [('throw',Mock(side_effect=ValueError)),('session',frappe._dict(user='approver@example.com'))]:
            p=patch.object(frappe,name,value,create=True);p.start();self.addCleanup(p.stop)
        for name,value in [('nowdate','2026-11-19'),('now','2026-11-19 12:00:00')]:
            p=patch('worldshading.api.bank_loan_revisions.'+name,return_value=value);p.start();self.addCleanup(p.stop)

    def test_initial_approval_creates_immutable_snapshot(self):
        d=loan('Approved');validate_revision(d,loan('Pending Loan - App'),[])
        self.assertEqual(len(d.revisions),1)
        self.assertEqual(json.loads(d.approved_plan)['schedule'][0]['name'],'row-1')
        old=Loan(d)
        d.approved_plan='forged';d.revisions=[]
        validate_revision(d,old,[])
        self.assertEqual(d.approved_plan,old.approved_plan)
        self.assertEqual(len(d.revisions),1)

    def test_revision_requires_reason_date_and_preserves_approved_plan_while_draft(self):
        old=loan('Approved');validate_revision(old,loan('Pending Loan - App'),[])
        d=loan('Draft',maturity_date='2027-03-01')
        with self.assertRaises(ValueError):validate_revision(d,old,[])
        d.revision_reason='Bank agreed two month extension';d.revision_effective_date='2026-12-01'
        validate_revision(d,old,[])
        self.assertEqual(d.approved_plan,old.approved_plan)
        self.assertEqual(len(d.revisions),1)
        d.workflow_state='Approved';validate_revision(d,old,[])
        self.assertEqual(len(d.revisions),2)
        self.assertEqual(json.loads(d.approved_plan)['maturity_date'],'2027-03-01')

    def test_revision_date_is_recorded_when_reason_is_entered(self):
        old=loan('Approved');validate_revision(old,loan('Pending Loan - App'),[])
        d=loan('Draft',maturity_date='2027-03-01',revision_reason='Bank agreed extension')
        validate_revision(d,old,[])
        self.assertEqual(d.revision_effective_date,'2026-11-19')
        prior=Loan(d)
        d.revision_effective_date='2030-01-01'
        with patch('worldshading.api.bank_loan_revisions.nowdate',return_value='2026-11-20'):
            validate_revision(d,prior,[])
        self.assertEqual(d.revision_effective_date,'2026-11-19')

    def test_lender_and_agreement_changes_are_audited_and_frozen_with_history(self):
        old=loan('Approved',bank='Bank A',agreement_number='REF-1')
        validate_revision(old,loan('Pending Loan - App'),[])
        for field,value in [('bank','Bank B'),('agreement_number','REF-2')]:
            d=loan('Draft',bank='Bank A',agreement_number='REF-1')
            d[field]=value
            with self.assertRaises(ValueError):validate_revision(d,old,[])
            d.revision_reason='Correction';d.revision_effective_date='2026-11-19'
            with self.assertRaises(ValueError):validate_revision(d,old,[dict(docstatus=1,allocations=[])])

    def test_payment_history_freezes_identity_and_opening_amount(self):
        d=loan();old=loan();d.opening_principal=700
        with self.assertRaises(ValueError):validate_revision(d,old,[dict(docstatus=2,allocations=[])])


if __name__=='__main__':unittest.main()
