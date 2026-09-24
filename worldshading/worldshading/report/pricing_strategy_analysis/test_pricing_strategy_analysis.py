from __future__ import unicode_literals

import unittest
from contextlib import ExitStack
from datetime import date
from decimal import Decimal
import json
import os
import re
from unittest.mock import MagicMock, patch

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

	def test_expense_can_be_excluded_from_recommended_price_calculation(self):
		filters = self._valid_filters()
		filters["exclude_expense_from_pricing"] = 1
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
		self.assertEqual(row["recommended_regular_net"], Decimal("143.636"))
		self.assertIn("Expense excluded from price calculation", row["warnings"])

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
		self.assertFalse(result["exclude_expense_from_pricing"])
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

	def test_strategy_master_overrides_controlled_filter_values(self):
		filters = self._valid_filters()
		filters["pricing_strategy"] = "Wholesale"
		settings = {
			"pricing_strategy": "Wholesale", "company": "World Shading",
			"cost_source": "Latest Purchase Rate",
			"exclude_expense_from_pricing": True,
			"indirect_expense_account": "Indirect Expenses - WS",
			"expense_allocation_method": "Sales Value Ratio",
			"vat_percent": Decimal("10"), "regular_price_list": "Regular",
			"regular_markup": Decimal("40"), "enable_b2b_pricing": False,
			"b2b_price_list": None, "b2b_markup": Decimal("0"),
			"show_pricing_rule_strategy": True,
			"tiers": [{"minimum": Decimal("5"), "maximum": None, "markup": Decimal("25")}]
		}
		with patch.object(report, "_get_pricing_strategy_settings", return_value=settings):
			normalized = report.validate_and_normalize_filters(filters)
		self.assertEqual(normalized["regular_price_list"], "Regular")
		self.assertEqual(normalized["regular_markup"], Decimal("40"))
		self.assertFalse(normalized["enable_b2b_pricing"])
		self.assertEqual(normalized["tiers"], settings["tiers"])

	def test_prepared_snapshot_uses_saved_tiers_without_reloading_master(self):
		filters = self._valid_filters()
		filters["pricing_strategy"] = "Wholesale"
		filters["pricing_tiers_json"] = json.dumps([
			{"minimum": 5, "maximum": 9, "markup": 30},
			{"minimum": 10, "maximum": None, "markup": 25}
		])
		filters.pop("tier_1_minimum")
		filters.pop("tier_1_maximum")
		filters.pop("tier_1_markup")
		filters.pop("tier_2_minimum")
		filters.pop("tier_2_maximum")
		filters.pop("tier_2_markup")
		filters.pop("tier_3_minimum")
		filters.pop("tier_3_maximum")
		filters.pop("tier_3_markup")
		filters.pop("tier_4_minimum")
		filters.pop("tier_4_maximum")
		filters.pop("tier_4_markup")
		with patch.object(report, "_get_pricing_strategy_settings") as get_settings:
			normalized = report.validate_and_normalize_filters(filters, apply_strategy=False)
		get_settings.assert_not_called()
		self.assertEqual(len(normalized["tiers"]), 2)
		self.assertEqual(normalized["tiers"][1]["markup"], Decimal("25"))

	def test_price_columns_are_grouped_by_regular_b2b_and_tier(self):
		filters = self._valid_filters()
		filters["b2b_price_list"] = "B2B"
		normalized = report.validate_and_normalize_filters(filters)
		fieldnames = [column["fieldname"] for column in report.get_columns(normalized)]
		regular_fields = [
			"current_normal_price", "recommended_regular_net", "recommended_regular_gross",
			"recommended_regular_gross_margin_percent", "change_from_current_normal",
			"change_from_current_normal_percent", "suggested_action"
		]
		b2b_fields = [
			"current_b2b_price", "recommended_b2b_net", "recommended_b2b_gross",
			"recommended_b2b_gross_margin_percent", "b2b_discount_percent"
		]
		regular_start = fieldnames.index("current_normal_price")
		b2b_start = fieldnames.index("current_b2b_price")
		self.assertEqual(fieldnames[regular_start:regular_start + len(regular_fields)], regular_fields)
		self.assertEqual(fieldnames[b2b_start:b2b_start + len(b2b_fields)], b2b_fields)
		self.assertGreater(fieldnames.index("tier_1_net"), b2b_start)
		self.assertGreater(fieldnames.index("tier_2_net"), fieldnames.index("tier_1_gross_margin_percent"))


