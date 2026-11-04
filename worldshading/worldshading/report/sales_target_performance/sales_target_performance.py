# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, nowdate


def execute(filters=None):
	filters = filters or {}
	target_name = filters.get("sales_target")
	if not target_name:
		frappe.throw(_("Sales Target is required."))

	target = frappe.get_doc("Sales Target", target_name)
	target.check_permission("read")
	if target.docstatus != 1:
		frappe.throw(_("Select a submitted Sales Target."))

	as_of_date = filters.get("as_of_date") or nowdate()
	if getdate(as_of_date) < getdate(target.from_date):
		aggregates = {}
	else:
		effective_to_date = (
			target.to_date
			if getdate(as_of_date) >= getdate(target.to_date)
			else as_of_date
		)
		aggregates = get_sales_aggregates(
			target.company, target.from_date, effective_to_date)

	rows = build_rows(
		target,
		aggregates,
		as_of_date,
		filters.get("sales_employee")
	)
	return get_columns(), rows


def get_columns():
	return [
		{"label": _("Rank"), "fieldname": "rank", "fieldtype": "Int", "width": 60},
		{"label": _("Sales Employee"), "fieldname": "sales_employee",
			"fieldtype": "Link", "options": "Employee", "width": 130},
		{"label": _("Employee Name"), "fieldname": "employee_name", "width": 170},
		{"label": _("Period Type"), "fieldname": "period_type", "width": 100},
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
		{"label": _("Invoice Count"), "fieldname": "invoice_count",
			"fieldtype": "Int", "width": 100},
		{"label": _("Status"), "fieldname": "status", "width": 105}
	]


def calculate_metrics(target_amount, achieved_amount, from_date, to_date,
		as_of_date):
	target = flt(target_amount)
	achieved = flt(achieved_amount)
	start = getdate(from_date)
	end = getdate(to_date)
	as_of = getdate(as_of_date)

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

	if achieved >= target:
		status = "Achieved"
	elif as_of >= end:
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


def get_sales_aggregates(company, from_date, effective_to_date):
	rows = frappe.db.sql("""
		select
			si.pb_sales_employee as sales_employee,
			sum(si.base_net_total) as achieved_amount,
			count(si.name) as invoice_count
		from `tabSales Invoice` si
		where si.docstatus = 1
			and si.company = %(company)s
			and si.posting_date between %(from_date)s and %(to_date)s
			and ifnull(si.pb_sales_employee, '') != ''
		group by si.pb_sales_employee
	""", {
		"company": company,
		"from_date": from_date,
		"to_date": effective_to_date
	}, as_dict=True)

	return dict((row.get("sales_employee"), {
		"achieved_amount": flt(row.get("achieved_amount")),
		"invoice_count": int(row.get("invoice_count") or 0)
	}) for row in rows)


def build_rows(target, aggregates, as_of_date, sales_employee=None):
	rows = []
	effective_to_date = str(min(getdate(as_of_date), getdate(target.to_date)))

	for target_row in target.targets:
		aggregate = aggregates.get(target_row.sales_employee, {})
		metrics = calculate_metrics(
			target_row.target_amount,
			aggregate.get("achieved_amount", 0),
			target.from_date,
			target.to_date,
			as_of_date
		)
		row = {
			"sales_target": target.name,
			"company": target.company,
			"currency": target.currency,
			"sales_employee": target_row.sales_employee,
			"employee_name": target_row.employee_name,
			"period_type": target.period_type,
			"from_date": target.from_date,
			"to_date": target.to_date,
			"effective_to_date": effective_to_date,
			"target_amount": flt(target_row.target_amount),
			"invoice_count": int(aggregate.get("invoice_count", 0))
		}
		row.update(metrics)
		rows.append(row)

	rows.sort(key=lambda row: (
		-flt(row.get("achievement_percent")),
		-flt(row.get("achieved_amount")),
		row.get("employee_name") or ""
	))
	for index, row in enumerate(rows):
		row["rank"] = index + 1

	if sales_employee:
		rows = [row for row in rows if row.get("sales_employee") == sales_employee]

	return rows
