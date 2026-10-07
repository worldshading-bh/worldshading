from __future__ import unicode_literals

import unittest

from frappe import _dict

from worldshading import hooks

try:
	from worldshading.dashboards import purchase_order_dashboard
except ImportError:
	purchase_order_dashboard = None


class TestPurchaseOrderDashboard(unittest.TestCase):
	def get_dashboard_data(self):
		return _dict({
			"fieldname": "purchase_order",
			"transactions": [
				{
					"label": "Related",
					"items": ["Purchase Receipt", "Purchase Invoice"],
				},
				{
					"label": "Payment",
					"items": ["Payment Entry", "Journal Entry"],
				},
			],
		})

	def test_adds_gl_payment_to_existing_payment_group(self):
		self.assertIsNotNone(
			purchase_order_dashboard,
			"Purchase Order dashboard override has not been implemented"
		)
		data = self.get_dashboard_data()

		result = purchase_order_dashboard.get_data(data)

		self.assertEqual(result.fieldname, "purchase_order")
		self.assertEqual(result.transactions[0], {
			"label": "Related",
			"items": ["Purchase Receipt", "Purchase Invoice"],
		})
		self.assertEqual(result.transactions[1]["items"], [
			"Payment Entry", "Journal Entry", "GL Payment"
		])

	def test_does_not_duplicate_existing_gl_payment(self):
		self.assertIsNotNone(
			purchase_order_dashboard,
			"Purchase Order dashboard override has not been implemented"
		)
		data = self.get_dashboard_data()
		data.transactions[1]["items"].append("GL Payment")

		result = purchase_order_dashboard.get_data(data)

		self.assertEqual(
			result.transactions[1]["items"].count("GL Payment"),
			1
		)

	def test_ignores_group_with_only_one_standard_payment_doctype(self):
		data = self.get_dashboard_data()
		data.transactions.insert(0, {
			"label": "Other",
			"items": ["Payment Entry"],
		})

		result = purchase_order_dashboard.get_data(data)

		self.assertEqual(result.transactions[0]["items"], ["Payment Entry"])
		self.assertEqual(result.transactions[2]["items"], [
			"Payment Entry", "Journal Entry", "GL Payment"
		])

	def test_purchase_order_dashboard_override_is_registered(self):
		self.assertEqual(
			hooks.override_doctype_dashboards["Purchase Order"],
			"worldshading.dashboards.purchase_order_dashboard.get_data"
		)


if __name__ == "__main__":
	unittest.main()
