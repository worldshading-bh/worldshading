from __future__ import unicode_literals

from frappe import _

from worldshading.dashboards.service_visit import add_service_visit


def get_data(data):
	data = add_service_visit(data)
	non_standard_fieldnames = data.setdefault("non_standard_fieldnames", {})
	non_standard_fieldnames["Payment Entry"] = "quotation"
	non_standard_fieldnames["Payment Request"] = "reference_name"
	dynamic_links = data.setdefault("dynamic_links", {})
	dynamic_links["reference_name"] = ["Quotation", "reference_doctype"]

	payment_group = next((
		group for group in data.transactions
		if group.get("label") in (_("Payment"), _("Payments"))
	), None)
	if not payment_group:
		payment_group = {
			"label": _("Payments"),
			"items": [],
		}
		data.transactions.append(payment_group)

	for doctype in ("Payment Entry", "Payment Request"):
		if doctype not in payment_group["items"]:
			payment_group["items"].append(doctype)

	return data
