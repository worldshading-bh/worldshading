from __future__ import unicode_literals

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import frappe

from worldshading.worldshading.report.pricing_strategy_analysis import pricing_strategy_analysis as report


class TestPricingStrategyCalculation(unittest.TestCase):

	def test_workbook_regular_example(self):
		result = report.calculate_price("46", "43", "10", "1", "Nearest")
		self.assertEqual(result["gross_price"], Decimal("72.000"))
		self.assertEqual(result["net_price"], Decimal("65.455"))

	def test_rounding_methods(self):
		self.assertEqual(
			report.round_to_increment("72.11", "0.5", "Nearest"),
			Decimal("72.0")
		)
		self.assertEqual(
			report.round_to_increment("72.11", "0.5", "Up"),
			Decimal("72.5")
		)
		self.assertEqual(
			report.round_to_increment("72.89", "0.5", "Down"),
			Decimal("72.5")
		)

	def test_markup_and_margin_are_distinct_after_rounding(self):
		result = report.calculate_price("46", "43", "10", "1", "Nearest")
		self.assertEqual(result["actual_markup_percent"], Decimal("42.292"))
		self.assertEqual(result["gross_margin_percent"], Decimal("29.722"))

	def test_zero_cost_returns_no_price(self):
		self.assertIsNone(
			report.calculate_price("0", "43", "10", "1", "Nearest")
		)

	def test_zero_vat_does_not_divide_by_zero(self):
		result = report.calculate_price("10", "25", "0", "1", "Nearest")
		self.assertEqual(result["net_price"], Decimal("13.000"))
		self.assertEqual(result["gross_price"], Decimal("13.000"))

	def test_warning_order_is_stable_and_duplicates_are_removed(self):
		warnings = report.compose_warnings([
			"No recent sales", "Missing cost", "No recent sales", ""
		])
		self.assertEqual(warnings, "No recent sales; Missing cost")

	def test_loaded_cost_and_price_action(self):
		filters = self._valid_filters()
		normalized = report.validate_and_normalize_filters(filters)
		row = report.calculate_item_row({
			"item_code": "A",
			"selected_base_cost": Decimal("100"),
			"current_normal_price": Decimal("120"),
			"warnings": []
		}, normalized)
		self.assertEqual(row["expense_amount"], Decimal("5.000"))
		self.assertEqual(row["fully_loaded_cost"], Decimal("105.000"))
		self.assertEqual(row["suggested_action"], "Increase Price")

	def test_price_action_keeps_change_below_increment(self):
		self.assertEqual(
			report.get_suggested_action(Decimal("100"), Decimal("100.49"), Decimal("1")),
			"Keep Price"
		)
		self.assertEqual(
			report.get_suggested_action(Decimal("100"), Decimal("99"), Decimal("1")),
			"Reduce Price"
		)
		self.assertEqual(
			report.get_suggested_action(None, Decimal("99"), Decimal("1")),
			"Set Initial Price"
		)

	def test_empty_and_string_filters_are_normalized(self):
		filters = self._valid_filters()
		filters.update({
			"expense_burden": "",
			"include_items_without_sales": "0",
			"tier_4_maximum": ""
		})
		result = report.validate_and_normalize_filters(filters)
		self.assertEqual(result["expense_burden"], Decimal("0"))
		self.assertFalse(result["include_items_without_sales"])
		self.assertIsNone(result["tiers"][3]["maximum"])
		self.assertEqual(result["from_date"], date(2026, 1, 1))

	def test_tier_gap_is_allowed_and_reported(self):
		filters = self._valid_filters()
		filters["tier_2_minimum"] = 11
		result = report.validate_and_normalize_filters(filters)
		self.assertEqual(
			result["gap_messages"],
			["Quantity tier gap between 9 and 11"]
		)

	def test_invalid_filter_values_are_rejected(self):
		invalid_cases = []
		case = self._valid_filters()
		case["from_date"] = "2027-01-01"
		invalid_cases.append(case)
		case = self._valid_filters()
		case["vat_percent"] = -1
		invalid_cases.append(case)
		case = self._valid_filters()
		case["rounding_increment"] = 0
		invalid_cases.append(case)
		case = self._valid_filters()
		case["tier_2_minimum"] = 9
		invalid_cases.append(case)
		case = self._valid_filters()
		case["tier_1_maximum"] = ""
		invalid_cases.append(case)

		with patch.object(report.frappe, "throw", side_effect=frappe.ValidationError):
			for filters in invalid_cases:
				with self.assertRaises(frappe.ValidationError):
					report.validate_and_normalize_filters(filters)

	def _valid_filters(self):
		return {
			"company": "World Shading",
			"from_date": "2026-01-01",
			"to_date": "2026-12-31",
			"regular_price_list": "Standard Selling",
			"cost_source": "Current Valuation Rate",
			"expense_burden": 5,
			"vat_percent": 10,
			"rounding_method": "Nearest",
			"rounding_increment": 1,
			"regular_markup": 43,
			"b2b_markup": 33,
			"tier_1_minimum": 5,
			"tier_1_maximum": 9,
			"tier_1_markup": 31,
			"tier_2_minimum": 10,
			"tier_2_maximum": 19,
			"tier_2_markup": 29,
			"tier_3_minimum": 20,
			"tier_3_maximum": 39,
			"tier_3_markup": 27,
			"tier_4_minimum": 40,
			"tier_4_maximum": "",
			"tier_4_markup": 25,
			"include_items_without_sales": 1
		}


if __name__ == "__main__":
	unittest.main()
