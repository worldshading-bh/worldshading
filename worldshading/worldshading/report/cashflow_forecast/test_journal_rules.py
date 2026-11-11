"""Pure journal/review accounting tests; no Frappe bootstrap."""
import os
import sys
import unittest
from decimal import Decimal
sys.path.insert(0, os.path.dirname(__file__))
import rules


class JournalRulesTests(unittest.TestCase):
    def test_internal_transfer_and_transfer_fee_use_net_pool_effect(self):
        rows=[dict(account='Bank',credit=1000,debit=0),dict(account='Cash',debit=1000,credit=0)]
        self.assertEqual(rules.journal_effect(rows,{'Bank','Cash'}),0)
        rows=[dict(account='Bank',credit=1001,debit=0),dict(account='Cash',debit=1000,credit=0),dict(account='Fee',debit=1,credit=0)]
        self.assertEqual(rules.journal_effect(rows,{'Bank','Cash'}),1)

    def test_untyped_pool_account_is_cash_but_noncash_journal_is_not(self):
        self.assertEqual(rules.journal_effect([dict(account='Untyped cash',credit=500),dict(account='Expense',debit=500)],{'Untyped cash'}),500)
        self.assertEqual(rules.journal_effect([dict(account='Depreciation',debit=500),dict(account='Accumulated depreciation',credit=500)],{'Bank'}),0)
        self.assertEqual(rules.journal_effect([dict(account='Bank',debit=500),dict(account='Income',credit=500)],{'Bank'}),-500)

    def test_explicit_invoice_reference_can_replace_obligation(self):
        rows=[dict(account='Bank',credit=500),dict(account='Payable',debit=500,reference_type='Purchase Invoice',reference_name='PI-1')]
        refs,ambiguous=rules.journal_reference_allocations(rows,{'Bank'})
        self.assertEqual(refs,{('Purchase Invoice','PI-1'):Decimal('500')})
        self.assertFalse(ambiguous)

    def test_complex_offsets_do_not_guess_invoice_settlement(self):
        rows=[dict(account='Bank',credit=100),dict(account='Payable A',debit=150,reference_type='Purchase Invoice',reference_name='PI-1'),dict(account='Payable B',credit=50)]
        refs,ambiguous=rules.journal_reference_allocations(rows,{'Bank'})
        self.assertEqual(refs,{})
        self.assertTrue(ambiguous)

    def test_explicit_payroll_link_uses_company_currency_debit(self):
        refs,ambiguous=rules.journal_reference_allocations([dict(account='Bank',credit=250),
            dict(account='Payroll payable',debit=250,reference_type='Payroll Entry',reference_name='PAY-1')],{'Bank'})
        self.assertEqual(refs,{('Payroll Entry','PAY-1'):Decimal('250')})

    def test_review_sections_separate_prepared_payments_from_source_obligations(self):
        rows=[dict(doctype='Payment Entry',name='PE-1',category='supplier_payments',amount=100),
            dict(doctype='GL Payment',name='GL-1',category='fixed_expenses',amount=50),
            dict(doctype='Journal Entry',name='JV-1',category='payroll',amount=200),
            dict(doctype='Purchase Invoice',name='PI-1',category='supplier_payments',amount=75)]
        groups=rules.group_overdue_review(rows)
        by_id={g['id']:g for g in groups}
        self.assertEqual(set(by_id),{'pe_supplier','gl','jv','supplier_due'})
        self.assertEqual(by_id['pe_supplier']['total_amount'],100)
        self.assertEqual(by_id['supplier_due']['total_amount'],75)
        self.assertEqual(sum(g['total_amount'] for g in groups),425)


if __name__=='__main__': unittest.main()
