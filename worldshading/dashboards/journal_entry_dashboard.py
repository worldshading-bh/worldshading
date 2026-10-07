from __future__ import unicode_literals

from frappe import _


def get_data(data):
	data.setdefault("fieldname", "journal_entry")

	transactions = data.setdefault("transactions", [])
	if any("GL Payment" in group.get("items", []) for group in transactions):
		return data

	payment_labels = (_("Payment"), _("Payments"))
	payment_group = next((
		group for group in transactions
		if group.get("label") in payment_labels
	), None)

	if not payment_group:
		payment_group = {
			"label": _("Payment"),
			"items": [],
		}
		transactions.append(payment_group)

	payment_group.setdefault("items", []).append("GL Payment")

	return data
