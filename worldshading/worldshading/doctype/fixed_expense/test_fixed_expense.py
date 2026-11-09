# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from datetime import datetime
import json
import os
import unittest
from unittest.mock import patch

import frappe
from frappe.model.naming import make_autoname

from worldshading.worldshading.doctype.fixed_expense.fixed_expense import FixedExpense


class TestFixedExpense(unittest.TestCase):

	def setUp(self):
		# Exercise the controller without loading metadata or opening a site/database.
		self.doc = FixedExpense.__new__(FixedExpense)
		self.doc.__dict__.update({
			"company": "World Shading", "expense_account": "Hosting - WS",
			"currency": "USD", "amount_type": "Fixed", "expected_amount": 30,
			"billing_currency": None, "provider_amount": None,
			"start_date": "2026-10-01", "first_due_date": "2026-10-15",
			"end_date": None, "billing_frequency": "Monthly",
			"status": "Active"
		})
		# Document.get checks table metadata even for absent optional scalar fields.
		self.doc._meta = type("ScalarMeta", (), {
			"get_table_fields": lambda self: []
		})()
		self.account = frappe._dict({
			"company": "World Shading", "root_type": "Expense",
			"is_group": 0, "disabled": 0, "account_currency": "BHD"
		})
		self.db_patch = patch.object(frappe, "db", create=True)
		self.db = self.db_patch.start()
		self.addCleanup(self.db_patch.stop)
		self.db.get_value.side_effect = self.get_value
		self.translate_patch = patch(
			"worldshading.worldshading.doctype.fixed_expense.fixed_expense._",
			side_effect=lambda text: text
		)
		self.translate_patch.start()
		self.addCleanup(self.translate_patch.stop)
		self.throw_patch = patch.object(frappe, "throw", side_effect=self.throw)
		self.throw_patch.start()
		self.addCleanup(self.throw_patch.stop)

	def get_value(self, doctype, name, fields, **kwargs):
		if doctype == "Company" and name == "World Shading" and fields == "default_currency":
			return "BHD"
		if doctype == "Account" and name == "Hosting - WS":
			return self.account
		if doctype == "Account" and name == "Input VAT - WS":
			return self.account
		raise AssertionError("Unexpected database read: {0} {1}".format(doctype, name))

	def throw(self, message, *args, **kwargs):
		raise frappe.ValidationError(message)

	def test_naming_series_generates_year_and_isolated_sequence(self):
		definition_path = os.path.join(os.path.dirname(__file__), "fixed_expense.json")
		with open(definition_path) as definition_file:
			pattern = json.load(definition_file)["autoname"]
		with patch("frappe.model.naming.now_datetime", return_value=datetime(2026, 10, 1)):
			with patch("frappe.model.naming.getseries", return_value="00001"):
				name = make_autoname(pattern, doc=frappe._dict())
		self.assertEqual(name, "FEX-26-00001")

	def test_schema_requires_operational_fields_and_validates_portal_as_url(self):
		definition_path = os.path.join(os.path.dirname(__file__), "fixed_expense.json")
		with open(definition_path) as definition_file:
			definition = json.load(definition_file)
		fields = dict((row["fieldname"], row) for row in definition["fields"])
		for fieldname in ("category", "provider_name"):
			self.assertEqual(fields[fieldname].get("reqd"), 1)
		self.assertEqual(fields["portal_url"].get("options"), "URL")

	def test_monthly_and_yearly_services_accept_the_same_provider_account(self):
		self.doc.registered_email = "hosting@example.com"
		for frequency, service_id in (("Monthly", "VPS-1"), ("Yearly", "VPS-2")):
			self.doc.billing_frequency = frequency
			self.doc.service_identifier = service_id
			self.doc.validate()
			self.assertEqual(self.doc.currency, "BHD")
			self.assertEqual(self.doc.first_due_date, "2026-10-15")

	def test_account_must_be_an_enabled_company_expense_leaf_in_company_currency(self):
		for field, value in (
			("company", "Other Company"), ("root_type", "Asset"),
			("is_group", 1), ("disabled", 1), ("account_currency", "USD")
		):
			with self.subTest(field=field):
				previous = self.account[field]
				self.account[field] = value
				with self.assertRaises(frappe.ValidationError):
					self.doc.validate()
				self.account[field] = previous

	def test_missing_account_is_rejected(self):
		self.account = None
		with self.assertRaises(frappe.ValidationError):
			self.doc.validate()

	def test_empty_ledger_is_rejected_before_an_unfiltered_lookup(self):
		self.doc.expense_account = None
		with self.assertRaises(frappe.ValidationError):
			self.doc.validate()

	def test_fixed_expense_requires_a_positive_amount(self):
		for amount in (None, 0):
			self.doc.expected_amount = amount
			with self.assertRaises(frappe.ValidationError):
				self.doc.validate()

	def test_negative_fixed_amount_and_variable_budget_are_rejected(self):
		for amount_type in ("Fixed", "Variable"):
			with self.subTest(amount_type=amount_type):
				self.doc.amount_type = amount_type
				self.doc.expected_amount = -1
				with self.assertRaises(frappe.ValidationError):
					self.doc.validate()

	def test_zero_budget_is_allowed_for_usage_services(self):
		self.doc.amount_type = "Variable"
		self.doc.expected_amount = 0
		self.doc.validate()
		self.assertEqual(self.doc.expected_amount, 0)

	def test_provider_currency_and_amount_are_entered_together(self):
		for billing_currency, provider_amount in (
			("EUR", None), (None, 25), ("EUR", 0), ("EUR", -1)
		):
			with self.subTest(
				billing_currency=billing_currency, provider_amount=provider_amount
			):
				self.doc.billing_currency = billing_currency
				self.doc.provider_amount = provider_amount
				with self.assertRaises(frappe.ValidationError):
					self.doc.validate()

	def test_positive_provider_amount_and_empty_provider_amount_are_allowed(self):
		for billing_currency, provider_amount in ((None, None), ("EUR", 25)):
			self.doc.billing_currency = billing_currency
			self.doc.provider_amount = provider_amount
			self.doc.validate()

	def test_due_date_before_tracking_start_is_rejected(self):
		self.doc.first_due_date = "2026-09-30"
		with self.assertRaises(frappe.ValidationError):
			self.doc.validate()

	def test_end_date_before_first_due_date_is_rejected(self):
		self.doc.end_date = "2026-10-14"
		with self.assertRaises(frappe.ValidationError):
			self.doc.validate()

	def test_closed_expense_requires_end_date(self):
		self.doc.status = "Closed"
		with self.assertRaises(frappe.ValidationError):
			self.doc.validate()

	def test_single_period_and_open_ended_schedules_are_allowed(self):
		for end_date in (None, "2026-10-15", "2027-10-15"):
			self.doc.end_date = end_date
			self.doc.validate()
			self.assertEqual(self.doc.end_date, end_date)

	def test_payment_account_must_be_a_company_currency_bank_or_cash_leaf(self):
		self.doc.payment_account = "Bank - WS"
		valid = dict(company="World Shading", account_type="Bank", is_group=0,
			disabled=0, account_currency="BHD")
		for field, value in (("company", "Other"), ("account_type", "Receivable"),
			("is_group", 1), ("disabled", 1), ("account_currency", "USD")):
			account = frappe._dict(dict(valid, **{field: value}))
			with patch.object(frappe.db, "get_value", return_value=account):
				with self.assertRaises(frappe.ValidationError):
					self.doc.validate_payment_defaults()

	def test_cost_center_cannot_belong_to_another_company_or_be_a_group(self):
		self.doc.cost_center = "Main - WS"
		for company, is_group in (("Other", 0), ("World Shading", 1)):
			with patch.object(frappe.db, "get_value", return_value=frappe._dict(
				company=company, is_group=is_group)):
				with self.assertRaises(frappe.ValidationError):
					self.doc.validate_payment_defaults()

	def test_estimate_includes_percentage_tax_and_clears_removed_tax(self):
		self.doc.currency = "BHD"
		self.doc.tax_template = "Local VAT"
		template = frappe._dict(company="World Shading", disabled=0, taxes=[
			frappe._dict(charge_type="On Net Total", add_deduct_tax="Add",
				included_in_print_rate=0, category="Total", rate=10,
				account_head="Input VAT - WS")])
		with patch.object(frappe, "get_doc", return_value=template):
			with patch.object(self.doc, "precision", return_value=3):
				self.doc.update_payment_estimate()
				self.assertEqual(self.doc.expected_tax_amount, 3)
				self.assertEqual(self.doc.expected_total_amount, 33)
				self.doc.tax_template = None
				self.doc.update_payment_estimate()
				self.assertEqual(self.doc.expected_tax_amount, 0)
				self.assertEqual(self.doc.expected_total_amount, 30)

	def test_unsupported_tax_templates_are_rejected(self):
		self.doc.tax_template = "Unsupported"
		row = frappe._dict(charge_type="On Net Total", add_deduct_tax="Add",
			included_in_print_rate=0, category="Total", rate=10, account_head="VAT")
		templates = [
			frappe._dict(company="Other", disabled=0, taxes=[row]),
			frappe._dict(company="World Shading", disabled=1, taxes=[row]),
			frappe._dict(company="World Shading", disabled=0, taxes=[]),
			frappe._dict(company="World Shading", disabled=0, taxes=[row, row])]
		for field, value in (("charge_type", "Actual"), ("add_deduct_tax", "Deduct"),
			("included_in_print_rate", 1), ("category", "Valuation"), ("rate", -1)):
			invalid_row = frappe._dict(dict(row, **{field: value}))
			templates.append(frappe._dict(company="World Shading", disabled=0,
				taxes=[invalid_row]))
		for template in templates:
			with patch.object(frappe, "get_doc", return_value=template):
				with self.assertRaises(frappe.ValidationError):
					self.doc.update_payment_estimate()

	def test_accounts_combine_rent_and_taxable_bank_charge(self):
		self.doc.accounts = [frappe._dict(account="Hosting - WS", tax_template=template,
			net_amount=amount, idx=idx, precision=lambda field: 3)
			for idx, template, amount in ((1, "Out of scope", 155), (2, "Local VAT", 0.1))]
		with patch("worldshading.worldshading.doctype.fixed_expense.fixed_expense.get_tax_details",
			side_effect=lambda company, currency, template: {
				"rate": 10 if template == "Local VAT" else 0, "account_head": "Input VAT - WS"}):
			with patch.object(self.doc, "precision", return_value=3):
				self.doc.validate_accounts()
		self.assertEqual(self.doc.expected_amount, 155.1)
		self.assertEqual(self.doc.expected_tax_amount, 0.01)
		self.assertEqual(self.doc.expected_total_amount, 155.11)
		self.assertEqual(self.doc.accounts[0].tax_amount, 0)
		self.assertEqual(self.doc.accounts[1].tax_amount, 0.01)
		self.assertEqual(self.doc.currency, "USD")
		self.assertEqual(self.doc.company_currency, "BHD")
		self.assertEqual(self.doc.accounts[0].currency, "USD")
		self.assertEqual(self.doc.accounts[1].currency, "USD")

	def test_usd_expense_can_use_a_bhd_payment_account(self):
		self.doc.currency = "USD"
		self.doc.payment_account = "Bank - WS"
		def get_value(doctype, name, fields, **kwargs):
			if doctype == "Company":
				return "BHD"
			return frappe._dict(company="World Shading", account_type="Bank",
				is_group=0, disabled=0, account_currency="BHD")
		with patch.object(frappe.db, "get_value", side_effect=get_value):
			self.doc.validate_payment_defaults()
		self.assertEqual(self.doc.currency, "USD")

	def test_accounts_require_explicit_tax_treatment(self):
		self.doc.accounts = [frappe._dict(account="Hosting - WS", tax_template=None,
			net_amount=155, idx=1)]
		with self.assertRaises(frappe.ValidationError):
			self.doc.validate_accounts()

	def test_base_estimate_uses_stored_rate_and_total_including_tax(self):
		self.doc.currency = "USD"
		self.doc.expected_total_amount = 125
		module = "worldshading.worldshading.doctype.fixed_expense.fixed_expense."
		with patch(module + "nowdate", return_value="2026-11-09"), \
			patch.object(frappe, "get_all", return_value=[frappe._dict(exchange_rate=0.376, date="2026-11-08")]), \
			patch.object(frappe.db, "get_single_value", return_value=4), \
			patch.object(self.doc, "precision", side_effect=lambda field: 9 if field == "estimate_exchange_rate" else 3):
			self.doc.update_base_estimate()
		self.assertEqual(self.doc.estimated_base_total, 47)
		self.assertEqual(self.doc.estimate_exchange_rate, 0.376)
		self.assertEqual(str(self.doc.estimate_rate_date), "2026-11-08")

	def test_base_estimate_missing_or_stale_rate_clears_previous_estimate(self):
		self.doc.currency = "USD"
		self.doc.expected_total_amount = 125
		module = "worldshading.worldshading.doctype.fixed_expense.fixed_expense."
		for rows in ([], [frappe._dict(exchange_rate=0.376, date="2026-11-01")],
			[frappe._dict(exchange_rate=0, date="2026-11-08")]):
			self.doc.estimated_base_total = 47
			self.doc.estimate_exchange_rate = 0.376
			with patch(module + "nowdate", return_value="2026-11-09"), \
				patch.object(frappe, "get_all", return_value=rows), \
				patch.object(frappe.db, "get_single_value", return_value=4):
				with self.assertRaises(frappe.ValidationError):
					self.doc.update_base_estimate()
			self.assertEqual(self.doc.estimated_base_total, 0)
			self.assertEqual(self.doc.estimate_exchange_rate, 0)
			self.assertIsNone(self.doc.estimate_rate_date)

	def test_base_estimate_same_currency_skips_conversion_and_clears_old_estimate(self):
		self.doc.currency = "BHD"
		self.doc.expected_total_amount = 155
		self.doc.estimated_base_total = 47
		self.doc.estimate_exchange_rate = 0.376
		self.doc.estimate_rate_date = "2026-11-08"
		with patch.object(frappe, "get_all", side_effect=AssertionError("Unnecessary rate lookup")), \
			patch.object(self.doc, "precision", return_value=3):
			self.doc.update_base_estimate()
		self.assertEqual(self.doc.estimated_base_total, 0)
		self.assertEqual(self.doc.estimate_exchange_rate, 0)
		self.assertIsNone(self.doc.estimate_rate_date)
		self.assertEqual(self.doc.expected_total_amount, 155)


if __name__ == "__main__":
	unittest.main()
