"""Database-free checks; run with Python unittest, not a bench/site test runner."""
import unittest
from unittest.mock import patch, Mock
from contextlib import ExitStack
import frappe
from worldshading.api import fixed_expense_payments as service
from datetime import date
from worldshading.api.fixed_expense_payments import (
    due_date, due_dates, next_balance_date, balance_from_payments, allocate_rows
)


class TestFixedExpensePayments(unittest.TestCase):
    def test_anchored_month_end_and_long_intervals(self):
        self.assertEqual(due_date('2024-01-31', 'Monthly', 1), date(2024, 2, 29))
        self.assertEqual(due_date('2024-01-31', 'Monthly', 2), date(2024, 3, 31))
        self.assertEqual(due_date('2024-02-29', 'Yearly', 1), date(2025, 2, 28))
        for years in range(2, 6):
            self.assertEqual(due_date('2024-02-29', 'Every {} Years'.format(years), 1),
                             date(2024 + years, 2, 29 if years == 4 else 28))

    def test_tracking_start_and_end(self):
        self.assertEqual(due_dates('2026-10-05', 'Monthly', '2026-11-01',
                                  '2027-01-01', '2026-12-05'),
                         [date(2026, 11, 5), date(2026, 12, 5)])

    def test_carryover_date_does_not_use_frequency(self):
        self.assertEqual(next_balance_date('2026-01-31', '2026-02-02', '2026-03-01'),
                         date(2026, 3, 31))

    def test_partial_close_cancel_and_draft(self):
        rows = [{'docstatus': 1, 'total_amount': 60},
                {'docstatus': 0, 'total_amount': 40, 'name': 'draft'}]
        state = balance_from_payments(100, rows, 3)
        self.assertEqual(state['remaining'], 40)
        self.assertEqual(state['active'], ['draft'])
        rows.pop()
        rows.append({'docstatus': 1, 'total_amount': 25})
        self.assertEqual(balance_from_payments(100, rows, 3)['remaining'], 15)
        rows.append({'docstatus': 1, 'total_amount': 10, 'custom_close_remaining_balance': 1})
        state = balance_from_payments(100, rows, 3)
        self.assertEqual(state['remaining'], 0)
        self.assertEqual(state['closed_remainder'], 5)
        rows[-1]['docstatus'] = 2
        self.assertEqual(balance_from_payments(100, rows, 3)['remaining'], 15)

    def test_excess(self):
        state = balance_from_payments(100, [{'docstatus': 1, 'total_amount': 125}], 3)
        self.assertEqual(state['excess'], 25)
        self.assertEqual(state['remaining'], 0)

    def test_mixed_tax_allocation_rounds_exactly(self):
        rows = [{'account': 'rent', 'rate': 0, 'net_amount': 100, 'tax_amount': 0},
                {'account': 'fees', 'rate': 10, 'net_amount': 1, 'tax_amount': .1}]
        result = allocate_rows(rows, 40, 3)
        self.assertEqual(round(sum(r['net_amount'] + r['tax_amount'] for r in result), 3), 40)
        self.assertEqual(result[0]['tax_amount'], 0)
        self.assertEqual(result[1]['tax_amount'], round(result[1]['net_amount'] * .1, 3))

    def test_tiny_balance_never_creates_negative_rows(self):
        rows = [{'account': str(i), 'rate': 0, 'net_amount': 1, 'tax_amount': 0}
                for i in range(10)]
        result = allocate_rows(rows, .006, 3)
        self.assertTrue(all(r['net_amount'] >= 0 and r['tax_amount'] >= 0 for r in result))
        self.assertEqual(round(sum(r['total_amount'] for r in result), 3), .006)


