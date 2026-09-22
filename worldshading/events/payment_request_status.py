# -*- coding: utf-8 -*-
"""Correct ERPNext v12 Payment Request status after Payment Entry changes.

ERPNext v12 derives a Payment Request's status from the outstanding amount of the
whole Sales/Purchase document.  A completely settled partial request is therefore
marked Partially Paid.  It is then deducted a second time when another request is
created.

Payment Entries created from a Payment Request already carry the request name in
``reference_no``.  This module uses that exact relationship and the matching
Payment Entry Reference allocation.  It never guesses a relationship for legacy
manual entries with an external reference number.
"""
from __future__ import unicode_literals

import frappe
from frappe.utils import flt


SUPPORTED_REFERENCE_DOCTYPES = (
	"Sales Order",
	"Sales Invoice",
	"Purchase Order",
	"Purchase Invoice",
)
SNAPSHOT_FLAG = "ws_payment_request_status_snapshot"


def status_for_allocation(payment_request_type, grand_total, allocated_amount, precision=3):
	"""Return the status of one request from allocations explicitly tied to it."""
	requested = flt(grand_total, precision)
	allocated = flt(allocated_amount, precision)

	if allocated <= 0:
		return "Initiated" if payment_request_type == "Outward" else "Requested"
	if allocated >= requested:
		return "Paid"
	return "Partially Paid"


def snapshot_related_statuses(doc, method=None):
	"""Remember related PR statuses before ERPNext v12's broad status hook runs."""
	snapshot = {}
	linked_request = _linked_payment_request(doc)
	if linked_request:
		snapshot[linked_request.name] = linked_request.status

	for reference_doctype, reference_name in _business_references(doc):
		rows = frappe.get_all(
			"Payment Request",
			filters={
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"docstatus": 1,
			},
			fields=["name", "status"],
		)
		for row in rows:
			snapshot[row.name] = row.status

	doc.flags[SNAPSHOT_FLAG] = snapshot


def validate_explicit_allocation(doc, method=None):
	"""Block a second PE from allocating more than the exact PR requested."""
	linked_request = _linked_payment_request(doc)
	if doc.get("quotation") and not linked_request:
		frappe.throw(
			"A Quotation advance must name its submitted Payment Request in Reference No."
		)
	if not linked_request:
		return

	existing = _submitted_allocation(linked_request)
	proposed = _document_allocation(doc, linked_request)
	if existing is None or proposed is None:
		frappe.throw(
			"Payment Entry currency does not match Payment Request {0}.".format(
				linked_request.name
			)
		)

	precision = frappe.get_precision("Payment Request", "grand_total") or 3
	requested = flt(linked_request.grand_total, precision)
	if allocation_exceeds_request(requested, existing, proposed, precision):
		frappe.throw(
			"Payment Request {0} is already fully allocated or this Payment Entry "
			"would exceed its requested amount of {1}.".format(
				linked_request.name, requested
			)
		)


def allocation_exceeds_request(requested, existing, proposed, precision=3):
	return flt(existing + proposed, precision) > flt(requested, precision)


def is_fully_settled(outstanding_amount, precision=3):
	"""Return whether a referenced document has no outstanding balance."""
	return flt(outstanding_amount, precision) == 0


def is_paid_invoice(docstatus, status, outstanding_amount, precision=3):
	"""Exclude cancelled and credit-note-settled invoices from manual payment sync."""
	return (
		docstatus == 1
		and status == "Paid"
		and is_fully_settled(outstanding_amount, precision)
	)


def party_currency(payment_type, paid_from_currency, paid_to_currency):
	"""Return the party-side currency using ERPNext v12 Payment Entry fields."""
	if payment_type == "Receive":
		return paid_from_currency
	if payment_type == "Pay":
		return paid_to_currency
	return None


def synchronize_after_submit(doc, method=None):
	_synchronize(doc)


def synchronize_after_cancel(doc, method=None):
	_synchronize(doc)


def _synchronize(doc):
	"""Undo v12's unrelated update, then update the explicitly linked PR."""
	snapshot = doc.flags.get(SNAPSHOT_FLAG) or {}
	linked_request = _linked_payment_request(doc)
	fully_settled = _fully_settled_business_references(doc)

	# ERPNext v12 selects an arbitrary submitted Payment Request for each business
	# document. Restore every snapshotted request except the one this PE proves it
	# belongs to. If a manual Payment Entry has fully settled the business document,
	# every request against it is satisfied even though Reference No contains the
	# customer's bank reference rather than a Payment Request name.
	for name, status in snapshot.items():
		request_reference = frappe.db.get_value(
			"Payment Request", name, ["reference_doctype", "reference_name"],
			as_dict=True,
		)
		if request_reference and (
			request_reference.reference_doctype,
			request_reference.reference_name,
		) in fully_settled:
			if frappe.db.get_value("Payment Request", name, "status") != "Paid":
				frappe.db.set_value(
					"Payment Request", name, "status", "Paid",
					update_modified=False,
				)
			continue
		if linked_request and name == linked_request.name:
			continue
		if frappe.db.get_value("Payment Request", name, "status") != status:
			frappe.db.set_value(
				"Payment Request", name, "status", status, update_modified=False
			)

	if not linked_request:
		return
	if (
		linked_request.reference_doctype,
		linked_request.reference_name,
	) in fully_settled:
		return

	allocated = _submitted_allocation(linked_request)
	if allocated is None:
		# Currency mismatch or ambiguous data: preserve the previous status and flag
		# the case for manual review instead of guessing.
		previous = snapshot.get(linked_request.name)
		if previous and frappe.db.get_value(
			"Payment Request", linked_request.name, "status"
		) != previous:
			frappe.db.set_value(
				"Payment Request", linked_request.name, "status", previous,
				update_modified=False,
			)
		frappe.log_error(
			"Could not safely calculate allocations for {0}".format(linked_request.name),
			"Payment Request status synchronization skipped",
		)
		return

	precision = frappe.get_precision("Payment Request", "grand_total") or 3
	requested = flt(linked_request.grand_total, precision)
	allocated = flt(allocated, precision)
	if allocated > requested:
		frappe.log_error(
			"Payment Request {0}: requested {1}, explicitly allocated {2}".format(
				linked_request.name, requested, allocated
			),
			"Payment Request is over-allocated",
		)

	status = status_for_allocation(
		linked_request.payment_request_type,
		requested,
		allocated,
		precision,
	)
	if linked_request.status != status:
		frappe.db.set_value(
			"Payment Request", linked_request.name, "status", status,
			update_modified=False,
		)