class TestPricingStrategyItemPriceUpdateHelpers(unittest.TestCase):

	def setUp(self):
		frappe.local.db = MagicMock()
		frappe.local.session = frappe._dict({"user": "test@example.com"})
		frappe.local.flags = frappe._dict()

	def test_update_item_codes_keep_first_50_unique_real_items(self):
		values = ["ITEM-{0:03d}".format(index) for index in range(55)]
		values.insert(2, "ITEM-001")
		values.insert(4, "")
		result = report._normalize_update_item_codes(values)
		self.assertEqual(len(result), 50)
		self.assertEqual(result[:3], ["ITEM-000", "ITEM-001", "ITEM-002"])
		self.assertEqual(result[-1], "ITEM-049")

	def test_update_item_codes_accept_dictionary_rows_and_json(self):
		values = json.dumps([
			{"item_code": " A "}, {"item_code": "B"},
			{"item_code": "A"}, {"total": "Total"}
		])
		self.assertEqual(report._normalize_update_item_codes(values), ["A", "B"])

	def test_prepared_report_must_be_completed_pricing_report(self):
		prepared = {
			"name": "PREP-1", "report_name": "Other Report",
			"status": "Completed", "owner": "test@example.com", "filters": "{}"
		}
		with patch.object(report.frappe.db, "get_value", return_value=prepared):
			with patch.object(report.frappe, "throw", side_effect=frappe.ValidationError):
				with self.assertRaises(frappe.ValidationError):
					report._get_prepared_pricing_report("PREP-1")

	def test_prepared_report_requires_name_completed_status_and_access(self):
		with patch.object(report.frappe, "throw", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				report._get_prepared_pricing_report(None)

		prepared = {
			"name": "PREP-1", "report_name": "Pricing Strategy Analysis",
			"status": "Queued", "owner": "test@example.com", "filters": "{}"
		}
		with patch.object(report.frappe.db, "get_value", return_value=prepared):
			with patch.object(report.frappe, "throw", side_effect=frappe.ValidationError):
				with self.assertRaises(frappe.ValidationError):
					report._get_prepared_pricing_report("PREP-1")

		prepared["status"] = "Completed"
		prepared["owner"] = "another@example.com"
		with patch.object(report.frappe.db, "get_value", return_value=prepared):
			with patch.object(report.frappe, "get_roles", return_value=[]):
				with patch.object(report.frappe, "throw", side_effect=frappe.PermissionError):
					with self.assertRaises(frappe.PermissionError):
						report._get_prepared_pricing_report("PREP-1")

	def test_prepared_report_rejects_malformed_filters(self):
		prepared = {
			"name": "PREP-1", "report_name": "Pricing Strategy Analysis",
			"status": "Completed", "owner": "test@example.com",
			"filters": "not-json"
		}
		with patch.object(report.frappe.db, "get_value", return_value=prepared):
			with patch.object(report.frappe, "throw", side_effect=frappe.ValidationError):
				with self.assertRaises(frappe.ValidationError):
					report._get_prepared_pricing_report("PREP-1")

	def test_prepared_rows_are_loaded_from_core_prepared_report_attachment(self):
		prepared = frappe._dict({
			"name": "PREP-1", "report_name": "Pricing Strategy Analysis",
			"status": "Completed", "owner": "test@example.com",
			"filters": {"company": "World Shading"}
		})
		rows = [{"item_code": "A", "recommended_regular_net": 12}, ["Total"]]
		content = frappe.utils.gzip_compress(frappe.safe_encode(json.dumps(rows)))
		file_doc = frappe._dict({"get_content": lambda: content})
		with patch.object(report, "_get_prepared_pricing_report", return_value=prepared):
			with patch.object(report.frappe.db, "get_value", return_value="FILE-1"):
				with patch.object(report.frappe, "get_doc", return_value=file_doc):
					self.assertEqual(
						report._get_prepared_pricing_rows("PREP-1"),
						[{"item_code": "A", "recommended_regular_net": 12}]
					)

	def test_prepared_rows_reject_missing_attachment(self):
		prepared = frappe._dict({"name": "PREP-1"})
		with patch.object(report, "_get_prepared_pricing_report", return_value=prepared):
			with patch.object(report.frappe.db, "get_value", return_value=None):
				with patch.object(report.frappe, "throw", side_effect=frappe.ValidationError):
					with self.assertRaises(frappe.ValidationError):
						report._get_prepared_pricing_rows("PREP-1")


class TestPricingStrategyItemPricePreview(unittest.TestCase):

	def setUp(self):
		frappe.local.db = MagicMock()
		frappe.local.session = frappe._dict({"user": "test@example.com"})
		frappe.local.flags = frappe._dict()

	def _prepared(self, b2b_price_list=None):
		return frappe._dict({
			"name": "PREP-1",
			"filters": {
				"regular_price_list": "Regular",
				"b2b_price_list": b2b_price_list,
				"to_date": date(2026, 9, 24)
			}
		})

	def _rows(self):
		return [
			{"item_code": "A", "item_name": "Item A", "stock_uom": "Nos",
			 "recommended_regular_net": 12, "recommended_b2b_net": 11},
			{"item_code": "B", "item_name": "Item B", "stock_uom": "Nos",
			 "recommended_regular_net": 20, "recommended_b2b_net": 18},
			{"item_code": "C", "item_name": "Item C", "stock_uom": "Nos",
			 "recommended_regular_net": 30, "recommended_b2b_net": 27}
		]

	def _items(self):
		return {
			code: frappe._dict({
				"name": code, "item_name": "Item " + code,
				"item_group": "Exact Group " + code, "stock_uom": "Nos"
			})
			for code in ("A", "B", "C")
		}

	def _regular_price_list(self):
		return [frappe._dict({
			"name": "Regular", "kind": "Regular", "currency": "BHD",
			"price_not_uom_dependent": 0,
			"recommendation_field": "recommended_regular_net"
		})]

	def test_preview_regular_only_classifies_update_create_and_unchanged(self):
		targets = [
			{"name": "IP-A", "rate": Decimal("10"), "modified": "2026-09-24 09:00:00",
			 "uom": "Nos", "duplicate_count": 1},
			{"name": None, "rate": None, "modified": None, "uom": "Nos", "duplicate_count": 0},
			{"name": "IP-C", "rate": Decimal("30"), "modified": "2026-09-24 09:00:00",
			 "uom": "Nos", "duplicate_count": 1}
		]
		cache = MagicMock()
		with patch.object(report, "_get_prepared_pricing_report", return_value=self._prepared()):
			with patch.object(report, "_get_prepared_pricing_rows", return_value=self._rows()):
				with patch.object(report, "_get_update_items", return_value=self._items()):
					with patch.object(report, "_get_update_price_lists", return_value=self._regular_price_list()):
						with patch.object(report, "_resolve_item_price_target", side_effect=targets):
							with patch.object(report.frappe, "generate_hash", return_value="TOKEN-1"):
								with patch.object(report.frappe, "cache", return_value=cache):
									preview = report.preview_item_price_update("PREP-1", ["A", "B", "C"])
		self.assertEqual(
			[row["action"] for row in preview["entries"]],
			["Update", "Create", "Unchanged"]
		)
		self.assertEqual(preview["counts"], {"create": 1, "update": 1, "unchanged": 1})
		self.assertFalse(any(row["price_list"] == "B2B" for row in preview["entries"]))
		self.assertEqual(preview["token"], "TOKEN-1")
		self.assertEqual(cache.set_value.call_args[1]["expires_in_sec"], 600)

	def test_preview_adds_b2b_entries_when_saved_filter_selects_b2b(self):
		price_lists = self._regular_price_list() + [frappe._dict({
			"name": "B2B", "kind": "B2B", "currency": "BHD",
			"price_not_uom_dependent": 0,
			"recommendation_field": "recommended_b2b_net"
		})]
		with patch.object(report, "_get_prepared_pricing_report", return_value=self._prepared("B2B")):
			with patch.object(report, "_get_prepared_pricing_rows", return_value=self._rows()):
				with patch.object(report, "_get_update_items", return_value=self._items()):
					with patch.object(report, "_get_update_price_lists", return_value=price_lists):
						with patch.object(report, "_resolve_item_price_target", return_value={
							"name": None, "rate": None, "modified": None,
							"uom": "Nos", "duplicate_count": 0
						}):
							with patch.object(report.frappe, "generate_hash", return_value="TOKEN-2"):
								with patch.object(report.frappe, "cache", return_value=MagicMock()):
									preview = report.preview_item_price_update("PREP-1", ["A"])
		self.assertEqual([row["price_kind"] for row in preview["entries"]], ["Regular", "B2B"])
		self.assertEqual([row["new_rate"] for row in preview["entries"]], [12.0, 11.0])

	def test_preview_limits_to_50_and_uses_saved_prices_not_client_values(self):
		rows = []
		items = {}
		for index in range(55):
			code = "ITEM-{0:03d}".format(index)
			rows.append({
				"item_code": code, "item_name": code, "stock_uom": "Nos",
				"recommended_regular_net": index + 1
			})
			items[code] = frappe._dict({"name": code, "item_name": code, "stock_uom": "Nos"})
		client_rows = [{"item_code": row["item_code"], "recommended_regular_net": 999} for row in rows]
		with patch.object(report, "_get_prepared_pricing_report", return_value=self._prepared()):
			with patch.object(report, "_get_prepared_pricing_rows", return_value=rows):
				with patch.object(report, "_get_update_items", return_value=items):
					with patch.object(report, "_get_update_price_lists", return_value=self._regular_price_list()):
						with patch.object(report, "_resolve_item_price_target", return_value={
							"name": None, "rate": None, "modified": None,
							"uom": "Nos", "duplicate_count": 0
						}):
							with patch.object(report.frappe, "generate_hash", return_value="TOKEN-3"):
								with patch.object(report.frappe, "cache", return_value=MagicMock()):
									preview = report.preview_item_price_update("PREP-1", client_rows)
		self.assertEqual(preview["requested_item_count"], 50)
		self.assertEqual(len(preview["entries"]), 50)
		self.assertEqual(preview["entries"][0]["new_rate"], 1.0)
		self.assertEqual(preview["entries"][-1]["item_code"], "ITEM-049")

	def test_preview_rejects_item_absent_from_saved_result(self):
		with patch.object(report, "_get_prepared_pricing_report", return_value=self._prepared()):
			with patch.object(report, "_get_prepared_pricing_rows", return_value=self._rows()):
				with patch.object(report.frappe, "throw", side_effect=frappe.ValidationError):
					with self.assertRaises(frappe.ValidationError):
						report.preview_item_price_update("PREP-1", ["MISSING"])

	def test_target_resolution_uses_stock_uom_and_warns_for_duplicates(self):
		item = frappe._dict({"name": "A", "stock_uom": "Nos"})
		price_list = frappe._dict({"name": "Regular", "price_not_uom_dependent": 0})
		rows = [
			frappe._dict({"name": "OLD", "price_list_rate": 10, "uom": "Nos",
				"valid_from": date(2025, 1, 1), "valid_upto": None,
				"creation": "2025-01-01", "modified": "2025-01-01"}),
			frappe._dict({"name": "NEW", "price_list_rate": 12, "uom": "Nos",
				"valid_from": date(2026, 1, 1), "valid_upto": None,
				"creation": "2026-01-01", "modified": "2026-01-01"}),
			frappe._dict({"name": "OTHER-UOM", "price_list_rate": 8, "uom": "Box",
				"valid_from": date(2026, 1, 1), "valid_upto": None,
				"creation": "2026-01-02", "modified": "2026-01-02"})
		]
		with patch.object(report.frappe, "get_list", return_value=rows):
			target = report._resolve_item_price_target(item, price_list, date(2026, 9, 24))
		self.assertEqual(target["name"], "NEW")
		self.assertEqual(target["rate"], Decimal("12.000"))
		self.assertEqual(target["duplicate_count"], 2)
		self.assertEqual(target["uom"], "Nos")


class TestPricingStrategyItemPriceExecution(unittest.TestCase):

	def setUp(self):
		frappe.local.db = MagicMock()
		frappe.local.session = frappe._dict({"user": "test@example.com"})
		frappe.local.flags = frappe._dict()

	def _payload(self):
		return {
			"prepared_report": "PREP-1",
			"user": "test@example.com",
			"entries": [
				{"item_code": "A", "price_list": "Regular", "price_kind": "Regular",
				 "currency": "BHD", "new_rate": 12.0, "action": "Create",
				 "item_price_name": None, "target_modified": None, "uom": "Nos"},
				{"item_code": "B", "price_list": "Regular", "price_kind": "Regular",
				 "currency": "BHD", "new_rate": 20.0, "action": "Update",
				 "item_price_name": "IP-OLD", "target_modified": "2026-09-24 09:00:00",
				 "current_rate": 18.0, "uom": "Nos"},
				{"item_code": "C", "price_list": "Regular", "price_kind": "Regular",
				 "currency": "BHD", "new_rate": 30.0, "action": "Unchanged",
				 "item_price_name": "IP-SAME", "target_modified": "2026-09-24 09:00:00",
				 "current_rate": 30.0, "uom": "Nos"}
			]
		}

	def _prepared(self):
		return frappe._dict({
			"name": "PREP-1",
			"filters": {
				"regular_price_list": "Regular", "b2b_price_list": None,
				"to_date": date(2026, 9, 24)
			}
		})

	def _items(self):
		return {
			code: frappe._dict({
				"name": code, "item_name": "Item " + code,
				"item_group": "Exact Group " + code, "stock_uom": "Nos"
			})
			for code in ("A", "B", "C")
		}

	def _price_lists(self):
		return [frappe._dict({
			"name": "Regular", "kind": "Regular", "currency": "BHD",
			"price_not_uom_dependent": 0,
			"recommendation_field": "recommended_regular_net"
		})]

	def _rows(self):
		return [
			{"item_code": "A", "recommended_regular_net": 12},
			{"item_code": "B", "recommended_regular_net": 20},
			{"item_code": "C", "recommended_regular_net": 30}
		]

	def _run_with_common_patches(self, payload=None, targets=None,
			create_permission=True, new_doc=None, old_doc=None):
		payload = payload if payload is not None else self._payload()
		targets = targets if targets is not None else [
			{"name": None, "rate": None, "modified": None, "uom": "Nos", "duplicate_count": 0},
			{"name": "IP-OLD", "rate": Decimal("18.000"),
			 "modified": "2026-09-24 09:00:00", "uom": "Nos", "duplicate_count": 1},
			{"name": "IP-SAME", "rate": Decimal("30.000"),
			 "modified": "2026-09-24 09:00:00", "uom": "Nos", "duplicate_count": 1}
		]
		cache = MagicMock()
		cache.get_value.return_value = payload
		new_doc = new_doc or MagicMock()
		new_doc.name = "IP-NEW"
		old_doc = old_doc or MagicMock()
		old_doc.name = "IP-OLD"
		with ExitStack() as stack:
			stack.enter_context(patch.object(report.frappe, "cache", return_value=cache))
			stack.enter_context(patch.object(report, "_get_prepared_pricing_report", return_value=self._prepared()))
			stack.enter_context(patch.object(report, "_get_prepared_pricing_rows", return_value=self._rows()))
			stack.enter_context(patch.object(report, "_get_update_items", return_value=self._items()))
			stack.enter_context(patch.object(report, "_get_update_price_lists", return_value=self._price_lists()))
			stack.enter_context(patch.object(report, "_resolve_item_price_target", side_effect=targets))
			stack.enter_context(patch.object(report.frappe, "has_permission", return_value=create_permission))
			stack.enter_context(patch.object(report.frappe, "get_doc", return_value=old_doc))
			stack.enter_context(patch.object(report.frappe, "new_doc", return_value=new_doc))
			result = report.execute_item_price_update("TOKEN-1")
		return result, cache, new_doc, old_doc

	def test_execute_creates_updates_and_skips_unchanged_prices(self):
		result, cache, new_doc, old_doc = self._run_with_common_patches()
		self.assertEqual(result["created"], 1)
		self.assertEqual(result["updated"], 1)
		self.assertEqual(result["unchanged"], 1)
		self.assertEqual(result["item_prices"], ["IP-NEW", "IP-OLD"])
		self.assertEqual(new_doc.item_code, "A")
		self.assertEqual(new_doc._item_group, "Exact Group A")
		self.assertEqual(new_doc.price_list_rate, Decimal("12.000"))
		self.assertEqual(new_doc.pricing_prepared_report, "PREP-1")
		new_doc.insert.assert_called_once_with()
		self.assertIn("PREP-1", new_doc.add_comment.call_args[0][1])
		old_doc.check_permission.assert_called_with("write")
		self.assertEqual(old_doc.price_list_rate, Decimal("20.000"))
		self.assertEqual(old_doc.pricing_prepared_report, "PREP-1")
		old_doc.save.assert_called_once_with()
		self.assertIn("18.000", old_doc.add_comment.call_args[0][1])
		self.assertIn("20.000", old_doc.add_comment.call_args[0][1])
		cache.delete_value.assert_called_once()

	def test_execute_rejects_missing_expired_or_other_user_token(self):
		cache = MagicMock()
		cache.get_value.return_value = None
		with patch.object(report.frappe, "cache", return_value=cache):
			with patch.object(report.frappe, "throw", side_effect=frappe.ValidationError):
				with self.assertRaises(frappe.ValidationError):
					report.execute_item_price_update("TOKEN-1")

		payload = self._payload()
		payload["user"] = "other@example.com"
		cache.get_value.return_value = payload
		with patch.object(report.frappe, "cache", return_value=cache):
			with patch.object(report.frappe, "throw", side_effect=frappe.PermissionError):
				with self.assertRaises(frappe.PermissionError):
					report.execute_item_price_update("TOKEN-1")

	def test_execute_rejects_missing_create_permission(self):
		with patch.object(report.frappe, "throw", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				self._run_with_common_patches(create_permission=False)

	def test_execute_rejects_concurrent_rate_change_before_writes(self):
		targets = [
			{"name": None, "rate": None, "modified": None, "uom": "Nos", "duplicate_count": 0},
			{"name": "IP-OLD", "rate": Decimal("19.000"),
			 "modified": "2026-09-24 09:00:00", "uom": "Nos", "duplicate_count": 1},
			{"name": "IP-SAME", "rate": Decimal("30.000"),
			 "modified": "2026-09-24 09:00:00", "uom": "Nos", "duplicate_count": 1}
		]
		new_doc = MagicMock()
		old_doc = MagicMock()
		with patch.object(report.frappe, "throw", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				self._run_with_common_patches(targets=targets, new_doc=new_doc, old_doc=old_doc)
		new_doc.insert.assert_not_called()
		old_doc.save.assert_not_called()

	def test_execute_keeps_token_when_save_raises(self):
		old_doc = MagicMock()
		old_doc.save.side_effect = RuntimeError("save failed")
		cache = None
		with self.assertRaises(RuntimeError):
			self._run_with_common_patches(old_doc=old_doc)
		# The execution method deletes its token only after every save succeeds.
		self.assertTrue(old_doc.save.called)


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
			"company", "pricing_strategy", "from_date", "to_date", "item", "item_group", "brand", "warehouse",
			"regular_price_list", "b2b_price_list", "show_pricing_rule_strategy",
			"exclude_items_without_sales", "exclude_expense_from_pricing", "cost_source",
			"indirect_expense_account", "pricing_tiers_json", "vat_percent",
			"regular_markup", "b2b_markup"
		]
		for fieldname in required_fields:
			self.assertIn('"fieldname": "{0}"'.format(fieldname), javascript)
		self.assertIn(r"Current Valuation Rate\nLatest Purchase Rate\nWeighted Average Purchase Rate", javascript)
		self.assertIn('report.page.add_inner_button(__("Update Item Price")', javascript)
		self.assertIn('report.page.add_inner_button(__("Update Pricing Rule")', javascript)
		self.assertIn("get_pricing_update_item_codes", javascript)
		self.assertIn("report.raw_data.add_total_row", javascript)
		self.assertIn("report_rows.slice(0, -1)", javascript)
		self.assertIn("show_item_price_update_dialog", javascript)
		self.assertIn("show_pricing_rule_update_notice", javascript)
		self.assertIn("preview_item_price_update", javascript)
		self.assertIn("execute_item_price_update", javascript)
		self.assertIn("frappe.confirm", javascript)
		self.assertIn("slice(0, 50)", javascript)
		self.assertIn("report.raw_data.doc.name", javascript)
		self.assertIn("cannot_add_rows: true", javascript)
		self.assertIn("cannot_delete_rows: true", javascript)
		self.assertIn("Only the first 50 Items", javascript)
		self.assertIn("freeze: true", javascript)
		self.assertIn("Pricing Rule update configuration is pending", javascript)
		self.assertNotIn("create_pricing_rule", javascript)
		self.assertIn("pricing-strategy-filter-label", javascript)
		self.assertIn('"prepared_report": 1', json.dumps(metadata))
		self.assertIn('"disable_prepared_report": 0', json.dumps(metadata))
		self.assertNotIn('"fieldname": "tier_1_minimum"', javascript)
		self.assertNotIn('"fieldname": "tier_1_maximum"', javascript)
		filter_order = re.findall(r'"fieldname": "([^"]+)"', javascript)
		self.assertEqual(filter_order[-1], "exclude_items_without_sales")
		self.assertEqual(filter_order[8:13], [
			"regular_price_list", "regular_markup", "b2b_price_list",
			"b2b_markup", "cost_source"
		])
		self.assertIn('"label": __("Regular Price Markup %")', javascript)
		self.assertIn('"label": __("B2B Price Markup %")', javascript)
		self.assertIn('"label": __("Exclude Items Without Sales")', javascript)
		self.assertIn('"label": __("Exclude Expense")', javascript)
		self.assertNotIn("Exclude Expense from Price Calculation", javascript)
		self.assertIn('"fieldtype": "Check", "default": 0', javascript)
		self.assertNotIn("Normal Price Markup %", javascript)
		self.assertNotIn('"fieldname": "expense_burden"', javascript)
		self.assertNotIn('"fieldname": "rounding_increment"', javascript)
		self.assertNotIn('"fieldname": "rounding_method"', javascript)
		self.assertIn("load_pricing_strategy_settings", javascript)
		self.assertIn("get_pricing_strategy_settings", javascript)
		self.assertIn('"on_change": function ()', javascript)
		self.assertNotIn("margin:0 !important;padding:0 !important", javascript)
		self.assertIn("padding-top:0 !important;padding-bottom:0 !important", javascript)
		self.assertIn("apply_pricing_strategy_column_colors", javascript)
		self.assertIn('"after_datatable_render": function (datatable)', javascript)
		self.assertIn('recommended_regular_net', javascript)
		self.assertIn('recommended_b2b_net', javascript)
		self.assertIn('/^tier_(\\d+)_/', javascript)
		self.assertIn('var regular_fields = [', javascript)
		self.assertIn('var b2b_fields = [', javascript)
		self.assertIn('var tier_colors = [', javascript)
		self.assertIn('pricing-strategy-result-column-style', javascript)
		self.assertIn("get_expense_per_unit_tooltip", javascript)
		self.assertIn('column.fieldname === "expense_per_unit"', javascript)
		self.assertIn('data.allocated_expense', javascript)
		self.assertIn('data.sales_value', javascript)
		self.assertIn('data.sales_qty', javascript)
		tooltip_source = javascript.split("function get_expense_per_unit_tooltip", 1)[1]
		tooltip_source = tooltip_source.split("function get_pricing_update_item_codes", 1)[0]
		self.assertNotIn("frappe.call", tooltip_source)


if __name__ == "__main__":
	unittest.main()
