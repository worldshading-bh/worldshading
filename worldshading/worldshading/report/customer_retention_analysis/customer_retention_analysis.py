from __future__ import unicode_literals

from bisect import bisect_right
from datetime import date

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today


STATUS_OPTIONS = ("", "Lost", "Decreased", "Stable", "Increased", "New", "Reactivated")
SORT_OPTIONS = (
	"Importance", "Decrease Amount", "Current Sales", "Comparison Sales", "Previous Sales",
	"Inactive Days", "Current Invoice Count",
)
SORT_DIRECTIONS = ("Descending", "Ascending")
TOP_RESULT_OPTIONS = ("20", "50", "100", "250", "All")
STATUS_CHANGE_THRESHOLD = 20.0
IMPORTANCE_VALUE_WEIGHT = 0.45
IMPORTANCE_DECREASE_WEIGHT = 0.45
IMPORTANCE_INACTIVITY_WEIGHT = 0.10


def normalize_filters(filters, current_year=None):
	filters = frappe._dict(filters or {})
	current_year = cint(current_year or today()[0:4])

	if not filters.get("company"):
		frappe.throw("Company is required")

	analysis_year = filters.get("analysis_year")
	comparison_year = filters.get("comparison_year")
	previous_years = filters.get("previous_years")
	top_results = filters.get("top_results")
	filters.analysis_year = cint(
		current_year if analysis_year in (None, "") else analysis_year
	)
	filters.comparison_year = cint(
		filters.analysis_year - 1
		if comparison_year in (None, "") else comparison_year
	)
	filters.previous_years = cint(
		1 if previous_years in (None, "") else previous_years
	)
	filters.retention_status = filters.get("retention_status") or ""
	filters.item_group = filters.get("item_group") or ""
	filters.minimum_historical_sales = flt(filters.get("minimum_historical_sales") or 0)
	filters.top_results = str("100" if top_results in (None, "") else top_results)
	filters.sort_by = filters.get("sort_by") or "Importance"
	filters.sort_direction = filters.get("sort_direction") or "Descending"

	if filters.analysis_year < 2000 or filters.analysis_year > current_year:
		frappe.throw("Analysis Year must be between 2000 and {0}".format(current_year))
	if filters.previous_years < 1 or filters.previous_years > 5:
		frappe.throw("Previous Years must be between 1 and 5")
	if filters.comparison_year >= filters.analysis_year \
			or filters.comparison_year < filters.analysis_year - 5:
		frappe.throw("Comparison Year must be within the five years before Analysis Year")
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


def get_reporting_years(filters):
	years = get_years(filters)
	comparison_year = cint(
		filters.get("comparison_year") or filters.analysis_year - 1
	)
	if comparison_year not in years:
		years.append(comparison_year)
	return years


def get_period_bounds(filters):
	years = get_reporting_years(filters)
	return date(min(years), 1, 1), date(filters.analysis_year, 12, 31)


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
	comparison_year = filters.comparison_year
	columns = [
		_column("Customer", "customer", "Link", 140, "Customer"),
		_column("Customer Name", "customer_name", width=190),
		_column("Customer Group", "customer_group", "Link", 130, "Customer Group"),
		_column("Territory", "territory", "Link", 120, "Territory"),
		_column("Retention Status", "retention_status", width=120),
		_column("Importance Score", "importance_score", "Float", 115),
		_column("{0} Sales".format(analysis_year), "current_sales", "Currency", 125, currency),
		_column("{0} Comparison Sales".format(comparison_year), "previous_sales", "Currency", 150, currency),
		_column("Change Amount", "change_amount", "Currency", 125, currency),
		_column("Change %", "change_percent", "Percent", 95),
		_column("Average Historical Sales", "average_historical_sales", "Currency", 150, currency),
		_column("{0} Invoice Count".format(analysis_year), "current_invoice_count", "Int", 125),
		_column("{0} Comparison Invoice Count".format(comparison_year), "previous_invoice_count", "Int", 165),
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
		_column("Next Follow-up", "next_follow_up", "Datetime", 145),
		_column("Number of Interactions", "number_of_interactions", "Int", 130),
	])
	return columns


def _year_metric(year_values, year, key):
	value = year_values.get(year, 0)
	if isinstance(value, dict):
		return value.get(key, 0)
	if key == "sales":
		return value
	return 0


