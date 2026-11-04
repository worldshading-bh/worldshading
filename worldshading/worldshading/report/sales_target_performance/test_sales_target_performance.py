from __future__ import unicode_literals

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from worldshading.worldshading.report.sales_target_performance import (
	sales_target_performance as report,
)


class TestPerformanceMetrics(unittest.TestCase):
	def metrics(self, target=300, achieved=0, from_date="2026-11-01",
			to_date="2026-11-30", as_of_date="2026-11-01"):
		return report.calculate_metrics(
			target, achieved, from_date, to_date, as_of_date)

	def test_before_period_is_not_started_and_ignores_sales(self):
		result = self.metrics(achieved=75, as_of_date="2026-10-31")
		self.assertEqual(result["achieved_amount"], 0)
		self.assertEqual(result["achievement_percent"], 0)
		self.assertEqual(result["expected_amount"], 0)
		self.assertEqual(result["progress_variance"], 0)
		self.assertEqual(result["remaining_amount"], 300)
		self.assertEqual(result["required_daily_run_rate"], 0)
		self.assertEqual(result["status"], "Not Started")

	def test_first_day_uses_one_elapsed_day_and_excludes_it_from_run_rate(self):
		result = self.metrics(achieved=5, as_of_date="2026-11-01")
		self.assertAlmostEqual(result["expected_amount"], 10)
		self.assertAlmostEqual(result["progress_variance"], -5)
		self.assertAlmostEqual(result["required_daily_run_rate"], 295.0 / 29.0)
		self.assertEqual(result["status"], "Behind")

	def test_on_end_date_below_target_is_not_achieved_with_zero_run_rate(self):
		result = self.metrics(achieved=299, as_of_date="2026-11-30")
		self.assertEqual(result["expected_amount"], 300)
		self.assertEqual(result["required_daily_run_rate"], 0)
		self.assertEqual(result["status"], "Not Achieved")

	def test_after_end_date_is_clipped_to_end_date(self):
		result = self.metrics(achieved=150, as_of_date="2026-12-15")
		self.assertEqual(result["expected_amount"], 300)
		self.assertEqual(result["remaining_amount"], 150)
		self.assertEqual(result["required_daily_run_rate"], 0)
		self.assertEqual(result["status"], "Not Achieved")

	def test_exact_and_above_target_are_achieved(self):
		exact = self.metrics(achieved=300, as_of_date="2026-11-15")
		above = self.metrics(achieved=350, as_of_date="2026-11-15")
		self.assertEqual(exact["status"], "Achieved")
		self.assertEqual(exact["remaining_amount"], 0)
		self.assertEqual(exact["over_target_amount"], 0)
		self.assertEqual(above["status"], "Achieved")
		self.assertEqual(above["remaining_amount"], 0)
		self.assertEqual(above["over_target_amount"], 50)
		self.assertEqual(above["required_daily_run_rate"], 0)

	def test_negative_returns_remain_negative_and_safe(self):
		result = self.metrics(target=300, achieved=-30, as_of_date="2026-11-10")
		self.assertEqual(result["achieved_amount"], -30)
		self.assertEqual(result["achievement_percent"], -10)
		self.assertEqual(result["expected_amount"], 100)
		self.assertEqual(result["progress_variance"], -130)
		self.assertEqual(result["remaining_amount"], 330)
		self.assertEqual(result["status"], "Behind")

	def test_zero_target_does_not_divide_by_zero(self):
		result = self.metrics(target=0, achieved=0)
		self.assertEqual(result["achievement_percent"], 0)
		self.assertEqual(result["remaining_amount"], 0)
		self.assertEqual(result["required_daily_run_rate"], 0)

	def test_columns_cover_the_approved_performance_view(self):
		fieldnames = [column["fieldname"] for column in report.get_columns()]
		self.assertEqual(fieldnames, [
			"rank", "sales_employee", "employee_name", "period_type",
			"from_date", "to_date", "target_amount", "achieved_amount",
			"achievement_percent", "expected_amount", "progress_variance",
			"remaining_amount", "over_target_amount",
			"required_daily_run_rate", "invoice_count", "status"
		])


