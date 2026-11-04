from __future__ import unicode_literals

import json
import os
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe.utils import getdate

from worldshading.worldshading import sales_target_utils
from worldshading.worldshading.report.sales_target_performance import (
	sales_target_performance as report,
)


class TestRecurringOccurrence(unittest.TestCase):
	def occurrence(self, frequency, as_of_date, from_date="2026-01-01",
			to_date="2026-12-31"):
		return sales_target_utils.get_occurrence(
			frequency, as_of_date, from_date, to_date)

	def assert_dates(self, occurrence, from_date, to_date, effective_to_date):
		self.assertEqual(str(occurrence["from_date"]), from_date)
		self.assertEqual(str(occurrence["to_date"]), to_date)
		self.assertEqual(str(occurrence["effective_to_date"]), effective_to_date)

	def test_daily_weekly_monthly_quarterly_and_annual_boundaries(self):
		cases = (
			("Daily", "2026-11-04", "2026-11-04", "2026-11-04"),
			("Weekly", "2026-10-31", "2026-11-06", "2026-11-04"),
			("Monthly", "2026-11-01", "2026-11-30", "2026-11-04"),
			("Quarterly", "2026-10-01", "2026-12-31", "2026-11-04"),
			("Annual", "2026-01-01", "2026-12-31", "2026-11-04")
		)
		for frequency, from_date, to_date, effective_to_date in cases:
			with self.subTest(frequency=frequency):
				result = self.occurrence(frequency, "2026-11-04")
				self.assert_dates(result, from_date, to_date, effective_to_date)
				self.assertFalse(result["not_started"])

	def test_week_is_saturday_through_friday_and_clipped_at_plan_edges(self):
		first = self.occurrence(
			"Weekly", "2026-01-01", "2026-01-01", "2026-01-12")
		last = self.occurrence(
			"Weekly", "2026-01-12", "2026-01-01", "2026-01-12")
		self.assert_dates(first, "2026-01-01", "2026-01-02", "2026-01-01")
		self.assert_dates(last, "2026-01-10", "2026-01-12", "2026-01-12")

	def test_before_plan_uses_first_occurrence_and_marks_not_started(self):
		result = self.occurrence(
			"Monthly", "2025-12-15", "2026-01-10", "2026-12-20")
		self.assert_dates(result, "2026-01-10", "2026-01-31", "2026-01-10")
		self.assertTrue(result["not_started"])

	def test_after_plan_uses_completed_final_occurrence(self):
		result = self.occurrence(
			"Quarterly", "2027-01-10", "2026-01-10", "2026-11-20")
		self.assert_dates(result, "2026-10-01", "2026-11-20", "2026-11-20")
		self.assertFalse(result["not_started"])

	def test_unknown_frequency_is_rejected(self):
		with patch.object(
				sales_target_utils.frappe, "throw",
				side_effect=ValueError("invalid frequency")):
			with self.assertRaises(ValueError):
				self.occurrence("Fortnightly", "2026-11-04")


