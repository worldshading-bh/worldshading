# -*- coding: utf-8 -*-
"""Store a printable customer invoice balance snapshot on Payment Entry."""
from __future__ import unicode_literals

import frappe
from frappe.utils import flt


def set_invoice_balance_snapshot(doc, method=None):
	"""Capture invoice balances immediately before a customer receipt is submitted."""
	doc.set("invoice_balance_snapshot", [])

	if not _is_customer_receipt(doc):
		return

	precision = frappe.get_precision("Sales Invoice", "outstanding_amount") or 3
	allocations = _sales_invoice_allocations(doc, precision)
	invoices = frappe.get_all(
		"Sales Invoice",
		filters={
			"customer": doc.party,
			"company": doc.company,
			"docstatus": 1,
			"outstanding_amount": [">", 0],
		},
		fields=[
			"name", "posting_date", "currency", "grand_total",
			"rounded_total", "outstanding_amount",
		],
		order_by="posting_date asc, name asc",
	)

	for invoice in invoices:
		allocated = allocations.get(invoice.name, 0)
		remaining = flt(invoice.outstanding_amount - allocated, precision)
		if remaining <= 0:
			continue

		doc.append("invoice_balance_snapshot", {
			"invoice_number": invoice.name,
			"invoice_date": invoice.posting_date,
			"currency": invoice.currency,
			"invoice_amount": invoice.rounded_total or invoice.grand_total,
			"this_payment": allocated,
			"remaining_amount": remaining,
		})


def _is_customer_receipt(doc):
	return (
		doc.payment_type == "Receive"
		and doc.party_type == "Customer"
		and doc.party
		and doc.company
	)


def _sales_invoice_allocations(doc, precision):
	allocations = {}
	for reference in doc.get("references") or []:
		if reference.reference_doctype != "Sales Invoice" or not reference.reference_name:
			continue
		allocations[reference.reference_name] = flt(
			allocations.get(reference.reference_name, 0)
			+ flt(reference.allocated_amount),
			precision,
		)
	return allocations
