# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, nowdate

from worldshading.worldshading.sales_target_utils import (
	FREQUENCY_CONFIG,
	get_frequency_config,
	get_occurrence,
)


def execute(filters=None):
	filters = filters or {}
	target_name = filters.get("sales_target")
	frequency = filters.get("frequency")
	if not target_name:
		frappe.throw(_("Sales Target is required."))

	target = frappe.get_doc("Sales Target", target_name)
	target.check_permission("read")
	if target.docstatus != 1:
		frappe.throw(_("Select a submitted Sales Target."))
	if target.target_model != "Recurring Plan":
		frappe.throw(_("Select a recurring Sales Target plan."))

	frequency_config = get_frequency_config(frequency) if frequency else None
	if frequency and not frequency_config:
		frappe.throw(_("Select a valid Frequency."))

	current_date = nowdate()
	as_of_date = filters.get("as_of_date") or current_date
	if getdate(as_of_date) > getdate(current_date):
		frappe.throw(_("As of Date cannot be in the future."))

	frequencies = (
		[frequency] if frequency else get_configured_frequencies(target))
	occurrences = dict((label, get_occurrence(
		label, as_of_date, target.from_date, target.to_date))
		for label in frequencies)
	employee_ids = get_target_employee_ids(target, frequencies)

	if frequency:
		aggregates = {}
		occurrence = occurrences[frequency]
		if not occurrence["not_started"] and employee_ids:
			aggregates = get_sales_aggregates(
				target.company,
				occurrence["from_date"],
				occurrence["effective_to_date"],
				employee_ids
			)
		team_rows = build_rows(
			target, frequency, occurrence, aggregates, as_of_date, current_date)
		summary = get_report_summary(team_rows, target.currency)
	else:
		date_aggregates = {}
		if frequencies and employee_ids and not all(
				occurrences[label]["not_started"] for label in frequencies):
			date_aggregates = get_sales_aggregates_by_date(
				target.company,
				min(occurrences[label]["from_date"] for label in frequencies),
				max(occurrences[label]["effective_to_date"]
					for label in frequencies),
				employee_ids
			)
		team_rows = build_frequency_rows(
			target, frequencies, occurrences, date_aggregates,
			as_of_date, current_date)

	rows = team_rows
	if filters.get("sales_employee"):
		rows = [row for row in team_rows
			if row.get("sales_employee") == filters.get("sales_employee")]
	if not frequency:
		summary = get_frequency_summary(rows, frequencies)

	return get_columns(), rows, None, None, summary, 1


def get_configured_frequencies(target):
	return [config[0] for config in FREQUENCY_CONFIG if any(
		flt(getattr(row, config[1], 0)) > 0 for row in target.targets)]


def get_target_employee_ids(target, frequencies):
	child_fields = [get_frequency_config(label)[1] for label in frequencies]
	return tuple(row.sales_employee for row in target.targets if any(
		flt(getattr(row, fieldname, 0)) > 0 for fieldname in child_fields))


def get_columns():
	return [
		{"label": _("Rank"), "fieldname": "rank", "fieldtype": "Int", "width": 60},
		{"label": _("Sales Employee"), "fieldname": "sales_employee",
			"fieldtype": "Link", "options": "Employee", "width": 130},
		{"label": _("Employee Name"), "fieldname": "employee_name", "width": 170},
		{"label": _("Frequency"), "fieldname": "frequency", "width": 90},
		{"label": _("From Date"), "fieldname": "from_date",
			"fieldtype": "Date", "width": 95},
		{"label": _("To Date"), "fieldname": "to_date",
			"fieldtype": "Date", "width": 95},
		{"label": _("Target Amount"), "fieldname": "target_amount",
			"fieldtype": "Currency", "options": "currency", "width": 130},
		{"label": _("Achieved Amount"), "fieldname": "achieved_amount",
			"fieldtype": "Currency", "options": "currency", "width": 140},
		{"label": _("Achievement %"), "fieldname": "achievement_percent",
			"fieldtype": "Percent", "width": 115},
		{"label": _("Expected Amount"), "fieldname": "expected_amount",
			"fieldtype": "Currency", "options": "currency", "width": 135},
		{"label": _("Progress Variance"), "fieldname": "progress_variance",
			"fieldtype": "Currency", "options": "currency", "width": 135},
		{"label": _("Remaining Amount"), "fieldname": "remaining_amount",
			"fieldtype": "Currency", "options": "currency", "width": 140},
		{"label": _("Over Target Amount"), "fieldname": "over_target_amount",
			"fieldtype": "Currency", "options": "currency", "width": 145},
		{"label": _("Required Daily Run Rate"),
			"fieldname": "required_daily_run_rate", "fieldtype": "Currency",
			"options": "currency", "width": 165},
		{"label": _("Contribution %"), "fieldname": "contribution_percent",
			"fieldtype": "Percent", "width": 115},
		{"label": _("Invoice Count"), "fieldname": "invoice_count",
			"fieldtype": "Int", "width": 100},
		{"label": _("Status"), "fieldname": "status", "width": 105}
	]


