# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import frappe
import math
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, nowdate, date_diff


class FixedExpense(Document):

	def validate(self):
		uses_accounts = self.get("doctype") and self.meta.has_field("accounts")
		if uses_accounts:
			self.validate_accounts()
		else:
			self.validate_expense_account()
		if flt(self.expected_amount) < 0:
			frappe.throw(_("Expected Amount / Budget cannot be negative."))
		if self.amount_type == "Fixed" and flt(self.expected_amount) <= 0:
			frappe.throw(_("Enter an Expected Amount greater than zero for a fixed expense."))
		self.validate_schedule()
		self.validate_payment_defaults()
		# Source changes may be deployed before the new fields are synchronized.
		if not uses_accounts and self.get("doctype") and self.meta.has_field("expected_total_amount"):
			self.update_payment_estimate()
		if self.get("doctype") and self.meta.has_field("estimated_base_total"):
			self.update_base_estimate()

	def update_base_estimate(self):
		self.estimated_base_total = 0
		self.estimate_exchange_rate = 0
		self.estimate_rate_date = None
		company_currency = frappe.db.get_value("Company", self.company, "default_currency")
		self.company_currency = company_currency
		if not company_currency or not self.currency:
			return
		today = getdate(nowdate())
		if self.currency == company_currency:
			return
		else:
			missing_rate_message = _("No valid recent exchange rate from {0} to {1}. Update Currency Exchange before saving.").format(self.currency, company_currency)
			rates = frappe.get_all("Currency Exchange", filters={
				"from_currency": self.currency, "to_currency": company_currency,
				"date": ["<=", today], "for_buying": 1
			}, fields=["exchange_rate", "date"], order_by="date desc, modified desc", limit_page_length=1)
			if not rates:
				frappe.throw(missing_rate_message)
			rate, rate_date = flt(rates[0].exchange_rate), getdate(rates[0].date)
			max_age = cint(frappe.db.get_single_value("WS Settings", "currency_exchange_max_age_days"))
			if max_age <= 0:
				max_age = 4
			if not math.isfinite(rate) or rate <= 0 or date_diff(today, rate_date) > max_age:
				frappe.throw(missing_rate_message)
		self.estimate_exchange_rate = flt(rate, self.precision("estimate_exchange_rate"))
		if self.estimate_exchange_rate <= 0:
			frappe.throw(missing_rate_message)
		self.estimate_rate_date = rate_date
		self.estimated_base_total = flt(flt(self.expected_total_amount) * self.estimate_exchange_rate,
			self.precision("estimated_base_total"))

	def validate_accounts(self):
		if not self.company:
			frappe.throw(_("Company is required."))
		self.company_currency = frappe.db.get_value("Company", self.company, "default_currency")
		if not self.company_currency:
			frappe.throw(_("Select a Company with a default currency."))
		if not self.currency:
			self.currency = self.company_currency
		if not self.get("accounts"):
			frappe.throw(_("Add at least one row to Accounts."))
		for row in self.accounts:
			if not row.account or not row.tax_template:
				frappe.throw(_("Row {0}: select an Account and Tax Template (including zero VAT or out of scope where applicable).").format(row.idx))
			account = frappe.db.get_value("Account", row.account,
				["company", "root_type", "is_group", "disabled", "account_currency"], as_dict=1)
			if (not account or account.company != self.company or account.root_type != "Expense"
				or cint(account.is_group) or cint(account.disabled) or account.account_currency != self.company_currency):
				frappe.throw(_("Row {0}: select an enabled, non-group expense account in company currency.").format(row.idx))
			if flt(row.net_amount) < 0:
				frappe.throw(_("Row {0}: Net Amount cannot be negative.").format(row.idx))
			tax = get_tax_details(self.company, self.company_currency, row.tax_template)
			row.currency = self.currency
			row.rate = tax["rate"]
			row.account_head = tax["account_head"]
			row.net_amount = flt(row.net_amount, row.precision("net_amount"))
			row.tax_amount = flt(row.net_amount * row.rate / 100, row.precision("tax_amount"))
			row.total_amount = flt(row.net_amount + row.tax_amount, row.precision("total_amount"))
		self.expected_amount = flt(sum(flt(row.net_amount) for row in self.accounts), self.precision("expected_amount"))
		self.expected_tax_amount = flt(sum(flt(row.tax_amount) for row in self.accounts), self.precision("expected_tax_amount"))
		self.expected_total_amount = flt(self.expected_amount + self.expected_tax_amount, self.precision("expected_total_amount"))
		# Retain legacy fields for compatibility; the table is now authoritative.
		self.expense_account = self.accounts[0].account
		self.tax_template = None

	def validate_payment_defaults(self):
		if self.get("cost_center"):
			cost_center = frappe.db.get_value("Cost Center", self.cost_center,
				["company", "is_group"], as_dict=1)
			if not cost_center or cost_center.company != self.company or cint(cost_center.is_group):
				frappe.throw(_("Select a non-group Cost Center belonging to this Company."))
		if self.get("payment_account"):
			company_currency = frappe.db.get_value("Company", self.company, "default_currency")
			account = frappe.db.get_value("Account", self.payment_account,
				["company", "account_type", "is_group", "disabled", "account_currency"], as_dict=1)
			if (not account or account.company != self.company
				or account.account_type not in ("Bank", "Cash")
				or cint(account.is_group) or cint(account.disabled)
				or account.account_currency != company_currency):
				frappe.throw(_("Payment Account must be an enabled, non-group Bank or Cash account in company currency."))

	def update_payment_estimate(self):
		rate = 0
		if self.get("tax_template"):
			rate = get_tax_details(self.company, self.currency, self.tax_template)["rate"]
		net_amount = flt(self.expected_amount, self.precision("expected_amount"))
		self.expected_tax_amount = flt(net_amount * rate / 100, self.precision("expected_tax_amount"))
		self.expected_total_amount = flt(net_amount + self.expected_tax_amount,
			self.precision("expected_total_amount"))

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


