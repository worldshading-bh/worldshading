from __future__ import unicode_literals

import unittest
from contextlib import ExitStack
from datetime import date
from decimal import Decimal
import json
import os
import re
from unittest.mock import patch

import frappe

from worldshading.worldshading.report.pricing_strategy_analysis import pricing_strategy_analysis as report


class TestPricingStrategyCalculation(unittest.TestCase):

	def test_workbook_regular_example(self):
		result = report.calculate_price("46", "43", "10")
		self.assertEqual(result["gross_price"], Decimal("72.500"))
		self.assertEqual(result["net_price"], Decimal("65.909"))
		self.assertEqual(result["rounding_increment"], Decimal("0.500"))

	def test_automatic_rounding_increment_boundaries(self):
		cases = (
			("0.001", "0.005"), ("0.099", "0.005"),
			("0.100", "0.100"), ("29.999", "0.100"),
			("30.000", "0.500"), ("99.999", "0.500"),
			("100.000", "1.000"), ("999.999", "1.000"),
			("1000.000", "10.000"), ("5000", "10.000")
		)
		for gross_price, expected in cases:
			self.assertEqual(report.get_rounding_increment(gross_price), Decimal(expected))

	def test_rounding_always_moves_up_to_the_next_increment(self):
		self.assertEqual(
			report.round_to_increment("72.11", "0.5"),
			Decimal("72.5")
		)
		self.assertEqual(
			report.round_to_increment("72.5", "0.5"),
			Decimal("72.5")
		)

	def test_markup_and_margin_are_distinct_after_rounding(self):
		result = report.calculate_price("46", "43", "10")
		self.assertEqual(result["actual_markup_percent"], Decimal("43.281"))
		self.assertEqual(result["gross_margin_percent"], Decimal("30.207"))

	def test_zero_cost_returns_no_price(self):
		self.assertIsNone(
			report.calculate_price("0", "43", "10")
		)

	def test_zero_vat_does_not_divide_by_zero(self):
		result = report.calculate_price("10", "25", "0")
		self.assertEqual(result["net_price"], Decimal("12.500"))
		self.assertEqual(result["gross_price"], Decimal("12.500"))

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
			"expense_per_unit": Decimal("5"),
			"current_normal_price": Decimal("120"),
			"warnings": []
		}, normalized)
		self.assertEqual(row["expense_per_unit"], Decimal("5.000"))
		self.assertEqual(row["fully_loaded_cost"], Decimal("105.000"))
		self.assertEqual(row["suggested_action"], "Increase Price")

	def test_real_expense_is_allocated_by_sales_value_per_unit(self):
		allocation = report.calculate_expense_allocation(
			Decimal("100"), Decimal("1000"), Decimal("15"), Decimal("0.10")
		)
		self.assertEqual(allocation["allocated_expense"], Decimal("100.000"))
		self.assertEqual(allocation["expense_per_unit"], Decimal("1.000"))
		self.assertEqual(allocation["expense_source"], "Actual period sales")

	def test_unsold_item_uses_regular_item_price_for_expense(self):
		allocation = report.calculate_expense_allocation(
			Decimal("0"), Decimal("0"), Decimal("100"), Decimal("0.10")
		)
		self.assertIsNone(allocation["allocated_expense"])
		self.assertEqual(allocation["expense_per_unit"], Decimal("10.000"))
		self.assertEqual(allocation["expense_source"], "Regular Item Price fallback")

	def test_unsold_item_without_regular_price_has_no_invented_expense(self):
		allocation = report.calculate_expense_allocation(
			Decimal("0"), Decimal("0"), None, Decimal("0.10")
		)
		self.assertIsNone(allocation["expense_per_unit"])
		self.assertIn("No basis for indirect expense allocation", allocation["warnings"])

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
			"exclude_items_without_sales": "1",
			"tier_4_maximum": ""
		})
		result = report.validate_and_normalize_filters(filters)
		self.assertTrue(result["exclude_items_without_sales"])
		self.assertIsNone(result["tiers"][3]["maximum"])
		self.assertEqual(result["from_date"], date(2026, 1, 1))

	def test_pricing_rule_strategy_is_disabled_by_default(self):
		filters = self._valid_filters()
		filters.pop("show_pricing_rule_strategy")
		result = report.validate_and_normalize_filters(filters)
		self.assertFalse(result["show_pricing_rule_strategy"])
		self.assertEqual(result["tiers"], [])
		self.assertEqual(result["gap_messages"], [])

	def test_tier_gap_is_allowed_and_reported(self):
		filters = self._valid_filters()
		filters["tier_2_minimum"] = 11
		result = report.validate_and_normalize_filters(filters)
		self.assertEqual(
			result["gap_messages"],
			["Quantity tier gap between 9 and 11"]
		)

	def test_single_quantity_range_fields_are_normalized(self):
		filters = self._valid_filters()
		filters.update({
			"tier_1_qty_range": "5:9",
			"tier_2_qty_range": "10:19",
			"tier_3_qty_range": "20:39",
			"tier_4_qty_range": "40+"
		})
		for index in range(1, 5):
			filters.pop("tier_{0}_minimum".format(index))
			filters.pop("tier_{0}_maximum".format(index))
		result = report.validate_and_normalize_filters(filters)
		self.assertEqual(result["tiers"][0]["minimum"], Decimal("5"))
		self.assertEqual(result["tiers"][0]["maximum"], Decimal("9"))
		self.assertEqual(result["tiers"][3]["minimum"], Decimal("40"))
		self.assertIsNone(result["tiers"][3]["maximum"])

	def test_invalid_single_quantity_range_is_rejected(self):
		filters = self._valid_filters()
		filters["tier_1_qty_range"] = "five to nine"
		with patch.object(report.frappe, "throw", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				report.validate_and_normalize_filters(filters)

	def test_invalid_filter_values_are_rejected(self):
		invalid_cases = []
		case = self._valid_filters()
		case["from_date"] = "2027-01-01"
		invalid_cases.append(case)
		case = self._valid_filters()
		case["vat_percent"] = -1
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
			"vat_percent": 10,
			"regular_markup": 43,
			"b2b_markup": 33,
			"show_pricing_rule_strategy": 1,
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
			"exclude_items_without_sales": 0
		}


