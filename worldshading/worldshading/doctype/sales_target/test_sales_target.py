from __future__ import unicode_literals

import json
import os
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from worldshading.worldshading.doctype.sales_target import sales_target


class TestSalesTargetMetadata(unittest.TestCase):
	def load_metadata(self, folder, filename):
		path = os.path.join(
			os.path.dirname(os.path.dirname(__file__)), folder, filename)
		with open(path) as source:
			return json.load(source)

	def field_map(self, metadata):
		return dict((field["fieldname"], field) for field in metadata["fields"])

	def permission_map(self, metadata):
		return dict((row["role"], row) for row in metadata["permissions"])

	def test_child_metadata_supports_recurring_targets_in_company_currency(self):
		metadata = self.load_metadata(
			"sales_target_detail", "sales_target_detail.json")
		fields = self.field_map(metadata)

		self.assertEqual(metadata["name"], "Sales Target Detail")
		self.assertEqual(metadata["istable"], 1)
		self.assertEqual(metadata["permissions"], [])
		self.assertEqual(fields["sales_employee"]["options"], "Employee")
		self.assertEqual(fields["sales_employee"]["reqd"], 1)
		self.assertEqual(
			fields["employee_name"]["fetch_from"],
			"sales_employee.employee_name")
		self.assertEqual(fields["currency"]["options"], "Currency")
		self.assertEqual(fields["currency"]["read_only"], 1)
		self.assertEqual(fields["currency"]["hidden"], 1)
		for fieldname in (
				"daily_target", "weekly_target", "monthly_target",
				"quarterly_target", "annual_target"):
			self.assertEqual(fields[fieldname]["fieldtype"], "Currency")
			self.assertEqual(fields[fieldname]["options"], "currency")
		self.assertEqual(fields["target_amount"]["fieldtype"], "Currency")
		self.assertEqual(fields["target_amount"]["options"], "currency")
		self.assertEqual(fields["target_amount"]["hidden"], 1)
		self.assertEqual(fields["target_amount"]["read_only"], 1)
		self.assertNotEqual(fields["target_amount"].get("reqd"), 1)

		inline_fields = [
			field["fieldname"] for field in metadata["fields"]
			if field.get("in_list_view")
		]
		self.assertEqual(inline_fields, [
			"sales_employee", "employee_name", "daily_target",
			"weekly_target", "monthly_target"
		])
		self.assertLessEqual(sum(
			field.get("columns", 0) for field in metadata["fields"]
			if field.get("in_list_view")), 10)

	def test_parent_metadata_is_submittable_and_has_recurring_plan_fields(self):
		metadata = self.load_metadata("sales_target", "sales_target.json")
		fields = self.field_map(metadata)

		self.assertEqual(metadata["name"], "Sales Target")
		self.assertEqual(metadata["autoname"], "ST-WS-.YYYY.-.#####")
		self.assertEqual(metadata["is_submittable"], 1)
		self.assertEqual(metadata["track_changes"], 1)
		self.assertEqual(metadata["title_field"], "target_name")
		self.assertNotEqual(metadata.get("quick_entry"), 1)
		for fieldname in (
				"company", "currency", "target_name", "from_date", "to_date",
				"targets"):
			self.assertEqual(fields[fieldname]["reqd"], 1)
		self.assertEqual(fields["target_model"]["hidden"], 1)
		self.assertEqual(fields["target_model"]["read_only"], 1)
		for fieldname in (
				"total_daily_target", "total_weekly_target",
				"total_monthly_target", "total_quarterly_target",
				"total_annual_target"):
			self.assertEqual(fields[fieldname]["fieldtype"], "Currency")
			self.assertEqual(fields[fieldname]["options"], "currency")
			self.assertEqual(fields[fieldname]["read_only"], 1)
		self.assertEqual(fields["currency"]["options"], "Currency")
		self.assertEqual(fields["currency"]["read_only"], 1)
		self.assertEqual(fields["targets"]["fieldtype"], "Table")
		self.assertEqual(fields["targets"]["options"], "Sales Target Detail")
		self.assertEqual(fields["total_target_amount"]["fieldtype"], "Currency")
		self.assertEqual(fields["total_target_amount"]["options"], "currency")
		self.assertEqual(fields["total_target_amount"]["read_only"], 1)
		for fieldname in ("period_type", "total_target_amount"):
			self.assertEqual(fields[fieldname]["hidden"], 1)
			self.assertEqual(fields[fieldname]["read_only"], 1)
			self.assertNotEqual(fields[fieldname].get("reqd"), 1)

	def test_parent_permissions_match_management_access_policy(self):
		metadata = self.load_metadata("sales_target", "sales_target.json")
		permissions = self.permission_map(metadata)

		self.assertEqual(set(permissions), {
			"Sales Manager", "General Manager", "System Manager", "Accounts Manager"
		})
		for role in ("Sales Manager", "General Manager", "System Manager"):
			for permission in (
					"create", "read", "write", "submit", "cancel", "amend",
					"report", "print", "email", "export"):
				self.assertEqual(permissions[role].get(permission), 1)
		self.assertEqual(permissions["General Manager"].get("share"), 1)
		self.assertEqual(permissions["System Manager"].get("share"), 1)
		self.assertEqual(permissions["System Manager"].get("delete"), 1)
		for permission in ("read", "report", "print", "export"):
			self.assertEqual(permissions["Accounts Manager"].get(permission), 1)
		for permission in ("create", "write", "submit", "cancel", "amend"):
			self.assertNotEqual(permissions["Accounts Manager"].get(permission), 1)


