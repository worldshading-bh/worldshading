from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow
from frappe.utils import flt


LAST_PURCHASE_FIELDS = (
	"last_purchase_invoice",
	"last_purchase_date",
	"last_purchase_currency",
	"last_purchase_rate",
	"last_purchase_base_rate",
)

PURCHASE_COMPARISON_FIELDS = (
	"last_purchase_comparable_total",
	"current_comparable_total",
	"purchase_difference_amount",
	"purchase_difference_percentage",
	"comparable_item_count",
)

AUTO_REJECT_STATES = ("Pending Approval", "Negotiation")


def set_last_supplier_purchase_details(doc, method=None):
	"""Set the latest purchase details for this supplier on each item row."""
	item_meta = frappe.get_meta("Supplier Quotation Item")
	available_fields = [
		fieldname for fieldname in LAST_PURCHASE_FIELDS
		if item_meta.has_field(fieldname)
	]
	comparison_fields = [
		fieldname for fieldname in PURCHASE_COMPARISON_FIELDS
		if doc.meta.has_field(fieldname)
	]
	if not available_fields and not comparison_fields:
		return

	items = [row for row in (doc.items or []) if row.item_code]
	details = {}
	if doc.supplier and items:
		details = _get_last_supplier_purchase_details(
			doc.supplier,
			[row.item_code for row in items],
			doc.get("company")
		)

	for row in (doc.items or []):
		detail = details.get(row.item_code, {})
		for fieldname in available_fields:
			row.set(fieldname, detail.get(fieldname))

	_set_purchase_comparison(doc, details, comparison_fields)


def reject_competing_supplier_quotations(doc, method=None):
	"""Reject eligible quotations for the RFQs won by this quotation."""
	if doc.workflow_state != "Approved" or doc.docstatus != 1:
		return

	rfqs = sorted(set([
		row.request_for_quotation for row in (doc.items or [])
		if row.request_for_quotation
	]))
	if not rfqs:
		return

	# Lock the shared RFQs until this transaction finishes so two competing
	# quotations cannot be approved concurrently without seeing each other.
	frappe.db.sql("""
		SELECT name
		FROM `tabRequest for Quotation`
		WHERE name IN %(rfqs)s
		ORDER BY name
		FOR UPDATE
	""", {"rfqs": tuple(rfqs)})

	linked_rows = frappe.get_all(
		"Supplier Quotation Item",
		filters={
			"request_for_quotation": ("in", rfqs),
			"parenttype": "Supplier Quotation",
		},
		fields=["parent"],
		limit_page_length=0,
	)
	quotation_names = sorted(set([
		row.parent for row in linked_rows if row.parent != doc.name
	]))
	if not quotation_names:
		return

	quotations = frappe.get_all(
		"Supplier Quotation",
		filters={"name": ("in", quotation_names)},
		fields=["name", "workflow_state", "docstatus"],
		limit_page_length=0,
	)
	approved = [
		quotation.name for quotation in quotations
		if quotation.docstatus == 1
		and quotation.workflow_state == "Approved"
	]
	if approved:
		frappe.throw(
			_("Another Supplier Quotation is already Approved for this RFQ: {0}")
			.format(", ".join(approved)),
			title=_("Approved Supplier Quotation Conflict")
		)

	for quotation in quotations:
		if quotation.docstatus != 1:
			continue
		if quotation.workflow_state not in AUTO_REJECT_STATES:
			continue
		quotation_doc = frappe.get_doc("Supplier Quotation", quotation.name)
		apply_workflow(quotation_doc.as_dict(), "Reject")


def _set_purchase_comparison(doc, details, available_fields):
	if not available_fields:
		return

	last_total = 0
	current_total = 0
	comparable_item_count = 0

	for row in (doc.items or []):
		detail = details.get(row.item_code)
		if not detail or detail.get("last_purchase_currency") != doc.currency:
			continue

		stock_qty = flt(row.stock_qty)
		if not stock_qty:
			stock_qty = flt(row.qty) * flt(row.conversion_factor or 1)
		last_total += flt(detail.get("last_purchase_rate")) * stock_qty
		current_total += flt(row.net_amount)
		comparable_item_count += 1

	difference = current_total - last_total
	percentage = (difference / last_total * 100) if last_total else 0
	values = {
		"last_purchase_comparable_total": last_total,
		"current_comparable_total": current_total,
		"purchase_difference_amount": difference,
		"purchase_difference_percentage": percentage,
		"comparable_item_count": comparable_item_count,
	}
	for fieldname in available_fields:
		doc.set(fieldname, values[fieldname])


def _get_last_supplier_purchase_details(supplier, item_codes, company=None):
	item_codes = list(set([item_code for item_code in item_codes if item_code]))
	if not supplier or not item_codes:
		return {}

	query_values = {
		"supplier": supplier,
		"item_codes": tuple(item_codes),
	}
	company_condition = ""
	if company:
		company_condition = "AND pi.company = %(company)s"
		query_values["company"] = company

	# A joined query is intentional: supplier and posting details are stored on
	# Purchase Invoice, while rates and conversion factors are on its item rows.
	rows = frappe.db.sql("""
		SELECT
			pii.item_code,
			pi.name AS purchase_invoice,
			pi.posting_date,
			pi.currency,
			pii.net_rate,
			pii.base_net_rate,
			pii.conversion_factor
		FROM `tabPurchase Invoice Item` pii
		INNER JOIN `tabPurchase Invoice` pi
			ON pi.name = pii.parent
		WHERE
			pi.docstatus = 1
			AND pi.supplier = %(supplier)s
			AND pii.item_code IN %(item_codes)s
			{company_condition}
		ORDER BY
			pii.item_code ASC,
			pi.posting_date DESC,
			pi.creation DESC,
			pii.idx DESC
	""".format(company_condition=company_condition), query_values, as_dict=1)

	details = {}
	for row in rows:
		if row.item_code in details:
			continue
		conversion_factor = flt(row.conversion_factor)
		if not conversion_factor:
			continue
		details[row.item_code] = {
			"last_purchase_invoice": row.purchase_invoice,
			"last_purchase_date": row.posting_date,
			"last_purchase_currency": row.currency,
			"last_purchase_rate": flt(row.net_rate) / conversion_factor,
			"last_purchase_base_rate": (
				flt(row.base_net_rate) / conversion_factor
			),
		}

	return details
