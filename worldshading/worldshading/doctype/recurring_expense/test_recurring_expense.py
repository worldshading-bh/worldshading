# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from datetime import datetime
import json
import os
import unittest
from unittest.mock import patch

import frappe
from frappe.model.naming import make_autoname

from worldshading.worldshading.doctype.recurring_expense.recurring_expense import RecurringExpense


class TestRecurringExpense(unittest.TestCase):

	def setUp(self):
		# Exercise the controller without loading metadata or opening a site/database.
		self.doc = RecurringExpense.__new__(RecurringExpense)
		self.doc.__dict__.update({
			"company": "World Shading", "expense_account": "Hosting - WS",
			"currency": "USD", "amount_type": "Fixed", "expected_amount": 30,
			"billing_currency": None, "provider_amount": None,
			"start_date": "2026-10-01", "first_due_date": "2026-10-15",
			"end_date": None, "billing_frequency": "Monthly",
			"status": "Active"
		})
		self.account = frappe._dict({
			"company": "World Shading", "root_type": "Expense",
			"is_group": 0, "disabled": 0, "account_currency": "BHD"
		})
		self.db_patch = patch.object(frappe, "db", create=True)
		self.db = self.db_patch.start()
		self.addCleanup(self.db_patch.stop)
		self.db.get_value.side_effect = self.get_value
		self.translate_patch = patch(
			"worldshading.worldshading.doctype.recurring_expense.recurring_expense._",
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
		raise AssertionError("Unexpected database read: {0} {1}".format(doctype, name))

	def throw(self, message, *args, **kwargs):
		raise frappe.ValidationError(message)

	def test_naming_series_generates_year_and_isolated_sequence(self):
		definition_path = os.path.join(os.path.dirname(__file__), "recurring_expense.json")
		with open(definition_path) as definition_file:
			pattern = json.load(definition_file)["autoname"]
		with patch("frappe.model.naming.now_datetime", return_value=datetime(2026, 10, 1)):
			with patch("frappe.model.naming.getseries", return_value="00001"):
				name = make_autoname(pattern, doc=frappe._dict())
		self.assertEqual(name, "REX-26-00001")

	def test_schema_requires_operational_fields_and_validates_portal_as_url(self):
		definition_path = os.path.join(os.path.dirname(__file__), "recurring_expense.json")
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


if __name__ == "__main__":
	unittest.main()