class TestPricingStrategyDataSources(unittest.TestCase):

	def test_sales_data_delegates_to_shared_packed_sales_aggregate(self):
		filters = {
			"company": "WS", "from_date": date(2026, 1, 1),
			"to_date": date(2026, 12, 31), "warehouse": "Main - WS",
			"tiers": [{"minimum": Decimal("5"), "maximum": Decimal("9"), "markup": Decimal("31")}],
			"gap_messages": []
		}
		expected = {
			"A": {"sales_qty": Decimal("4"), "sales_value": Decimal("80.000"),
				  "weighted_average_sold_rate": Decimal("20.000"),
				  "invoice_count": 2, "last_sale_date": date(2026, 9, 1),
				  "lowest_sold_rate": Decimal("18.000"),
				  "highest_sold_rate": Decimal("22.000"),
				  "last_sold_rate": Decimal("21.000"), "warnings": []}
		}
		captured = {}

		def shared_reader(received_filters, item_codes=None):
			captured["filters"] = received_filters
			captured["item_codes"] = item_codes
			return expected

		with patch.object(report, "get_item_sales_aggregates", side_effect=shared_reader):
			result = report.get_sales_data(filters, ["A"])
		self.assertIs(result, expected)
		self.assertEqual(captured["filters"], {
			"company": "WS", "from_date": date(2026, 1, 1),
			"to_date": date(2026, 12, 31), "warehouse": "Main - WS",
			"include_returns": 1, "sales_basis": "All"
		})
		self.assertNotIn("tiers", captured["filters"])
		self.assertEqual(captured["item_codes"], ["A"])

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
		normalized = report.normalize_sales_rows(rows, [
			{"item_code": "A", "last_sold_rate": 14}
		])
		self.assertEqual(normalized["A"]["weighted_average_sold_rate"], Decimal("12.500"))
		self.assertEqual(normalized["A"]["last_sold_rate"], Decimal("14.000"))

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

	def test_warehouse_filter_uses_each_stock_table_alias(self):
		filters = {"company": "WS", "warehouse": "Main - WS", "to_date": date(2026, 12, 31)}
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.side_effect = [[], []]
			report.get_stock_data(filters, ["A"])
		bin_query = frappe_mock.db.sql.call_args_list[0][0][0]
		sle_query = frappe_mock.db.sql.call_args_list[1][0][0]
		self.assertIn("bin.warehouse = %(warehouse)s", bin_query)
		self.assertIn("sle.warehouse = %(warehouse)s", sle_query)

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
		self.assertIn("`tabPurchase Invoice Item`", average_query)
		self.assertIn("`tabPurchase Invoice`", average_query)
		self.assertIn("`tabPurchase Invoice Item`", latest_query)
		self.assertNotIn("`tabPurchase Receipt Item`", average_query)
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

	def test_indirect_expense_context_uses_account_tree_and_company_net_sales(self):
		filters = {"company": "WS", "from_date": date(2026, 1, 1), "to_date": date(2026, 12, 31)}
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.get_value.return_value = frappe._dict({"lft": 10, "rgt": 20})
			frappe_mock.db.sql.side_effect = [[frappe._dict({"expense_total": 200})], [frappe._dict({"net_sales": 2000})]]
			context = report.get_indirect_expense_context(filters)
		expense_query = frappe_mock.db.sql.call_args_list[0][0][0]
		self.assertIn("account.lft between %(lft)s and %(rgt)s", expense_query)
		self.assertIn("Period Closing Voucher", expense_query)
		self.assertEqual(context["expense_ratio"], Decimal("0.100000"))

	def test_item_price_query_matches_v12_schema_and_stock_uom(self):
		filters = {
			"regular_price_list": "Regular", "b2b_price_list": None,
			"to_date": date(2026, 12, 31)
		}
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.return_value = []
			report.get_item_prices(filters, ["A"])
		query = frappe_mock.db.sql.call_args[0][0]
		self.assertNotIn("min_qty", query)
		self.assertIn("price_not_uom_dependent", query)
		self.assertIn("item.stock_uom", query)

	def test_item_group_lookup_uses_v12_get_all_without_pluck(self):
		filters = {"item_group": "Products"}
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.get_value.return_value = frappe._dict({"lft": 1, "rgt": 2})
			frappe_mock.get_all.return_value = [frappe._dict({"name": "Products"})]
			frappe_mock.get_list.return_value = []
			report.get_items(filters)
		self.assertNotIn("pluck", frappe_mock.get_all.call_args[1])
		self.assertEqual(frappe_mock.get_all.call_args[1]["limit_page_length"], 0)
		self.assertEqual(frappe_mock.get_list.call_args[1]["limit_page_length"], 0)
		self.assertEqual(frappe_mock.get_list.call_args[1]["filters"]["item_group"], ("in", ["Products"]))


