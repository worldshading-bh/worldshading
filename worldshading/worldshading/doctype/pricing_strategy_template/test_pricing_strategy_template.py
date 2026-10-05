# -*- coding: utf-8 -*-
# Copyright (c) 2026, Hilal Habeeb and Contributors
# See license.txt
from __future__ import unicode_literals

# import frappe
import json
import os
import unittest

class TestPricingStrategyTemplate(unittest.TestCase):
	def test_cost_basis_is_selected_in_report_not_strategy_template(self):
		definition_path = os.path.join(
			os.path.dirname(__file__), "pricing_strategy_template.json"
		)
		with open(definition_path) as definition_file:
			definition = json.load(definition_file)
		self.assertNotIn("cost_basis", definition["field_order"])
		self.assertFalse(any(
			row.get("fieldname") == "cost_basis" for row in definition["fields"]
		))

	def test_expense_treatment_has_clear_pricing_label_and_description(self):
		definition_path = os.path.join(
			os.path.dirname(__file__), "pricing_strategy_template.json"
		)
		with open(definition_path) as definition_file:
			definition = json.load(definition_file)
		field = next(row for row in definition["fields"]
			if row.get("fieldname") == "expense_treatment")
		self.assertEqual(field.get("label"), "Expense in Price Calculation")
		self.assertEqual(
			field.get("description"),
			"Controls whether the allocated indirect expense per unit is included "
			"in the cost used to calculate recommended prices."
		)
