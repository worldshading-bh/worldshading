from __future__ import unicode_literals

from frappe import _


def get_data(data):
	data.setdefault("fieldname", "gl_payment")

	internal_links = data.setdefault("internal_links", {})
	internal_links["Purchase Order"] = "purchase_order"
	internal_links["Journal Entry"] = "journal_entry"

	transactions = data.setdefault("transactions", [])
	reference_label = _("Reference")
	reference_group = next((
		group for group in transactions
		if group.get("label") == reference_label
	), None)

	for doctype in ("Purchase Order", "Journal Entry"):
		if any(doctype in group.get("items", []) for group in transactions):
			continue
		if not reference_group:
			reference_group = {
				"label": reference_label,
				"items": [],
			}
			transactions.append(reference_group)
		reference_group.setdefault("items", []).append(doctype)

	return data