class TestPricingStrategyReport(unittest.TestCase):

	def test_execute_assembles_json_serializable_row(self):
		filters = self._filters()
		with self._mock_readers() as readers:
			columns, data, message, chart = report.execute(filters)
		self.assertEqual(data[0]["item_code"], "A")
		self.assertEqual(data[0]["recommended_regular_gross"], 72.5)
		self.assertEqual(data[0]["suggested_action"], "Increase Price")
		self.assertIsNone(chart)
		self.assertIsNone(message)
		self.assertTrue(any(column["fieldname"] == "tier_4_net" for column in columns))
		self.assertEqual(readers["items"].call_count, 1)

	def test_execute_excludes_items_without_sales_when_requested(self):
		filters = self._filters()
		filters["exclude_items_without_sales"] = 1
		with self._mock_readers(sales={}):
			columns, data, message, chart = report.execute(filters)
		self.assertEqual(data, [])

	def test_basic_item_price_strategy_omits_tier_columns_and_values(self):
		filters = self._filters()
		filters["show_pricing_rule_strategy"] = 0
		with self._mock_readers():
			columns, data, message, chart = report.execute(filters)
		fieldnames = [column["fieldname"] for column in columns]
		self.assertFalse(any(fieldname.startswith("tier_") for fieldname in fieldnames))
		self.assertFalse(any(fieldname.startswith("tier_") for fieldname in data[0]))
		self.assertIsNone(message)

	def test_execute_keeps_missing_cost_with_warning(self):
		filters = self._filters()
		with self._mock_readers(stock={"A": {"valuation_rate": None, "available_qty": 0, "warnings": []}}):
			columns, data, message, chart = report.execute(filters)
		self.assertIsNone(data[0]["recommended_regular_net"])
		self.assertIn("Missing cost", data[0]["warnings"])

	def test_runtime_tier_labels_and_gap_message(self):
		filters = self._filters()
		filters["tier_2_minimum"] = 11
		with self._mock_readers():
			columns, data, message, chart = report.execute(filters)
		labels = [column["label"] for column in columns]
		self.assertIn("Qty 5-9 Net", labels)
		self.assertIn("Qty 40+ Net", labels)
		self.assertIn("Quantity tier gap between 9 and 11", message)

	def test_columns_are_compact_and_omit_repeated_analysis_fields(self):
		filters = report.validate_and_normalize_filters(self._filters())
		fieldnames = [column["fieldname"] for column in report.get_columns(filters)]
		for unwanted in (
			"valuation_rate", "latest_purchase_rate", "weighted_average_purchase_rate",
			"cost_source_detail", "expense_amount", "sales_value", "invoice_count", "last_sale_date",
			"lowest_sold_rate", "highest_sold_rate", "recommended_regular_profit",
			"recommended_regular_actual_markup_percent", "recommended_b2b_profit",
			"tier_1_profit", "tier_2_profit", "tier_3_profit", "tier_4_profit"
		):
			self.assertNotIn(unwanted, fieldnames)
		for required in (
			"selected_base_cost", "expense_per_unit", "fully_loaded_cost", "weighted_average_sold_rate",
			"recommended_regular_net", "recommended_regular_gross", "tier_4_gross"
		):
			self.assertIn(required, fieldnames)

	def _filters(self):
		return {
			"company": "WS", "from_date": "2026-01-01", "to_date": "2026-12-31",
			"regular_price_list": "Regular", "b2b_price_list": "B2B",
			"cost_source": "Current Valuation Rate",
			"vat_percent": 10,
			"regular_markup": 43, "b2b_markup": 33,
			"show_pricing_rule_strategy": 1,
			"tier_1_minimum": 5, "tier_1_maximum": 9, "tier_1_markup": 31,
			"tier_2_minimum": 10, "tier_2_maximum": 19, "tier_2_markup": 29,
			"tier_3_minimum": 20, "tier_3_maximum": 39, "tier_3_markup": 27,
			"tier_4_minimum": 40, "tier_4_maximum": "", "tier_4_markup": 25,
			"exclude_items_without_sales": 0
		}

	def _mock_readers(self, stock=None, sales=None):
		stock = stock if stock is not None else {
			"A": {"valuation_rate": Decimal("46"), "available_qty": Decimal("3"), "warnings": []}
		}
		sales = sales if sales is not None else {
			"A": {"sales_qty": Decimal("2"), "sales_value": Decimal("130"),
				  "weighted_average_sold_rate": Decimal("65"), "warnings": []}
		}
		stack = ExitStack()
		mocks = {
			"master": stack.enter_context(patch.object(report, "validate_master_filters", return_value="BHD")),
			"items": stack.enter_context(patch.object(report, "get_items", return_value=[{
				"item_code": "A", "item_name": "Item A", "item_group": "Products",
				"brand": "", "stock_uom": "Nos"
			}])),
			"stock": stack.enter_context(patch.object(report, "get_stock_data", return_value=stock)),
			"purchase": stack.enter_context(patch.object(report, "get_purchase_data", return_value={})),
			"sales": stack.enter_context(patch.object(report, "get_sales_data", return_value=sales)),
			"expense": stack.enter_context(patch.object(report, "get_indirect_expense_context", return_value={
				"expense_total": Decimal("0"), "net_sales": Decimal("1000"),
				"expense_ratio": Decimal("0"), "warnings": []
			})),
			"prices": stack.enter_context(patch.object(report, "get_item_prices", return_value={
				"A": {"current_normal_price": Decimal("60"), "current_b2b_price": Decimal("55"), "warnings": []}
			}))
		}
		class ManagedStack(object):
			def __enter__(self_inner):
				return mocks
			def __exit__(self_inner, exc_type, exc_value, traceback):
				return stack.__exit__(exc_type, exc_value, traceback)
		return ManagedStack()


