from __future__ import unicode_literals

import json
import os
import unittest
from datetime import date
from unittest.mock import patch

from worldshading.worldshading.report.customer_retention_analysis import (
	customer_retention_analysis as report,
)


class TestCustomerRetentionAnalysis(unittest.TestCase):
	def valid_filters(self, **overrides):
		filters = {
			"company": "World Shading",
			"analysis_year": 2026,
			"previous_years": 1,
		}
		filters.update(overrides)
		return filters

	def test_metadata_defines_prepared_script_report_and_exact_roles(self):
		path = os.path.join(os.path.dirname(__file__), "customer_retention_analysis.json")
		with open(path) as source:
			metadata = json.load(source)

		self.assertEqual(metadata["name"], "Customer Retention Analysis")
		self.assertEqual(metadata["report_name"], "Customer Retention Analysis")
		self.assertEqual(metadata["module"], "Worldshading")
		self.assertEqual(metadata["report_type"], "Script Report")
		self.assertEqual(metadata["ref_doctype"], "Sales Invoice")
		self.assertEqual(metadata["is_standard"], "Yes")
		self.assertEqual(metadata["prepared_report"], 1)
		self.assertEqual(metadata["disable_prepared_report"], 0)
		self.assertEqual(metadata["add_total_row"], 0)
		self.assertEqual(
			set(row["role"] for row in metadata["roles"]),
			set([
				"Cashier", "Sales Manager", "General Manager",
				"Accounts Manager", "System Manager",
			]),
		)

	def test_normalize_filters_applies_approved_defaults(self):
		filters = report.normalize_filters({"company": "World Shading"}, current_year=2026)

		self.assertEqual(filters.analysis_year, 2026)
		self.assertEqual(filters.previous_years, 1)
		self.assertEqual(filters.top_results, "100")
		self.assertEqual(filters.sort_by, "Importance")
		self.assertEqual(filters.sort_direction, "Descending")
		self.assertEqual(filters.minimum_historical_sales, 0.0)

	def test_normalize_filters_rejects_missing_company(self):
		with patch.object(report.frappe, "throw", side_effect=ValueError("Company is required")):
			with self.assertRaises(ValueError):
				report.normalize_filters({}, current_year=2026)

	def test_normalize_filters_rejects_invalid_controlled_values(self):
		invalid_filters = [
			{"analysis_year": 0},
			{"analysis_year": 1999},
			{"analysis_year": 2027},
			{"previous_years": 0},
			{"previous_years": 6},
			{"minimum_historical_sales": -1},
			{"retention_status": "Dormant"},
			{"sort_by": "Revenue"},
			{"sort_direction": "Sideways"},
			{"top_results": "10"},
			{"top_results": 0},
		]
		for invalid in invalid_filters:
			filters = self.valid_filters(**invalid)
			with self.subTest(invalid=invalid):
				with patch.object(report.frappe, "throw", side_effect=ValueError("Invalid filters")):
					with self.assertRaises(ValueError):
						report.normalize_filters(filters, current_year=2026)

	def test_period_helpers_use_full_calendar_years(self):
		filters = report.normalize_filters(
			self.valid_filters(previous_years=3), current_year=2026
		)

		self.assertEqual(report.get_years(filters), [2026, 2025, 2024, 2023])
		self.assertEqual(
			report.get_period_bounds(filters),
			(date(2023, 1, 1), date(2026, 12, 31)),
		)

	def test_columns_use_year_labels_and_newest_first_dynamic_history(self):
		filters = report.normalize_filters(
			self.valid_filters(previous_years=3), current_year=2026
		)
		columns = report.get_columns(filters, "BHD")
		fieldnames = [column["fieldname"] for column in columns]

		self.assertEqual(fieldnames[0:6], [
			"rank", "customer", "customer_name", "customer_group", "territory",
			"retention_status",
		])
		self.assertEqual(
			[fieldname for fieldname in fieldnames if fieldname.startswith("sales_")],
			["sales_2025", "sales_2024", "sales_2023"],
		)
		labels = dict((column["fieldname"], column["label"]) for column in columns)
		self.assertEqual(labels["current_sales"], "2026 Sales")
		self.assertEqual(labels["previous_sales"], "2025 Sales")
		self.assertEqual(labels["sales_2023"], "2023 Sales")
		for column in columns:
			if column["fieldtype"] == "Currency":
				self.assertEqual(column["options"], "BHD")

	def test_classification_covers_status_boundaries_and_older_history(self):
		cases = [
			("older year loss", {2026: 0, 2025: 0, 2024: 50}, "Lost"),
			("negative current loss", {2026: -10, 2025: 100, 2024: 0}, "Lost"),
			("exact decrease", {2026: 80, 2025: 100, 2024: 0}, "Decreased"),
			("above decrease boundary", {2026: 80.01, 2025: 100, 2024: 0}, "Stable"),
			("exact increase", {2026: 120, 2025: 100, 2024: 0}, "Increased"),
			("below increase boundary", {2026: 119.99, 2025: 100, 2024: 0}, "Stable"),
			("new", {2026: 25, 2025: 0, 2024: -5}, "New"),
			("reactivated", {2026: 25, 2025: 0, 2024: 50}, "Reactivated"),
		]
		for label, values, expected in cases:
			with self.subTest(label=label):
				self.assertEqual(report.classify_customer(values, 2026, 2), expected)

	def test_build_customer_row_calculates_sales_activity_and_inactivity(self):
		filters = report.normalize_filters(
			self.valid_filters(previous_years=3), current_year=2026
		)
		year_values = {
			2026: {"sales": 80, "invoice_count": 2},
			2025: {"sales": 100, "invoice_count": 4},
			2024: {"sales": 0, "invoice_count": 0},
			2023: {"sales": 50, "invoice_count": 1},
		}
		row = report.build_customer_row(
			"CUST-001",
			{"customer_name": "Alpha", "customer_group": "Commercial", "territory": "Bahrain"},
			year_values,
			date(2025, 12, 31),
			filters,
			date(2026, 10, 22),
		)

		self.assertEqual(row["retention_status"], "Decreased")
		self.assertEqual(row["current_sales"], 80.0)
		self.assertEqual(row["previous_sales"], 100.0)
		self.assertEqual(row["change_amount"], -20.0)
		self.assertEqual(row["decrease_amount"], 20.0)
		self.assertEqual(row["change_percent"], -20.0)
		self.assertEqual(row["average_historical_sales"], 50.0)
		self.assertEqual([row["sales_2025"], row["sales_2024"], row["sales_2023"]], [100.0, 0.0, 50.0])
		self.assertEqual(row["current_invoice_count"], 2)
		self.assertEqual(row["previous_invoice_count"], 4)
		self.assertEqual(row["total_invoice_count"], 7)
		self.assertEqual(row["last_invoice_date"], date(2025, 12, 31))
		self.assertEqual(row["inactive_days"], 295)

	def test_build_customer_row_caps_historical_inactivity_and_handles_zero_baseline(self):
		filters = report.normalize_filters(
			self.valid_filters(analysis_year=2024, previous_years=2), current_year=2026
		)
		new_row = report.build_customer_row(
			"NEW", {}, {2024: {"sales": 10}, 2023: {"sales": 0}, 2022: {"sales": 0}},
			date(2024, 12, 1), filters, date(2026, 10, 22)
		)
		reactivated_row = report.build_customer_row(
			"BACK", {}, {2024: {"sales": 10}, 2023: {"sales": 0}, 2022: {"sales": 20}},
			None, filters, date(2026, 10, 22)
		)

		self.assertEqual(new_row["retention_status"], "New")
		self.assertIsNone(new_row["change_percent"])
		self.assertEqual(new_row["inactive_days"], 30)
		self.assertEqual(reactivated_row["retention_status"], "Reactivated")
		self.assertIsNone(reactivated_row["change_percent"])
		self.assertIsNone(reactivated_row["inactive_days"])

	def test_filter_sort_and_limit_applies_scope_before_deterministic_ranking(self):
		filters = report.normalize_filters(
			self.valid_filters(previous_years=2, minimum_historical_sales=50, top_results="20"),
			current_year=2026,
		)
		rows = [
			{"customer": "B", "retention_status": "Lost", "current_sales": 0,
			 "previous_sales": 100, "sales_2025": 100, "sales_2024": 0,
			 "decrease_amount": 100, "inactive_days": 20, "current_invoice_count": 0},
			{"customer": "A", "retention_status": "Lost", "current_sales": 0,
			 "previous_sales": 100, "sales_2025": 100, "sales_2024": 0,
			 "decrease_amount": 100, "inactive_days": 30, "current_invoice_count": 0},
			{"customer": "OLDER", "retention_status": "Lost", "current_sales": 0,
			 "previous_sales": 0, "sales_2025": 0, "sales_2024": 75,
			 "decrease_amount": 0, "inactive_days": 400, "current_invoice_count": 0},
			{"customer": "ZERO", "retention_status": "", "current_sales": 0,
			 "previous_sales": 0, "sales_2025": 0, "sales_2024": 0,
			 "decrease_amount": 0, "inactive_days": None, "current_invoice_count": 0},
			{"customer": "SMALL", "retention_status": "Decreased", "current_sales": 5,
			 "previous_sales": 10, "sales_2025": 10, "sales_2024": 20,
			 "decrease_amount": 5, "inactive_days": 1, "current_invoice_count": 1},
		]

		ranked = report.filter_sort_and_limit(rows, filters)

		self.assertEqual([row["customer"] for row in ranked], ["A", "B", "OLDER"])
		self.assertEqual([row["rank"] for row in ranked], [1, 2, 3])

	def test_filter_sort_and_limit_filters_status_then_limits_by_decrease(self):
		filters = report.normalize_filters(self.valid_filters(
			previous_years=1, retention_status="Decreased", minimum_historical_sales=0,
			top_results="20", sort_by="Decrease Amount", sort_direction="Descending",
		), current_year=2026)
		rows = []
		for index in range(25):
			rows.append({
				"customer": "CUST-{0:02d}".format(index),
				"retention_status": "Decreased" if index else "Lost",
				"current_sales": 1, "previous_sales": index + 1,
				"sales_2025": index + 1, "decrease_amount": index,
				"inactive_days": index, "current_invoice_count": 1,
			})

		ranked = report.filter_sort_and_limit(rows, filters)

		self.assertEqual(len(ranked), 20)
		self.assertEqual(ranked[0]["customer"], "CUST-24")
		self.assertEqual(ranked[-1]["customer"], "CUST-05")
		self.assertTrue(all(row["retention_status"] == "Decreased" for row in ranked))


if __name__ == "__main__":
	unittest.main()
