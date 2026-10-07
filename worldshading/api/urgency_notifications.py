from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.workflow import get_workflow, get_workflow_name
from frappe.utils import cint, escape_html
from frappe.desk.doctype.notification_settings.notification_settings import is_notifications_enabled
from frappe.desk.doctype.notification_log.notification_log import NotificationLog, set_notifications_as_unseen


SUPPORTED_DOCTYPES = ("Purchase Order", "Payment Entry", "GL Payment")


class UrgencyNotificationLog(NotificationLog):
	"""Use standard Notification Log storage with desk-only delivery."""
	def after_insert(self):
		frappe.publish_realtime("notification", after_commit=True, user=self.for_user)
		set_notifications_as_unseen(self.for_user)


def notify_urgency_change(doc, method=None):
	"""Create desk notifications only; never create or change assignments."""
	if doc.doctype not in SUPPORTED_DOCTYPES or doc.docstatus == 2:
		return
	if not cint(doc.get("custom_is_urgent")) or not get_workflow_name(doc.doctype):
		return
	workflow = get_workflow(doc.doctype)
	state = doc.get(workflow.workflow_state_field)
	if not state or state == "Completed":
		return
	previous = doc.get_doc_before_save()
	if previous and cint(previous.get("custom_is_urgent")) and previous.get(workflow.workflow_state_field) == state:
		return

	roles = list(set(row.allow_edit for row in workflow.states if row.state == state and row.allow_edit))
	if not roles:
		return
	members = frappe.get_all("Has Role", filters={
		"role": ["in", roles], "parenttype": "User", "parentfield": "roles"
	}, fields=["parent"])
	user_names = list(set(row.parent for row in members))
	if not user_names:
		return
	users = frappe.get_all("User", filters={
		"name": ["in", user_names], "enabled": 1, "user_type": "System User"
	}, fields=["name"])
	subject = _("Urgent {0} {1} needs your action — {2}. Reason: {3}").format(
		escape_html(doc.doctype), escape_html(doc.name), escape_html(state),
		escape_html(doc.get("custom_urgent_reason") or "")
	)
	for user in users:
		if not is_notifications_enabled(user.name):
			continue
		# Match popup visibility, including custom permission-query conditions.
		try:
			visible = frappe.get_list(doc.doctype, filters={"name": doc.name},
				fields=["name"], limit_page_length=1, user=user.name)
		except frappe.PermissionError:
			continue
		if not visible or not frappe.has_permission(doc=doc, user=user.name, ptype="read"):
			continue
		UrgencyNotificationLog({
			"doctype": "Notification Log", "type": "Assignment",
			"for_user": user.name, "from_user": frappe.session.user,
			"document_type": doc.doctype, "document_name": doc.name,
			"subject": subject
		}).insert(ignore_permissions=True)


def activate_urgency_notification_hooks():
	"""Explicit operator activation; no migration or document updates."""
	frappe.cache().delete_key("app_hooks")
	frappe.get_hooks()
	return {"doctypes": list(SUPPORTED_DOCTYPES)}