def classify_customer(year_values, analysis_year, comparison_year, historical_years):
	current_sales = flt(_year_metric(year_values, analysis_year, "sales"))
	prior_sales = [
		flt(_year_metric(year_values, year, "sales")) for year in historical_years
	]
	comparison_sales = flt(_year_metric(year_values, comparison_year, "sales"))

	if current_sales > 0 and not any(value > 0 for value in prior_sales):
		return "New"
	if current_sales > 0 and comparison_sales <= 0 and any(
		flt(_year_metric(year_values, year, "sales")) > 0
		for year in historical_years if year != comparison_year
	):
		return "Reactivated"
	if current_sales <= 0 and any(value > 0 for value in prior_sales):
		return "Lost"
	if current_sales > 0 and comparison_sales > 0:
		change_percent = (current_sales - comparison_sales) / comparison_sales * 100.0
		if change_percent <= -STATUS_CHANGE_THRESHOLD:
			return "Decreased"
		if change_percent >= STATUS_CHANGE_THRESHOLD:
			return "Increased"
		return "Stable"
	return ""


def build_customer_row(customer, customer_context, year_values, last_invoice_date,
		filters, as_of_date):
	years = get_years(filters)
	analysis_year = years[0]
	comparison_year = filters.comparison_year
	current_sales = flt(_year_metric(year_values, analysis_year, "sales"))
	previous_sales = flt(_year_metric(year_values, comparison_year, "sales"))
	current_invoice_count = cint(_year_metric(year_values, analysis_year, "invoice_count"))
	previous_invoice_count = cint(_year_metric(year_values, comparison_year, "invoice_count"))
	historical_sales = [
		flt(_year_metric(year_values, year, "sales")) for year in years[1:]
	]
	change_amount = current_sales - previous_sales
	change_percent = None
	if previous_sales > 0:
		change_percent = change_amount / previous_sales * 100.0

	last_invoice_date = getdate(last_invoice_date) if last_invoice_date else None
	inactive_days = None
	if last_invoice_date:
		inactivity_end = min(getdate(as_of_date), date(analysis_year, 12, 31))
		inactive_days = max((inactivity_end - last_invoice_date).days, 0)

	row = {
		"customer": customer,
		"customer_name": customer_context.get("customer_name") or customer,
		"customer_group": customer_context.get("customer_group"),
		"territory": customer_context.get("territory"),
		"retention_status": classify_customer(
			year_values, analysis_year, comparison_year,
			get_reporting_years(filters)[1:]
		),
		"current_sales": current_sales,
		"previous_sales": previous_sales,
		"change_amount": change_amount,
		"decrease_amount": max(previous_sales - current_sales, 0),
		"change_percent": change_percent,
		"average_historical_sales": sum(historical_sales) / float(len(historical_sales)),
		"current_invoice_count": current_invoice_count,
		"previous_invoice_count": previous_invoice_count,
		"total_invoice_count": sum(
			cint(_year_metric(year_values, year, "invoice_count")) for year in years
		),
		"last_invoice_date": last_invoice_date,
		"inactive_days": inactive_days,
	}
	for year in years[1:]:
		row["sales_{0}".format(year)] = flt(_year_metric(year_values, year, "sales"))
	return row


def get_positive_percentile_ranks(rows, fieldname):
	positive_values = sorted(
		max(flt(row.get(fieldname)), 0) for row in rows
		if flt(row.get(fieldname)) > 0
	)
	if not positive_values:
		return [0.0 for unused_row in rows]
	total = float(len(positive_values))
	return [
		(bisect_right(positive_values, max(flt(row.get(fieldname)), 0)) / total * 100.0)
		if flt(row.get(fieldname)) > 0 else 0.0
		for row in rows
	]


def apply_importance_scores(rows):
	value_ranks = get_positive_percentile_ranks(rows, "average_historical_sales")
	decrease_ranks = get_positive_percentile_ranks(rows, "decrease_amount")
	inactivity_ranks = get_positive_percentile_ranks(rows, "inactive_days")
	for index, row in enumerate(rows):
		row["importance_score"] = (
			value_ranks[index] * IMPORTANCE_VALUE_WEIGHT
			+ decrease_ranks[index] * IMPORTANCE_DECREASE_WEIGHT
			+ inactivity_ranks[index] * IMPORTANCE_INACTIVITY_WEIGHT
		)
	return rows


