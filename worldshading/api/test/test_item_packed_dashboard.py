from __future__ import unicode_literals

import unittest
from unittest.mock import patch

from frappe import _dict

from worldshading.api import item_packed_dashboard
from worldshading.dashboards import item_dashboard


class TestItemPackedDashboard(unittest.TestCase):
	def test_worldshading_dashboard_preserves_repack_request_once(self):
		data = _dict({
			"transactions": [
				{"label": "Sell", "items": [
					"Quotation", "Sales Order", "Delivery Note", "Sales Invoice"
				]},
				{"label": "Buy", "items": ["Purchase Order", "Purchase Invoice"]},
				{"label": "Move", "items": ["Stock Entry", "Repack Request"]},
			],
		})

		result = item_dashboard.get_data(data)

		move_items = result.transactions[3]["items"]
		self.assertEqual(move_items.count("Repack Request"), 1)
		self.assertEqual(result.transactions[0]["label"], "Sell")
		self.assertEqual(result.transactions[1]["label"], "Buy")
		self.assertEqual(result.transactions[2], {
			"label": "Sell - Packed Items",
			"items": ["Quotation", "Sales Order", "Delivery Note", "Sales Invoice"],
		})

	def packed_row(self, parent, parenttype="Sales Order", **overrides):
		row = {
			"parent": parent,
			"parenttype": parenttype,
		}
		row.update(overrides)
		return _dict(row)

	def test_counts_distinct_readable_parent_documents(self):
		packed_rows = [
			self.packed_row("SO-001"),
			self.packed_row("SO-001", qty=3),
			self.packed_row("SO-002"),
			self.packed_row("QTN-001", parenttype="Quotation"),
		]

		def visible_parents(doctype, parent_names):
			visible = {
				"Quotation": {"QTN-001": _dict({"name": "QTN-001"})},
				"Sales Order": {"SO-001": _dict({"name": "SO-001"})},
				"Delivery Note": {},
				"Sales Invoice": {},
			}
			return dict((name, visible[doctype][name]) for name in parent_names
				if name in visible[doctype])

		with patch.object(item_packed_dashboard, "get_packed_rows",
				return_value=packed_rows), \
				patch.object(item_packed_dashboard, "get_visible_parent_map",
					side_effect=visible_parents):
			counts = item_packed_dashboard.get_packed_transaction_counts_value(
				"COMPONENT-001")

		self.assertEqual(counts, {
			"Quotation": 1,
			"Sales Order": 1,
			"Delivery Note": 0,
			"Sales Invoice": 0,
		})

if __name__ == "__main__":
	unittest.main()
