from __future__ import unicode_literals

from frappe import _


def get_data(data):
	transactions = data.setdefault("transactions", [])
	sell_group_index = next((
		index for index, group in enumerate(transactions)
		if all(doctype in group.get("items", []) for doctype in (
			"Quotation", "Sales Order", "Delivery Note", "Sales Invoice"
		))
	), None)
	buy_group_index = next((
		index for index, group in enumerate(transactions)
		if "Purchase Order" in group.get("items", [])
	), None)
	packed_group = {
		"label": _("Sell - Packed Items"),
		"items": ["Quotation", "Sales Order", "Delivery Note", "Sales Invoice"],
	}
	if not any(group.get("label") == packed_group["label"] for group in transactions):
		if buy_group_index is not None:
			insert_at = buy_group_index + 1
		elif sell_group_index is not None:
			insert_at = sell_group_index + 1
		else:
			insert_at = len(transactions)
		transactions.insert(insert_at, packed_group)

	move_group = next((
		group for group in data.get("transactions", [])
		if "Stock Entry" in group.get("items", [])
	), None)
	if not move_group:
		move_group = {"label": _("Move"), "items": ["Stock Entry"]}
		transactions.append(move_group)

	if "Repack Request" not in move_group["items"]:
		move_group["items"].append("Repack Request")

	return data
