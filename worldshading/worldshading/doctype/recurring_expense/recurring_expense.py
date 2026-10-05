# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate


class RecurringExpense(Document):

	def validate(self):
		self.validate_expense_account()
		if flt(self.expected_amount) < 0:
			frappe.throw(_("Expected Amount / Budget cannot be negative."))
		if self.amount_type == "Fixed" and flt(self.expected_amount) <= 0:
			frappe.throw(_("Enter an Expected Amount greater than zero for a fixed expense."))
		self.validate_provider_amount()
		self.validate_schedule()

	def validate_expense_account(self):
		if not self.company or not self.expense_account:
			frappe.throw(_("Company and Expense Ledger are required."))
		self.currency = frappe.db.get_value("Company", self.company, "default_currency")
		if not self.currency:
			frappe.throw(_("Select a Company with a default currency."))
		account = frappe.db.get_value(
			"Account", self.expense_account,
			["company", "root_type", "is_group", "disabled", "account_currency"],
			as_dict=1
		)
		if not account or account.company != self.company:
			frappe.throw(_("Expense Ledger must belong to the selected Company."))
		if account.root_type != "Expense" or cint(account.is_group) or cint(account.disabled):
			frappe.throw(_("Select an enabled Expense Ledger that is not a group."))
		if account.account_currency != self.currency:
			frappe.throw(_("Expense Ledger must use company currency {0}.").format(self.currency))

	def validate_provider_amount(self):
		provider_amount = flt(self.provider_amount)
		if self.billing_currency and provider_amount <= 0:
			frappe.throw(_("Enter a Billing Amount greater than zero."))
		if not self.billing_currency and provider_amount:
			frappe.throw(_("Select the Billing Currency."))

	def validate_schedule(self):
		if self.status == "Closed" and not self.end_date:
			frappe.throw(_("End Date is required when the recurring expense is Closed."))
		if self.start_date and self.first_due_date:
			if getdate(self.first_due_date) < getdate(self.start_date):
				frappe.throw(_("First Due Date cannot be before Start Date."))
		if self.end_date:
			if self.start_date and getdate(self.end_date) < getdate(self.start_date):
				frappe.throw(_("End Date cannot be before Start Date."))
			if self.first_due_date and getdate(self.end_date) < getdate(self.first_due_date):
				frappe.throw(_("End Date cannot be before First Due Date."))