class TestPerformanceMetrics(unittest.TestCase):
	def metrics(self, target=300, achieved=0, from_date="2026-11-01",
			to_date="2026-11-30", as_of_date="2026-11-01",
			current_date="2026-11-15"):
		return report.calculate_metrics(
			target, achieved, from_date, to_date, as_of_date, current_date)

	def test_before_period_is_not_started_and_ignores_sales(self):
		result = self.metrics(achieved=75, as_of_date="2026-10-31")
		self.assertEqual(result["achieved_amount"], 0)
		self.assertEqual(result["achievement_percent"], 0)
		self.assertEqual(result["expected_amount"], 0)
		self.assertEqual(result["remaining_amount"], 300)
		self.assertEqual(result["status"], "Not Started")

	def test_active_period_calculates_pace_and_run_rate(self):
		result = self.metrics(achieved=5, as_of_date="2026-11-01")
		self.assertAlmostEqual(result["expected_amount"], 10)
		self.assertAlmostEqual(result["progress_variance"], -5)
		self.assertAlmostEqual(result["required_daily_run_rate"], 295.0 / 29.0)
		self.assertEqual(result["status"], "Behind")

	def test_historical_end_is_not_achieved_but_today_end_remains_active(self):
		historical = self.metrics(
			achieved=299, as_of_date="2026-11-30", current_date="2026-12-01")
		today = self.metrics(
			achieved=299, as_of_date="2026-11-30", current_date="2026-11-30")
		self.assertEqual(historical["status"], "Not Achieved")
		self.assertEqual(today["status"], "Behind")
		self.assertEqual(today["required_daily_run_rate"], 0)

	def test_after_end_is_clipped_and_exact_or_above_target_is_achieved(self):
		ended = self.metrics(
			achieved=150, as_of_date="2026-12-15", current_date="2026-12-15")
		exact = self.metrics(achieved=300, as_of_date="2026-11-15")
		above = self.metrics(achieved=350, as_of_date="2026-11-15")
		self.assertEqual(ended["expected_amount"], 300)
		self.assertEqual(ended["status"], "Not Achieved")
		self.assertEqual(exact["status"], "Achieved")
		self.assertEqual(above["over_target_amount"], 50)

	def test_negative_returns_and_zero_target_are_safe(self):
		negative = self.metrics(achieved=-30, as_of_date="2026-11-10")
		zero = self.metrics(target=0, achieved=0)
		self.assertEqual(negative["achievement_percent"], -10)
		self.assertEqual(negative["remaining_amount"], 330)
		self.assertEqual(negative["status"], "Behind")
		self.assertEqual(zero["achievement_percent"], 0)
		self.assertEqual(zero["required_daily_run_rate"], 0)

	def test_columns_cover_recurring_performance_view(self):
		fieldnames = [column["fieldname"] for column in report.get_columns()]
		self.assertEqual(fieldnames, [
			"rank", "sales_employee", "employee_name", "frequency",
			"from_date", "to_date", "target_amount", "achieved_amount",
			"achievement_percent", "expected_amount", "progress_variance",
			"remaining_amount", "over_target_amount",
			"required_daily_run_rate", "contribution_percent", "invoice_count",
			"status"
		])


