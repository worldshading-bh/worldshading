from __future__ import unicode_literals

import unittest

from frappe import _dict

from worldshading import hooks

try:
	from worldshading.dashboards import payment_entry_dashboard
except ImportError:
	payment_entry_dashboard = None


class TestPaymentEntryDashboard(unittest.TestCase):
	def test_adds_reference_table_relationships_and_online_payment_last(self):
		self.assertIsNotNone(
			payment_entry_dashboard,
			"Payment Entry dashboard override has not been implemented"
		)

		result = payment_entry_dashboard.get_data(_dict())

		self.assertEqual(result.fieldname, "payment_entry")
		self.assertEqual(result.internal_links, {
			"Sales Invoice": ["references", "reference_name"],
			"Purchase Invoice": ["references", "reference_name"],
			"Sales Order": ["references", "reference_name"],
			"Purchase Order": ["references", "reference_name"],
			"Journal Entry": ["references", "reference_name"],
			"Expense Claim": ["references", "reference_name"],
			"Employee Advance": ["references", "reference_name"],
			"Fees": ["references", "reference_name"],
			"Quotation": "quotation",
			"Service Visit": "service_visit",
			"Project": "project",
		})
		self.assertEqual(result.non_standard_fieldnames, {
			"WS Payment Transaction": "payment_entry",
		})
		self.assertEqual(result.transactions, [
			{
				"label": "Reference",
				"items": [
					"Sales Invoice", "Purchase Invoice", "Sales Order",
					"Purchase Order", "Journal Entry", "Expense Claim",
					"Employee Advance", "Fees", "Quotation",
					"Service Visit", "Project"
				],
			},
			{
				"label": "Online Payment",
				"items": ["WS Payment Transaction"],
			},
		])

	def test_preserves_existing_dashboard_data_without_duplicates(self):
		self.assertIsNotNone(
			payment_entry_dashboard,
			"Payment Entry dashboard override has not been implemented"
		)
		data = _dict({
			"heatmap": True,
			"internal_links": {
				"Quotation": "existing_quotation",
			},
			"transactions": [
				{
					"label": "Online Payment",
					"items": ["WS Payment Transaction", "Auto Repeat"],
				},
				{
					"label": "Existing",
					"items": ["Project", "Payment Order"],
				},
				{
					"label": "Amendment",
					"items": ["Payment Entry"],
				},
			],
		})

		result = payment_entry_dashboard.get_data(data)
		result = payment_entry_dashboard.get_data(result)

		self.assertTrue(result.heatmap)
		self.assertEqual(
			result.internal_links["Quotation"], "existing_quotation"
		)
		all_items = [
			item
			for group in result.transactions
			for item in group.get("items", [])
		]
		for doctype in (
			"Sales Invoice", "Purchase Invoice", "Sales Order",
			"Purchase Order", "Journal Entry", "Expense Claim",
			"Employee Advance", "Fees", "Quotation", "Service Visit",
			"Project", "WS Payment Transaction"
		):
			self.assertEqual(all_items.count(doctype), 1)
		for unused_doctype in ("Payment Order", "Payment Entry", "Auto Repeat"):
			self.assertNotIn(unused_doctype, all_items)
		self.assertEqual(result.transactions[-1]["label"], "Online Payment")

	def test_payment_entry_dashboard_override_is_registered(self):
		self.assertEqual(
			hooks.override_doctype_dashboards.get("Payment Entry"),
			"worldshading.dashboards.payment_entry_dashboard.get_data"
		)
		self.assertEqual(hooks.doctype_js.get("Payment Entry"), [
			"public/js/payment_entry_urgency.js",
			"public/js/payment_entry_dashboard.js",
		])


if __name__ == "__main__":
	unittest.main()