class TestPerformanceReport(unittest.TestCase):
	def target_row(self, employee, name, amount):
		return SimpleNamespace(
			sales_employee=employee,
			employee_name=name,
			target_amount=amount
		)

	def target(self, **overrides):
		values = {
			"name": "ST-WS-2026-00001",
			"docstatus": 1,
			"company": "World Shading",
			"currency": "BHD",
			"period_type": "Monthly",
			"from_date": "2026-11-01",
			"to_date": "2026-11-30",
			"targets": [
				self.target_row("EMP-B", "Bader", 200),
				self.target_row("EMP-A", "Aisha", 100),
				self.target_row("EMP-C", "Charles", 100)
			]
		}
		values.update(overrides)
		return SimpleNamespace(**values)

	def test_sales_aggregate_is_one_parameterized_parent_invoice_query(self):
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.return_value = [
				{"sales_employee": "EMP-A", "achieved_amount": 125,
					"invoice_count": 3}
			]
			result = report.get_sales_aggregates(
				"World Shading", "2026-11-01", "2026-11-30")

		self.assertEqual(frappe_mock.db.sql.call_count, 1)
		query, values = frappe_mock.db.sql.call_args[0][:2]
		query = " ".join(query.lower().split())
		self.assertIn("from `tabsales invoice` si", query)
		self.assertNotIn("sales invoice item", query)
		self.assertIn("si.docstatus = 1", query)
		self.assertIn("si.company = %(company)s", query)
		self.assertIn("si.posting_date between %(from_date)s and %(to_date)s", query)
		self.assertIn("group by si.pb_sales_employee", query)
		self.assertIn("sum(si.base_net_total)", query)
		self.assertIn("count(si.name)", query)
		self.assertNotIn("World Shading", query)
		self.assertEqual(values, {
			"company": "World Shading",
			"from_date": "2026-11-01",
			"to_date": "2026-11-30"
		})
		self.assertEqual(result, {
			"EMP-A": {"achieved_amount": 125, "invoice_count": 3}
		})

	def test_sales_aggregate_preserves_negative_return_totals(self):
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.return_value = [
				{"sales_employee": "EMP-A", "achieved_amount": -25,
					"invoice_count": 1}
			]
			result = report.get_sales_aggregates(
				"World Shading", "2026-11-01", "2026-11-30")
		self.assertEqual(result["EMP-A"]["achieved_amount"], -25)

	def test_rows_rank_full_plan_and_keep_zero_sales_employees(self):
		aggregates = {
			"EMP-B": {"achieved_amount": 150, "invoice_count": 4},
			"EMP-A": {"achieved_amount": 60, "invoice_count": 2}
		}
		rows = report.build_rows(
			self.target(), aggregates, "2026-11-15")

		self.assertEqual(
			[(row["sales_employee"], row["rank"]) for row in rows],
			[("EMP-B", 1), ("EMP-A", 2), ("EMP-C", 3)])
		zero_row = rows[2]
		self.assertEqual(zero_row["achieved_amount"], 0)
		self.assertEqual(zero_row["invoice_count"], 0)
		self.assertEqual(zero_row["currency"], "BHD")
		self.assertEqual(zero_row["sales_target"], "ST-WS-2026-00001")
		self.assertEqual(zero_row["company"], "World Shading")
		self.assertEqual(zero_row["from_date"], "2026-11-01")
		self.assertEqual(zero_row["to_date"], "2026-11-30")
		self.assertEqual(zero_row["effective_to_date"], "2026-11-15")
		for fieldname in (
				"target_amount", "achievement_percent", "expected_amount",
				"progress_variance", "remaining_amount", "over_target_amount",
				"required_daily_run_rate", "status"):
			self.assertIn(fieldname, zero_row)

	def test_employee_filter_preserves_full_plan_rank(self):
		aggregates = {
			"EMP-B": {"achieved_amount": 150, "invoice_count": 4},
			"EMP-A": {"achieved_amount": 60, "invoice_count": 2}
		}
		rows = report.build_rows(
			self.target(), aggregates, "2026-11-15", "EMP-A")
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["sales_employee"], "EMP-A")
		self.assertEqual(rows[0]["rank"], 2)

	def test_execute_rejects_missing_or_unsubmitted_target(self):
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.throw.side_effect = ValueError("rejected")
			with self.assertRaises(ValueError):
				report.execute({})

		for docstatus in (0, 2):
			with self.subTest(docstatus=docstatus), patch.object(
					report, "frappe") as frappe_mock:
				frappe_mock.get_doc.return_value = self.target(docstatus=docstatus)
				frappe_mock.throw.side_effect = ValueError("rejected")
				with self.assertRaises(ValueError):
					report.execute({"sales_target": "ST-WS-2026-00001"})

	def test_execute_clips_after_end_and_does_not_change_target_dates(self):
		target = self.target()
		with patch.object(report, "frappe") as frappe_mock, patch.object(
				report, "get_sales_aggregates", return_value={}) as aggregate:
			frappe_mock.get_doc.return_value = target
			columns, rows = report.execute({
				"sales_target": target.name,
				"as_of_date": "2026-12-15"
			})

		self.assertTrue(columns)
		self.assertEqual(len(rows), 3)
		aggregate.assert_called_once_with(
			"World Shading", "2026-11-01", "2026-11-30")
		self.assertEqual(target.from_date, "2026-11-01")
		self.assertEqual(target.to_date, "2026-11-30")

	def test_execute_skips_invoice_query_before_period(self):
		target = self.target()
		with patch.object(report, "frappe") as frappe_mock, patch.object(
				report, "get_sales_aggregates") as aggregate:
			frappe_mock.get_doc.return_value = target
			unused_columns, rows = report.execute({
				"sales_target": target.name,
				"as_of_date": "2026-10-15"
			})

		aggregate.assert_not_called()
		self.assertEqual(set(row["status"] for row in rows), {"Not Started"})


if __name__ == "__main__":
	unittest.main()