def _business_references(doc):
	result = []
	seen = set()
	for row in doc.get("references") or []:
		key = (row.reference_doctype, row.reference_name)
		if (
			row.reference_doctype in SUPPORTED_REFERENCE_DOCTYPES
			and row.reference_name
			and key not in seen
		):
			seen.add(key)
			result.append(key)
	return result


def _fully_settled_business_references(doc):
	"""Return submitted invoice references currently marked Paid with zero outstanding."""
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_reference_details

	result = set()
	precision = frappe.get_precision("Payment Request", "grand_total") or 3
	for reference_doctype, reference_name in _business_references(doc):
		if reference_doctype not in ("Sales Invoice", "Purchase Invoice"):
			continue
		invoice = frappe.db.get_value(
			reference_doctype, reference_name, ["docstatus", "status"], as_dict=True
		)
		if not invoice:
			continue
		details = get_reference_details(
			reference_doctype,
			reference_name,
			doc.get("party_account_currency"),
		)
		if is_paid_invoice(
			invoice.docstatus, invoice.status, details.outstanding_amount, precision
		):
			result.add((reference_doctype, reference_name))
	return result


def _linked_payment_request(doc):
	"""Return a strictly correlated PR, or None for ordinary manual PEs."""
	name = (doc.get("reference_no") or "").strip()
	if not name:
		return None

	row = frappe.db.get_value(
		"Payment Request",
		{"name": name, "docstatus": 1},
		[
			"name", "reference_doctype", "reference_name", "grand_total",
			"currency", "payment_request_type", "status",
		],
		as_dict=True,
	)
	if not row:
		return None

	if row.reference_doctype == "Quotation":
		if doc.get("quotation") != row.reference_name:
			return None
		return row

	if (row.reference_doctype, row.reference_name) not in _business_references(doc):
		return None
	return row


def _submitted_allocation(payment_request):
	"""Sum same-currency submitted PE allocations explicitly naming this PR."""
	if payment_request.reference_doctype == "Quotation":
		entries = frappe.get_all(
			"Payment Entry",
			filters={
				"reference_no": payment_request.name,
				"quotation": payment_request.reference_name,
				"docstatus": 1,
				"payment_type": "Receive",
			},
			fields=[
				"paid_amount", "paid_from_account_currency",
			],
		)
		for entry in entries:
			if entry.paid_from_account_currency != payment_request.currency:
				return None
		return sum(flt(entry.paid_amount) for entry in entries)

	entries = frappe.get_all(
		"Payment Entry",
		filters={"reference_no": payment_request.name, "docstatus": 1},
		fields=[
			"name", "payment_type", "paid_from_account_currency",
			"paid_to_account_currency",
		],
	)
	if not entries:
		return 0

	entry_names = []
	for entry in entries:
		entry_currency = party_currency(
			entry.payment_type,
			entry.paid_from_account_currency,
			entry.paid_to_account_currency,
		)
		if entry_currency != payment_request.currency:
			return None
		entry_names.append(entry.name)

	rows = frappe.get_all(
		"Payment Entry Reference",
		filters={
			"parent": ("in", entry_names),
			"reference_doctype": payment_request.reference_doctype,
			"reference_name": payment_request.reference_name,
		},
		fields=["allocated_amount"],
	)
	return sum(flt(row.allocated_amount) for row in rows)


def _document_allocation(doc, payment_request):
	if payment_request.reference_doctype == "Quotation":
		if doc.get("references"):
			frappe.throw("A Quotation customer advance cannot contain allocation references.")
		if doc.get("payment_type") != "Receive":
			frappe.throw("A Quotation customer advance must be a Receive Payment Entry.")
		if doc.get("paid_from_account_currency") != payment_request.currency:
			return None
		return flt(doc.get("paid_amount"))

	document_currency = party_currency(
		doc.get("payment_type"),
		doc.get("paid_from_account_currency"),
		doc.get("paid_to_account_currency"),
	)
	if document_currency != payment_request.currency:
		return None
	return sum(
		flt(row.allocated_amount)
		for row in doc.get("references") or []
		if row.reference_doctype == payment_request.reference_doctype
		and row.reference_name == payment_request.reference_name
	)
