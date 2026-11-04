# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import date_diff, flt, getdate

from worldshading.worldshading.sales_target_utils import FREQUENCY_CONFIG


class SalesTarget(Document):
	def before_insert(self):
		_set_target_model(self)

	def validate(self):
		_set_company_currency(self)
		_validate_dates(self)
		_validate_employee_rows(self)
		_set_frequency_totals(self)

	def before_submit(self):
		_validate_amendment_source(self)
		_lock_company(self.company)
		_validate_no_overlap(self)


def _set_target_model(doc):
	doc.target_model = "Recurring Plan"


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

	if date_diff(doc.to_date, doc.from_date) + 1 > 366:
		frappe.throw(_("A recurring Sales Target plan cannot exceed 366 days."))


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

		has_positive_target = False
		for frequency, child_field, unused_parent_field in FREQUENCY_CONFIG:
			value = flt(getattr(row, child_field, 0))
			if value < 0:
				frappe.throw(_("{0} Target cannot be negative for {1}.").format(
					frequency, row.sales_employee))
			if value > 0:
				has_positive_target = True

		if not has_positive_target:
			frappe.throw(_(
				"Enter at least one positive target for {0}."
			).format(row.sales_employee))
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


def _set_frequency_totals(doc):
	for unused_frequency, child_field, parent_field in FREQUENCY_CONFIG:
		setattr(doc, parent_field, round(sum(
			flt(getattr(row, child_field, 0)) for row in doc.targets or []
		), 3))


def _validate_amendment_source(doc):
	if not doc.amended_from:
		return

	source_docstatus = frappe.db.get_value(
		"Sales Target", doc.amended_from, "docstatus")
	if source_docstatus != 2:
		frappe.throw(_(
			"Amended From must reference a cancelled Sales Target."))


def _lock_company(company):
	# The Company row is a stable per-company lock held until commit/rollback.
	# It serializes target submissions without introducing another lock table.
	frappe.db.sql("""
		select name
		from `tabCompany`
		where name = %(company)s
		for update
	""", {"company": company})


def _validate_no_overlap(doc):
	excluded_names = []
	if doc.name:
		excluded_names.append(doc.name)

	conflicts = frappe.db.sql("""
		select
			p.name,
			d.sales_employee,
			d.daily_target,
			d.weekly_target,
			d.monthly_target,
			d.quarterly_target,
			d.annual_target
		from `tabSales Target` p
		inner join `tabSales Target Detail` d
			on d.parent = p.name and d.parenttype = 'Sales Target'
		where p.docstatus = 1
			and p.name not in %(excluded_names)s
			and p.company = %(company)s
			and p.target_model = %(target_model)s
			and p.from_date <= %(to_date)s
			and p.to_date >= %(from_date)s
			and d.sales_employee in %(employee_ids)s
		order by p.from_date, p.name
		for update
	""", {
		"excluded_names": tuple(excluded_names or [""]),
		"company": doc.company,
		"target_model": "Recurring Plan",
		"from_date": doc.from_date,
		"to_date": doc.to_date,
		"employee_ids": tuple(row.sales_employee for row in doc.targets)
	}, as_dict=True)

	current_rows = dict(
		(row.sales_employee, row) for row in doc.targets or [])
	for conflict in conflicts:
		current_row = current_rows.get(conflict.get("sales_employee"))
		if not current_row:
			continue

		for frequency, child_field, unused_parent_field in FREQUENCY_CONFIG:
			if (flt(getattr(current_row, child_field, 0)) > 0 and
					flt(conflict.get(child_field)) > 0):
				frappe.throw(_(
					"Employee {0} already has an overlapping submitted "
					"{1} target in {2}."
				).format(
					conflict.get("sales_employee"), frequency,
					conflict.get("name")))