@frappe.whitelist()
def make_gl_payment(source_name):
	"""Prepare an unsaved payment for accounts to review through the normal workflow."""
	source = frappe.get_doc("Fixed Expense", source_name)
	source.check_permission("read")
	if not frappe.has_permission("GL Payment", "create"):
		frappe.throw(_("Not permitted to create GL Payments."), frappe.PermissionError)
	if source.status != "Active":
		frappe.throw(_("Only active Fixed Expenses can create a GL Payment."))
	# Revalidate the accounting defaults and refresh the exchange estimate in memory.
	# Do not save the source or create a payment until the user reviews it.
	source.validate()
	rate = source.estimate_exchange_rate if source.currency != source.company_currency else 1
	payment = frappe.new_doc("GL Payment")
	payment.update({
		"custom_fixed_expense": source.name,
		"company": source.company,
		"posting_date": nowdate(),
		"payment_type": "Outgoing",
		"cost_center": source.cost_center or frappe.db.get_value("Company", source.company, "cost_center"),
		"mode_of_payment": source.mode_of_payment,
		"payment_account": source.payment_account,
		"party_type": "Supplier",
		"party": source.supplier,
		"party_name": None,
		"tax_id": None,
		"reference_no": None,
		"reference_date": None,
		"remarks": _("Fixed Expense {0}: {1} — {2}").format(source.name, source.expense_name, source.provider_name)
	})
	if source.supplier:
		supplier = frappe.get_doc("Supplier", source.supplier)
		payment.party_name = supplier.supplier_name
		payment.tax_id = supplier.tax_id
	if source.currency != source.company_currency:
		payment.remarks += "\n" + _("Estimated from {0} {1} at {2} {3} per {0} (rate dated {4}).").format(
			source.currency, source.expected_total_amount, rate, source.company_currency, source.estimate_rate_date)
	payment.set("items", [])
	for account in source.accounts:
		row = payment.append("items", {
			"account": account.account,
			"template_type": "Purchase Taxes and Charges Template",
			"tax_template": account.tax_template,
			"rate": account.rate,
			"account_head": account.account_head,
			"remarks": account.remarks
		})
		row.net_amount = flt(account.net_amount * rate, payment.precision("net_amount", "items"))
		row.tax_amount = flt(row.net_amount * row.rate / 100, payment.precision("tax_amount", "items"))
		row.total_amount = flt(row.net_amount + row.tax_amount, payment.precision("total_amount", "items"))
	for field in ("net_amount", "tax_amount", "total_amount"):
		payment.set(field, flt(sum(flt(row.get(field)) for row in payment.items), payment.precision(field)))
	payment.check_permission("create")
	return payment.as_dict()


def get_tax_details(company, currency, tax_template):
	template = frappe.get_doc("Purchase Taxes and Charges Template", tax_template)
	if template.company != company or cint(template.disabled):
		frappe.throw(_("Select an enabled Purchase Tax Template belonging to this Company."))
	if len(template.taxes) != 1:
		frappe.throw(_("Select a Purchase Tax Template with exactly one percentage tax row."))
	tax = template.taxes[0]
	if (tax.charge_type != "On Net Total" or tax.add_deduct_tax != "Add"
		or cint(tax.included_in_print_rate) or tax.category not in ("Total", "Valuation and Total")
		or flt(tax.rate) < 0 or not tax.account_head):
		frappe.throw(_("This expense supports only an added percentage tax on the net amount, excluding inclusive or valuation-only taxes."))
	account = frappe.db.get_value("Account", tax.account_head,
		["company", "is_group", "disabled", "account_currency"], as_dict=1)
	if (not account or account.company != company or cint(account.is_group)
		or cint(account.disabled) or account.account_currency != currency):
		frappe.throw(_("The tax account must be enabled, non-group, and use this Company's currency."))
	return {"rate": flt(tax.rate), "account_head": tax.account_head}


@frappe.whitelist()
def get_expense_tax(company, tax_template):
	if not (frappe.has_permission("Fixed Expense", "read")
		or frappe.has_permission("Fixed Expense", "create")):
		frappe.throw(_("Not permitted to view recurring expenses."), frappe.PermissionError)
	currency = frappe.db.get_value("Company", company, "default_currency")
	if not currency:
		frappe.throw(_("Select a Company with a default currency."))
	return get_tax_details(company, currency, tax_template)