def calculate_metrics(target_amount, achieved_amount, from_date, to_date,
		as_of_date, current_date=None):
	target = flt(target_amount)
	achieved = flt(achieved_amount)
	start = getdate(from_date)
	end = getdate(to_date)
	as_of = getdate(as_of_date)
	current = getdate(current_date or nowdate())

	if as_of < start:
		return {
			"achieved_amount": 0,
			"achievement_percent": 0,
			"expected_amount": 0,
			"progress_variance": 0,
			"remaining_amount": max(target, 0),
			"over_target_amount": 0,
			"required_daily_run_rate": 0,
			"status": "Not Started"
		}

	effective_date = min(as_of, end)
	total_days = date_diff(end, start) + 1
	elapsed_days = date_diff(effective_date, start) + 1
	expected = target * elapsed_days / total_days if total_days > 0 else target
	achievement_percent = achieved / target * 100 if target else 0
	remaining = max(target - achieved, 0)
	over_target = max(achieved - target, 0)
	remaining_days = max(date_diff(end, effective_date), 0)
	required_daily = remaining / remaining_days if remaining_days and remaining else 0
	occurrence_ended = as_of > end or (as_of == end and end < current)

	if achieved >= target:
		status = "Achieved"
	elif occurrence_ended:
		status = "Not Achieved"
	elif achieved >= expected:
		status = "On Track"
	else:
		status = "Behind"

	return {
		"achieved_amount": achieved,
		"achievement_percent": achievement_percent,
		"expected_amount": expected,
		"progress_variance": achieved - expected,
		"remaining_amount": remaining,
		"over_target_amount": over_target,
		"required_daily_run_rate": required_daily,
		"status": status
	}


def get_sales_aggregates(company, from_date, effective_to_date, employee_ids):
	rows = frappe.db.sql("""
		select
			si.pb_sales_employee as sales_employee,
			sum(si.base_net_total) as achieved_amount,
			count(si.name) as invoice_count
		from `tabSales Invoice` si
		where si.docstatus = 1
			and si.company = %(company)s
			and si.posting_date between %(from_date)s and %(to_date)s
			and si.pb_sales_employee in %(employee_ids)s
		group by si.pb_sales_employee
	""", {
		"company": company,
		"from_date": from_date,
		"to_date": effective_to_date,
		"employee_ids": tuple(employee_ids)
	}, as_dict=True)

	return dict((row.get("sales_employee"), {
		"achieved_amount": flt(row.get("achieved_amount")),
		"invoice_count": int(row.get("invoice_count") or 0)
	}) for row in rows)


def get_sales_aggregates_by_date(company, from_date, effective_to_date,
		employee_ids):
	rows = frappe.db.sql("""
		select
			si.pb_sales_employee as sales_employee,
			si.posting_date,
			sum(si.base_net_total) as achieved_amount,
			count(si.name) as invoice_count
		from `tabSales Invoice` si
		where si.docstatus = 1
			and si.company = %(company)s
			and si.posting_date between %(from_date)s and %(to_date)s
			and si.pb_sales_employee in %(employee_ids)s
		group by si.pb_sales_employee, si.posting_date
	""", {
		"company": company,
		"from_date": from_date,
		"to_date": effective_to_date,
		"employee_ids": tuple(employee_ids)
	}, as_dict=True)

	aggregates = {}
	for row in rows:
		employee = row.get("sales_employee")
		posting_date = getdate(row.get("posting_date"))
		aggregates.setdefault(employee, {})[posting_date] = {
			"achieved_amount": flt(row.get("achieved_amount")),
			"invoice_count": int(row.get("invoice_count") or 0)
		}
	return aggregates