def get_sort_value(row, sort_by):
	fieldname = {
		"Importance": "importance_score",
		"Decrease Amount": "decrease_amount",
		"Current Sales": "current_sales",
		"Comparison Sales": "previous_sales",
		"Previous Sales": "previous_sales",
		"Inactive Days": "inactive_days",
		"Current Invoice Count": "current_invoice_count",
	}[sort_by]
	value = row.get(fieldname)
	return -1 if value is None else flt(value)


def filter_sort_and_limit(rows, filters):
	prior_years = get_years(filters)[1:]
	filtered_rows = []
	for row in rows:
		historical_sales = [
			flt(row.get("sales_{0}".format(year))) for year in prior_years
		]
		reporting_sales = [flt(row.get("current_sales")), flt(row.get("previous_sales"))]
		reporting_sales.extend(historical_sales)
		if not any(value != 0 for value in reporting_sales):
			continue
		if max(historical_sales) < filters.minimum_historical_sales:
			continue
		if filters.retention_status and row.get("retention_status") != filters.retention_status:
			continue
		filtered_rows.append(row)

	apply_importance_scores(filtered_rows)
	filtered_rows.sort(key=lambda row: row.get("customer") or "")
	filtered_rows.sort(
		key=lambda row: get_sort_value(row, filters.sort_by),
		reverse=filters.sort_direction == "Descending",
	)
	if filters.top_results != "All":
		filtered_rows = filtered_rows[:cint(filters.top_results)]
	return filtered_rows


def get_company_context(company):
	company_doc = frappe.get_doc("Company", company)
	company_doc.check_permission("read")
	return company_doc.default_currency


def get_sales_activity(filters):
	start_date, end_date = get_period_bounds(filters)
	conditions = [
		"si.company = %(company)s",
		"si.docstatus = 1",
		"si.posting_date between %(start_date)s and %(end_date)s",
		"year(si.posting_date) in %(reporting_years)s",
	]
	values = {
		"company": filters.company,
		"start_date": start_date,
		"end_date": end_date,
		"reporting_years": tuple(get_reporting_years(filters)),
	}
	for fieldname, sql_field in (
		("customer", "si.customer"),
		("customer_group", "customer.customer_group"),
		("territory", "customer.territory"),
	):
		if filters.get(fieldname):
			conditions.append("{0} = %({1})s".format(sql_field, fieldname))
			values[fieldname] = filters.get(fieldname)

	from_clause = """from `tabSales Invoice` si
		inner join `tabCustomer` customer on customer.name = si.customer"""
	sales_expression = "sum(si.base_net_total)"
	if filters.get("item_group"):
		from_clause = """from `tabSales Invoice Item` sii
		inner join `tabSales Invoice` si on si.name = sii.parent
		inner join `tabItem` item on item.name = sii.item_code
		inner join `tabCustomer` customer on customer.name = si.customer"""
		sales_expression = "sum(sii.base_net_amount)"
		conditions.append("item.item_group = %(item_group)s")
		values["item_group"] = filters.item_group

	# Aggregate SQL is required here to process several calendar years in one
	# database pass and avoid one query per Customer.
	return frappe.db.sql("""
		select
			si.customer,
			customer.customer_name,
			customer.customer_group,
			customer.territory,
			year(si.posting_date) as sales_year,
			{sales_expression} as sales,
			count(distinct case
				when ifnull(si.is_return, 0) = 0 then si.name
			end) as invoice_count
		{from_clause}
		where {conditions}
		group by si.customer, year(si.posting_date), customer.customer_name,
			customer.customer_group, customer.territory
	""".format(
		sales_expression=sales_expression,
		from_clause=from_clause,
		conditions=" and ".join(conditions),
	), values, as_dict=True)


