from __future__ import unicode_literals

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.workflow import get_workflow, get_workflow_name
from frappe.utils import cint, escape_html
from frappe.desk.doctype.notification_settings.notification_settings import is_notifications_enabled
from frappe.desk.doctype.notification_log.notification_log import NotificationLog, set_notifications_as_unseen
from worldshading.api.urgency_recipients import get_company_permissions, get_role_preferences


SUPPORTED_DOCTYPES = ("Purchase Order", "Payment Entry", "GL Payment", "Journal Entry")


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
	}, fields=["parent", "role"])
	routing_roles = defaultdict(set)
	for row in members:
		routing_roles[row.parent].add(row.role)
	user_names = list(routing_roles)
	if not user_names:
		return
	users = frappe.get_all("User", filters={
		"name": ["in", user_names], "enabled": 1, "user_type": "System User"
	}, fields=["name"])
	preferences = get_role_preferences([user.name for user in users])
	recipients = [user.name for user in users if not preferences.get(user.name)
		or routing_roles[user.name].intersection(preferences[user.name])]
	company = doc.get("company")
	company_permissions = get_company_permissions(doc.doctype, recipients) if company else {}
	subject = _("Urgent {0} {1} needs your action — {2}. Reason: {3}").format(
		escape_html(doc.doctype), escape_html(doc.name), escape_html(state),
		escape_html(doc.get("custom_urgent_reason") or "")
	)
	for user in recipients:
		allowed_companies = company_permissions.get(user)
		if allowed_companies and company not in allowed_companies:
			continue
		if not is_notifications_enabled(user):
			continue
		# Match popup visibility, including custom permission-query conditions.
		try:
			visible = frappe.get_list(doc.doctype, filters={"name": doc.name},
				fields=["name"], limit_page_length=1, user=user)
		except frappe.PermissionError:
			continue
		if not visible or not frappe.has_permission(doc=doc, user=user, ptype="read"):
			continue
		UrgencyNotificationLog({
			"doctype": "Notification Log", "type": "Assignment",
			"for_user": user, "from_user": frappe.session.user,
			"document_type": doc.doctype, "document_name": doc.name,
			"subject": subject
		}).insert(ignore_permissions=True)


def activate_urgency_notification_hooks():
	"""Explicit operator activation; no migration or document updates."""
	frappe.cache().delete_key("app_hooks")
	frappe.get_hooks()
	return {"doctypes": list(SUPPORTED_DOCTYPES)}
