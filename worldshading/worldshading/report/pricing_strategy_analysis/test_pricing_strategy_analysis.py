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


class TestPricingStrategyDataSources(unittest.TestCase):

	def test_sales_zero_net_quantity_has_no_average(self):
		rows = [{
			"item_code": "A", "sales_qty": 0, "sales_value": 20,
			"invoice_count": 2, "last_sale_date": "2026-08-01",
			"last_sold_rate": 10, "lowest_sold_rate": 9, "highest_sold_rate": 11
		}]
		normalized = report.normalize_sales_rows(rows)
		self.assertIsNone(normalized["A"]["weighted_average_sold_rate"])
		self.assertIn("Sales returns equal or exceed sales", normalized["A"]["warnings"])

	def test_sales_weighted_average_uses_company_currency_stock_uom_values(self):
		rows = [{"item_code": "A", "sales_qty": 4, "sales_value": 50}]
		normalized = report.normalize_sales_rows(rows)
		self.assertEqual(normalized["A"]["weighted_average_sold_rate"], Decimal("12.500"))

	def test_purchase_return_imbalance_has_no_average(self):
		result = report.normalize_purchase_rows(
			[{"item_code": "A", "purchase_qty": -1, "purchase_value": -10}],
			[{"item_code": "A", "latest_purchase_rate": 12}]
		)
		self.assertIsNone(result["A"]["weighted_average_purchase_rate"])
		self.assertEqual(result["A"]["latest_purchase_rate"], Decimal("12.000"))
		self.assertIn("Purchase returns equal or exceed purchases", result["A"]["warnings"])

	def test_stock_uses_positive_bins_and_sle_fallback(self):
		result = report.normalize_stock_rows([
			{"item_code": "A", "actual_qty": 3, "valuation_value": 30},
			{"item_code": "B", "actual_qty": 0, "valuation_value": 0}
		], [{"item_code": "B", "valuation_rate": 8}])
		self.assertEqual(result["A"]["valuation_rate"], Decimal("10.000"))
		self.assertEqual(result["B"]["valuation_rate"], Decimal("8.000"))
		self.assertIn("Valuation uses latest Stock Ledger rate", result["B"]["warnings"])

	def test_duplicate_item_prices_are_deterministic(self):
		rows = [
			{"name": "OLD", "item_code": "A", "price_list": "Standard Selling", "price_list_rate": 10,
			 "valid_from": "2026-01-01", "creation": "2026-01-01 10:00:00"},
			{"name": "NEW", "item_code": "A", "price_list": "Standard Selling", "price_list_rate": 11,
			 "valid_from": "2026-02-01", "creation": "2026-02-01 10:00:00"}
		]
		prices = report.normalize_item_prices(rows, "Standard Selling", None)
		self.assertEqual(prices["A"]["current_normal_price"], Decimal("11.000"))
		self.assertIn("Multiple valid normal Item Prices", prices["A"]["warnings"])

	def test_database_readers_use_parameters_and_latest_purchase_ignores_from_date(self):
		filters = {"company": "WS", "from_date": date(2026, 1, 1), "to_date": date(2026, 12, 31)}
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.return_value = []
			report.get_purchase_data(filters, ["A", "B"])
			sql = frappe_mock.db.sql
		self.assertEqual(sql.call_count, 2)
		average_query, average_values = sql.call_args_list[0][0][0:2]
		latest_query, latest_values = sql.call_args_list[1][0][0:2]
		self.assertIn("%(from_date)s", average_query)
		self.assertNotIn("%(from_date)s", latest_query)
		self.assertEqual(average_values["item_codes"], ("A", "B"))
		self.assertEqual(latest_values["company"], "WS")

	def test_price_list_currency_must_match_company(self):
		filters = {
			"company": "WS", "regular_price_list": "Regular", "b2b_price_list": "B2B"
		}
		values = {
			("Company", "WS"): "BHD",
			("Price List", "Regular"): {"enabled": 1, "selling": 1, "currency": "BHD"},
			("Price List", "B2B"): {"enabled": 1, "selling": 1, "currency": "USD"}
		}
		def get_value(doctype, name, fields=None, as_dict=False):
			value = values[(doctype, name)]
			return frappe._dict(value) if isinstance(value, dict) else value
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.get_value.side_effect = get_value
			frappe_mock.throw.side_effect = frappe.ValidationError
			with self.assertRaises(frappe.ValidationError):
				report.validate_master_filters(filters)


if __name__ == "__main__":
	unittest.main()
