from __future__ import unicode_literals

from datetime import date

import frappe
from frappe.utils import cint, flt, getdate, today


STATUS_OPTIONS = ("", "Lost", "Decreased", "Stable", "Increased", "New", "Reactivated")
SORT_OPTIONS = (
	"Importance", "Decrease Amount", "Current Sales", "Previous Sales",
	"Inactive Days", "Current Invoice Count",
)
SORT_DIRECTIONS = ("Descending", "Ascending")
TOP_RESULT_OPTIONS = ("20", "50", "100", "250", "All")
STATUS_CHANGE_THRESHOLD = 20.0


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


def _year_metric(year_values, year, key):
	value = year_values.get(year, 0)
	if isinstance(value, dict):
		return value.get(key, 0)
	if key == "sales":
		return value
	return 0


def classify_customer(year_values, analysis_year, previous_years):
	current_sales = flt(_year_metric(year_values, analysis_year, "sales"))
	prior_sales = [
		flt(_year_metric(year_values, analysis_year - offset, "sales"))
		for offset in range(1, previous_years + 1)
	]
	previous_sales = prior_sales[0]

	if current_sales > 0 and not any(value > 0 for value in prior_sales):
		return "New"
	if current_sales > 0 and previous_sales <= 0 and any(value > 0 for value in prior_sales[1:]):
		return "Reactivated"
	if current_sales <= 0 and any(value > 0 for value in prior_sales):
		return "Lost"
	if current_sales > 0 and previous_sales > 0:
		change_percent = (current_sales - previous_sales) / previous_sales * 100.0
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
	previous_year = years[1]
	current_sales = flt(_year_metric(year_values, analysis_year, "sales"))
	previous_sales = flt(_year_metric(year_values, previous_year, "sales"))
	current_invoice_count = cint(_year_metric(year_values, analysis_year, "invoice_count"))
	previous_invoice_count = cint(_year_metric(year_values, previous_year, "invoice_count"))
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
			year_values, analysis_year, filters.previous_years
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


def get_sort_value(row, sort_by):
	fieldname = {
		"Importance": "previous_sales",
		"Decrease Amount": "decrease_amount",
		"Current Sales": "current_sales",
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
		annual_sales = [flt(row.get("current_sales"))]
		annual_sales.extend(
			flt(row.get("sales_{0}".format(year))) for year in prior_years
		)
		if not any(value != 0 for value in annual_sales):
			continue
		if max(annual_sales[1:]) < filters.minimum_historical_sales:
			continue
		if filters.retention_status and row.get("retention_status") != filters.retention_status:
			continue
		filtered_rows.append(row)

	filtered_rows.sort(key=lambda row: row.get("customer") or "")
	filtered_rows.sort(
		key=lambda row: get_sort_value(row, filters.sort_by),
		reverse=filters.sort_direction == "Descending",
	)
	if filters.top_results != "All":
		filtered_rows = filtered_rows[:cint(filters.top_results)]
	for index, row in enumerate(filtered_rows):
		row["rank"] = index + 1
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
	]
	values = {
		"company": filters.company,
		"start_date": start_date,
		"end_date": end_date,
	}
	for fieldname, sql_field in (
		("customer", "si.customer"),
		("customer_group", "customer.customer_group"),
		("territory", "customer.territory"),
	):
		if filters.get(fieldname):
			conditions.append("{0} = %({1})s".format(sql_field, fieldname))
			values[fieldname] = filters.get(fieldname)

	# Aggregate SQL is required here to process several calendar years in one
	# database pass and avoid one query per Customer.
	return frappe.db.sql("""
		select
			si.customer,
			customer.customer_name,
			customer.customer_group,
			customer.territory,
			year(si.posting_date) as sales_year,
			sum(si.base_net_total) as sales,
			count(distinct case
				when ifnull(si.is_return, 0) = 0 then si.name
			end) as invoice_count
		from `tabSales Invoice` si
		inner join `tabCustomer` customer on customer.name = si.customer
		where {conditions}
		group by si.customer, year(si.posting_date), customer.customer_name,
			customer.customer_group, customer.territory
	""".format(conditions=" and ".join(conditions)), values, as_dict=True)


def get_last_invoice_dates(filters, customers):
	if not customers:
		return {}
	unused_start_date, end_date = get_period_bounds(filters)
	rows = frappe.db.sql("""
		select si.customer, max(si.posting_date) as last_invoice_date
		from `tabSales Invoice` si
		where si.company = %(company)s
			and si.docstatus = 1
			and ifnull(si.is_return, 0) = 0
			and si.posting_date <= %(end_date)s
			and si.customer in %(customers)s
		group by si.customer
	""", {
		"company": filters.company,
		"end_date": end_date,
		"customers": tuple(customers),
	}, as_dict=True)
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


def enrich_rows(rows, filters):
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
		"label": "At-risk Previous Sales",
		"value": at_risk,
		"indicator": "red" if at_risk else "gray",
		"datatype": "Currency",
		"currency": currency,
	})
	return summary


def get_chart(rows):
	declines = [row for row in rows if flt(row.get("decrease_amount")) > 0][:10]
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


def get_message(filters, current_date=None):
	current_date = getdate(current_date or today())
	if (filters.analysis_year == current_date.year and
			current_date < date(current_date.year, 12, 31)):
		return (
			"The selected Analysis Year is in progress. Status uses year-to-date "
			"transactions compared with the complete previous calendar year; values "
			"are not annualized."
		)
	return None


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
		rows = enrich_rows(rows, filters)
	message = get_message(filters)
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
