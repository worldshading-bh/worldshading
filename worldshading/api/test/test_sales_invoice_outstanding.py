# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import unittest
from unittest.mock import Mock, patch

import frappe
from worldshading.api import sales_invoice_outstanding


class TestSalesInvoiceOutstanding(unittest.TestCase):
	def test_non_manager_cannot_recalculate(self):
		with patch.object(frappe, "get_roles", return_value=["Accounts Manager"]), \
			patch.object(frappe, "get_doc") as get_doc, \
			patch.object(frappe, "throw", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				sales_invoice_outstanding.recalculate_outstanding("SI-RETURN")
			get_doc.assert_not_called()

	def test_document_write_permission_is_required(self):
		doc = Mock()
		doc.check_permission.side_effect = frappe.PermissionError
		with patch.object(frappe, "get_roles", return_value=["System Manager"]), \
			patch.object(frappe, "get_doc", return_value=doc), \
			patch.object(sales_invoice_outstanding, "update_outstanding_amt") as update:
			with self.assertRaises(frappe.PermissionError):
				sales_invoice_outstanding.recalculate_outstanding("SI-RETURN")
			doc.check_permission.assert_called_once_with("write")
			update.assert_not_called()

	def test_draft_and_cancelled_invoices_are_rejected(self):
		for docstatus in (0, 2):
			doc = Mock(docstatus=docstatus)
			with patch.object(frappe, "get_roles", return_value=["System Manager"]), \
				patch.object(frappe, "get_doc", return_value=doc), \
				patch.object(frappe, "throw", side_effect=frappe.ValidationError), \
				patch.object(sales_invoice_outstanding, "update_outstanding_amt") as update:
				with self.assertRaises(frappe.ValidationError):
					sales_invoice_outstanding.recalculate_outstanding("SI-RETURN")
				update.assert_not_called()

	def test_recalculates_selected_invoice_without_saving_or_forcing_zero(self):
		for balance in (0, -27.8, 12.5):
			doc = Mock(docstatus=1, outstanding_amount=-55.7, debit_to="Debtors - WS",
				customer="CUSTOMER", currency="BHD", party_account_currency="BHD",
				is_return=1, return_against="SI-ORIGINAL", status="Return")
			doc.name = "SI-RETURN"
			doc.reload.side_effect = lambda: setattr(doc, "outstanding_amount", balance)
			with patch.object(frappe, "get_roles", return_value=["System Manager"]), \
				patch.object(frappe, "get_doc", return_value=doc), \
				patch.object(sales_invoice_outstanding, "update_outstanding_amt") as update:
				result = sales_invoice_outstanding.recalculate_outstanding(doc.name)
				update.assert_called_once_with(
					"Debtors - WS", "Customer", "CUSTOMER", "Sales Invoice", "SI-RETURN"
				)
				doc.reload.assert_called_once_with()
				doc.save.assert_not_called()
				self.assertEqual(result["previous_outstanding"], -55.7)
				self.assertEqual(result["outstanding_amount"], balance)
