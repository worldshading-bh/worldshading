from __future__ import unicode_literals

import frappe
from frappe import _


def add_service_visit(data, merge_into_reference=False):
	data = frappe._dict(data)

	internal_links = data.setdefault("internal_links", frappe._dict())
	internal_links["Service Visit"] = "service_visit"

	transactions = list(data.get("transactions") or [])

	if not _has_transaction(transactions, "Service Visit"):
		if merge_into_reference:
			_append_to_reference_group(transactions)
		else:
			transactions.append({
				"label": _("Service"),
				"items": ["Service Visit"],
			})

	data.transactions = transactions

	return data


def _append_to_reference_group(transactions):
	for group in transactions:
		if "Quotation" in (group.get("items") or []):
			group.setdefault("items", []).append("Service Visit")
			return

	# fallback if Reference group is missing
	transactions.append({
		"label": _("Reference"),
		"items": ["Service Visit"],
	})


def _has_transaction(transactions, doctype):
	for group in transactions:
		if doctype in (group.get("items") or []):
			return True

	return False