from __future__ import unicode_literals

import unittest

from frappe import _dict

from worldshading import hooks

try:
	from worldshading.dashboards import journal_entry_dashboard
except ImportError:
	journal_entry_dashboard = None


class TestJournalEntryDashboard(unittest.TestCase):
	def test_adds_gl_payment_relationship(self):
		self.assertIsNotNone(
			journal_entry_dashboard,
			"Journal Entry dashboard override has not been implemented"
		)

		result = journal_entry_dashboard.get_data(_dict())

		self.assertEqual(result.fieldname, "journal_entry")
		self.assertEqual(result.transactions, [{
			"label": "Payment",
			"items": ["GL Payment"],
		}])

	def test_preserves_existing_dashboard_data_without_duplicates(self):
		self.assertIsNotNone(
			journal_entry_dashboard,
			"Journal Entry dashboard override has not been implemented"
		)
		data = _dict({
			"heatmap": True,
			"transactions": [
				{"label": "Existing", "items": ["GL Payment"]},
			],
		})

		result = journal_entry_dashboard.get_data(data)
		result = journal_entry_dashboard.get_data(result)

		self.assertTrue(result.heatmap)
		self.assertEqual(result.transactions, [{
			"label": "Existing",
			"items": ["GL Payment"],
		}])

	def test_journal_entry_dashboard_override_is_registered(self):
		self.assertEqual(
			hooks.override_doctype_dashboards.get("Journal Entry"),
			"worldshading.dashboards.journal_entry_dashboard.get_data"
		)


if __name__ == "__main__":
	unittest.main()
