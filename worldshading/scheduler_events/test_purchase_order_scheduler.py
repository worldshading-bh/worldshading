from __future__ import unicode_literals

import unittest
from datetime import date
from types import SimpleNamespace

try:
	from unittest.mock import MagicMock, patch
except ImportError:
	from mock import MagicMock, patch

from worldshading.scheduler_events import purchase_order_scheduler


class TestPurchaseOrderScheduler(unittest.TestCase):
	def test_initial_shipment_does_not_mark_followup_completed(self):
		doc = SimpleNamespace(
			doctype="Purchase Order",
			name="PO-TEST-1",
			workflow_state="Shipped",
			shipment_followup_completed=0,
			_doc_before_save=SimpleNamespace(workflow_state="Ready To Ship"),
			db_set=MagicMock(),
		)

		purchase_order_scheduler.mark_shipment_followup_completed(doc)

		doc.db_set.assert_not_called()

	def test_shipment_update_marks_followup_completed(self):
		doc = SimpleNamespace(
			doctype="Purchase Order",
			name="PO-TEST-1",
			workflow_state="Shipped",
			shipment_followup_completed=0,
			_doc_before_save=SimpleNamespace(workflow_state="Shipment Follow-Up"),
			db_set=MagicMock(),
		)

		purchase_order_scheduler.mark_shipment_followup_completed(doc)

		doc.db_set.assert_called_once_with(
			"shipment_followup_completed", 1, update_modified=False
		)

	def test_completed_shipment_followup_is_not_created_again(self):
		commit = MagicMock()
		fake_db = SimpleNamespace(commit=commit)
		doc = SimpleNamespace(
			name="PO-TEST-1",
			workflow_state="Shipped",
			schedule_date=date(2026, 9, 7),
			eta_date=date(2026, 10, 23),
			shipment_followup_completed=1,
			save=MagicMock(),
			add_comment=MagicMock(),
		)

		with patch.object(
			purchase_order_scheduler.frappe,
			"get_all",
			return_value=[SimpleNamespace(name=doc.name)],
		), patch.object(
			purchase_order_scheduler.frappe,
			"get_doc",
			return_value=doc,
		), patch.object(
			purchase_order_scheduler,
			"nowdate",
			return_value="2026-10-11",
		), patch.object(
			purchase_order_scheduler.frappe,
			"db",
			fake_db,
		), patch.object(
			purchase_order_scheduler.frappe,
			"logger",
			return_value=MagicMock(),
		):
			purchase_order_scheduler.auto_update_purchase_order()

		self.assertEqual(doc.workflow_state, "Shipped")
		doc.save.assert_not_called()
		doc.add_comment.assert_not_called()
		commit.assert_not_called()

	def test_completed_followup_still_moves_to_pre_arrival(self):
		commit = MagicMock()
		fake_db = SimpleNamespace(commit=commit)
		doc = SimpleNamespace(
			name="PO-TEST-1",
			workflow_state="Shipped",
			schedule_date=date(2026, 9, 7),
			eta_date=date(2026, 10, 23),
			shipment_followup_completed=1,
			save=MagicMock(),
			add_comment=MagicMock(),
		)

		with patch.object(
			purchase_order_scheduler.frappe,
			"get_all",
			return_value=[SimpleNamespace(name=doc.name)],
		), patch.object(
			purchase_order_scheduler.frappe,
			"get_doc",
			return_value=doc,
		), patch.object(
			purchase_order_scheduler,
			"nowdate",
			return_value="2026-10-16",
		), patch.object(
			purchase_order_scheduler.frappe,
			"db",
			fake_db,
		), patch.object(
			purchase_order_scheduler.frappe,
			"logger",
			return_value=MagicMock(),
		):
			purchase_order_scheduler.auto_update_purchase_order()

		self.assertEqual(doc.workflow_state, "Pre-Arrival")
		doc.save.assert_called_once_with(ignore_permissions=True)
		doc.add_comment.assert_called_once()
		commit.assert_called_once()


if __name__ == "__main__":
	unittest.main()
