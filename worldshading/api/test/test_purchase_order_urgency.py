from __future__ import unicode_literals

import unittest
from unittest.mock import MagicMock, patch

import frappe

try:
	from worldshading.api import purchase_order_urgency
except ImportError:
	purchase_order_urgency = None


class TestPurchaseOrderUrgency(unittest.TestCase):

	def setUp(self):
		self.assertIsNotNone(
			purchase_order_urgency,
			"Purchase Order urgency API has not been implemented"
		)
		self.purchase_order = MagicMock()
		self.purchase_order.doctype = "Purchase Order"
		self.purchase_order.docstatus = 1
		self.purchase_order.get.return_value = "Pending"
		self.workflow = frappe._dict({
			"workflow_state_field": "workflow_state",
			"states": [frappe._dict({"state": "Pending", "allow_edit": "Purchase User"})]
		})
		self.workflow_name_patch = patch.object(
			purchase_order_urgency, "get_workflow_name",
			return_value="Purchase Order Workflow"
		)
		self.workflow_name_patch.start()
		self.addCleanup(self.workflow_name_patch.stop)
		self.workflow_patch = patch.object(
			purchase_order_urgency, "get_workflow", return_value=self.workflow
		)
		self.workflow_patch.start()
		self.addCleanup(self.workflow_patch.stop)
		self.roles_patch = patch.object(
			purchase_order_urgency,
			"_get_user_roles",
			return_value=["Purchase User"],
			create=True
		)
		self.roles_patch.start()
		self.addCleanup(self.roles_patch.stop)
		self.throw_patch = patch.object(frappe, "throw", side_effect=self.raise_validation_error)
		self.throw_patch.start()
		self.addCleanup(self.throw_patch.stop)

	@staticmethod
	def raise_validation_error(message):
		raise frappe.ValidationError(message)

	def test_mark_urgent_requires_and_trims_reason(self):
		with patch.object(frappe, "get_doc", return_value=self.purchase_order):
			result = purchase_order_urgency.set_purchase_order_urgency(
				"PO-0001", 1, "  Supplier needs advance today  "
			)

		self.purchase_order.check_permission.assert_called_once_with("write")
		self.purchase_order.db_set.assert_called_once_with({
			"custom_is_urgent": 1,
			"custom_urgent_reason": "Supplier needs advance today"
		}, notify=True)
		self.assertEqual(result["urgent"], 1)
		self.assertEqual(result["reason"], "Supplier needs advance today")
		self.purchase_order.save_version.assert_called_once_with()
		methods = [call[0] for call in self.purchase_order.method_calls]
		self.assertLess(methods.index("db_set"), methods.index("save_version"))

	def test_mark_urgent_rejects_empty_reason(self):
		with patch.object(frappe, "get_doc", return_value=self.purchase_order):
			with self.assertRaises(frappe.ValidationError):
				purchase_order_urgency.set_purchase_order_urgency("PO-0001", 1, "   ")

		self.purchase_order.db_set.assert_not_called()
		self.purchase_order.save_version.assert_not_called()

	def test_mark_normal_clears_reason(self):
		with patch.object(frappe, "get_doc", return_value=self.purchase_order):
			result = purchase_order_urgency.set_purchase_order_urgency(
				"PO-0001", 0, "old reason"
			)

		self.purchase_order.db_set.assert_called_once_with({
			"custom_is_urgent": 0,
			"custom_urgent_reason": ""
		}, notify=True)
		self.assertEqual(result, {"urgent": 0, "reason": ""})
		self.purchase_order.save_version.assert_called_once_with()

	def test_version_failure_is_not_silenced(self):
		self.purchase_order.save_version.side_effect = RuntimeError("Audit failed")
		with patch.object(frappe, "get_doc", return_value=self.purchase_order):
			with self.assertRaises(RuntimeError):
				purchase_order_urgency.set_purchase_order_urgency("PO-0001", 1, "Urgent")

	def test_cancelled_purchase_order_cannot_be_changed(self):
		self.purchase_order.docstatus = 2
		with patch.object(frappe, "get_doc", return_value=self.purchase_order):
			with self.assertRaises(frappe.ValidationError):
				purchase_order_urgency.set_purchase_order_urgency(
					"PO-0001", 1, "Urgent"
				)

		self.purchase_order.db_set.assert_not_called()

	def test_purchase_order_name_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			purchase_order_urgency.set_purchase_order_urgency(None, 1, "Urgent")

	def test_user_must_hold_current_workflow_state_edit_role(self):
		with patch.object(purchase_order_urgency, "_get_user_roles",
				return_value=["Purchase Manager"], create=True):
			with patch.object(frappe, "get_doc", return_value=self.purchase_order):
				with self.assertRaises(frappe.ValidationError):
					purchase_order_urgency.set_purchase_order_urgency(
						"PO-0001", 1, "Urgent"
					)

		self.purchase_order.db_set.assert_not_called()

	def test_current_workflow_state_supplies_allowed_edit_role(self):
		self.assertTrue(hasattr(purchase_order_urgency, "_get_workflow_allowed_role"))
		purchase_order = MagicMock()
		purchase_order.doctype = "Purchase Order"
		purchase_order.get.return_value = "Pending Accounts"
		workflow = frappe._dict({
			"workflow_state_field": "workflow_state",
			"states": [
				frappe._dict({"state": "Draft", "allow_edit": "Purchase User"}),
				frappe._dict({"state": "Pending Accounts", "allow_edit": "Accounts User"})
			]
		})

		with patch.object(purchase_order_urgency, "get_workflow_name",
				return_value="Purchase Order Workflow", create=True):
			with patch.object(purchase_order_urgency, "get_workflow",
					return_value=workflow, create=True):
				role = purchase_order_urgency._get_workflow_allowed_role(purchase_order)

		self.assertEqual(role, "Accounts User")

	def test_setup_creates_only_po_urgency_fields_and_refreshes_metadata(self):
		self.assertTrue(hasattr(
			purchase_order_urgency, "setup_purchase_order_urgency_fields"
		))
		cache = MagicMock()
		with patch.object(purchase_order_urgency, "create_custom_fields",
				create=True) as create_fields:
			with patch.object(frappe, "cache", return_value=cache):
				with patch.object(frappe, "get_hooks") as get_hooks:
					with patch.object(frappe, "clear_cache") as clear_cache:
						result = purchase_order_urgency.setup_purchase_order_urgency_fields()

		create_fields.assert_called_once_with(
			purchase_order_urgency.PURCHASE_ORDER_URGENCY_FIELDS,
			update=True
		)
		cache.delete_key.assert_called_once_with("app_hooks")
		get_hooks.assert_called_once_with()
		clear_cache.assert_called_once_with(doctype="Purchase Order")
		self.assertEqual(result, {
			"doctype": "Purchase Order",
			"fields": ["custom_is_urgent", "custom_urgent_reason"]
		})

	def test_popup_query_filters_urgent_pos_by_workflow_roles_in_one_query(self):
		self.assertTrue(hasattr(
			purchase_order_urgency, "get_urgent_purchase_orders"
		), "Urgent Purchase Order popup endpoint has not been implemented")
		self.workflow.states = [
			frappe._dict({"state": "Draft", "allow_edit": "Purchase User"}),
			frappe._dict({"state": "Pending Payment", "allow_edit": "Maker - ACC (Workflow)"}),
			frappe._dict({"state": "Pending Finance", "allow_edit": "Finance (Workflow)"})
		]
		rows = [frappe._dict({
			"name": "PO-0001",
			"workflow_state": "Pending Payment",
			"custom_urgent_reason": "Advance required"
		})]

		with patch.object(purchase_order_urgency, "_get_user_roles",
				return_value=["Purchase User", "Maker - ACC (Workflow)"]):
			with patch.object(frappe, "get_list", return_value=rows) as get_list:
				result = purchase_order_urgency.get_urgent_purchase_orders()

		self.assertEqual(result, rows)
		get_list.assert_called_once_with(
			"Purchase Order",
			filters=[
				["custom_is_urgent", "=", 1],
				["docstatus", "!=", 2],
				["workflow_state", "in", ["Draft", "Pending Payment"]]
			],
			fields=[
				"name", "supplier", "supplier_name", "currency", "grand_total",
				"workflow_state", "custom_urgent_reason", "modified"
			],
			order_by="modified desc",
			limit_page_length=50
		)

	def test_popup_query_skips_database_when_user_has_no_workflow_state(self):
		self.assertTrue(hasattr(
			purchase_order_urgency, "get_urgent_purchase_orders"
		), "Urgent Purchase Order popup endpoint has not been implemented")
		with patch.object(purchase_order_urgency, "_get_user_roles",
				return_value=["Sales User"]):
			with patch.object(frappe, "get_list") as get_list:
				result = purchase_order_urgency.get_urgent_purchase_orders()

		self.assertEqual(result, [])
		get_list.assert_not_called()


if __name__ == "__main__":
	unittest.main()