def get_last_invoice_dates(filters, customers):
	if not customers:
		return {}
	unused_start_date, end_date = get_period_bounds(filters)
	conditions = [
		"si.company = %(company)s",
		"si.docstatus = 1",
		"ifnull(si.is_return, 0) = 0",
		"si.posting_date <= %(end_date)s",
		"si.customer in %(customers)s",
	]
	values = {
		"company": filters.company,
		"end_date": end_date,
		"customers": tuple(customers),
	}
	if filters.get("item_group"):
		conditions.append("""exists (
			select 1
			from `tabSales Invoice Item` sii
			inner join `tabItem` item on item.name = sii.item_code
			where sii.parent = si.name
				and item.item_group = %(item_group)s
		)""")
		values["item_group"] = filters.item_group

	rows = frappe.db.sql("""
		select si.customer, max(si.posting_date) as last_invoice_date
		from `tabSales Invoice` si
		where {conditions}
		group by si.customer
	""".format(conditions=" and ".join(conditions)), values, as_dict=True)
	return dict((row["customer"], row["last_invoice_date"]) for row in rows)


def index_sales_activity(rows):
	indexed = {}
	for row in rows:
		customer = row["customer"]
		if customer not in indexed:
			indexed[customer] = {
				"context": {
					"customer_name": row.get("customer_name"),
					"customer_group": row.get("customer_group"),
					"territory": row.get("territory"),
				},
				"years": {},
			}
		indexed[customer]["years"][cint(row["sales_year"])] = {
			"sales": flt(row.get("sales")),
			"invoice_count": cint(row.get("invoice_count")),
		}
	return indexed


def get_item_group_context(filters, customers):
	if not customers:
		return {}
	start_date, end_date = get_period_bounds(filters)
	conditions = [
		"si.company = %(company)s",
		"si.docstatus = 1",
		"si.posting_date between %(start_date)s and %(end_date)s",
		"year(si.posting_date) in %(reporting_years)s",
		"si.customer in %(customers)s",
	]
	values = {
		"company": filters.company,
		"start_date": start_date,
		"end_date": end_date,
		"reporting_years": tuple(get_reporting_years(filters)),
		"customers": tuple(customers),
	}
	if filters.get("item_group"):
		conditions.append("item.item_group = %(item_group)s")
		values["item_group"] = filters.item_group

	rows = frappe.db.sql("""
		select
			si.customer,
			item.item_group,
			sum(sii.base_net_amount) as net_amount
		from `tabSales Invoice Item` sii
		inner join `tabSales Invoice` si on si.name = sii.parent
		inner join `tabItem` item on item.name = sii.item_code
		where {conditions}
		group by si.customer, item.item_group
	""".format(conditions=" and ".join(conditions)), values, as_dict=True)

	grouped = {}
	for row in rows:
		if not row.get("item_group") or flt(row.get("net_amount")) <= 0:
			continue
		grouped.setdefault(row["customer"], []).append({
			"item_group": row["item_group"],
			"net_amount": flt(row["net_amount"]),
		})

	context = {}
	for customer, customer_groups in grouped.items():
		customer_groups.sort(key=lambda row: row["item_group"])
		customer_groups.sort(key=lambda row: row["net_amount"], reverse=True)
		context[customer] = customer_groups[:3]
	return context


def get_campaign_context(customers):
	if not customers:
		return {}
	if not frappe.has_permission("Campaign Customer", "read"):
		return {}
	rows = frappe.db.sql("""
		select
			customer,
			name as campaign_customer,
			campaign,
			status as outreach_status,
			priority,
			planned_contact_date,
			next_follow_up,
			number_of_interactions
		from `tabCampaign Customer`
		where customer in %(customers)s
		order by customer, modified desc, name desc
	""", {"customers": tuple(customers)}, as_dict=True)

	context = {}
	fields = (
		"campaign_customer", "campaign", "outreach_status", "priority",
		"planned_contact_date", "next_follow_up", "number_of_interactions",
	)
	for row in rows:
		if row["customer"] not in context:
			context[row["customer"]] = dict(
				(fieldname, row.get(fieldname)) for fieldname in fields
			)
	return context


def apply_customer_context(rows, item_group_context, campaign_context):
	campaign_fields = (
		"campaign_customer", "campaign", "outreach_status", "priority",
		"planned_contact_date", "next_follow_up", "number_of_interactions",
	)
	for row in rows:
		groups = item_group_context.get(row["customer"], [])
		for index in range(3):
			group = groups[index] if index < len(groups) else {}
			row["top_item_group_{0}".format(index + 1)] = group.get("item_group")
			row["top_item_group_{0}_sales".format(index + 1)] = group.get("net_amount")
		campaign = campaign_context.get(row["customer"], {})
		for fieldname in campaign_fields:
			row[fieldname] = campaign.get(fieldname)
	return rows


