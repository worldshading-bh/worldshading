# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import unittest
from decimal import Decimal
from unittest.mock import patch

from worldshading.api import dynamic_rounding
from worldshading.api.dynamic_rounding import (
	DynamicRoundingConfigurationError,
	apply_dynamic_rounding,
	calculate_dynamic_rounding,
	is_pilot_user,
)


class FakeSalesDocument(object):
	def __init__(self, doctype="Quotation"):
		self.doctype = doctype
		self.grand_total = 122.151
		self.base_grand_total = 122.151
		self.rounded_total = 122.200
		self.base_rounded_total = 122.200
		self.rounding_adjustment = 0.049
		self.base_rounding_adjustment = 0.049
		self.conversion_rate = 1
		self.is_return = False
		self.payment_schedule_updated = False
		self.payment_schedule_validated = False
		self.in_words_updated = False
		self.outstanding_amount = 122.200
		self.outstanding_updated = False

	def precision(self, fieldname):
		if fieldname.startswith("base_"):
			return 2
		return 3

	def is_rounded_total_disabled(self):
		return False

	def set_total_in_words(self):
		self.in_words_updated = True

	def set_payment_schedule(self):
		self.payment_schedule_updated = True

	def validate_payment_schedule_amount(self):
		self.payment_schedule_validated = True


class FakeTaxesAndTotals(object):
	def calculate_outstanding_amount(self):
		self.doc.outstanding_amount = self.doc.rounded_total
		self.doc.outstanding_updated = True


