from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.model.workflow import get_workflow, get_workflow_name
from frappe.utils import cint
from worldshading.api.purchase_order_urgency import is_completed_workflow


GL_PAYMENT_URGENCY_FIELDS = {
	"GL Payment": [
		{
			"fieldname": "custom_is_urgent",
			"label": "Urgent",
			"fieldtype": "Check",
			"insert_after": "total_amount",
			"default": "0",
			"description": "Marks this GL Payment for urgent attention without changing its workflow state.",
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
			"description": "Reason entered when the GL Payment was marked urgent.",
			"depends_on": "eval:doc.custom_is_urgent",
			"allow_on_submit": 1,
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1
		}
	]
}


def setup_gl_payment_urgency_fields():
	"""Install GLP urgency fields and refresh only the metadata they require."""
	create_custom_fields(GL_PAYMENT_URGENCY_FIELDS, update=True)

	# Rebuild the cached hooks from this checkout so the GLP form/list scripts
	# become available without a migration or service restart.
	frappe.cache().delete_key("app_hooks")
	frappe.get_hooks()
	frappe.clear_cache(doctype="GL Payment")

	return {
		"doctype": "GL Payment",
		"fields": ["custom_is_urgent", "custom_urgent_reason"]
	}


@frappe.whitelist()
def get_urgent_gl_payments():
	"""Return urgent GL payments actionable by the current user's workflow roles."""
	if not frappe.get_meta("GL Payment").has_field("custom_is_urgent"):
		return []

	if not get_workflow_name("GL Payment"):
		return []

	workflow = get_workflow("GL Payment")
	user_roles = set(_get_user_roles())
	allowed_states = []

	for state in workflow.states:
		if state.allow_edit in user_roles and state.state not in allowed_states:
			allowed_states.append(state.state)

	if not allowed_states:
		return []

	rows = frappe.get_list(
		"GL Payment",
		filters=[
			["custom_is_urgent", "=", 1],
			["docstatus", "!=", 2],
			[workflow.workflow_state_field, "in", allowed_states]
		],
		fields=[
			"name", "party", "party_name", "company", "total_amount",
			workflow.workflow_state_field + " as workflow_state", "custom_urgent_reason", "modified"
		],
		order_by="modified desc",
		limit_page_length=50
	)

	companies = list(set(row.company for row in rows if row.company))
	currencies = {}
	if companies:
		currencies = {row.name: row.default_currency for row in frappe.get_all(
			"Company", filters={"name": ["in", companies]}, fields=["name", "default_currency"]
		)}
	for row in rows:
		row["currency"] = currencies.get(row.company, "")
	return rows


@frappe.whitelist()
def set_gl_payment_urgency(glp_name, urgent, reason=None):
	"""Set or clear a GL Payment's urgency without changing its workflow."""
	if not glp_name:
		frappe.throw(_("GL Payment is required."))

	gl_payment = frappe.get_doc("GL Payment", glp_name)
	gl_payment.check_permission("write")
	allowed_role = _get_workflow_allowed_role(gl_payment)
	user_roles = _get_user_roles()
	if allowed_role and allowed_role not in user_roles and "Administrator" not in user_roles:
		frappe.throw(_(
			"Only users with the {0} role can change urgency in the current workflow state."
		).format(frappe.bold(allowed_role)))

	if gl_payment.docstatus == 2:
		frappe.throw(_("A cancelled GL Payment cannot be marked urgent."))

	urgent = cint(urgent)
	reason = (reason or "").strip()

	if urgent and not reason:
		frappe.throw(_("Urgency Reason is required."))
	if urgent and is_completed_workflow(gl_payment):
		frappe.throw(_("A completed document cannot be marked urgent."))

	if not urgent:
		reason = ""

	gl_payment.db_set({
		"custom_is_urgent": urgent,
		"custom_urgent_reason": reason
	}, notify=True)
	# db_set captures _doc_before_save but does not create a Version itself.
	# Use the native diff so urgency and reason changes appear in the timeline.
	gl_payment.save_version()

	return {
		"urgent": urgent,
		"reason": reason
	}


def _get_user_roles():
	return frappe.get_roles()


def _get_workflow_allowed_role(gl_payment):
	workflow_name = get_workflow_name(gl_payment.doctype)
	if not workflow_name:
		return None

	workflow = get_workflow(gl_payment.doctype)
	current_state = gl_payment.get(workflow.workflow_state_field)

	for state in workflow.states:
		if state.state == current_state:
			return state.allow_edit

	frappe.throw(_(
		"Workflow state {0} is not configured in the active GL Payment workflow."
	).format(frappe.bold(current_state or "")))
