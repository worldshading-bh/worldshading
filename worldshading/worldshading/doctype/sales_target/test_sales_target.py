from __future__ import unicode_literals

import json
import os
import unittest


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

	def test_child_metadata_supports_employee_targets_in_company_currency(self):
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
		self.assertEqual(fields["target_amount"]["fieldtype"], "Currency")
		self.assertEqual(fields["target_amount"]["options"], "currency")
		self.assertEqual(fields["target_amount"]["reqd"], 1)

	def test_parent_metadata_is_submittable_and_has_required_period_fields(self):
		metadata = self.load_metadata("sales_target", "sales_target.json")
		fields = self.field_map(metadata)

		self.assertEqual(metadata["name"], "Sales Target")
		self.assertEqual(metadata["autoname"], "ST-WS-.YYYY.-.#####")
		self.assertEqual(metadata["is_submittable"], 1)
		self.assertEqual(metadata["track_changes"], 1)
		self.assertEqual(metadata["title_field"], "target_name")
		self.assertNotEqual(metadata.get("quick_entry"), 1)
		self.assertEqual(
			fields["period_type"]["options"],
			"Daily\nWeekly\nMonthly\nQuarterly\nAnnual\nCustom")
		for fieldname in ("company", "currency", "target_name", "period_type",
				"from_date", "to_date", "targets"):
			self.assertEqual(fields[fieldname]["reqd"], 1)
		self.assertEqual(fields["currency"]["options"], "Currency")
		self.assertEqual(fields["currency"]["read_only"], 1)
		self.assertEqual(fields["targets"]["fieldtype"], "Table")
		self.assertEqual(fields["targets"]["options"], "Sales Target Detail")
		self.assertEqual(fields["total_target_amount"]["fieldtype"], "Currency")
		self.assertEqual(fields["total_target_amount"]["options"], "currency")
		self.assertEqual(fields["total_target_amount"]["read_only"], 1)

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


if __name__ == "__main__":
	unittest.main()