def build_frequency_rows(target, frequencies, occurrences, date_aggregates,
		as_of_date, current_date):
	rows = []
	for frequency in frequencies:
		occurrence = occurrences[frequency]
		aggregates = {}
		if not occurrence["not_started"]:
			from_date = getdate(occurrence["from_date"])
			to_date = getdate(occurrence["effective_to_date"])
			for employee, daily_values in date_aggregates.items():
				matching = [value for posting_date, value in daily_values.items()
					if from_date <= getdate(posting_date) <= to_date]
				if matching:
					aggregates[employee] = {
						"achieved_amount": sum(flt(value.get("achieved_amount"))
							for value in matching),
						"invoice_count": sum(int(value.get("invoice_count") or 0)
							for value in matching)
					}
		rows.extend(build_rows(
			target, frequency, occurrence, aggregates, as_of_date, current_date))
	return rows


def build_rows(target, frequency, occurrence, aggregates, as_of_date,
		current_date):
	frequency_config = get_frequency_config(frequency)
	child_field = frequency_config[1]
	rows = []

	for target_row in target.targets:
		target_amount = flt(getattr(target_row, child_field, 0))
		if target_amount <= 0:
			continue

		aggregate = aggregates.get(target_row.sales_employee, {})
		metrics = calculate_metrics(
			target_amount,
			aggregate.get("achieved_amount", 0),
			occurrence["from_date"],
			occurrence["to_date"],
			as_of_date,
			current_date
		)
		row = {
			"sales_target": target.name,
			"company": target.company,
			"currency": target.currency,
			"sales_employee": target_row.sales_employee,
			"employee_name": target_row.employee_name,
			"frequency": frequency,
			"from_date": str(occurrence["from_date"]),
			"to_date": str(occurrence["to_date"]),
			"effective_to_date": str(occurrence["effective_to_date"]),
			"target_amount": target_amount,
			"invoice_count": int(aggregate.get("invoice_count", 0))
		}
		row.update(metrics)
		rows.append(row)

	team_achieved = sum(flt(row.get("achieved_amount")) for row in rows)
	for row in rows:
		row["contribution_percent"] = (
			flt(row.get("achieved_amount")) / team_achieved * 100
			if team_achieved else 0
		)

	rows.sort(key=lambda row: (
		-flt(row.get("achievement_percent")),
		-flt(row.get("achieved_amount")),
		row.get("employee_name") or ""
	))
	for index, row in enumerate(rows):
		row["rank"] = index + 1

	return rows


def get_report_summary(rows, currency):
	team_target = sum(flt(row.get("target_amount")) for row in rows)
	team_achieved = sum(flt(row.get("achieved_amount")) for row in rows)
	team_percent = team_achieved / team_target * 100 if team_target else 0
	achieved_count = sum(1 for row in rows if row.get("status") == "Achieved")
	on_track_count = sum(1 for row in rows if row.get("status") == "On Track")
	behind_count = sum(1 for row in rows
		if row.get("status") in ("Behind", "Not Achieved"))

	return [
		{"label": _("Team Target"), "value": team_target,
			"datatype": "Currency", "currency": currency},
		{"label": _("Team Achieved"), "value": team_achieved,
			"datatype": "Currency", "currency": currency},
		{"label": _("Team Achievement %"), "value": team_percent,
			"datatype": "Percent"},
		{"label": _("Achieved"), "value": achieved_count, "datatype": "Int"},
		{"label": _("On Track"), "value": on_track_count, "datatype": "Int"},
		{"label": _("Behind"), "value": behind_count, "datatype": "Int"}
	]


def get_frequency_summary(rows, frequencies):
	summary = []
	for frequency in frequencies:
		frequency_rows = [row for row in rows
			if row.get("frequency") == frequency]
		if not frequency_rows:
			continue
		target = sum(flt(row.get("target_amount")) for row in frequency_rows)
		achieved = sum(flt(row.get("achieved_amount")) for row in frequency_rows)
		percentage = achieved / target * 100 if target else 0
		summary.append({
			"label": _("{0} Achievement %").format(frequency),
			"value": percentage,
			"datatype": "Percent",
			"indicator": "green" if percentage >= 100 else "red"
		})
	return summary