class TestDynamicRounding(unittest.TestCase):
	def setUp(self):
		self.rules = [
			{
				"minimum_amount": "0.000",
				"maximum_amount": "10.000",
				"rounding_method": "Nearest",
				"rounding_value": "0.050",
			},
			{
				"minimum_amount": "10.000",
				"maximum_amount": "30.000",
				"rounding_method": "Nearest",
				"rounding_value": "0.100",
			},
		]

	def test_only_hilal_is_pilot_user(self):
		self.assertTrue(is_pilot_user("hilal@worldshading.com"))
		self.assertFalse(is_pilot_user("sales@worldshading.com"))
		self.assertFalse(is_pilot_user("Administrator"))

	def test_nearest_rounds_half_up(self):
		result = calculate_dynamic_rounding("10.250", self.rules)

		self.assertEqual(result["rounded_total"], Decimal("10.300"))
		self.assertEqual(result["rounding_adjustment"], Decimal("0.050"))

	def test_nearest_rounds_to_closest_increment(self):
		self.assertEqual(
			calculate_dynamic_rounding("9.970", self.rules)["rounded_total"],
			Decimal("9.950"),
		)
		self.assertEqual(
			calculate_dynamic_rounding("9.980", self.rules)["rounded_total"],
			Decimal("10.000"),
		)

	def test_boundary_uses_next_range(self):
		result = calculate_dynamic_rounding("10.000", self.rules)

		self.assertEqual(result["minimum_amount"], Decimal("10.000"))
		self.assertEqual(result["maximum_amount"], Decimal("30.000"))
		self.assertEqual(result["rounding_value"], Decimal("0.100"))

	def test_lowest_and_highest_methods(self):
		lowest = [dict(self.rules[1], rounding_method="Lowest")]
		highest = [dict(self.rules[1], rounding_method="Highest")]

		self.assertEqual(
			calculate_dynamic_rounding("10.270", lowest)["rounded_total"],
			Decimal("10.200"),
		)
		self.assertEqual(
			calculate_dynamic_rounding("10.270", highest)["rounded_total"],
			Decimal("10.300"),
		)

	def test_exact_multiple_is_unchanged(self):
		result = calculate_dynamic_rounding("10.200", self.rules)

		self.assertEqual(result["rounded_total"], Decimal("10.200"))
		self.assertEqual(result["rounding_adjustment"], Decimal("0.000"))

	def test_return_uses_absolute_range_and_restores_sign(self):
		result = calculate_dynamic_rounding("-10.270", self.rules)

		self.assertEqual(result["rounded_total"], Decimal("-10.300"))
		self.assertEqual(result["rounding_adjustment"], Decimal("-0.030"))

	def test_lowest_and_highest_are_numeric_for_returns(self):
		lowest = [dict(self.rules[1], rounding_method="Lowest")]
		highest = [dict(self.rules[1], rounding_method="Highest")]

		self.assertEqual(
			calculate_dynamic_rounding("-10.270", lowest)["rounded_total"],
			Decimal("-10.300"),
		)
		self.assertEqual(
			calculate_dynamic_rounding("-10.270", highest)["rounded_total"],
			Decimal("-10.200"),
		)

	def test_gap_returns_no_rule(self):
		rules = [dict(self.rules[0], maximum_amount="9.000")]

		self.assertIsNone(calculate_dynamic_rounding("9.500", rules))

	def test_overlapping_ranges_are_rejected(self):
		rules = [self.rules[0], dict(self.rules[1], minimum_amount="9.000")]

		with self.assertRaises(DynamicRoundingConfigurationError):
			calculate_dynamic_rounding("9.500", rules)

	def test_non_positive_rounding_value_is_rejected(self):
		rules = [dict(self.rules[0], rounding_value="0")]

		with self.assertRaises(DynamicRoundingConfigurationError):
			calculate_dynamic_rounding("5.000", rules)

	def test_non_finite_values_are_rejected(self):
		with self.assertRaises(DynamicRoundingConfigurationError):
			calculate_dynamic_rounding("NaN", self.rules)

		with self.assertRaises(DynamicRoundingConfigurationError):
			calculate_dynamic_rounding("Infinity", self.rules)

	def test_maximum_boundary_is_exclusive(self):
		self.assertIsNone(calculate_dynamic_rounding("30.000", self.rules))

	def test_invalid_method_is_rejected(self):
		rules = [dict(self.rules[0], rounding_method="Sideways")]

		with self.assertRaises(DynamicRoundingConfigurationError):
			calculate_dynamic_rounding("5.000", rules)

	def test_real_rounding_applies_to_enabled_sales_documents(self):
		for doctype in ("Quotation", "Sales Order", "Sales Invoice"):
			doc = FakeSalesDocument(doctype)
			settings = {
				"enable_dynamic_rounding": 1,
				"dynamic_rounding_rules": [{
					"minimum_amount": "100.000",
					"maximum_amount": "1000.000",
					"rounding_method": "Lowest",
					"rounding_value": "1.000",
				}]
			}

			with patch.object(
				dynamic_rounding.frappe, "get_single", return_value=settings
			), patch.object(
				dynamic_rounding, "calculate_taxes_and_totals", FakeTaxesAndTotals
			):
				applied = apply_dynamic_rounding(doc)

			self.assertTrue(applied)
			self.assertEqual(doc.rounded_total, 122.000)
			self.assertEqual(doc.rounding_adjustment, -0.151)
			self.assertEqual(doc.base_rounded_total, 122.000)
			self.assertEqual(doc.base_rounding_adjustment, -0.15)
			self.assertTrue(doc.in_words_updated)
			self.assertTrue(doc.payment_schedule_updated)
			self.assertTrue(doc.payment_schedule_validated)
			if doctype == "Sales Invoice":
				self.assertTrue(doc.outstanding_updated)
				self.assertEqual(doc.outstanding_amount, doc.rounded_total)
			else:
				self.assertFalse(doc.outstanding_updated)

	def test_real_rounding_does_not_apply_when_disabled(self):
		doc = FakeSalesDocument()
		settings = {
			"enable_dynamic_rounding": 0,
			"dynamic_rounding_rules": self.rules,
		}

		with patch.object(
			dynamic_rounding.frappe, "get_single", return_value=settings
		), patch.object(
			dynamic_rounding, "calculate_taxes_and_totals", FakeTaxesAndTotals
		):
			applied = apply_dynamic_rounding(doc)

		self.assertFalse(applied)
		self.assertEqual(doc.rounded_total, 122.200)
		self.assertEqual(doc.rounding_adjustment, 0.049)

	def test_real_rounding_does_not_apply_to_other_doctypes(self):
		doc = FakeSalesDocument("Delivery Note")
		settings = {
			"enable_dynamic_rounding": 1,
			"dynamic_rounding_rules": self.rules,
		}

		with patch.object(
			dynamic_rounding.frappe, "get_single", return_value=settings
		), patch.object(
			dynamic_rounding, "calculate_taxes_and_totals", FakeTaxesAndTotals
		):
			applied = apply_dynamic_rounding(doc)

		self.assertFalse(applied)
		self.assertEqual(doc.rounded_total, 122.200)
		self.assertEqual(doc.rounding_adjustment, 0.049)

	def test_base_adjustment_reconciles_with_base_totals(self):
		doc = FakeSalesDocument()
		doc.conversion_rate = 0.376
		doc.base_grand_total = 45.93
		settings = {
			"enable_dynamic_rounding": 1,
			"dynamic_rounding_rules": [{
				"minimum_amount": "100.000",
				"maximum_amount": "1000.000",
				"rounding_method": "Lowest",
				"rounding_value": "1.000",
			}]
		}

		with patch.object(
			dynamic_rounding.frappe, "get_single", return_value=settings
		):
			applied = apply_dynamic_rounding(doc)

		self.assertTrue(applied)
		self.assertEqual(doc.base_rounded_total, 45.87)
		self.assertEqual(doc.base_rounding_adjustment, -0.06)
		self.assertEqual(
			doc.base_rounding_adjustment,
			doc.base_rounded_total - doc.base_grand_total,
		)

	def test_nonzero_total_cannot_round_to_zero(self):
		doc = FakeSalesDocument("Sales Invoice")
		doc.grand_total = 0.020
		doc.base_grand_total = 0.020
		settings = {
			"enable_dynamic_rounding": 1,
			"dynamic_rounding_rules": [{
				"minimum_amount": "0.000",
				"maximum_amount": "10.000",
				"rounding_method": "Lowest",
				"rounding_value": "0.050",
			}]
		}

		with patch.object(
			dynamic_rounding.frappe, "get_single", return_value=settings
		), patch.object(
			dynamic_rounding.frappe, "throw", side_effect=ValueError
		):
			with self.assertRaises(ValueError):
				apply_dynamic_rounding(doc)

	def test_enabled_rounding_blocks_unmatched_amount(self):
		doc = FakeSalesDocument()
		settings = {
			"enable_dynamic_rounding": 1,
			"dynamic_rounding_rules": [{
				"minimum_amount": "0.000",
				"maximum_amount": "10.000",
				"rounding_method": "Nearest",
				"rounding_value": "0.050",
			}]
		}

		with patch.object(
			dynamic_rounding.frappe, "get_single", return_value=settings
		), patch.object(
			dynamic_rounding.frappe, "throw", side_effect=ValueError
		):
			with self.assertRaises(ValueError):
				apply_dynamic_rounding(doc)

	def test_sales_invoice_return_does_not_change_payment_schedule(self):
		doc = FakeSalesDocument("Sales Invoice")
		doc.is_return = True
		doc.grand_total = -122.151
		doc.base_grand_total = -122.151
		settings = {
			"enable_dynamic_rounding": 1,
			"dynamic_rounding_rules": [{
				"minimum_amount": "100.000",
				"maximum_amount": "1000.000",
				"rounding_method": "Lowest",
				"rounding_value": "1.000",
			}]
		}

		with patch.object(
			dynamic_rounding.frappe, "get_single", return_value=settings
		), patch.object(
			dynamic_rounding, "calculate_taxes_and_totals", FakeTaxesAndTotals
		):
			applied = apply_dynamic_rounding(doc)

		self.assertTrue(applied)
		self.assertEqual(doc.rounded_total, -123.000)
		self.assertTrue(doc.in_words_updated)
		self.assertTrue(doc.outstanding_updated)
		self.assertEqual(doc.outstanding_amount, doc.rounded_total)
		self.assertFalse(doc.payment_schedule_updated)
		self.assertFalse(doc.payment_schedule_validated)


if __name__ == "__main__":
	unittest.main()
