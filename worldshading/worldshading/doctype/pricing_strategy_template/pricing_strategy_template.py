# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class PricingStrategyTemplate(Document):

	def validate(self):
		self.validate_default_strategy()
		self.validate_percentages()
		self.validate_expense_account()
		self.validate_price_lists()
		self.validate_quantity_tiers()

	def validate_default_strategy(self):
		if not self.is_default:
			return
		if not self.enabled:
			frappe.throw(_("A disabled Pricing Strategy cannot be the default."))
		existing = frappe.db.get_value(
			"Pricing Strategy Template",
			{
				"company": self.company,
				"enabled": 1,
				"is_default": 1,
				"name": ["!=", self.name or ""]
			},
			"name"
		)
		if existing:
			frappe.throw(_(
				"{0} is already the default Pricing Strategy for {1}."
			).format(existing, self.company))

	def validate_percentages(self):
		fields = ["vat_percent", "regular_markup"]
		if self.b2b_price_list:
			fields.append("b2b_markup")
		for fieldname in fields:
			if flt(self.get(fieldname)) < 0:
				frappe.throw(_("{0} cannot be negative.").format(
					self.meta.get_label(fieldname)
				))

	def validate_expense_account(self):
		if self.expense_treatment == "Exclude Expense":
			return
		if not self.indirect_expense_account:
			frappe.throw(_("Indirect Expense Account is required when expenses are included."))
		account = frappe.db.get_value(
			"Account", self.indirect_expense_account,
			["company", "root_type"], as_dict=1
		)
		if not account or account.company != self.company:
			frappe.throw(_("Indirect Expense Account must belong to {0}.").format(
				self.company
			))
		if account.root_type != "Expense":
			frappe.throw(_("Indirect Expense Account must be an Expense account."))

	def validate_price_lists(self):
		company_currency = frappe.db.get_value("Company", self.company, "default_currency")
		if not company_currency:
			frappe.throw(_("Company {0} has no default currency.").format(self.company))

		self.validate_price_list(self.regular_price_list, company_currency, _("Regular"))
		if self.b2b_price_list:
			if self.b2b_price_list == self.regular_price_list:
				frappe.throw(_("Regular and B2B Price Lists must be different."))
			self.validate_price_list(self.b2b_price_list, company_currency, _("B2B"))

	def validate_price_list(self, price_list, company_currency, label):
		if not price_list:
			frappe.throw(_("{0} Price List is required.").format(label))
		details = frappe.db.get_value(
			"Price List", price_list,
			["enabled", "selling", "currency"], as_dict=1
		)
		if not details or not details.enabled or not details.selling:
			frappe.throw(_("{0} Price List must be enabled and marked as Selling.").format(label))
		if details.currency != company_currency:
			frappe.throw(_(
				"{0} Price List must use company currency {1}."
			).format(label, company_currency))

	def validate_quantity_tiers(self):
		if not self.enable_quantity_pricing:
			return
		if not self.pricing_tiers:
			frappe.throw(_("Add at least one Pricing Rule tier."))
		previous_maximum = None
		for index, tier in enumerate(self.pricing_tiers, 1):
			minimum = cint(tier.minimum_qty)
			maximum_value = cint(tier.maximum_qty)
			maximum = maximum_value if maximum_value > 0 else None
			if minimum <= 0:
				frappe.throw(_("Row {0}: Minimum Qty must be greater than zero.").format(index))
			if maximum is not None and maximum < minimum:
				frappe.throw(_("Row {0}: Maximum Qty cannot be below Minimum Qty.").format(index))
			if flt(tier.markup_percent) < 0:
				frappe.throw(_("Row {0}: Markup % cannot be negative.").format(index))
			if previous_maximum is not None and minimum != previous_maximum + 1:
				frappe.throw(_(
					"Tier {0} must start at {1} so quantity ranges have no gaps or overlaps."
				).format(index, previous_maximum + 1))
			if maximum is None and index != len(self.pricing_tiers):
				frappe.throw(_("Only the final quantity tier may be open-ended."))
			previous_maximum = maximum
