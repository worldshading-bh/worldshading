"""Database-free approval and payment boundary checks."""
import unittest
from types import SimpleNamespace
from datetime import date
from unittest.mock import patch, Mock

import frappe
from worldshading.api import fixed_expense_payments as payments
from worldshading.api.fixed_expense_workflow import (
    require_approved_expense, validate_expense_workflow, workflow_definition, set_workflow_status)
from worldshading.worldshading.doctype.fixed_expense.fixed_expense import FixedExpense


def expense(state='Draft', status='Active', amount=100):
    fields = [frappe._dict(fieldname='status', fieldtype='Select', read_only=1),
              frappe._dict(fieldname='accounts', fieldtype='Table')]
    row = frappe._dict(net_amount=amount, account='Rent')
    row.meta = SimpleNamespace(fields=[frappe._dict(fieldname='net_amount', fieldtype='Currency'),
                                      frappe._dict(fieldname='account', fieldtype='Link')])
    doc = frappe._dict(workflow_state=state, status=status, accounts=[row])
    doc.meta = SimpleNamespace(fields=fields)
    return doc


class TestFixedExpenseWorkflow(unittest.TestCase):
    def setUp(self):
        self.throw = patch.object(frappe, 'throw', side_effect=ValueError)
        self.throw.start()
        self.addCleanup(self.throw.stop)
        session = patch.object(frappe, 'session', frappe._dict(user='staff@example.com'), create=True)
        session.start()
        self.addCleanup(session.stop)

    def test_only_approved_active_can_start_payment(self):
        require_approved_expense(expense('Approved'))
        for state, status in [('Draft', 'Active'), ('Pending Expense - Chkr', 'Active'),
                              ('Pending Expense - App', 'Active'), (None, 'Active'),
                              ('Approved', 'Closed')]:
            with self.assertRaises(ValueError):
                require_approved_expense(expense(state, status))

    def test_draft_edit_requires_maker_role(self):
        with patch.object(frappe, 'get_roles', return_value=['Accounts User']):
            with self.assertRaises(ValueError):
                validate_expense_workflow(expense(), expense())
        with patch.object(frappe, 'get_roles', return_value=['Maker - ACC (Workflow)']):
            validate_expense_workflow(expense(amount=125), expense())

    def test_new_record_cannot_start_approved(self):
        with patch.object(frappe, 'get_roles', return_value=['Maker - ACC (Workflow)']):
            with self.assertRaises(ValueError):
                validate_expense_workflow(expense('Approved'))

    def test_locked_fields_even_during_return_or_approval(self):
        for previous, target in [('Pending Expense - Chkr', 'Pending Expense - App'),
                                 ('Pending Expense - App', 'Approved'), ('Approved', 'Draft'),
                                 ('Approved', 'Approved')]:
            old = expense(previous)
            validate_expense_workflow(expense(target), old)
            with self.assertRaises(ValueError):
                validate_expense_workflow(expense(target, amount=125), old)

    def test_workflow_stays_non_submitted_and_has_return_actions(self):
        definition = workflow_definition()
        self.assertEqual({s['doc_status'] for s in definition['states']}, {'0'})
        self.assertEqual([s['state'] for s in definition['states']],
                         ['Draft', 'Pending Expense - Chkr', 'Pending Expense - App', 'Approved', 'Closed'])
        returns = [t['state'] for t in definition['transitions'] if t['next_state'] == 'Draft']
        self.assertEqual(set(returns), {'Pending Expense - Chkr', 'Pending Expense - App', 'Approved'})

    def test_status_is_owned_by_workflow_not_client_input(self):
        expected = {'Draft': 'Inactive', 'Pending Expense - Chkr': 'Inactive',
                    'Pending Expense - App': 'Inactive', 'Approved': 'Active', 'Closed': 'Closed'}
        for state, status in expected.items():
            doc = expense(state, status='tampered')
            set_workflow_status(doc)
            self.assertEqual(doc.status, status)
        for row in workflow_definition()['states']:
            self.assertEqual(row['update_field'], 'status')
            self.assertEqual(row['update_value'], expected[row['state']])

    def test_approver_can_close_approved_expense_without_changing_details(self):
        transitions = workflow_definition()['transitions']
        close = [t for t in transitions if t['action'] == 'Close Expense']
        self.assertEqual(len(close), 1)
        self.assertEqual((close[0]['state'], close[0]['next_state'], close[0]['allowed']),
                         ('Approved', 'Closed', 'Approver - ACC (Workflow)'))
        validate_expense_workflow(expense('Closed', 'Closed'), expense('Approved', 'Active'))
        doc = expense('Closed', 'Closed')
        doc.update(dict(start_date='2026-12-01', first_due_date='2026-12-05', end_date=None))
        FixedExpense.validate_schedule(doc)
        with self.assertRaises(ValueError):
            require_approved_expense(doc)

    def test_browser_date_and_database_date_are_equivalent(self):
        old, doc = expense('Pending Expense - Chkr'), expense('Pending Expense - App')
        for item in (old, doc):
            item.meta.fields.append(frappe._dict(fieldname='first_due_date', fieldtype='Date'))
        old.first_due_date = date(2026, 12, 5)
        doc.first_due_date = '2026-12-05'
        validate_expense_workflow(doc, old)
        doc.first_due_date = '2026-12-06'
        with self.assertRaises(ValueError):
            validate_expense_workflow(doc, old)

    def test_manual_payment_gate_applies_even_to_existing_balance(self):
        source = expense('Draft')
        source.check_permission = Mock()
        with patch.object(payments.frappe, 'get_doc', return_value=source), \
             patch.object(payments.frappe, 'has_permission', return_value=True), \
             patch.object(payments, '_lock_expense'), \
             patch.object(payments, '_state', return_value=(source, [frappe._dict()], {}, {})):
            with self.assertRaises(ValueError):
                payments.make_payment('FEX', '2026-12-05')
            with self.assertRaises(ValueError):
                payments.payment_context('FEX', '2026-12-05')
            with self.assertRaises(ValueError):
                payments.get_payment_dates('FEX')

    def test_auto_candidates_exclude_unapproved_carried_balances(self):
        def records(doctype, **kwargs):
            if doctype == 'Fixed Expense':
                self.assertEqual(kwargs['filters'], {'status': 'Active', 'workflow_state': 'Approved'})
                return [frappe._dict(name='APPROVED', first_due_date='2026-12-05',
                                    start_date='2026-12-01', end_date=None, billing_frequency='Monthly')]
            return [frappe._dict(custom_fixed_expense=name, custom_expense_due_date='2026-11-05')
                    for name in ['APPROVED', 'DRAFT']]
        with patch.object(payments.frappe, 'get_all', side_effect=records):
            candidates = payments._due_candidates('2026-12-03')
        self.assertEqual(candidates, [('APPROVED', '2026-11-05'), ('APPROVED', '2026-12-05')])


if __name__ == '__main__':
    unittest.main()
