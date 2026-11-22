"""Load real app configuration: financial handlers must be registered, not just tested alone."""
import runpy
import unittest
from pathlib import Path


class TestBankLoanHooks(unittest.TestCase):
    def test_native_jv_and_form_routes_are_registered(self):
        hooks=runpy.run_module('worldshading.hooks')
        self.assertEqual(hooks['doctype_js']['Bank Loan'],'public/js/bank_loan_payments.js')
        self.assertEqual(hooks['scheduler_events']['daily'].count('worldshading.api.bank_loan_payments.create_due_payments'),1)
        events=hooks['doc_events']['Journal Entry']
        self.assertIn('worldshading.api.bank_loan_payments.validate_journal',events['validate'])
        self.assertIn('worldshading.api.bank_loan_payments.protect_history',events['before_update_after_submit'])
        self.assertIn('worldshading.api.bank_loan_payments.before_cancel',events['before_cancel'])
        self.assertIn('worldshading.api.bank_loan_payments.protect_journal_delete',events['on_trash'])
        self.assertIn('worldshading.worldshading.doctype.commission_payout.commission_payout.unlink_journal_entry',events['before_cancel'])
        self.assertEqual(hooks['after_migrate'].count('worldshading.api.bank_loan_setup.setup_payment_fields'),1)


if __name__=='__main__':unittest.main()
