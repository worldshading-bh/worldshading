from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.model.workflow import get_workflow, get_workflow_name
from frappe.utils import cint
from worldshading.api.purchase_order_urgency import is_completed_workflow


PAYMENT_ENTRY_URGENCY_FIELDS = {
	"Payment Entry": [
		{
			"fieldname": "custom_is_urgent",
			"label": "Urgent",
			"fieldtype": "Check",
			"insert_after": "status",
			"default": "0",
			"description": "Marks this Payment Entry for urgent attention without changing its workflow state.",
			"allow_on_submit": 1,
			"read_only": 1,
			"bold": 1,
			"in_list_view": 0,
			"in_standard_filter": 1,
			"no_copy": 1,
			"print_hide": 1
		},
		{
			"fieldname": "custom_urgent_reason",
			"label": "Urgency Reason",
			"fieldtype": "Small Text",
			"insert_after": "custom_is_urgent",
			"description": "Reason entered when the Payment Entry was marked urgent.",
			"depends_on": "eval:doc.custom_is_urgent",
			"allow_on_submit": 1,
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1
		}
	]
}


def setup_payment_entry_urgency_fields():
	"""Install PE urgency fields and refresh only the metadata they require."""
	create_custom_fields(PAYMENT_ENTRY_URGENCY_FIELDS, update=True)

	# Rebuild the cached hooks from this checkout so the PE form/list scripts
	# become available without a migration or service restart.
	frappe.cache().delete_key("app_hooks")
	frappe.get_hooks()
	frappe.clear_cache(doctype="Payment Entry")

	return {
		"doctype": "Payment Entry",
		"fields": ["custom_is_urgent", "custom_urgent_reason"]
	}


@frappe.whitelist()
def get_urgent_payment_entries():
	"""Return urgent PEs actionable by the current user's workflow roles."""
	if not frappe.get_meta("Payment Entry").has_field("custom_is_urgent"):
		return []

	if not get_workflow_name("Payment Entry"):
		return []

	workflow = get_workflow("Payment Entry")
	user_roles = set(_get_user_roles())
	allowed_states = []

	for state in workflow.states:
		if state.allow_edit in user_roles and state.state not in allowed_states:
			allowed_states.append(state.state)

	if not allowed_states:
		return []

	return frappe.get_list(
		"Payment Entry",
		filters=[
			["custom_is_urgent", "=", 1],
			["docstatus", "!=", 2],
			[workflow.workflow_state_field, "in", allowed_states]
		],
		fields=[
			"name", "party", "party_name", "paid_from_account_currency", "paid_amount",
			workflow.workflow_state_field + " as workflow_state", "custom_urgent_reason", "modified"
		],
		order_by="modified desc",
		limit_page_length=50
	)


@frappe.whitelist()
def set_payment_entry_urgency(pe_name, urgent, reason=None):
	"""Set or clear a Payment Entry's urgency without changing its workflow."""
	if not pe_name:
		frappe.throw(_("Payment Entry is required."))

	payment_entry = frappe.get_doc("Payment Entry", pe_name)
	payment_entry.check_permission("write")
	allowed_role = _get_workflow_allowed_role(payment_entry)
	user_roles = _get_user_roles()
	if allowed_role and allowed_role not in user_roles and "Administrator" not in user_roles:
		frappe.throw(_(
			"Only users with the {0} role can change urgency in the current workflow state."
		).format(frappe.bold(allowed_role)))

	if payment_entry.docstatus == 2:
		frappe.throw(_("A cancelled Payment Entry cannot be marked urgent."))

	urgent = cint(urgent)
	reason = (reason or "").strip()

	if urgent and not reason:
		frappe.throw(_("Urgency Reason is required."))
	if urgent and is_completed_workflow(payment_entry):
		frappe.throw(_("A completed document cannot be marked urgent."))

	if not urgent:
		reason = ""

	payment_entry.db_set({
		"custom_is_urgent": urgent,
		"custom_urgent_reason": reason
	}, notify=True)
	# db_set captures _doc_before_save but does not create a Version itself.
	# Use the native diff so urgency and reason changes appear in the timeline.
	payment_entry.save_version()

	return {
		"urgent": urgent,
		"reason": reason
	}


def _get_user_roles():
	return frappe.get_roles()


def _get_workflow_allowed_role(payment_entry):
	workflow_name = get_workflow_name(payment_entry.doctype)
	if not workflow_name:
		return None

	workflow = get_workflow(payment_entry.doctype)
	current_state = payment_entry.get(workflow.workflow_state_field)

	for state in workflow.states:
		if state.state == current_state:
			return state.allow_edit

	frappe.throw(_(
		"Workflow state {0} is not configured in the active Payment Entry workflow."
	).format(frappe.bold(current_state or "")))
