"""Preserve original rounding for exact, non-POS invoice reversals only."""
import frappe
from frappe.utils import cint, flt


def get_original_return_rounding(doc):
	if (doc.get("doctype") != "Sales Invoice" or not cint(doc.get("is_return"))
		or cint(doc.get("is_pos")) or cint(doc.get("docstatus")) not in (0, 1)
		or not doc.get("return_against") or flt(doc.get("grand_total")) >= 0
		or doc.get("payments") or doc.get("advances")):
		return None

	source = frappe.get_doc("Sales Invoice", doc.get("return_against"))
	if source.docstatus != 1 or cint(source.get("is_return")):
		return None
	for field in ("company", "customer", "currency", "party_account_currency"):
		if not doc.get(field) or doc.get(field) != source.get(field):
			return None
	if flt(doc.get("conversion_rate"), 9) != flt(source.get("conversion_rate"), 9):
		return None
	# Special settlements require a separate allocation-aware design.
	for field in ("write_off_amount", "base_write_off_amount", "change_amount",
		"base_change_amount", "total_advance", "loyalty_amount", "redeem_loyalty_points",
		"credit_note", "credit_note_invoice"):
		if doc.get(field) or source.get(field):
			return None
	if flt(doc.get("paid_amount")) or flt(doc.get("base_paid_amount")):
		return None
	if frappe.db.exists("Sales Invoice", {
		"return_against": source.name, "is_return": 1, "docstatus": 1,
		"name": ["!=", doc.get("name") or ""],
	}):
		return None

	for field in ("grand_total", "base_grand_total", "net_total", "base_net_total",
		"total_taxes_and_charges", "base_total_taxes_and_charges"):
		if flt(doc.get(field), 6) != -flt(source.get(field), 6):
			return None

	original_items = {row.name: row for row in source.get("items", [])}
	seen = set()
	for row in doc.get("items", []):
		link = row.get("sales_invoice_item")
		original = original_items.get(link)
		if not original or link in seen:
			return None
		seen.add(link)
		for field in ("item_code", "uom"):
			if row.get(field) != original.get(field):
				return None
		for field in ("conversion_factor", "rate"):
			if flt(row.get(field), 6) != flt(original.get(field), 6):
				return None
		for field in ("qty", "stock_qty", "net_amount", "base_net_amount"):
			if flt(row.get(field), 6) != -flt(original.get(field), 6):
				return None
	if not seen or seen != set(original_items):
		return None

	taxes, original_taxes = doc.get("taxes", []), source.get("taxes", [])
	if len(taxes) != len(original_taxes):
		return None
	for row, original in zip(taxes, original_taxes):
		for field in ("account_head", "charge_type", "included_in_print_rate", "cost_center"):
			if row.get(field) != original.get(field):
				return None
		if row.get("charge_type") != "Actual" and flt(row.get("rate"), 6) != flt(original.get("rate"), 6):
			return None
		for field in ("tax_amount_after_discount_amount", "base_tax_amount_after_discount_amount"):
			if flt(row.get(field), 6) != -flt(original.get(field), 6):
				return None

	# Reject inconsistent historical rounded fields rather than inventing a reversal.
	for prefix in ("", "base_"):
		total = flt(source.get(prefix + "rounded_total"), 6)
		if total <= 0 or flt(total - flt(source.get(prefix + "grand_total")), 6) != flt(
			source.get(prefix + "rounding_adjustment"), 6
		):
			return None
	return {field: -flt(source.get(field)) for field in (
		"rounded_total", "rounding_adjustment", "base_rounded_total", "base_rounding_adjustment"
	)}


@frappe.whitelist()
def preview_original_return_rounding(return_doc):
	"""Read-only preview; saving always repeats eligibility against current records."""
	doc = frappe.get_doc(frappe.parse_json(return_doc))
	if doc.doctype != "Sales Invoice" or cint(doc.docstatus) != 0:
		return None
	doc.check_permission("create" if doc.is_new() else "write")
	if not doc.get("return_against"):
		return None
	frappe.get_doc("Sales Invoice", doc.return_against).check_permission("read")
	if doc.is_rounded_total_disabled() or not cint(
		frappe.get_single("WS Settings").get("enable_dynamic_rounding")
	):
		return None
	return get_original_return_rounding(doc)