class TestSalesTargetValidation(unittest.TestCase):
	def row(self, employee="EMP-001", amount=100):
		return SimpleNamespace(
			sales_employee=employee,
			target_amount=amount,
			currency=None,
			idx=1
		)

	def document(self, **overrides):
		values = {
			"name": "ST-WS-2026-00001",
			"company": "World Shading",
			"currency": None,
			"period_type": "Monthly",
			"from_date": "2026-11-01",
			"to_date": "2026-11-30",
			"targets": [self.row()],
			"total_target_amount": 0,
			"amended_from": None
		}
		values.update(overrides)
		return SimpleNamespace(**values)

	def assert_rejected(self, function, document):
		with patch.object(
				sales_target.frappe, "throw", side_effect=ValueError("rejected")):
			with self.assertRaises(ValueError):
				function(document)

	def test_dates_allow_a_single_day(self):
		doc = self.document(from_date="2026-11-04", to_date="2026-11-04")
		sales_target._validate_dates(doc)

	def test_dates_reject_an_end_before_the_start(self):
		doc = self.document(from_date="2026-11-05", to_date="2026-11-04")
		self.assert_rejected(sales_target._validate_dates, doc)

	def test_company_currency_is_copied_to_parent_and_every_child(self):
		doc = self.document(targets=[self.row("EMP-001"), self.row("EMP-002")])
		with patch.object(sales_target, "frappe") as frappe_mock:
			frappe_mock.db.get_value.return_value = "BHD"
			sales_target._set_company_currency(doc)

		self.assertEqual(doc.currency, "BHD")
		self.assertEqual([row.currency for row in doc.targets], ["BHD", "BHD"])

	def test_company_without_default_currency_is_rejected(self):
		doc = self.document()
		with patch.object(sales_target, "frappe") as frappe_mock:
			frappe_mock.db.get_value.return_value = None
			frappe_mock.throw.side_effect = ValueError("rejected")
			with self.assertRaises(ValueError):
				sales_target._set_company_currency(doc)

	def test_employee_rows_require_at_least_one_target(self):
		self.assert_rejected(
			sales_target._validate_employee_rows,
			self.document(targets=[]))

	def test_employee_rows_reject_duplicate_employees(self):
		doc = self.document(targets=[self.row(), self.row()])
		self.assert_rejected(sales_target._validate_employee_rows, doc)

	def test_employee_rows_reject_non_positive_amounts(self):
		for amount in (0, -1, None):
			with self.subTest(amount=amount):
				self.assert_rejected(
					sales_target._validate_employee_rows,
					self.document(targets=[self.row(amount=amount)]))

	def test_employee_rows_reject_missing_inactive_and_wrong_company_employees(self):
		cases = (
			([], "missing"),
			([{"name": "EMP-001", "status": "Inactive", "company": "World Shading"}],
				"inactive"),
			([{"name": "EMP-001", "status": "Active", "company": "Another Company"}],
				"wrong company")
		)
		for employees, label in cases:
			with self.subTest(case=label), patch.object(
					sales_target.frappe, "get_all", return_value=employees):
				self.assert_rejected(
					sales_target._validate_employee_rows, self.document())

	def test_employee_rows_validate_all_employees_in_one_bulk_read(self):
		doc = self.document(targets=[self.row("EMP-001"), self.row("EMP-002")])
		employees = [
			{"name": "EMP-001", "status": "Active", "company": "World Shading"},
			{"name": "EMP-002", "status": "Active", "company": "World Shading"}
		]
		with patch.object(
				sales_target.frappe, "get_all", return_value=employees) as get_all:
			sales_target._validate_employee_rows(doc)

		self.assertEqual(get_all.call_count, 1)

	def test_total_uses_numeric_conversion_and_three_decimal_precision(self):
		doc = self.document(targets=[
			self.row("EMP-001", "1.2345"),
			self.row("EMP-002", "2.3456")
		])
		sales_target._set_total_target(doc)
		self.assertEqual(doc.total_target_amount, 3.58)

	def test_validate_runs_currency_dates_rows_and_total_in_order(self):
		doc = self.document()
		calls = []
		patches = [
			patch.object(sales_target, name, side_effect=lambda unused, name=name: calls.append(name))
			for name in (
				"_set_company_currency", "_validate_dates",
				"_validate_employee_rows", "_set_total_target")
		]
		for helper_patch in patches:
			helper_patch.start()
		try:
			sales_target.SalesTarget.validate(doc)
		finally:
			for helper_patch in reversed(patches):
				helper_patch.stop()

		self.assertEqual(calls, [
			"_set_company_currency", "_validate_dates",
			"_validate_employee_rows", "_set_total_target"
		])