class TestPaymentValidation(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ('_lock_expense', '_validate_items', 'validate_account_mapping', '_set_initial_workflow'):
            self.stack.enter_context(patch.object(service, target))
        self.stack.enter_context(patch.object(service, '_previous', return_value=None))
        self.stack.enter_context(patch.object(service, 'nowdate', return_value='2026-12-05'))
        self.stack.enter_context(patch.object(service.frappe, 'throw', side_effect=ValueError))
        self.source = Mock(company='Example')
        self.source.get.side_effect = lambda key: {'workflow_state': 'Approved', 'status': 'Active'}.get(key)
        self.state = {'remaining': 40, 'closed': False, 'active': []}
        self.state_mock = self.stack.enter_context(patch.object(service, '_state',
            return_value=(self.source, [], {'company': 'Example', 'amount': 100, 'precision': 3}, self.state)))
        self.doc = frappe._dict(name='new', flags=frappe._dict(), custom_fixed_expense='FEX',
            custom_expense_due_date='2026-11-01', company='Example', payment_type='Outgoing',
            total_amount=40, docstatus=0, posting_date='2026-12-05', custom_close_remaining_balance=0,
            custom_expense_amount=999, custom_expense_snapshot='tampered')

    def test_server_replaces_client_amount_and_snapshot(self):
        service.validate_payment(self.doc)
        self.assertEqual(self.doc.custom_expense_amount, 40)
        self.assertNotEqual(self.doc.custom_expense_snapshot, 'tampered')
        self.assertTrue(self.doc.flags.valid_fixed_expense_payment)
        self.source.check_permission.assert_called_with('read')

    def test_new_direct_gl_cannot_bypass_master_approval(self):
        self.source.get.side_effect = lambda key: {'workflow_state': 'Draft', 'status': 'Active'}.get(key)
        with self.assertRaises(ValueError):
            service.validate_payment(self.doc)

    def test_saved_gl_can_continue_after_master_returned_or_closed(self):
        self.source.get.side_effect = lambda key: {'workflow_state': 'Draft', 'status': 'Closed'}.get(key)
        self.state_mock.return_value = (self.source, [frappe._dict(name='new')],
            {'company': 'Example', 'amount': 100, 'precision': 3}, self.state)
        service.validate_payment(self.doc)
        self.assertTrue(self.doc.flags.valid_fixed_expense_payment)

    def test_under_and_over_payment_require_reason(self):
        for amount in (25, 50):
            self.doc.total_amount = amount
            with self.assertRaises(ValueError):
                service.validate_payment(self.doc)

    def test_partial_completion_schedules_separate_balance(self):
        self.doc.update(dict(total_amount=25, docstatus=1, custom_adjustment_reason='Pay remaining later'))
        service.validate_payment(self.doc)
        self.assertEqual(self.doc.custom_next_balance_due_date, date(2027, 1, 1))
        self.assertEqual(str(self.doc.custom_expense_due_date), '2026-11-01')

    def test_close_stops_retry_only_after_completion(self):
        self.doc.update(dict(total_amount=25, docstatus=1, custom_adjustment_reason='Agreed discount',
                        custom_close_remaining_balance=1))
        service.validate_payment(self.doc)
        self.assertIsNone(self.doc.custom_next_balance_due_date)

    def test_variable_actual_amount_needs_no_adjustment_reason_or_retry(self):
        self.state_mock.return_value[2]['amount_type'] = 'Variable'
        for amount in (25, 50):
            self.doc.update(dict(total_amount=amount, docstatus=1, custom_close_remaining_balance=0))
            service.validate_payment(self.doc)
            self.assertIsNone(self.doc.custom_next_balance_due_date)

    def test_variable_completion_settles_estimate_without_waiver(self):
        state = balance_from_payments(100, [{'docstatus': 1, 'total_amount': 60}], 3, 'Variable')
        self.assertEqual(state['remaining'], 0)
        self.assertEqual(state['closed_remainder'], 0)
        self.assertTrue(state['closed'])
        state = balance_from_payments(100, [{'docstatus': 0, 'total_amount': 60, 'name': 'draft'}], 3, 'Variable')
        self.assertEqual(state['remaining'], 100)
        self.assertFalse(state['closed'])
        state = balance_from_payments(100, [{'docstatus': 2, 'total_amount': 60}], 3, 'Variable')
        self.assertEqual(state['remaining'], 100)


    def test_foreign_tolerance_settles_small_difference(self):
        self.state_mock.return_value[2].update(dict(amount_type='Fixed', currency='USD',
            company_currency='BHD', currency_exchange_tolerance=1))
        for amount in (39, 39.5, 40.5, 41):
            self.doc.update(dict(total_amount=amount, docstatus=1, custom_adjustment_reason=None,
                                 custom_close_remaining_balance=0))
            service.validate_payment(self.doc)
            self.assertIsNone(self.doc.custom_next_balance_due_date)
            self.assertEqual(self.doc.custom_close_remaining_balance, int(amount < 40))
            self.assertTrue(self.doc.custom_adjustment_reason)

    def test_tolerance_draft_does_not_close_and_large_difference_needs_reason(self):
        self.state_mock.return_value[2].update(dict(amount_type='Fixed', currency='USD',
            company_currency='BHD', currency_exchange_tolerance=1))
        self.doc.total_amount = 39
        service.validate_payment(self.doc)
        self.assertEqual(self.doc.custom_close_remaining_balance, 0)
        self.assertFalse(self.doc.get('custom_adjustment_reason'))
        for amount in (38.999, 41.001):
            self.doc.total_amount = amount
            with self.assertRaises(ValueError):
                service.validate_payment(self.doc)

    def test_local_currency_and_zero_tolerance_keep_reason_requirement(self):
        snapshot = self.state_mock.return_value[2]
        for currency, tolerance in [('BHD', 1), ('USD', 0)]:
            snapshot.update(dict(amount_type='Fixed', currency=currency, company_currency='BHD',
                                 currency_exchange_tolerance=tolerance))
            self.doc.total_amount = 39.5
            with self.assertRaises(ValueError):
                service.validate_payment(self.doc)

    def test_existing_active_payment_blocks_manual_save(self):
        self.state['active'] = ['GLP-existing']
        with self.assertRaises(ValueError):
            service.validate_payment(self.doc)

    def test_fully_paid_and_closed_block_new_attempt(self):
        self.state['remaining'] = 0
        with self.assertRaises(ValueError):
            service.validate_payment(self.doc)

    def test_invalid_close_on_full_payment(self):
        self.doc.custom_close_remaining_balance = 1
        with self.assertRaises(ValueError):
            service.validate_payment(self.doc)

    def test_reference_exception_requires_verified_draft(self):
        self.doc.workflow_state = 'Draft'
        self.assertFalse(service.is_fixed_expense_draft(self.doc))
        self.doc.flags.valid_fixed_expense_payment = True
        self.assertTrue(service.is_fixed_expense_draft(self.doc))
        self.doc.workflow_state = 'Pending Bank Payment - Chkr'
        self.assertFalse(service.is_fixed_expense_draft(self.doc))


class TestAccountMapping(unittest.TestCase):
    def test_amount_changes_and_reordering_allowed(self):
        rows = [dict(account='Rent', template_type='Purchase Taxes and Charges Template', tax_template='Zero', net_amount=155),
                dict(account='Fees', template_type='Purchase Taxes and Charges Template', tax_template='VAT', net_amount=1)]
        actual = [dict(rows[1], net_amount=2), dict(rows[0], net_amount=100)]
        service.validate_account_mapping(actual, {'items': rows})

    def test_account_template_and_row_changes_rejected(self):
        row = dict(account='Rent', template_type='Purchase Taxes and Charges Template', tax_template='Zero')
        with patch.object(service.frappe, 'throw', side_effect=ValueError):
            for actual in ([dict(row, account='Other')], [dict(row, tax_template='VAT')],
                           [dict(row, template_type='Sales Taxes and Charges Template')], [], [row, row]):
                with self.assertRaises(ValueError):
                    service.validate_account_mapping(actual, {'items': [row]})


if __name__ == '__main__':
    unittest.main()
