from __future__ import unicode_literals

from datetime import date

import frappe
from frappe.utils import cint, flt, today


STATUS_OPTIONS = ("", "Lost", "Decreased", "Stable", "Increased", "New", "Reactivated")
SORT_OPTIONS = (
	"Importance", "Decrease Amount", "Current Sales", "Previous Sales",
	"Inactive Days", "Current Invoice Count",
)
SORT_DIRECTIONS = ("Descending", "Ascending")
TOP_RESULT_OPTIONS = ("20", "50", "100", "250", "All")


def normalize_filters(filters, current_year=None):
	filters = frappe._dict(filters or {})
	current_year = cint(current_year or today()[0:4])

	if not filters.get("company"):
		frappe.throw("Company is required")

	analysis_year = filters.get("analysis_year")
	previous_years = filters.get("previous_years")
	top_results = filters.get("top_results")
	filters.analysis_year = cint(
		current_year if analysis_year in (None, "") else analysis_year
	)
	filters.previous_years = cint(
		1 if previous_years in (None, "") else previous_years
	)
	filters.retention_status = filters.get("retention_status") or ""
	filters.minimum_historical_sales = flt(filters.get("minimum_historical_sales") or 0)
	filters.top_results = str("100" if top_results in (None, "") else top_results)
	filters.sort_by = filters.get("sort_by") or "Importance"
	filters.sort_direction = filters.get("sort_direction") or "Descending"

	if filters.analysis_year < 2000 or filters.analysis_year > current_year:
		frappe.throw("Analysis Year must be between 2000 and {0}".format(current_year))
	if filters.previous_years < 1 or filters.previous_years > 5:
		frappe.throw("Previous Years must be between 1 and 5")
	if filters.minimum_historical_sales < 0:
		frappe.throw("Minimum Historical Sales cannot be negative")
	if filters.retention_status not in STATUS_OPTIONS:
		frappe.throw("Invalid Retention Status")
	if filters.sort_by not in SORT_OPTIONS:
		frappe.throw("Invalid Sort By value")
	if filters.sort_direction not in SORT_DIRECTIONS:
		frappe.throw("Invalid Sort Direction")
	if filters.top_results not in TOP_RESULT_OPTIONS:
		frappe.throw("Invalid Top Results value")

	return filters


def get_years(filters):
	return [filters.analysis_year - offset for offset in range(filters.previous_years + 1)]


def get_period_bounds(filters):
	years = get_years(filters)
	return date(years[-1], 1, 1), date(years[0], 12, 31)


def _column(label, fieldname, fieldtype="Data", width=110, options=None):
	column = {
		"label": label,
		"fieldname": fieldname,
		"fieldtype": fieldtype,
		"width": width,
	}
	if options:
		column["options"] = options
	return column


def get_columns(filters, currency):
	analysis_year = filters.analysis_year
	previous_year = analysis_year - 1
	columns = [
		_column("Rank", "rank", "Int", 65),
		_column("Customer", "customer", "Link", 140, "Customer"),
		_column("Customer Name", "customer_name", width=190),
		_column("Customer Group", "customer_group", "Link", 130, "Customer Group"),
		_column("Territory", "territory", "Link", 120, "Territory"),
		_column("Retention Status", "retention_status", width=120),
		_column("{0} Sales".format(analysis_year), "current_sales", "Currency", 125, currency),
		_column("{0} Sales".format(previous_year), "previous_sales", "Currency", 125, currency),
		_column("Change Amount", "change_amount", "Currency", 125, currency),
		_column("Change %", "change_percent", "Percent", 95),
		_column("Average Historical Sales", "average_historical_sales", "Currency", 150, currency),
		_column("{0} Invoice Count".format(analysis_year), "current_invoice_count", "Int", 125),
		_column("{0} Invoice Count".format(previous_year), "previous_invoice_count", "Int", 125),
		_column("Total Invoice Count", "total_invoice_count", "Int", 120),
		_column("Last Invoice Date", "last_invoice_date", "Date", 115),
		_column("Inactive Days", "inactive_days", "Int", 100),
	]

	for year in get_years(filters)[1:]:
		columns.append(_column(
			"{0} Sales".format(year), "sales_{0}".format(year), "Currency", 115, currency
		))

	columns.extend([
		_column("Top Item Group 1", "top_item_group_1", "Link", 140, "Item Group"),
		_column("Top Item Group 2", "top_item_group_2", "Link", 140, "Item Group"),
		_column("Top Item Group 3", "top_item_group_3", "Link", 140, "Item Group"),
		_column("Campaign Customer", "campaign_customer", "Link", 145, "Campaign Customer"),
		_column("Campaign", "campaign", "Link", 130, "Campaign"),
		_column("Outreach Status", "outreach_status", width=120),
		_column("Priority", "priority", width=90),
		_column("Planned Contact Date", "planned_contact_date", "Date", 125),
		_column("Next Follow-up", "next_follow_up", "Date", 115),
		_column("Number of Interactions", "number_of_interactions", "Int", 130),
	])
	return columns