class TestSalesTargetOverlap(TestSalesTargetValidation):
	def test_overlap_rejects_an_inclusive_submitted_conflict(self):
		doc = self.document(from_date="2026-11-01", to_date="2026-11-30")
		with patch.object(sales_target, "frappe") as frappe_mock:
			frappe_mock.db.sql.return_value = [{
				"name": "ST-WS-2026-00002",
				"sales_employee": "EMP-001"
			}]
			frappe_mock.throw.side_effect = ValueError("overlap")
			with self.assertRaises(ValueError):
				sales_target._validate_no_overlap(doc)

	def test_overlap_query_scopes_every_business_dimension_with_parameters(self):
		doc = self.document(targets=[self.row("EMP-001"), self.row("EMP-002")])
		with patch.object(sales_target, "frappe") as frappe_mock:
			frappe_mock.db.sql.return_value = []
			sales_target._validate_no_overlap(doc)

		query, values = frappe_mock.db.sql.call_args[0][:2]
		query = " ".join(query.lower().split())
		self.assertIn("p.docstatus = 1", query)
		self.assertIn("p.company = %(company)s", query)
		self.assertIn("p.period_type = %(period_type)s", query)
		self.assertIn("p.from_date <= %(to_date)s", query)
		self.assertIn("p.to_date >= %(from_date)s", query)
		self.assertIn("d.sales_employee in %(employee_ids)s", query)
		self.assertIn("p.name not in %(excluded_names)s", query)
		self.assertIn("limit 1 for update", query)
		self.assertNotIn("World Shading", query)
		self.assertNotIn("EMP-001", query)
		self.assertEqual(values["company"], "World Shading")
		self.assertEqual(values["period_type"], "Monthly")
		self.assertEqual(values["from_date"], "2026-11-01")
		self.assertEqual(values["to_date"], "2026-11-30")
		self.assertEqual(values["employee_ids"], ("EMP-001", "EMP-002"))
		self.assertEqual(values["excluded_names"], ("ST-WS-2026-00001",))

	def test_amended_target_excludes_only_itself_from_active_overlap_check(self):
		doc = self.document(
			name="ST-WS-2026-00001-1",
			amended_from="ST-WS-2026-00001")
		with patch.object(sales_target, "frappe") as frappe_mock:
			frappe_mock.db.sql.return_value = []
			sales_target._validate_no_overlap(doc)

		values = frappe_mock.db.sql.call_args[0][1]
		self.assertEqual(values["excluded_names"], ("ST-WS-2026-00001-1",))

	def test_amendment_source_must_be_cancelled(self):
		doc = self.document(amended_from="ST-WS-2026-00000")
		for docstatus in (None, 0, 1):
			with self.subTest(docstatus=docstatus), patch.object(
					sales_target, "frappe") as frappe_mock:
				frappe_mock.db.get_value.return_value = docstatus
				frappe_mock.throw.side_effect = ValueError("invalid amendment")
				with self.assertRaises(ValueError):
					sales_target._validate_amendment_source(doc)

	def test_cancelled_amendment_source_is_allowed(self):
		doc = self.document(amended_from="ST-WS-2026-00000")
		with patch.object(sales_target, "frappe") as frappe_mock:
			frappe_mock.db.get_value.return_value = 2
			sales_target._validate_amendment_source(doc)

		frappe_mock.db.get_value.assert_called_once_with(
			"Sales Target", "ST-WS-2026-00000", "docstatus")

	def test_company_lock_uses_a_parameterized_transaction_row_lock(self):
		with patch.object(sales_target, "frappe") as frappe_mock:
			sales_target._lock_company("World Shading")

		query, values = frappe_mock.db.sql.call_args[0][:2]
		query = " ".join(query.lower().split())
		self.assertIn("from `tabcompany`", query)
		self.assertIn("name = %(company)s", query)
		self.assertIn("for update", query)
		self.assertNotIn("World Shading", query)
		self.assertEqual(values, {"company": "World Shading"})

	def test_before_submit_validates_amendment_then_locks_then_checks_overlap(self):
		doc = self.document()
		calls = []
		with patch.object(
				sales_target, "_validate_amendment_source",
				side_effect=lambda unused: calls.append("amendment")), patch.object(
					sales_target, "_lock_company",
					side_effect=lambda unused: calls.append("lock")), patch.object(
					sales_target, "_validate_no_overlap",
					side_effect=lambda unused: calls.append("overlap")):
			sales_target.SalesTarget.before_submit(doc)
		self.assertEqual(calls, ["amendment", "lock", "overlap"])


class TestSalesTargetClientContract(unittest.TestCase):
	def test_client_handlers_apply_defaults_filters_totals_and_read_only_updates(self):
		script = os.path.join(
			os.path.dirname(__file__), "test_sales_target_client.js")
		result = subprocess.run(
			["node", script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
			universal_newlines=True)
		self.assertEqual(result.returncode, 0, result.stdout)
		self.assertIn("sales_target client behavior: ok", result.stdout)


if __name__ == "__main__":
	unittest.main()