class TestPerformanceReport(unittest.TestCase):
	def target_row(self, employee, name, monthly, **overrides):
		values = {
			"sales_employee": employee,
			"employee_name": name,
			"daily_target": 0,
			"weekly_target": 0,
			"monthly_target": monthly,
			"quarterly_target": 0,
			"annual_target": 0
		}
		values.update(overrides)
		return SimpleNamespace(**values)

	def target(self, **overrides):
		values = {
			"name": "ST-WS-2026-00001",
			"docstatus": 1,
			"check_permission": Mock(),
			"company": "World Shading",
			"currency": "BHD",
			"target_model": "Recurring Plan",
			"from_date": "2026-01-01",
			"to_date": "2026-12-31",
			"targets": [
				self.target_row("EMP-B", "Bader", 200),
				self.target_row("EMP-A", "Aisha", 100),
				self.target_row("EMP-C", "Charles", 100)
			]
		}
		values.update(overrides)
		return SimpleNamespace(**values)

	def occurrence(self, target=None):
		target = target or self.target()
		return sales_target_utils.get_occurrence(
			"Monthly", "2026-11-15", target.from_date, target.to_date)

	def test_sales_aggregate_is_one_parameterized_employee_scoped_query(self):
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.return_value = [{
				"sales_employee": "EMP-A", "achieved_amount": 125,
				"invoice_count": 3
			}]
			result = report.get_sales_aggregates(
				"World Shading", "2026-11-01", "2026-11-30",
				["EMP-A", "EMP-B"])

		self.assertEqual(frappe_mock.db.sql.call_count, 1)
		query, values = frappe_mock.db.sql.call_args[0][:2]
		query = " ".join(query.lower().split())
		self.assertIn("from `tabsales invoice` si", query)
		self.assertNotIn("sales invoice item", query)
		self.assertIn("si.docstatus = 1", query)
		self.assertIn("si.company = %(company)s", query)
		self.assertIn("si.posting_date between %(from_date)s and %(to_date)s", query)
		self.assertIn("si.pb_sales_employee in %(employee_ids)s", query)
		self.assertIn("group by si.pb_sales_employee", query)
		self.assertIn("sum(si.base_net_total)", query)
		self.assertIn("count(si.name)", query)
		self.assertEqual(values, {
			"company": "World Shading", "from_date": "2026-11-01",
			"to_date": "2026-11-30", "employee_ids": ("EMP-A", "EMP-B")
		})
		self.assertEqual(result, {
			"EMP-A": {"achieved_amount": 125, "invoice_count": 3}
		})

	def test_sales_aggregate_preserves_negative_returns(self):
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.return_value = [{
				"sales_employee": "EMP-A", "achieved_amount": -25,
				"invoice_count": 1
			}]
			result = report.get_sales_aggregates(
				"World Shading", "2026-11-01", "2026-11-30", ["EMP-A"])
		self.assertEqual(result["EMP-A"]["achieved_amount"], -25)

	def test_date_aggregate_is_one_parameterized_employee_scoped_query(self):
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.return_value = [{
				"sales_employee": "EMP-A", "posting_date": getdate("2026-11-04"),
				"achieved_amount": 125, "invoice_count": 3
			}]
			result = report.get_sales_aggregates_by_date(
				"World Shading", "2026-01-01", "2026-11-04",
				["EMP-A", "EMP-B"])

		self.assertEqual(frappe_mock.db.sql.call_count, 1)
		query, values = frappe_mock.db.sql.call_args[0][:2]
		query = " ".join(query.lower().split())
		self.assertIn("si.posting_date", query)
		self.assertIn("group by si.pb_sales_employee, si.posting_date", query)
		self.assertIn("si.company = %(company)s", query)
		self.assertIn("si.pb_sales_employee in %(employee_ids)s", query)
		self.assertEqual(values, {
			"company": "World Shading", "from_date": "2026-01-01",
			"to_date": "2026-11-04", "employee_ids": ("EMP-A", "EMP-B")
		})
		self.assertEqual(result, {
			"EMP-A": {getdate("2026-11-04"): {
				"achieved_amount": 125, "invoice_count": 3
			}}
		})

	def test_rows_select_frequency_rank_team_and_calculate_contribution(self):
		aggregates = {
			"EMP-B": {"achieved_amount": 150, "invoice_count": 4},
			"EMP-A": {"achieved_amount": 60, "invoice_count": 2}
		}
		rows = report.build_rows(
			self.target(), "Monthly", self.occurrence(), aggregates,
			"2026-11-15", "2026-11-15")

		self.assertEqual(
			[(row["sales_employee"], row["rank"]) for row in rows],
			[("EMP-B", 1), ("EMP-A", 2), ("EMP-C", 3)])
		self.assertAlmostEqual(rows[0]["contribution_percent"], 150 / 210.0 * 100)
		self.assertAlmostEqual(rows[1]["contribution_percent"], 60 / 210.0 * 100)
		self.assertEqual(rows[2]["contribution_percent"], 0)
		self.assertEqual(rows[2]["invoice_count"], 0)
		self.assertEqual(rows[2]["frequency"], "Monthly")
		self.assertEqual(rows[2]["from_date"], "2026-11-01")
		self.assertEqual(rows[2]["effective_to_date"], "2026-11-15")

	def test_rows_skip_employees_without_positive_selected_frequency(self):
		target = self.target(targets=[
			self.target_row("EMP-A", "Aisha", 100),
			self.target_row("EMP-B", "Bader", 0, daily_target=20)
		])
		rows = report.build_rows(
			target, "Monthly", self.occurrence(target), {},
			"2026-11-15", "2026-11-15")
		self.assertEqual([row["sales_employee"] for row in rows], ["EMP-A"])

	def test_report_summary_counts_team_and_completed_failures(self):
		rows = [
			{"target_amount": 100, "achieved_amount": 120, "status": "Achieved"},
			{"target_amount": 200, "achieved_amount": 100, "status": "On Track"},
			{"target_amount": 300, "achieved_amount": 50, "status": "Behind"},
			{"target_amount": 400, "achieved_amount": 0, "status": "Not Achieved"}
		]
		values = dict((item["label"], item["value"])
			for item in report.get_report_summary(rows, "BHD"))
		self.assertEqual(values, {
			"Team Target": 1000, "Team Achieved": 270,
			"Team Achievement %": 27, "Achieved": 1,
			"On Track": 1, "Behind": 2
		})

	def test_execute_requires_target_but_frequency_is_optional(self):
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.throw.side_effect = ValueError("required")
			with self.assertRaises(ValueError):
				report.execute({})

		target = self.target(targets=[
			self.target_row("EMP-A", "Aisha", 100, daily_target=10)
		])
		with patch.object(report, "frappe") as frappe_mock, patch.object(
				report, "get_sales_aggregates_by_date", return_value={}), \
				patch.object(report, "nowdate", return_value="2026-11-04"):
			frappe_mock.get_doc.return_value = target
			rows = report.execute({"sales_target": target.name})[1]
		self.assertEqual(
			[(row["frequency"], row["sales_employee"]) for row in rows],
			[("Daily", "EMP-A"), ("Monthly", "EMP-A")])

	def test_blank_frequency_folds_one_date_query_into_every_period(self):
		target = self.target(targets=[
			self.target_row(
				"EMP-A", "Aisha", 300, daily_target=10, weekly_target=70),
			self.target_row(
				"EMP-B", "Bader", 200, daily_target=20)
		])
		date_aggregates = {
			"EMP-A": {
				getdate("2026-11-01"): {"achieved_amount": 15, "invoice_count": 1},
				getdate("2026-11-03"): {"achieved_amount": 10, "invoice_count": 1},
				getdate("2026-11-04"): {"achieved_amount": 5, "invoice_count": 2}
			},
			"EMP-B": {
				getdate("2026-11-04"): {"achieved_amount": 25, "invoice_count": 1}
			}
		}
		with patch.object(report, "frappe") as frappe_mock, patch.object(
				report, "get_sales_aggregates_by_date",
				return_value=date_aggregates) as aggregate, patch.object(
				report, "nowdate", return_value="2026-11-04"):
			frappe_mock.get_doc.return_value = target
			unused_columns, rows, unused_message, unused_chart, summary = \
				report.execute({"sales_target": target.name})[:5]

		self.assertEqual(aggregate.call_count, 1)
		aggregate.assert_called_once_with(
			"World Shading", getdate("2026-10-31"), getdate("2026-11-04"),
			("EMP-A", "EMP-B"))
		values = dict(((row["frequency"], row["sales_employee"]), (
			row["achieved_amount"], row["invoice_count"])) for row in rows)
		self.assertEqual(values, {
			("Daily", "EMP-A"): (5, 2),
			("Daily", "EMP-B"): (25, 1),
			("Weekly", "EMP-A"): (30, 4),
			("Monthly", "EMP-A"): (30, 4),
			("Monthly", "EMP-B"): (25, 1)
		})
		self.assertEqual([item["label"] for item in summary], [
			"Daily Achievement %", "Weekly Achievement %",
			"Monthly Achievement %"
		])
		self.assertTrue(all(item["datatype"] == "Percent" for item in summary))
		self.assertNotIn("Team Target", [item["label"] for item in summary])

	def test_blank_frequency_employee_filter_keeps_all_its_frequencies(self):
		target = self.target(targets=[
			self.target_row(
				"EMP-A", "Aisha", 100, daily_target=10, weekly_target=50),
			self.target_row(
				"EMP-B", "Bader", 200, daily_target=20)
		])
		date_aggregates = {
			"EMP-A": {getdate("2026-11-04"): {
				"achieved_amount": 10, "invoice_count": 1}},
			"EMP-B": {getdate("2026-11-04"): {
				"achieved_amount": 40, "invoice_count": 1}}
		}
		with patch.object(report, "frappe") as frappe_mock, patch.object(
				report, "get_sales_aggregates_by_date",
				return_value=date_aggregates), patch.object(
				report, "nowdate", return_value="2026-11-04"):
			frappe_mock.get_doc.return_value = target
			unused_columns, rows, unused_message, unused_chart, summary = \
				report.execute({
					"sales_target": target.name, "sales_employee": "EMP-A"
				})[:5]

		self.assertEqual(
			[row["frequency"] for row in rows],
			["Daily", "Weekly", "Monthly"])
		self.assertEqual(set(row["sales_employee"] for row in rows), {"EMP-A"})
		summary_values = dict((item["label"], item["value"]) for item in summary)
		self.assertEqual(summary_values, {
			"Daily Achievement %": 100,
			"Weekly Achievement %": 20,
			"Monthly Achievement %": 10
		})
		self.assertEqual(
			next(item["indicator"] for item in summary
				if item["label"] == "Daily Achievement %"), "green")
		self.assertEqual(
			next(item["indicator"] for item in summary
				if item["label"] == "Weekly Achievement %"), "red")

	def test_execute_rejects_unsubmitted_and_legacy_before_invoice_query(self):
		for docstatus in (0, 2):
			with self.subTest(docstatus=docstatus), patch.object(
					report, "frappe") as frappe_mock:
				frappe_mock.get_doc.return_value = self.target(docstatus=docstatus)
				frappe_mock.throw.side_effect = ValueError("unsubmitted")
				with self.assertRaises(ValueError):
					report.execute({
						"sales_target": "ST-WS-2026-00001", "frequency": "Monthly"})

		legacy = self.target(target_model=None)
		with patch.object(report, "frappe") as frappe_mock, patch.object(
				report, "get_sales_aggregates") as aggregate:
			frappe_mock.get_doc.return_value = legacy
			frappe_mock.throw.side_effect = ValueError("recurring required")
			with self.assertRaises(ValueError):
				report.execute({
					"sales_target": legacy.name, "frequency": "Monthly"})
		aggregate.assert_not_called()

	def test_execute_checks_permission_before_invoice_query(self):
		target = self.target()
		target.check_permission = Mock(side_effect=ValueError("not permitted"))
		with patch.object(report, "frappe") as frappe_mock, patch.object(
				report, "get_sales_aggregates") as aggregate:
			frappe_mock.get_doc.return_value = target
			with self.assertRaises(ValueError):
				report.execute({
					"sales_target": target.name, "frequency": "Monthly"})
		target.check_permission.assert_called_once_with("read")
		aggregate.assert_not_called()

	def test_execute_returns_six_items_and_filters_after_team_summary(self):
		target = self.target()
		aggregates = {
			"EMP-B": {"achieved_amount": 150, "invoice_count": 4},
			"EMP-A": {"achieved_amount": 60, "invoice_count": 2}
		}
		with patch.object(report, "frappe") as frappe_mock, patch.object(
				report, "get_sales_aggregates", return_value=aggregates) as aggregate, \
				patch.object(report, "nowdate", return_value="2026-11-15"):
			frappe_mock.get_doc.return_value = target
			result = report.execute({
				"sales_target": target.name, "frequency": "Monthly",
				"sales_employee": "EMP-A", "as_of_date": "2026-11-15"
			})

		self.assertEqual(len(result), 6)
		columns, rows, message, chart, summary, skip_total_row = result
		self.assertTrue(columns)
		self.assertEqual([(row["sales_employee"], row["rank"]) for row in rows],
			[("EMP-A", 2)])
		self.assertIsNone(message)
		self.assertIsNone(chart)
		self.assertEqual(skip_total_row, 1)
		self.assertEqual(next(item["value"] for item in summary
			if item["label"] == "Team Target"), 400)
		aggregate.assert_called_once_with(
			"World Shading", getdate("2026-11-01"), getdate("2026-11-15"),
			("EMP-B", "EMP-A", "EMP-C"))

	def test_execute_skips_invoice_query_before_plan(self):
		target = self.target()
		with patch.object(report, "frappe") as frappe_mock, patch.object(
				report, "get_sales_aggregates") as aggregate, patch.object(
				report, "nowdate", return_value="2026-11-15"):
			frappe_mock.get_doc.return_value = target
			unused_columns, rows = report.execute({
				"sales_target": target.name, "frequency": "Monthly",
				"as_of_date": "2025-12-15"
			})[:2]
		aggregate.assert_not_called()
		self.assertEqual(set(row["status"] for row in rows), {"Not Started"})

	def test_execute_rejects_future_as_of_date_before_invoice_query(self):
		target = self.target()
		with patch.object(report, "frappe") as frappe_mock, patch.object(
				report, "get_sales_aggregates") as aggregate, patch.object(
				report, "nowdate", return_value="2026-11-04"):
			frappe_mock.get_doc.return_value = target
			frappe_mock.throw.side_effect = ValueError("future")
			with self.assertRaises(ValueError):
				report.execute({
					"sales_target": target.name, "frequency": "Monthly",
					"as_of_date": "2026-11-05"})
		aggregate.assert_not_called()


