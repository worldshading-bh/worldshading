import unittest
from unittest.mock import MagicMock, patch

import frappe
from worldshading.api import urgency_notifications as notifications


class TestUrgencyNotifications(unittest.TestCase):
	def setUp(self):
		self.doc = MagicMock()
		self.doc.doctype = "Purchase Order"
		self.doc.name = "PO-1"
		self.doc.docstatus = 1
		self.values = {"custom_is_urgent": 1, "approval_status": "Pending Payment",
			"custom_urgent_reason": '<img src=x onerror="bad">Pay today'}
		self.doc.get.side_effect = self.values.get
		self.old = frappe._dict(custom_is_urgent=0, approval_status="Pending Payment")
		self.doc.get_doc_before_save.return_value = self.old
		workflow = frappe._dict(workflow_state_field="approval_status", states=[
			frappe._dict(state="Pending Payment", allow_edit="Maker"),
			frappe._dict(state="Approval", allow_edit="Approver")])
		self.patch(notifications, "get_workflow_name", return_value="Active")
		self.patch(notifications, "get_workflow", return_value=workflow)
		self.patch(frappe, "session", frappe._dict(user="officer@example.com"))
		self.get_all = self.patch(frappe, "get_all", side_effect=[
			[frappe._dict(parent="maker@example.com"), frappe._dict(parent="maker@example.com")],
			[frappe._dict(name="maker@example.com")]])
		self.get_list = self.patch(frappe, "get_list", return_value=[frappe._dict(name="PO-1")])
		self.permission = self.patch(frappe, "has_permission", return_value=True)
		self.enabled = self.patch(notifications, "is_notifications_enabled", return_value=True)
		self.log = self.patch(notifications, "UrgencyNotificationLog")

	def patch(self, target, name, *args, **kwargs):
		p = patch.object(target, name, *args, **kwargs)
		self.addCleanup(p.stop)
		return p.start()

	def test_marking_urgent_notifies_current_role_without_assigning(self):
		notifications.notify_urgency_change(self.doc)
		self.assertEqual(self.get_all.call_args_list[0][1]["filters"]["role"], ["in", ["Maker"]])
		self.assertEqual(self.get_all.call_args_list[1][1]["filters"]["name"], ["in", ["maker@example.com"]])
		data = self.log.call_args[0][0]
		self.assertEqual(data["doctype"], "Notification Log")
		self.assertEqual(data["for_user"], "maker@example.com")
		self.assertIn("&lt;img", data["subject"])
		self.assertNotIn("<img", data["subject"])
		self.log.return_value.insert.assert_called_once_with(ignore_permissions=True)
		self.get_list.assert_called_once_with("Purchase Order", filters={"name": "PO-1"},
			fields=["name"], limit_page_length=1, user="maker@example.com")
		self.doc.db_set.assert_not_called()

	def test_transition_notifies_new_role(self):
		self.old.custom_is_urgent = 1
		self.values["approval_status"] = "Approval"
		notifications.notify_urgency_change(self.doc)
		self.assertEqual(self.get_all.call_args_list[0][1]["filters"]["role"], ["in", ["Approver"]])
		self.assertIn("Approval", self.log.call_args[0][0]["subject"])

	def test_ordinary_save_or_reason_edit_does_not_notify(self):
		self.old.custom_is_urgent = 1
		self.old.custom_urgent_reason = "Different reason"
		notifications.notify_urgency_change(self.doc)
		self.get_all.assert_not_called()
		self.log.assert_not_called()

	def test_normal_completed_and_cancelled_do_not_notify(self):
		for flag, state, status in [(0, "Pending Payment", 1), (1, "Completed", 1), (1, "Approval", 2)]:
			self.values.update(custom_is_urgent=flag, approval_status=state)
			self.doc.docstatus = status
			notifications.notify_urgency_change(self.doc)
		self.get_all.assert_not_called()
		self.log.assert_not_called()

	def test_no_list_access_no_notification(self):
		self.get_list.return_value = []
		notifications.notify_urgency_change(self.doc)
		self.log.assert_not_called()

	def test_permission_exception_no_notification(self):
		self.get_list.side_effect = frappe.PermissionError
		notifications.notify_urgency_change(self.doc)
		self.log.assert_not_called()

	def test_document_permission_denial_no_notification(self):
		self.permission.return_value = False
		notifications.notify_urgency_change(self.doc)
		self.log.assert_not_called()

	def test_disabled_notifications_no_notification(self):
		self.enabled.return_value = False
		notifications.notify_urgency_change(self.doc)
		self.log.assert_not_called()

	def test_all_three_doctypes_supported(self):
		for doctype in notifications.SUPPORTED_DOCTYPES:
			self.doc.doctype = doctype
			self.get_all.side_effect = [[frappe._dict(parent="maker@example.com")],
				[frappe._dict(name="maker@example.com")]]
			notifications.notify_urgency_change(self.doc)
		self.assertEqual(self.log.call_count, 3)


class TestDeskOnlyDelivery(unittest.TestCase):
	def test_realtime_is_after_commit_and_no_email(self):
		with patch.object(frappe, "publish_realtime") as publish, \
			patch.object(notifications, "set_notifications_as_unseen") as unseen, \
			patch.object(frappe, "sendmail") as sendmail:
			notifications.UrgencyNotificationLog.after_insert(frappe._dict(for_user="maker@example.com"))
		publish.assert_called_once_with("notification", after_commit=True, user="maker@example.com")
		unseen.assert_called_once_with("maker@example.com")
		sendmail.assert_not_called()
