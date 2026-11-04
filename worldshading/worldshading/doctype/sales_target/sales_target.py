# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class SalesTarget(Document):
	def validate(self):
		_set_company_currency(self)
		_validate_dates(self)
		_validate_employee_rows(self)
		_set_total_target(self)

	def before_submit(self):
		_validate_no_overlap(self)


def _set_company_currency(doc):
	currency = frappe.db.get_value("Company", doc.company, "default_currency")
	if not currency:
		frappe.throw(_("Company {0} does not have a default currency.").format(
			doc.company))

	doc.currency = currency
	for row in doc.targets or []:
		row.currency = currency


def _validate_dates(doc):
	if not doc.from_date or not doc.to_date:
		frappe.throw(_("From Date and To Date are required."))

	if getdate(doc.to_date) < getdate(doc.from_date):
		frappe.throw(_("To Date cannot be before From Date."))


def _validate_employee_rows(doc):
	rows = doc.targets or []
	if not rows:
		frappe.throw(_("Add at least one employee target."))

	employee_ids = []
	seen = set()
	for row in rows:
		if not row.sales_employee:
			frappe.throw(_("Sales Employee is required in row {0}.").format(
				row.idx))
		if row.sales_employee in seen:
			frappe.throw(_("Sales Employee {0} is entered more than once.").format(
				row.sales_employee))
		if flt(row.target_amount) <= 0:
			frappe.throw(_("Target Amount must be greater than zero for {0}.").format(
				row.sales_employee))
		seen.add(row.sales_employee)
		employee_ids.append(row.sales_employee)

	employees = frappe.get_all(
		"Employee",
		filters={"name": ["in", employee_ids]},
		fields=["name", "status", "company"]
	)
	employee_map = dict((employee.get("name"), employee) for employee in employees)

	for employee_id in employee_ids:
		employee = employee_map.get(employee_id)
		if not employee:
			frappe.throw(_("Employee {0} does not exist.").format(employee_id))
		if employee.get("status") != "Active":
			frappe.throw(_("Employee {0} is not active.").format(employee_id))
		if employee.get("company") != doc.company:
			frappe.throw(_("Employee {0} does not belong to company {1}.").format(
				employee_id, doc.company))


def _set_total_target(doc):
	doc.total_target_amount = round(
		sum(flt(row.target_amount) for row in doc.targets or []), 3)


def _validate_no_overlap(doc):
	excluded_names = []
	if doc.name:
		excluded_names.append(doc.name)
	if doc.amended_from:
		excluded_names.append(doc.amended_from)

	conflicts = frappe.db.sql("""
		select
			p.name,
			d.sales_employee
		from `tabSales Target` p
		inner join `tabSales Target Detail` d
			on d.parent = p.name and d.parenttype = 'Sales Target'
		where p.docstatus = 1
			and p.name not in %(excluded_names)s
			and p.company = %(company)s
			and p.period_type = %(period_type)s
			and p.from_date <= %(to_date)s
			and p.to_date >= %(from_date)s
			and d.sales_employee in %(employee_ids)s
		order by p.from_date, p.name
		limit 1
	""", {
		"excluded_names": tuple(excluded_names or [""]),
		"company": doc.company,
		"period_type": doc.period_type,
		"from_date": doc.from_date,
		"to_date": doc.to_date,
		"employee_ids": tuple(row.sales_employee for row in doc.targets)
	}, as_dict=True)

	if conflicts:
		conflict = conflicts[0]
		frappe.throw(_(
			"Employee {0} already has an overlapping submitted {1} target in {2}."
		).format(
			conflict.get("sales_employee"), doc.period_type,
			conflict.get("name")))