class TestPerformanceReportMetadata(unittest.TestCase):
	def test_report_metadata_registers_management_only_script_report(self):
		path = os.path.join(
			os.path.dirname(__file__), "sales_target_performance.json")
		with open(path) as source:
			metadata = json.load(source)

		self.assertEqual(metadata["name"], "Sales Target Performance")
		self.assertEqual(metadata["report_name"], "Sales Target Performance")
		self.assertEqual(metadata["report_type"], "Script Report")
		self.assertEqual(metadata["is_standard"], "Yes")
		self.assertEqual(metadata["module"], "Worldshading")
		self.assertEqual(metadata["ref_doctype"], "Sales Target")
		self.assertEqual(metadata["prepared_report"], 0)
		self.assertEqual(metadata["disable_prepared_report"], 1)
		self.assertEqual(
			set(row["role"] for row in metadata["roles"]),
			{"System Manager", "General Manager", "Sales Manager", "Accounts Manager"})

	def test_report_client_configures_filters_statuses_and_safe_drilldown(self):
		script = os.path.join(
			os.path.dirname(__file__), "test_sales_target_performance_client.js")
		result = subprocess.run(
			["node", script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
			universal_newlines=True)
		self.assertEqual(result.returncode, 0, result.stdout)
		self.assertIn(
			"sales_target_performance recurring client behavior: ok", result.stdout)


if __name__ == "__main__":
	unittest.main()
