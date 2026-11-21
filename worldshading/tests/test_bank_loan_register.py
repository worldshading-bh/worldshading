"""Controller checks with database boundaries replaced; no site or test runner."""
import unittest
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import patch, Mock
import frappe
from worldshading.worldshading.doctype.bank_loan.bank_loan import BankLoan, agreement_identity
from worldshading.api.bank_loan_workflow import validate_loan_workflow, workflow_definition


def doc(state='Draft', amount=600):
    item = frappe._dict(workflow_state=state, loan_name='Vehicle', opening_principal=amount)
    item.meta = SimpleNamespace(fields=[frappe._dict(fieldname='loan_name', fieldtype='Data'),
                                       frappe._dict(fieldname='opening_principal', fieldtype='Currency')])
    return item


class BankLoanRegisterTests(unittest.TestCase):
    def setUp(self):
        for target, value in [('throw', Mock(side_effect=ValueError)),
                              ('session', frappe._dict(user='accounts@example.com')),
                              ('get_roles', Mock(return_value=['Maker - ACC (Workflow)']))]:
            context = patch.object(frappe, target, value, create=True)
            context.start()
            self.addCleanup(context.stop)

    def test_register_imports_without_fixed_expense_upgrade(self):
        from worldshading.api import bank_loan_workflow
        with patch.dict(sys.modules, {'worldshading.api.fixed_expense_workflow': None}):
            importlib.reload(bank_loan_workflow)

    def test_agreement_identity_normalizes_but_is_company_and_lender_specific(self):
        first = agreement_identity('Company A', 'Bank A', ' ab-123 ')
        self.assertEqual(first, agreement_identity('Company A', 'Bank A', 'AB-123'))
        self.assertNotEqual(first, agreement_identity('Company B', 'Bank A', 'AB-123'))
        self.assertNotEqual(first, agreement_identity('Company A', 'Bank B', 'AB-123'))
        with self.assertRaises(ValueError):
            agreement_identity('Company A', 'Bank A', '  ')

    def test_new_loans_cannot_start_approved(self):
        with self.assertRaises(ValueError):
            validate_loan_workflow(doc('Approved'), None)
        validate_loan_workflow(doc(), None)
        blank = doc(None)
        validate_loan_workflow(blank, None)
        self.assertEqual(blank.workflow_state, 'Draft')

    def test_only_maker_can_edit_draft_and_transitions_do_not_allow_detail_changes(self):
        with patch.object(frappe, 'get_roles', return_value=['Accounts User']):
            with self.assertRaises(ValueError):
                validate_loan_workflow(doc(), None)
        for state in ['Pending Loan - Chkr', 'Pending Loan - App', 'Approved', 'Closed']:
            with self.subTest(state=state), self.assertRaises(ValueError):
                validate_loan_workflow(doc('Draft', amount=601), doc(state))
        validate_loan_workflow(doc('Draft'), doc('Approved'))

    def test_workflow_controls_activation_and_has_separate_loan_route(self):
        definition = workflow_definition()
        self.assertEqual(definition['document_type'], 'Bank Loan')
        states = {s['state']: s for s in definition['states']}
        self.assertEqual(states['Approved']['update_value'], 'Active')
        self.assertEqual(states['Draft']['update_value'], 'Inactive')
        self.assertEqual(states['Closed']['update_value'], 'Closed')
        self.assertTrue(all(s['doc_status'] == '0' for s in states.values()))

    def test_controller_persists_authoritative_totals_and_blocks_duplicate_agreement(self):
        row = frappe._dict(due_date='2026-11-30', principal_amount=600,
                           interest_amount='53.6664', charges_amount=0)
        row.set = lambda key, value: row.__setitem__(key, value)
        item = frappe._dict(company='WS', bank='AUB', agreement_number='  ABC-1  ',
            currency='BHD', workflow_state='Draft', original_principal=1000,
            opening_principal=600, annual_interest_rate=6, disbursement_date='2026-01-01',
            tracking_start_date='2026-11-01', maturity_date='2026-12-31', schedule=[row])
        item.get_doc_before_save = lambda: None
        item.validate_accounts = lambda: None  # independently exercised below
        item.as_dict = lambda: item
        item.precision = lambda field: 3
        item.set = lambda key, value: item.__setitem__(key, value)
        db = Mock()
        db.get_value.return_value = None
        with patch.object(frappe, 'db', db, create=True):
            BankLoan.validate(item)
            self.assertEqual(item.agreement_number, 'ABC-1')
            self.assertEqual(item.status, 'Inactive')
            self.assertEqual(item.scheduled_total, 653.666)
            self.assertEqual(row.interest_amount, 53.666)
            self.assertEqual(row.projected_principal_balance, 0)
            self.assertEqual(row.currency, 'BHD')
            db.get_value.return_value = 'BLN-26-00001'
            with self.assertRaises(ValueError):
                BankLoan.validate(item)

    def test_reject_wrong_company_currency_and_account_kind(self):
        loan = frappe._dict(company='WS', currency='BHD', loan_account='Loan',
                            interest_account='Interest', charges_account='Charges',
                            payment_account='Bank', cost_center='Main')
        records = dict(Loan=frappe._dict(company='WS', root_type='Liability', account_currency='BHD'),
                       Interest=frappe._dict(company='WS', root_type='Expense', account_currency='BHD'),
                       Charges=frappe._dict(company='WS', root_type='Expense', account_currency='BHD'),
                       Bank=frappe._dict(company='WS', root_type='Asset', account_type='Bank', account_currency='BHD'),
                       Main=frappe._dict(company='WS', is_group=0))
        database = Mock()
        database.get_value.side_effect = lambda dt, name, *args, **kwargs: records.get(name)
        with patch.object(frappe, 'db', database, create=True):
            BankLoan.validate_accounts(loan)
            for field, value in [('company', 'Other'), ('account_currency', 'USD'),
                                 ('root_type', 'Asset'), ('disabled', 1), ('is_group', 1)]:
                saved = records['Loan'].copy()
                records['Loan'][field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    BankLoan.validate_accounts(loan)
                records['Loan'] = saved
            records['Bank']['account_type'] = 'Cash'
            with self.assertRaises(ValueError):
                BankLoan.validate_accounts(loan)


if __name__ == '__main__':
    unittest.main()