class TestPricingStrategyReportFiles(unittest.TestCase):

	def test_report_metadata_and_filter_contract(self):
		base_path = os.path.dirname(__file__)
		with open(os.path.join(base_path, "pricing_strategy_analysis.json")) as source:
			metadata = json.load(source)
		with open(os.path.join(base_path, "pricing_strategy_analysis.js")) as source:
			javascript = source.read()
		self.assertEqual(metadata["report_name"], "Pricing Strategy Analysis")
		self.assertEqual(metadata["report_type"], "Script Report")
		self.assertEqual(metadata["ref_doctype"], "Item")
		self.assertEqual(
			sorted(row["role"] for row in metadata["roles"]),
			["Accounts Manager", "System Manager"]
		)
		required_fields = [
			"company", "from_date", "to_date", "item", "item_group", "brand", "warehouse",
			"regular_price_list", "b2b_price_list", "show_pricing_rule_strategy",
			"exclude_items_without_sales", "cost_source",
			"vat_percent",
			"regular_markup", "b2b_markup"
		]
		for index in range(1, 5):
			required_fields.extend(["tier_{0}_qty_range".format(index), "tier_{0}_markup".format(index)])
		for fieldname in required_fields:
			self.assertIn('"fieldname": "{0}"'.format(fieldname), javascript)
		self.assertIn(r"Current Valuation Rate\nLatest Purchase Rate\nWeighted Average Purchase Rate", javascript)
		self.assertNotIn("frappe.call", javascript)
		self.assertNotIn("add_inner_button", javascript)
		self.assertIn("pricing-strategy-filter-label", javascript)
		self.assertIn('"prepared_report": 1', json.dumps(metadata))
		self.assertIn('"disable_prepared_report": 0', json.dumps(metadata))
		self.assertNotIn('"fieldname": "tier_1_minimum"', javascript)
		self.assertNotIn('"fieldname": "tier_1_maximum"', javascript)
		filter_order = re.findall(r'"fieldname": "([^"]+)"', javascript)
		self.assertEqual(filter_order[-1], "exclude_items_without_sales")
		self.assertEqual(filter_order[7:12], [
			"regular_price_list", "regular_markup", "b2b_price_list",
			"b2b_markup", "cost_source"
		])
		self.assertIn('"label": __("Regular Price Markup %")', javascript)
		self.assertIn('"label": __("B2B Price Markup %")', javascript)
		self.assertIn('"label": __("Exclude Items Without Sales")', javascript)
		self.assertIn('"fieldtype": "Check", "default": 0', javascript)
		self.assertNotIn("Normal Price Markup %", javascript)
		self.assertNotIn('"fieldname": "expense_burden"', javascript)
		self.assertNotIn('"fieldname": "rounding_increment"', javascript)
		self.assertNotIn('"fieldname": "rounding_method"', javascript)
		self.assertIn("toggle_pricing_rule_strategy_filters", javascript)
		self.assertIn('"on_change": function ()', javascript)
		self.assertNotIn("margin:0 !important;padding:0 !important", javascript)
		self.assertIn("padding-top:0 !important;padding-bottom:0 !important", javascript)


if __name__ == "__main__":
	unittest.main()
