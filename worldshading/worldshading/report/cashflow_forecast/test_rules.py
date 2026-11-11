"""Read-only fixture tests, no Frappe bootstrap or database."""
import os
import sys
import unittest
from decimal import Decimal
sys.path.insert(0, os.path.dirname(__file__))
try:
    import rules
except ImportError:
    rules = None


class SourceRulesTests(unittest.TestCase):
    def test_scheduled_draft_does_not_settle_obligation(self):
        self.assertEqual(rules.paid_before({'docstatus': 0, 'posting_date': '2026-12-01', 'paid_amount': 500}, '2026-11-09'), 0)
        self.assertEqual(rules.paid_before({'docstatus': 1, 'posting_date': '2026-12-01', 'paid_amount': 500}, '2026-11-09'), 0)
        self.assertEqual(rules.paid_before({'docstatus': 2, 'posting_date': '2026-11-01', 'paid_amount': 500}, '2026-11-09'), 0)
        self.assertEqual(rules.paid_before({'docstatus': 1, 'posting_date': '2026-11-01', 'paid_amount': 500}, '2026-11-09'), 500)

    def test_invoice_and_advance_replace_po_not_twice(self):
        self.assertEqual(rules.po_remaining(100, 50, 20, 20), Decimal('50'))
        self.assertEqual(rules.po_remaining(100, 50, 60, 50), Decimal('40'))
        self.assertEqual(rules.po_remaining(100, 100, 0, 0), Decimal('0'))

    def test_import_vat_removed_from_supplier_cash_only(self):
        self.assertEqual(rules.supplier_amount(1100, 100), Decimal('1000'))
        self.assertEqual(rules.supplier_amount(500, 0), Decimal('500'))

    def test_paid_supplier_cash_is_not_proportionally_assigned_to_import_vat(self):
        self.assertEqual(rules.supplier_outstanding(1100, 600, 100), Decimal('500'))
        self.assertEqual(rules.supplier_outstanding(1100, 100, 100), Decimal('0'))

    def test_partial_customs_payment_keeps_unpaid_eta_residual(self):
        self.assertEqual(rules.arrival_residual(500, 100, 0), Decimal('400'))
        self.assertEqual(rules.arrival_residual(1050, 0, 100), Decimal('950'))

    def test_salary_normal_components_and_statistical_rows(self):
        rows = [{'parentfield': 'earnings', 'amount': 100}, {'parentfield': 'earnings', 'amount': 20},
                {'parentfield': 'earnings', 'amount': 999, 'statistical_component': 1},
                {'parentfield': 'deductions', 'amount': 5}]
        self.assertEqual(rules.salary_estimate(rows, {}, lambda expression, context: 0), Decimal('115'))

    def test_salary_formula_and_joining_proration(self):
        rows = [{'parentfield': 'earnings', 'abbr': 'B', 'amount_based_on_formula': 1,
                 'formula': 'base', 'depends_on_payment_days': 1},
                {'parentfield': 'deductions', 'amount': 10}]
        self.assertEqual(rules.salary_estimate(rows, {'base': 300}, lambda expression, context: context['base'], Decimal('.5')), Decimal('140'))

    def test_advance_on_multi_po_payment_only_consumes_invoiced_po(self):
        shares = rules.advance_shares(30, [{'reference_name': 'PO-A', 'allocated_amount': 30},
            {'reference_name': 'PO-B', 'allocated_amount': 70}], {'PO-A'})
        self.assertEqual(shares, {'PO-A': Decimal('30')})

    def test_invoice_outstanding_party_currency(self):
        self.assertEqual(rules.base_outstanding(100, 'USD', 'BHD', '0.376'), Decimal('37.600'))
        self.assertEqual(rules.base_outstanding(100, 'BHD', 'BHD', '0.376'), Decimal('100'))


if __name__ == '__main__': unittest.main()
