from __future__ import unicode_literals

from frappe import _


REFERENCE_LINKS = (
	("Sales Invoice", "references"),
	("Purchase Invoice", "references"),
	("Sales Order", "references"),
	("Purchase Order", "references"),
	("Journal Entry", "references"),
	("Expense Claim", "references"),
	("Employee Advance", "references"),
	("Fees", "references"),
)

UNUSED_LINKS = ("Payment Order", "Payment Entry", "Auto Repeat")


def _add_transaction_item(transactions, label, doctype):
	if any(doctype in group.get("items", []) for group in transactions):
		return

	group = next((
		group for group in transactions
		if group.get("label") == label
	), None)

	if not group:
		group = {
			"label": label,
			"items": [],
		}
		transactions.append(group)

	group.setdefault("items", []).append(doctype)


def _remove_unused_links(transactions):
	for group in transactions:
		group["items"] = [
			item for item in group.get("items", [])
			if item not in UNUSED_LINKS
		]
	transactions[:] = [group for group in transactions if group.get("items")]


def _move_online_payment_last(transactions):
	label = _("Online Payment")
	items = []
	remaining_groups = []

	for group in transactions:
		group_items = [
			item for item in group.get("items", [])
			if item != "WS Payment Transaction"
		]
		if group.get("label") == label:
			items.extend(group_items)
		elif group_items:
			group["items"] = group_items
			remaining_groups.append(group)

	items.append("WS Payment Transaction")
	remaining_groups.append({
		"label": label,
		"items": list(dict.fromkeys(items)),
	})
	transactions[:] = remaining_groups


def get_data(data):
	data.setdefault("fieldname", "payment_entry")

	internal_links = data.setdefault("internal_links", {})
	for doctype, table_fieldname in REFERENCE_LINKS:
		internal_links.setdefault(
			doctype, [table_fieldname, "reference_name"]
		)
	for doctype, fieldname in (
		("Quotation", "quotation"),
		("Service Visit", "service_visit"),
		("Project", "project"),
	):
		internal_links.setdefault(doctype, fieldname)
	for doctype in UNUSED_LINKS:
		internal_links.pop(doctype, None)

	non_standard_fieldnames = data.setdefault("non_standard_fieldnames", {})
	non_standard_fieldnames.setdefault(
		"WS Payment Transaction", "payment_entry"
	)
	for doctype in UNUSED_LINKS:
		non_standard_fieldnames.pop(doctype, None)

	transactions = data.setdefault("transactions", [])
	_remove_unused_links(transactions)
	for doctype, unused_fieldname in REFERENCE_LINKS:
		_add_transaction_item(transactions, _("Reference"), doctype)
	for doctype in ("Quotation", "Service Visit", "Project"):
		_add_transaction_item(transactions, _("Reference"), doctype)
	_move_online_payment_last(transactions)

	return data