def enrich_rows(rows, filters):
	filters = frappe._dict(filters or {})
	customers = [row["customer"] for row in rows]
	item_group_context = get_item_group_context(filters, customers)
	campaign_context = get_campaign_context(customers)
	rows = apply_customer_context(rows, item_group_context, campaign_context)
	period = ", ".join(
		str(year) for year in sorted(get_reporting_years(filters))
	)
	for row in rows:
		row["item_group_sales_period"] = period
	return rows


def get_report_summary(rows, currency):
	indicators = {
		"Lost": "red",
		"Decreased": "orange",
		"Stable": "gray",
		"Increased": "green",
		"New": "blue",
		"Reactivated": "purple",
	}
	summary = []
	for status in ("Lost", "Decreased", "Stable", "Increased", "New", "Reactivated"):
		summary.append({
			"label": status,
			"value": sum(1 for row in rows if row.get("retention_status") == status),
			"indicator": indicators[status],
			"datatype": "Int",
		})
	at_risk = sum(
		flt(row.get("previous_sales")) for row in rows
		if row.get("retention_status") in ("Lost", "Decreased")
	)
	summary.append({
		"label": "At-risk Comparison Sales",
		"value": at_risk,
		"indicator": "red" if at_risk else "gray",
		"datatype": "Currency",
		"currency": currency,
	})
	return summary


def get_chart(rows):
	declines = [row for row in rows if flt(row.get("decrease_amount")) > 0]
	declines.sort(key=lambda row: row.get("customer") or "")
	declines.sort(key=lambda row: flt(row.get("decrease_amount")), reverse=True)
	declines = declines[:10]
	if not declines:
		return None
	return {
		"data": {
			"labels": [row.get("customer_name") or row.get("customer") for row in declines],
			"datasets": [{
				"name": "Sales Decrease",
				"values": [flt(row.get("decrease_amount")) for row in declines],
			}],
		},
		"type": "bar",
		"title": "Largest Sales Decreases",
		"colors": ["#e74c3c"],
	}


def execute(filters=None):
	filters = normalize_filters(filters)
	currency = get_company_context(filters.company)
	columns = get_columns(filters, currency)
	sales_rows = get_sales_activity(filters)
	if not sales_rows:
		return (
			columns, [], "No customers matched the selected filters.", None,
			get_report_summary([], currency), 1,
		)

	activity = index_sales_activity(sales_rows)
	customers = sorted(activity.keys())
	last_invoice_dates = get_last_invoice_dates(filters, customers)
	rows = []
	for customer in customers:
		customer_activity = activity[customer]
		rows.append(build_customer_row(
			customer,
			customer_activity["context"],
			customer_activity["years"],
			last_invoice_dates.get(customer),
			filters,
			getdate(today()),
		))

	rows = filter_sort_and_limit(rows, filters)
	if rows:
		for row in rows:
			row["report_currency"] = currency
		rows = enrich_rows(rows, filters)
	message = None
	if not rows:
		message = "No customers matched the selected filters."
	return (
		columns,
		rows,
		message,
		get_chart(rows),
		get_report_summary(rows, currency),
		1,
	)


@frappe.whitelist()
def get_prepared_report_filters(prepared_report_name=None):
	if not prepared_report_name:
		frappe.throw(_("Prepared Report is required."))
	prepared = frappe.db.get_value(
		"Prepared Report", prepared_report_name,
		["report_name", "status", "owner"], as_dict=True
	)
	if not prepared \
			or prepared.report_name != "Customer Retention Analysis" \
			or prepared.status != "Completed":
		frappe.throw(_("The Prepared Report is invalid or incomplete."))
	if prepared.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You do not have permission to read this Prepared Report."),
			frappe.PermissionError,
		)
	raw_filters = frappe.db.get_value("Prepared Report", prepared_report_name, "filters")
	filters = frappe.parse_json(raw_filters) if isinstance(raw_filters, str) else raw_filters
	return filters if isinstance(filters, dict) else {}
