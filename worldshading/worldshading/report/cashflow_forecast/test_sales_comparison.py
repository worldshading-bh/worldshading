"""Permission-aware year-to-date comparison; no site or database writes."""
import unittest
from datetime import date
from unittest.mock import patch
import frappe
from worldshading.worldshading.report.cashflow_forecast.sources import Sources

class SalesComparisonTests(unittest.TestCase):
    def source(self):
        source=Sources.__new__(Sources);source.company='Example';source.start=date(2026,11,17)
        return source

    def test_current_and_prior_matching_periods_with_signed_gross_sales(self):
        source=self.source();calls=[]
        def listing(doctype,**kwargs):
            calls.append(kwargs)
            return [frappe._dict(amount=120 if len(calls)==1 else 100)]
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_list',side_effect=listing):
            source.collect_sales_comparison()
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0]['filters']['posting_date'],['between',[date(2026,1,1),date(2026,11,17)]])
        self.assertEqual(calls[1]['filters']['posting_date'],['between',[date(2025,1,1),date(2025,11,17)]])
        self.assertEqual(calls[0]['filters']['docstatus'],1)
        self.assertEqual(calls[0]['fields'],['sum(base_grand_total) as amount'])
        self.assertEqual(source.sales_comparison['difference'],'20.000')
        self.assertEqual(source.sales_comparison['percentage'],'20.00')

    def test_zero_prior_sales_and_no_permission(self):
        source=self.source()
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_list',return_value=[]):
            source.collect_sales_comparison()
        self.assertIsNone(source.sales_comparison['percentage'])
        with patch.object(frappe,'has_permission',return_value=False),patch.object(frappe,'get_list') as listing:
            source.collect_sales_comparison()
        self.assertIsNone(source.sales_comparison);listing.assert_not_called()

    def test_leap_day_matches_february_28_of_prior_year(self):
        source=self.source();source.start=date(2024,2,29)
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_list',return_value=[]):
            source.collect_sales_comparison()
        self.assertEqual(source.sales_comparison['previous_end'],'2023-02-28')

    def test_saved_sales_comparison_rechecks_invoice_read_access(self):
        from worldshading.worldshading.report.cashflow_forecast import prepared_access
        saved=dict(result=[dict(_cashflow_context=dict(sales_comparison=dict(current='120',previous='100')))])
        with patch.object(frappe,'has_permission',return_value=False),patch.object(frappe,'throw',side_effect=PermissionError):
            with self.assertRaises(PermissionError):prepared_access.check_payroll_access(saved)
