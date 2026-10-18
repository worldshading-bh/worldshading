from __future__ import unicode_literals

from frappe import _

from worldshading.dashboards.service_visit import add_service_visit


def get_data(data):
	data = add_service_visit(data, merge_into_reference=True)
	data.setdefault("internal_links", {}).setdefault("Project", "project")

	transactions = data.setdefault("transactions", [])
	if not any("Project" in group.get("items", []) for group in transactions):
		transactions.append({
			"label": _("Projects"),
			"items": ["Project"],
		})

	return data
