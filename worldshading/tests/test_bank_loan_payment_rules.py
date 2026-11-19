import unittest
from decimal import Decimal
from worldshading.worldshading.doctype.bank_loan.payment_rules import (
    allocation_totals, expected_postings, validate_postings, payment_status, validate_schedule_edit)


def allocation(**kw):
    d=dict(installment='row-1',principal_amount=100,interest_amount=10,charges_amount=2,
           booked_interest=0,booked_charges=0)
    d.update(kw);return d


def payment(status=1, before=False, **kw):
    return dict(name='JV-1',docstatus=status,before_tracking=before,allocations=[allocation(**kw)])


class TestLoanPaymentRules(unittest.TestCase):
    def test_booked_interest_settles_liability_without_second_expense(self):
        mapping=dict(loan_account='Loan',interest_account='Interest',charges_account='Fees',payment_account='Bank')
        totals=allocation_totals([allocation(booked_interest=7,booked_charges=2)],3)
        self.assertEqual(totals['cash'],112)
        postings=expected_postings(mapping,totals)
        self.assertEqual(postings,{'Loan':Decimal('109.000'),'Interest':Decimal('3.000'),'Bank':Decimal('-112.000')})
        rows=[dict(account=k,debit=max(v,0),credit=max(-v,0)) for k,v in postings.items()]
        validate_postings(mapping,totals,rows,3)
        rows[0]['debit']+=1
        with self.assertRaises(ValueError):validate_postings(mapping,totals,rows,3)

    def test_bad_allocations_are_rejected(self):
        for rows in [[],[allocation(principal_amount=-1)],[allocation(interest_amount='NaN')],
                     [allocation(booked_interest=11)],[allocation(booked_charges=3)],
                     [allocation(),allocation()]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):allocation_totals(rows,3)

    def test_only_submitted_non_cancelled_since_tracking_reduces_principal(self):
        rows=[dict(name='row-1',principal_amount=100,interest_amount=10,charges_amount=2)]
        result=payment_status(rows,[payment(),payment(0),payment(2),payment(before=True)],1000,3)
        self.assertEqual(result['principal_paid'],100)
        self.assertEqual(result['interest_paid'],10)
        self.assertEqual(result['total_paid'],112)
        self.assertEqual(result['outstanding_principal'],900)
        self.assertEqual(result['all_linked_cash_paid'],224)
        self.assertEqual(result['installments'][0]['remaining'],0)

    def test_partial_payment_and_variance(self):
        rows=[dict(name='row-1',principal_amount=100,interest_amount=10,charges_amount=0)]
        result=payment_status(rows,[payment(principal_amount=40,interest_amount=10,charges_amount=0)],100,3)
        self.assertEqual(result['installments'][0]['remaining'],60)
        result=payment_status(rows,[payment(principal_amount=100,interest_amount=10,charges_amount=5)],100,3)
        self.assertTrue(result['needs_reschedule'])
        self.assertEqual(result['outstanding_principal'],0)

    def test_existing_variance_does_not_prevent_opening_a_revision(self):
        old=[dict(name='row-1',due_date='2026-12-19',principal_amount=100,interest_amount=10,charges_amount=0)]
        actual=[payment(principal_amount=100,interest_amount=10,charges_amount=5)]
        validate_schedule_edit(old,old,actual,3)
        with self.assertRaises(ValueError):
            validate_schedule_edit(old,old,actual,3,require_reconciled=True)

    def test_revisions_preserve_referenced_rows_and_paid_amounts(self):
        old=[dict(name='row-1',due_date='2026-12-19',principal_amount=100,interest_amount=10,charges_amount=0)]
        paid=[payment(principal_amount=40,interest_amount=10,charges_amount=0)]
        revised=[dict(old[0],principal_amount=40),dict(name='row-2',due_date='2027-02-19',principal_amount=60,interest_amount=1)]
        validate_schedule_edit(old,revised,paid,3)
        for rows in [[],[dict(old[0],principal_amount=30)],[dict(old[0],due_date='2027-01-19')]]:
            with self.assertRaises(ValueError):validate_schedule_edit(old,rows,paid,3)
        with self.assertRaises(ValueError):validate_schedule_edit(old,revised,[payment(0)],3)


if __name__=='__main__':unittest.main()
