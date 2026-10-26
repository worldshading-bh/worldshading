from __future__ import unicode_literals

import json
import os
import unittest
from datetime import date
from unittest.mock import Mock, patch

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
		self.assertEqual(filters.comparison_year, 2025)
		self.assertEqual(filters.previous_years, 1)
		self.assertEqual(filters.item_group, "")
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
			{"comparison_year": 2026},
			{"comparison_year": 2027},
			{"comparison_year": 2020},
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
			self.valid_filters(previous_years=3, comparison_year=2021), current_year=2026
		)

		self.assertEqual(report.get_years(filters), [2026, 2025, 2024, 2023])
		self.assertEqual(
			report.get_reporting_years(filters),
			[2026, 2025, 2024, 2023, 2021],
		)
		self.assertEqual(
			report.get_period_bounds(filters),
			(date(2021, 1, 1), date(2026, 12, 31)),
		)

	def test_columns_use_year_labels_and_newest_first_dynamic_history(self):
		filters = report.normalize_filters(
			self.valid_filters(previous_years=3, comparison_year=2024), current_year=2026
		)
		columns = report.get_columns(filters, "BHD")
		fieldnames = [column["fieldname"] for column in columns]

		self.assertEqual(fieldnames[0:6], [
			"customer", "customer_name", "customer_group", "territory",
			"retention_status", "importance_score",
		])
		self.assertNotIn("rank", fieldnames)
		self.assertEqual(
			[fieldname for fieldname in fieldnames if fieldname.startswith("sales_")],
			["sales_2025", "sales_2024", "sales_2023"],
		)
		labels = dict((column["fieldname"], column["label"]) for column in columns)
		self.assertEqual(labels["current_sales"], "2026 Sales")
		self.assertEqual(labels["previous_sales"], "2024 Comparison Sales")
		self.assertEqual(labels["previous_invoice_count"], "2024 Comparison Invoice Count")
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
				self.assertEqual(
					report.classify_customer(values, 2026, 2025, [2025, 2024]),
					expected,
				)

	def test_classification_uses_comparison_year_and_other_relevant_history(self):
		cases = [
			("reactivated", {2026: 25, 2025: 50, 2021: 0}, "Reactivated"),
			("new", {2026: 25, 2025: 0, 2021: 0}, "New"),
			("lost from comparison", {2026: 0, 2025: 0, 2021: 100}, "Lost"),
			("decreased", {2026: 80, 2025: 200, 2021: 100}, "Decreased"),
		]
		for label, values, expected in cases:
			with self.subTest(label=label):
				self.assertEqual(
					report.classify_customer(values, 2026, 2021, [2025, 2021]),
					expected,
				)

	def test_build_customer_row_uses_independent_comparison_year(self):
		filters = report.normalize_filters(self.valid_filters(
			previous_years=3, comparison_year=2021,
		), current_year=2026)
		year_values = {
			2026: {"sales": 80, "invoice_count": 2},
			2025: {"sales": 60, "invoice_count": 3},
			2024: {"sales": 30, "invoice_count": 2},
			2023: {"sales": 0, "invoice_count": 0},
			2021: {"sales": 100, "invoice_count": 5},
		}

		row = report.build_customer_row(
			"CUST-001", {}, year_values, date(2026, 1, 1), filters, date(2026, 10, 26)
		)

		self.assertEqual(row["retention_status"], "Decreased")
		self.assertEqual(row["previous_sales"], 100.0)
		self.assertEqual(row["previous_invoice_count"], 5)
		self.assertEqual(row["change_amount"], -20.0)
		self.assertEqual(row["decrease_amount"], 20.0)
		self.assertEqual(row["change_percent"], -20.0)
		self.assertEqual(row["average_historical_sales"], 30.0)
		self.assertEqual(row["total_invoice_count"], 7)
		self.assertEqual(
			[row["sales_2025"], row["sales_2024"], row["sales_2023"]],
			[60.0, 30.0, 0.0],
		)

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
		self.assertTrue(all("rank" not in row for row in ranked))

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

	def test_importance_ranks_filtered_customers_by_value_loss_and_inactivity(self):
		filters = report.normalize_filters(self.valid_filters(
			previous_years=2, top_results="All", sort_by="Importance",
			sort_direction="Descending",
		), current_year=2026)
		rows = [
			{"customer": "VALUE", "retention_status": "Decreased", "current_sales": 150,
			 "previous_sales": 200, "sales_2025": 200, "sales_2024": 200,
			 "average_historical_sales": 200, "decrease_amount": 50,
			 "inactive_days": 100, "current_invoice_count": 2},
			{"customer": "PRIORITY", "retention_status": "Lost", "current_sales": 0,
			 "previous_sales": 100, "sales_2025": 100, "sales_2024": 100,
			 "average_historical_sales": 100, "decrease_amount": 100,
			 "inactive_days": 300, "current_invoice_count": 0},
			{"customer": "LOW", "retention_status": "Stable", "current_sales": 50,
			 "previous_sales": 50, "sales_2025": 50, "sales_2024": 50,
			 "average_historical_sales": 50, "decrease_amount": 0,
			 "inactive_days": None, "current_invoice_count": 1},
		]

		ranked = report.filter_sort_and_limit(rows, filters)

		self.assertEqual([row["customer"] for row in ranked], [
			"PRIORITY", "VALUE", "LOW",
		])
		self.assertAlmostEqual(ranked[0]["importance_score"], 85.0, places=5)
		self.assertAlmostEqual(ranked[1]["importance_score"], 72.5, places=5)
		self.assertAlmostEqual(ranked[2]["importance_score"], 15.0, places=5)

	def test_positive_percentile_ranks_handle_zero_ties_singletons_and_empty_rows(self):
		rows = [
			{"value": 0}, {"value": 10}, {"value": 10}, {"value": 20},
		]

		ranks = report.get_positive_percentile_ranks(rows, "value")

		self.assertEqual(ranks[0], 0.0)
		self.assertAlmostEqual(ranks[1], 66.666667, places=5)
		self.assertAlmostEqual(ranks[2], 66.666667, places=5)
		self.assertEqual(ranks[3], 100.0)
		self.assertEqual(
			report.get_positive_percentile_ranks([{"value": 5}], "value"),
			[100.0],
		)
		self.assertEqual(report.get_positive_percentile_ranks([], "value"), [])

	def test_importance_scores_use_filtered_population_before_top_results(self):
		rows = []
		for index in range(25):
			value = index + 1
			rows.append({
				"customer": "CUST-{0:02d}".format(index),
				"retention_status": "Lost", "current_sales": 0,
				"previous_sales": value, "sales_2025": value,
				"average_historical_sales": value, "decrease_amount": value,
				"inactive_days": value, "current_invoice_count": 0,
			})
		all_filters = report.normalize_filters(self.valid_filters(
			top_results="All", sort_by="Importance",
		), current_year=2026)
		top_filters = report.normalize_filters(self.valid_filters(
			top_results="20", sort_by="Importance",
		), current_year=2026)

		all_rows = report.filter_sort_and_limit([dict(row) for row in rows], all_filters)
		top_rows = report.filter_sort_and_limit([dict(row) for row in rows], top_filters)

		self.assertEqual(len(top_rows), 20)
		self.assertEqual(
			[(row["customer"], row["importance_score"]) for row in top_rows],
			[(row["customer"], row["importance_score"]) for row in all_rows[:20]],
		)

	def test_sales_query_uses_bound_scope_and_return_safe_activity_count(self):
		filters = report.normalize_filters(self.valid_filters(
			previous_years=3, customer="CUST-'quoted", customer_group="Retail",
			territory="Bahrain",
		), current_year=2026)
		captured = {}

		def fake_sql(query, values=None, as_dict=False):
			captured.update({"query": query, "values": values, "as_dict": as_dict})
			return []

		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.side_effect = fake_sql
			report.get_sales_activity(filters)

		query = " ".join(captured["query"].lower().split())
		self.assertEqual(captured["values"]["company"], "World Shading")
		self.assertEqual(captured["values"]["start_date"], date(2023, 1, 1))
		self.assertEqual(captured["values"]["end_date"], date(2026, 12, 31))
		self.assertEqual(captured["values"]["customer"], "CUST-'quoted")
		self.assertEqual(captured["values"]["customer_group"], "Retail")
		self.assertEqual(captured["values"]["territory"], "Bahrain")
		self.assertIn("si.docstatus = 1", query)
		self.assertIn("year(si.posting_date)", query)
		self.assertIn("sum(si.base_net_total)", query)
		self.assertIn("case when ifnull(si.is_return, 0) = 0 then si.name", query)
		self.assertIn("group by si.customer, year(si.posting_date)", query)
		self.assertNotIn("disabled", query)
		self.assertNotIn("cust-'quoted", query)
		self.assertTrue(captured["as_dict"])

	def test_last_invoice_query_uses_full_history_and_skips_empty_customers(self):
		filters = report.normalize_filters(
			self.valid_filters(previous_years=2), current_year=2026
		)
		calls = []

		def fake_sql(query, values=None, as_dict=False):
			calls.append((query, values, as_dict))
			return []

		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.side_effect = fake_sql
			self.assertEqual(report.get_last_invoice_dates(filters, []), {})
			result = report.get_last_invoice_dates(filters, ["CUST-1", "CUST-2"])

		self.assertEqual(result, {})
		self.assertEqual(len(calls), 1)
		query = " ".join(calls[0][0].lower().split())
		values = calls[0][1]
		self.assertIn("si.customer in %(customers)s", query)
		self.assertIn("si.docstatus = 1", query)
		self.assertIn("ifnull(si.is_return, 0) = 0", query)
		self.assertIn("si.posting_date <= %(end_date)s", query)
		self.assertNotIn("start_date", query)
		self.assertEqual(values["company"], "World Shading")
		self.assertEqual(values["customers"], ("CUST-1", "CUST-2"))
		self.assertEqual(values["end_date"], date(2026, 12, 31))

	def test_company_context_checks_read_permission_and_returns_currency(self):
		company = type("Company", (object,), {
			"default_currency": "BHD",
			"check_permission": Mock(),
		})()
		with patch.object(report.frappe, "get_doc", return_value=company) as get_doc:
			currency = report.get_company_context("World Shading")

		self.assertEqual(currency, "BHD")
		get_doc.assert_called_once_with("Company", "World Shading")
		company.check_permission.assert_called_once_with("read")

	def test_execute_builds_limits_then_enriches_and_returns_v12_contract(self):
		sales_rows = [
			{"customer": "CUST-1", "customer_name": "Alpha", "customer_group": "Retail",
			 "territory": "Bahrain", "sales_year": 2026, "sales": 80, "invoice_count": 2},
			{"customer": "CUST-1", "customer_name": "Alpha", "customer_group": "Retail",
			 "territory": "Bahrain", "sales_year": 2025, "sales": 100, "invoice_count": 4},
		]
		captured = {}

		def enrich(displayed, filters):
			captured["customers"] = [row["customer"] for row in displayed]
			displayed[0]["top_item_group_1"] = "Outdoor"
			return displayed

		with patch.object(report, "get_company_context", return_value="BHD"), \
				patch.object(report, "get_sales_activity", return_value=sales_rows), \
				patch.object(report, "get_last_invoice_dates", return_value={"CUST-1": date(2026, 1, 1)}), \
				patch.object(report, "today", return_value="2026-10-22"), \
				patch.object(report, "enrich_rows", side_effect=enrich):
			result = report.execute(self.valid_filters())

		columns, rows, message, chart, summary, skip_total_row = result
		self.assertEqual(captured["customers"], ["CUST-1"])
		self.assertNotIn("rank", rows[0])
		self.assertEqual(rows[0]["top_item_group_1"], "Outdoor")
		self.assertEqual(rows[0]["report_currency"], "BHD")
		self.assertEqual(rows[0]["retention_status"], "Decreased")
		self.assertTrue(any(column["options"] == "BHD" for column in columns if column["fieldtype"] == "Currency"))
		self.assertIsNone(message)
		self.assertEqual(chart["data"]["labels"], ["Alpha"])
		self.assertTrue(any(item["label"] == "At-risk Comparison Sales" for item in summary))
		self.assertEqual(skip_total_row, 1)

	def test_execute_returns_no_notice_for_completed_analysis_year(self):
		sales_rows = [
			{"customer": "CUST-1", "customer_name": "Alpha", "customer_group": "Retail",
			 "territory": "Bahrain", "sales_year": 2025, "sales": 80, "invoice_count": 2},
			{"customer": "CUST-1", "customer_name": "Alpha", "customer_group": "Retail",
			 "territory": "Bahrain", "sales_year": 2024, "sales": 100, "invoice_count": 4},
		]
		with patch.object(report, "get_company_context", return_value="BHD"), \
				patch.object(report, "get_sales_activity", return_value=sales_rows), \
				patch.object(report, "get_last_invoice_dates", return_value={"CUST-1": date(2025, 1, 1)}), \
				patch.object(report, "today", return_value="2026-10-24"), \
				patch.object(report, "enrich_rows", side_effect=lambda rows, filters: rows):
			result = report.execute(self.valid_filters(analysis_year=2025))

		self.assertIsNone(result[2])

	def test_execute_preserves_return_only_value_without_purchase_activity(self):
		sales_rows = [{
			"customer": "RETURN-ONLY", "customer_name": "Returns", "customer_group": "Retail",
			"territory": "Bahrain", "sales_year": 2026, "sales": -50, "invoice_count": 0,
		}]
		with patch.object(report, "get_company_context", return_value="BHD"), \
				patch.object(report, "get_sales_activity", return_value=sales_rows), \
				patch.object(report, "get_last_invoice_dates", return_value={}), \
				patch.object(report, "today", return_value="2026-10-22"), \
				patch.object(report, "enrich_rows", side_effect=lambda rows, filters: rows):
			unused_columns, rows, unused_message, unused_chart, unused_summary, unused_skip = report.execute(
				self.valid_filters()
			)

		self.assertEqual(rows[0]["current_sales"], -50.0)
		self.assertEqual(rows[0]["current_invoice_count"], 0)
		self.assertEqual(rows[0]["total_invoice_count"], 0)
		self.assertIsNone(rows[0]["last_invoice_date"])
		self.assertIsNone(rows[0]["inactive_days"])

	def test_execute_returns_empty_contract_without_enrichment(self):
		with patch.object(report, "get_company_context", return_value="BHD"), \
				patch.object(report, "get_sales_activity", return_value=[]), \
				patch.object(report, "get_last_invoice_dates") as last_dates, \
				patch.object(report, "today", return_value="2026-10-22"), \
				patch.object(report, "enrich_rows") as enrich:
			columns, rows, message, chart, summary, skip_total_row = report.execute(
				self.valid_filters()
			)

		self.assertTrue(columns)
		self.assertEqual(rows, [])
		self.assertIn("No customers", message)
		self.assertIsNone(chart)
		self.assertTrue(all(item["value"] == 0 for item in summary))
		self.assertEqual(skip_total_row, 1)
		last_dates.assert_not_called()
		enrich.assert_not_called()

	def test_item_group_context_uses_limited_customers_and_positive_top_three(self):
		filters = report.normalize_filters(
			self.valid_filters(previous_years=2), current_year=2026
		)
		query_rows = [
			{"customer": "CUST-1", "item_group": "Blinds", "net_amount": 100},
			{"customer": "CUST-1", "item_group": "Awnings", "net_amount": 100},
			{"customer": "CUST-1", "item_group": "Outdoor", "net_amount": 80},
			{"customer": "CUST-1", "item_group": "Fabric", "net_amount": 70},
			{"customer": "CUST-1", "item_group": "Returns", "net_amount": -5},
			{"customer": "CUST-1", "item_group": "", "net_amount": 20},
			{"customer": "CUST-2", "item_group": "Outdoor", "net_amount": 0},
		]
		captured = {}

		def fake_sql(query, values=None, as_dict=False):
			captured.update({"query": query, "values": values, "as_dict": as_dict})
			return query_rows

		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.side_effect = fake_sql
			self.assertEqual(report.get_item_group_context(filters, []), {})
			context = report.get_item_group_context(filters, ["CUST-1", "CUST-2"])

		query = " ".join(captured["query"].lower().split())
		self.assertIn("`tabsales invoice item`", query)
		self.assertIn("inner join `tabsales invoice`", query)
		self.assertIn("inner join `tabitem`", query)
		self.assertIn("si.docstatus = 1", query)
		self.assertIn("sum(sii.base_net_amount)", query)
		self.assertIn("group by si.customer, item.item_group", query)
		self.assertEqual(captured["values"]["company"], "World Shading")
		self.assertEqual(captured["values"]["start_date"], date(2024, 1, 1))
		self.assertEqual(captured["values"]["end_date"], date(2026, 12, 31))
		self.assertEqual(captured["values"]["customers"], ("CUST-1", "CUST-2"))
		self.assertEqual(context, {"CUST-1": [
			{"item_group": "Awnings", "net_amount": 100.0},
			{"item_group": "Blinds", "net_amount": 100.0},
			{"item_group": "Outdoor", "net_amount": 80.0},
		]})

	def test_campaign_context_denies_without_query_when_user_lacks_permission(self):
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.has_permission.return_value = False
			context = report.get_campaign_context(["CUST-1"])

		self.assertEqual(context, {})
		frappe_mock.has_permission.assert_called_once_with("Campaign Customer", "read")
		frappe_mock.db.sql.assert_not_called()

	def test_campaign_context_keeps_latest_ordered_record_per_customer(self):
		query_rows = [
			{"customer": "CUST-1", "campaign_customer": "CC-NEW", "campaign": "Winter",
			 "outreach_status": "Interested", "priority": "Top 20",
			 "planned_contact_date": date(2026, 10, 25), "next_follow_up": "2026-10-26 10:00:00",
			 "number_of_interactions": 3},
			{"customer": "CUST-1", "campaign_customer": "CC-OLD", "campaign": "Summer",
			 "outreach_status": "Closed", "priority": "Standard",
			 "planned_contact_date": date(2026, 6, 1), "next_follow_up": None,
			 "number_of_interactions": 1},
			{"customer": "CUST-2", "campaign_customer": "CC-2", "campaign": "Winter",
			 "outreach_status": "Planned", "priority": "Standard",
			 "planned_contact_date": date(2026, 10, 27), "next_follow_up": None,
			 "number_of_interactions": 0},
		]
		captured = {}

		def fake_sql(query, values=None, as_dict=False):
			captured.update({"query": query, "values": values, "as_dict": as_dict})
			return query_rows

		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.has_permission.return_value = True
			frappe_mock.db.sql.side_effect = fake_sql
			context = report.get_campaign_context(["CUST-1", "CUST-2"])

		query = " ".join(captured["query"].lower().split())
		self.assertIn("customer in %(customers)s", query)
		self.assertIn("order by customer, modified desc, name desc", query)
		self.assertEqual(captured["values"]["customers"], ("CUST-1", "CUST-2"))
		self.assertEqual(context["CUST-1"]["campaign_customer"], "CC-NEW")
		self.assertEqual(context["CUST-1"]["outreach_status"], "Interested")
		self.assertEqual(context["CUST-1"]["number_of_interactions"], 3)
		self.assertEqual(context["CUST-2"]["campaign_customer"], "CC-2")

	def test_apply_and_enrich_context_keep_blanks_and_existing_order(self):
		rows = [
			{"customer": "CUST-2"},
			{"customer": "CUST-1"},
		]
		campaign = {"CUST-2": {
			"campaign_customer": "CC-2", "campaign": "Winter", "outreach_status": "Planned",
			"priority": "Standard", "planned_contact_date": date(2026, 10, 27),
			"next_follow_up": None, "number_of_interactions": 0,
		}}
		applied = report.apply_customer_context(rows, {"CUST-2": [
			{"item_group": "Outdoor", "net_amount": 4250.75},
		]}, campaign)

		self.assertEqual([row["customer"] for row in applied], ["CUST-2", "CUST-1"])
		self.assertEqual(applied[0]["top_item_group_1"], "Outdoor")
		self.assertEqual(applied[0]["top_item_group_1_sales"], 4250.75)
		self.assertEqual(applied[0]["campaign_customer"], "CC-2")
		self.assertIsNone(applied[0]["top_item_group_2"])
		self.assertIsNone(applied[0]["top_item_group_2_sales"])
		self.assertIsNone(applied[1]["top_item_group_1"])
		self.assertIsNone(applied[1]["top_item_group_1_sales"])
		self.assertIsNone(applied[1]["campaign_customer"])
		self.assertIsNone(applied[1]["number_of_interactions"])

		with patch.object(report, "get_item_group_context", return_value={}) as item_groups, \
				patch.object(report, "get_campaign_context", return_value={}) as campaigns:
			enriched = report.enrich_rows(rows, self.valid_filters(previous_years=3))
		item_groups.assert_called_once_with(
			self.valid_filters(previous_years=3), ["CUST-2", "CUST-1"]
		)
		campaigns.assert_called_once_with(["CUST-2", "CUST-1"])
		self.assertEqual(enriched[0]["item_group_sales_period"], "2023\u20132026")

	def test_javascript_defines_filters_visual_contract_and_safe_read_only_behavior(self):
		path = os.path.join(os.path.dirname(__file__), "customer_retention_analysis.js")
		with open(path) as source:
			script = source.read()

		self.assertIn('frappe.query_reports["Customer Retention Analysis"]', script)
		for fieldname in (
			"company", "analysis_year", "previous_years", "customer", "customer_group",
			"territory", "retention_status", "minimum_historical_sales", "top_results",
			"sort_by", "sort_direction",
		):
			self.assertIn('fieldname: "{0}"'.format(fieldname), script)
		self.assertIn('options: "1\\n2\\n3\\n4\\n5"', script)
		self.assertIn('options: "20\\n50\\n100\\n250\\nAll"', script)
		self.assertIn('options: "\\nLost\\nDecreased\\nStable\\nIncreased\\nNew\\nReactivated"', script)
		self.assertIn('options: "Importance\\nDecrease Amount\\nCurrent Sales\\nPrevious Sales\\nInactive Days\\nCurrent Invoice Count"', script)
		self.assertIn('options: "Descending\\nAscending"', script)
		self.assertIn('"default": 1', script)
		self.assertIn('"default": "100"', script)
		self.assertIn('"default": "Importance"', script)
		self.assertIn('"default": "Descending"', script)
		self.assertIn("formatter:", script)
		self.assertIn("frappe.utils.escape_html", script)
		for color in ("red", "orange", "gray", "green", "blue", "purple"):
			self.assertIn('"{0}"'.format(color), script)
		self.assertIn('fieldname === "change_amount"', script)
		self.assertIn('fieldname === "change_percent"', script)
		self.assertIn("prepared_report_name", script)
		self.assertIn("customer_retention_analysis.get_prepared_report_filters", script)
		self.assertNotIn("update_partial_year_notice", script)
		self.assertNotIn("cra-partial-year-notice", script)
		self.assertNotIn("sales are not annualized", script)
		self.assertIn("cra-filter-summary", script)
		self.assertIn("cra-table", script)
		self.assertNotIn('text === __("Rank")', script)
		self.assertNotIn("--cra-rank-width", script)
		self.assertIn('text === __("Customer")', script)
		self.assertIn('text === __("Customer Name")', script)
		self.assertNotIn("annualized_value", script)
		self.assertNotIn("localStorage", script)
		self.assertNotIn("frappe.new_doc", script)
		self.assertNotIn("frappe.db.insert", script)
		self.assertNotIn("bulk_actions", script)

	def test_prepared_filter_reader_requires_name(self):
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.throw.side_effect = ValueError("Prepared Report is required")
			with self.assertRaises(ValueError):
				report.get_prepared_report_filters()

	def test_prepared_filter_reader_accepts_owner_and_system_manager(self):
		prepared = type("Prepared", (object,), {
			"report_name": "Customer Retention Analysis",
			"status": "Completed", "owner": "owner@example.com",
		})()
		for user, roles in (("owner@example.com", []), ("manager@example.com", ["System Manager"])):
			with self.subTest(user=user):
				with patch.object(report, "frappe") as frappe_mock:
					frappe_mock.session.user = user
					frappe_mock.get_roles.return_value = roles
					frappe_mock.db.get_value.side_effect = [prepared, '{"company":"World Shading"}']
					frappe_mock.parse_json.side_effect = json.loads
					self.assertEqual(
						report.get_prepared_report_filters("PREP-1"),
						{"company": "World Shading"},
					)

	def test_prepared_filter_reader_rejects_wrong_incomplete_or_unauthorized_report(self):
		cases = [
			type("Prepared", (object,), {"report_name": "Other", "status": "Completed", "owner": "user@example.com"})(),
			type("Prepared", (object,), {"report_name": "Customer Retention Analysis", "status": "Queued", "owner": "user@example.com"})(),
			type("Prepared", (object,), {"report_name": "Customer Retention Analysis", "status": "Completed", "owner": "other@example.com"})(),
		]
		for prepared in cases:
			with self.subTest(report_name=prepared.report_name, status=prepared.status, owner=prepared.owner):
				with patch.object(report, "frappe") as frappe_mock:
					frappe_mock.session.user = "user@example.com"
					frappe_mock.get_roles.return_value = []
					frappe_mock.db.get_value.return_value = prepared
					frappe_mock.throw.side_effect = ValueError("Rejected")
					with self.assertRaises(ValueError):
						report.get_prepared_report_filters("PREP-1")

	def test_prepared_filter_reader_returns_only_json_object(self):
		prepared = type("Prepared", (object,), {
			"report_name": "Customer Retention Analysis",
			"status": "Completed", "owner": "user@example.com",
		})()
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.session.user = "user@example.com"
			frappe_mock.db.get_value.side_effect = [prepared, '["not", "an", "object"]']
			frappe_mock.parse_json.side_effect = json.loads
			self.assertEqual(report.get_prepared_report_filters("PREP-1"), {})

	def test_chart_orders_largest_decreases_independently_of_report_sort(self):
		rows = [
			{"customer": "C", "customer_name": "Third", "decrease_amount": 10},
			{"customer": "A", "customer_name": "First", "decrease_amount": 80},
			{"customer": "B", "customer_name": "Second", "decrease_amount": 40},
		]

		chart = report.get_chart(rows)

		self.assertEqual(chart["data"]["labels"], ["First", "Second", "Third"])
		self.assertEqual(chart["data"]["datasets"][0]["values"], [80.0, 40.0, 10.0])

	def test_next_follow_up_column_preserves_campaign_time(self):
		filters = report.normalize_filters(self.valid_filters(), current_year=2026)
		columns = dict(
			(column["fieldname"], column) for column in report.get_columns(filters, "BHD")
		)

		self.assertEqual(columns["next_follow_up"]["fieldtype"], "Datetime")

	def test_client_rebuilds_chart_and_result_summary_from_prepared_rows(self):
		path = os.path.join(os.path.dirname(__file__), "customer_retention_analysis.js")
		with open(path) as source:
			script = source.read()

		self.assertIn("get_chart_data:", script)
		self.assertIn("build_decline_chart", script)
		self.assertIn("update_result_summary", script)
		self.assertIn("cra-result-summary", script)
		self.assertIn("At-risk Previous Sales", script)

	def test_client_uses_purchase_plan_sticky_and_highlight_safeguards(self):
		path = os.path.join(os.path.dirname(__file__), "customer_retention_analysis.js")
		with open(path) as source:
			script = source.read()

		self.assertIn("--cra-row-index-width", script)
		self.assertIn(".dt-cell--col-0", script)
		self.assertIn("cra-selected-row", script)
		self.assertIn("MutationObserver", script)
		self.assertIn("requestAnimationFrame(restore_selected_row)", script)
		self.assertIn(".dt-scrollable__no-data", script)
		self.assertIn("datatable.bodyRenderer.renderFooter()", script)
		self.assertIn("cra_last_scroll_left", script)
		self.assertIn("scroll.cra_sticky_columns", script)
		self.assertIn("mousedown.cra_sticky_resize", script)
		self.assertIn("dblclick.cra_sticky_resize", script)
		for event_name in ("onSortColumn", "onSwitchColumn", "onRemoveColumn"):
			self.assertIn('"{0}"'.format(event_name), script)
		self.assertIn('sortable.option("disabled", true)', script)
		self.assertIn("cra-important-columns-style", script)
		for fieldname in (
			"retention_status", "current_sales", "previous_sales", "change_amount",
			"change_percent", "inactive_days",
		):
			self.assertIn('"{0}"'.format(fieldname), script)
		self.assertIn("cursor:pointer", script)
		self.assertIn(":hover .dt-cell", script)


if __name__ == "__main__":
	unittest.main()
