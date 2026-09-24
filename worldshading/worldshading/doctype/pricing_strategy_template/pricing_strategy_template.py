# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


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
		if self.enable_b2b_pricing:
			fields.append("b2b_markup")
		if self.enable_quantity_pricing:
			fields.extend([
				"tier_1_markup", "tier_2_markup",
				"tier_3_markup", "tier_4_markup"
			])
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
		if self.enable_b2b_pricing:
			if not self.b2b_price_list:
				frappe.throw(_("B2B Price List is required when B2B Pricing is enabled."))
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
		tiers = []
		for index in range(1, 5):
			range_value = self.get("tier_{0}_qty_range".format(index))
			minimum, maximum = parse_quantity_range(range_value, index)
			tiers.append((minimum, maximum))

		previous_maximum = None
		for index, values in enumerate(tiers, 1):
			minimum, maximum = values
			if previous_maximum is not None and minimum != previous_maximum + Decimal("1"):
				frappe.throw(_(
					"Tier {0} must start at {1} so quantity ranges have no gaps or overlaps."
				).format(index, format_decimal(previous_maximum + Decimal("1"))))
			if maximum is None and index != len(tiers):
				frappe.throw(_("Only the final quantity tier may be open-ended."))
			previous_maximum = maximum


def parse_quantity_range(value, tier_number):
	text = str(value or "").strip().replace(" ", "")
	try:
		if text.endswith("+") and text[:-1]:
			minimum = Decimal(text[:-1])
			maximum = None
		else:
			parts = text.split(":")
			if len(parts) != 2 or not parts[0] or not parts[1]:
				raise InvalidOperation
			minimum = Decimal(parts[0])
			maximum = Decimal(parts[1])
		if minimum <= 0 or (maximum is not None and maximum < minimum):
			raise InvalidOperation
		return minimum, maximum
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_(
			"Tier {0} Qty Range must use From:To or From+ format, for example 5:9 or 40+."
		).format(tier_number))


def format_decimal(value):
	text = format(value, "f")
	return text.rstrip("0").rstrip(".") if "." in text else text
