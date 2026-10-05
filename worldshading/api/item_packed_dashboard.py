from __future__ import unicode_literals

import frappe


TRANSACTION_TYPES = [
	"Quotation",
	"Sales Order",
	"Delivery Note",
	"Sales Invoice",
]


def get_packed_rows(item_code):
	return frappe.get_all(
		"Packed Item",
		filters={
			"item_code": item_code,
			"parenttype": ["in", TRANSACTION_TYPES],
		},
		fields=["parent", "parenttype"],
		limit_page_length=0,
	)


def get_visible_parent_map(transaction_type, parent_names):
	parent_names = list(set(parent_names or []))
	if not parent_names:
		return {}
	parents = frappe.get_list(
		transaction_type,
		filters={"name": ["in", parent_names]},
		fields=["name"],
		limit_page_length=0,
	)
	return dict((parent.name, parent) for parent in parents)


@frappe.whitelist()
def get_packed_transaction_counts(item_code):
	return get_packed_transaction_counts_value(item_code)


def get_packed_transaction_counts_value(item_code):
	counts = dict((transaction_type, 0) for transaction_type in TRANSACTION_TYPES)
	if not item_code:
		return counts

	parents_by_type = dict((transaction_type, set()) for transaction_type in TRANSACTION_TYPES)
	for row in get_packed_rows(item_code):
		if row.parenttype in parents_by_type:
			parents_by_type[row.parenttype].add(row.parent)

	for transaction_type in TRANSACTION_TYPES:
		counts[transaction_type] = len(get_visible_parent_map(
			transaction_type, parents_by_type[transaction_type]
		))
	return counts
