# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import frappe
from frappe import _
from erpnext.accounts.doctype.gl_entry.gl_entry import update_outstanding_amt


@frappe.whitelist(methods=["POST"])
def recalculate_outstanding(invoice_name):
	"""Refresh a submitted invoice's balance from its own GL allocations."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only a System Manager can recalculate outstanding."), frappe.PermissionError)

	doc = frappe.get_doc("Sales Invoice", invoice_name)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Outstanding can only be recalculated for a submitted Sales Invoice."))

	previous_outstanding = doc.outstanding_amount
	# Use the selected invoice, not return_against: ERPNext follows the GL allocation.
	# Do not save the document or rerun taxes, payments, rounding, or validation hooks.
	update_outstanding_amt(
		doc.debit_to, "Customer", doc.customer, "Sales Invoice", doc.name
	)
	doc.reload()
	return {
		"name": doc.name,
		"previous_outstanding": previous_outstanding,
		"outstanding_amount": doc.outstanding_amount,
		"currency": doc.party_account_currency or doc.currency,
		"status": doc.status,
	}
