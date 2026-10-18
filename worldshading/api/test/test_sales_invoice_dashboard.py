from __future__ import unicode_literals

import unittest

from frappe import _dict

from worldshading.dashboards import sales_invoice_dashboard


class TestSalesInvoiceDashboard(unittest.TestCase):
	def test_adds_direct_project_link_without_losing_service_visit(self):
		data = _dict({
			"fieldname": "sales_invoice",
			"transactions": [{
				"label": "Reference",
				"items": ["Timesheet", "Delivery Note", "Sales Order"],
			}],
		})

		result = sales_invoice_dashboard.get_data(data)

		self.assertEqual(result.internal_links["Project"], "project")
		self.assertEqual(result.internal_links["Service Visit"], "service_visit")
		self.assertIn({
			"label": "Projects",
			"items": ["Project"],
		}, result.transactions)

	def test_project_link_is_idempotent_and_preserves_existing_dashboard(self):
		data = _dict({
			"heatmap": True,
			"internal_links": {"Project": "existing_project"},
			"transactions": [{
				"label": "Existing Projects",
				"items": ["Project"],
			}],
		})

		result = sales_invoice_dashboard.get_data(data)
		result = sales_invoice_dashboard.get_data(result)

		self.assertTrue(result.heatmap)
		self.assertEqual(result.internal_links["Project"], "existing_project")
		all_items = [
			item
			for group in result.transactions
			for item in group.get("items", [])
		]
		self.assertEqual(all_items.count("Project"), 1)
		self.assertEqual(all_items.count("Service Visit"), 1)


if __name__ == "__main__":
	unittest.main()
