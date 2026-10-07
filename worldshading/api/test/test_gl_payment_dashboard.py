from __future__ import unicode_literals

import unittest

from frappe import _dict

from worldshading import hooks

try:
	from worldshading.dashboards import gl_payment_dashboard
except ImportError:
	gl_payment_dashboard = None


class TestGLPaymentDashboard(unittest.TestCase):
	def test_adds_purchase_order_and_journal_entry_links(self):
		self.assertIsNotNone(
			gl_payment_dashboard,
			"GL Payment dashboard override has not been implemented"
		)

		result = gl_payment_dashboard.get_data(_dict())

		self.assertEqual(result.fieldname, "gl_payment")
		self.assertEqual(result.internal_links, {
			"Purchase Order": "purchase_order",
			"Journal Entry": "journal_entry",
		})
		self.assertEqual(result.transactions, [{
			"label": "Reference",
			"items": ["Purchase Order", "Journal Entry"],
		}])

	def test_preserves_existing_dashboard_data_without_duplicates(self):
		self.assertIsNotNone(
			gl_payment_dashboard,
			"GL Payment dashboard override has not been implemented"
		)
		data = _dict({
			"heatmap": True,
			"transactions": [
				{
					"label": "Existing",
					"items": ["Payment Entry", "Journal Entry"],
				},
				{"label": "Reference", "items": ["Purchase Order"]},
			],
		})

		result = gl_payment_dashboard.get_data(data)
		result = gl_payment_dashboard.get_data(result)

		self.assertTrue(result.heatmap)
		self.assertEqual(result.transactions[0], {
			"label": "Existing",
			"items": ["Payment Entry", "Journal Entry"],
		})
		self.assertEqual(result.transactions[1]["items"], ["Purchase Order"])

	def test_gl_payment_dashboard_override_is_registered(self):
		self.assertEqual(
			hooks.override_doctype_dashboards.get("GL Payment"),
			"worldshading.dashboards.gl_payment_dashboard.get_data"
		)


if __name__ == "__main__":
	unittest.main()
