from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.model.workflow import get_workflow, get_workflow_name
from frappe.utils import cint


PURCHASE_ORDER_URGENCY_FIELDS = {
	"Purchase Order": [
		{
			"fieldname": "custom_is_urgent",
			"label": "Urgent",
			"fieldtype": "Check",
			"insert_after": "status",
			"default": "0",
			"description": "Marks this Purchase Order for urgent attention without changing its workflow state.",
			"allow_on_submit": 1,
			"read_only": 1,
			"bold": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"no_copy": 1,
			"print_hide": 1
		},
		{
			"fieldname": "custom_urgent_reason",
			"label": "Urgency Reason",
			"fieldtype": "Small Text",
			"insert_after": "custom_is_urgent",
			"description": "Reason entered when the Purchase Order was marked urgent.",
			"depends_on": "eval:doc.custom_is_urgent",
			"allow_on_submit": 1,
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1
		}
	]
}


def setup_purchase_order_urgency_fields():
	"""Install PO urgency fields and refresh only the metadata they require."""
	create_custom_fields(PURCHASE_ORDER_URGENCY_FIELDS, update=True)

	# Rebuild the cached hooks from this checkout so the PO form/list scripts
	# become available without a migration or service restart.
	frappe.cache().delete_key("app_hooks")
	frappe.get_hooks()
	frappe.clear_cache(doctype="Purchase Order")

	return {
		"doctype": "Purchase Order",
		"fields": ["custom_is_urgent", "custom_urgent_reason"]
	}


@frappe.whitelist()
def get_urgent_purchase_orders():
	"""Return urgent POs actionable by the current user's workflow roles."""
	if not get_workflow_name("Purchase Order"):
		return []

	workflow = get_workflow("Purchase Order")
	user_roles = set(_get_user_roles())
	allowed_states = []

	for state in workflow.states:
		if state.allow_edit in user_roles and state.state not in allowed_states:
			allowed_states.append(state.state)

	if not allowed_states:
		return []

	return frappe.get_list(
		"Purchase Order",
		filters=[
			["custom_is_urgent", "=", 1],
			["docstatus", "!=", 2],
			["workflow_state", "in", allowed_states]
		],
		fields=[
			"name", "supplier", "supplier_name", "currency", "grand_total",
			"workflow_state", "custom_urgent_reason", "modified"
		],
		order_by="modified desc",
		limit_page_length=50
	)


@frappe.whitelist()
def set_purchase_order_urgency(po_name, urgent, reason=None):
	"""Set or clear a Purchase Order's urgency without changing its workflow."""
	if not po_name:
		frappe.throw(_("Purchase Order is required."))

	purchase_order = frappe.get_doc("Purchase Order", po_name)
	purchase_order.check_permission("write")
	allowed_role = _get_workflow_allowed_role(purchase_order)
	user_roles = _get_user_roles()
	if allowed_role and allowed_role not in user_roles and "Administrator" not in user_roles:
		frappe.throw(_(
			"Only users with the {0} role can change urgency in the current workflow state."
		).format(frappe.bold(allowed_role)))

	if purchase_order.docstatus == 2:
		frappe.throw(_("A cancelled Purchase Order cannot be marked urgent."))

	urgent = cint(urgent)
	reason = (reason or "").strip()

	if urgent and not reason:
		frappe.throw(_("Urgency Reason is required."))
	if urgent and is_completed_workflow(purchase_order):
		frappe.throw(_("A completed document cannot be marked urgent."))

	if not urgent:
		reason = ""

	purchase_order.db_set({
		"custom_is_urgent": urgent,
		"custom_urgent_reason": reason
	}, notify=True)
	# db_set captures _doc_before_save but does not create a Version itself.
	# Use the native diff so urgency and reason changes appear in the timeline.
	purchase_order.save_version()

	return {
		"urgent": urgent,
		"reason": reason
	}


def _get_user_roles():
	return frappe.get_roles()


def is_completed_workflow(doc):
	if not get_workflow_name(doc.doctype):
		return False
	workflow = get_workflow(doc.doctype)
	return doc.get(workflow.workflow_state_field) == "Completed"


def clear_completed_urgency(doc, method=None):
	"""Clear urgency within the workflow save, including submitted documents."""
	if doc.docstatus == 2 or not cint(doc.get("custom_is_urgent")):
		return
	if is_completed_workflow(doc):
		doc.custom_is_urgent = 0
		doc.custom_urgent_reason = ""


def clear_cancelled_urgency(doc, method=None):
	"""Clear within the cancellation transaction and its normal Version entry."""
	if doc.docstatus != 2:
		return
	if doc.get("custom_is_urgent") is not None:
		doc.custom_is_urgent = 0
	if doc.get("custom_urgent_reason") is not None:
		doc.custom_urgent_reason = ""


def _get_workflow_allowed_role(purchase_order):
	workflow_name = get_workflow_name(purchase_order.doctype)
	if not workflow_name:
		return None

	workflow = get_workflow(purchase_order.doctype)
	current_state = purchase_order.get(workflow.workflow_state_field)

	for state in workflow.states:
		if state.state == current_state:
			return state.allow_edit

	frappe.throw(_(
		"Workflow state {0} is not configured in the active Purchase Order workflow."
	).format(frappe.bold(current_state or "")))
