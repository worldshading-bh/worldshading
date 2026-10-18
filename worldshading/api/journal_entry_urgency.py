from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.model.workflow import get_workflow, get_workflow_name
from frappe.utils import cint
from worldshading.api.purchase_order_urgency import is_completed_workflow


JOURNAL_ENTRY_URGENCY_FIELDS = {
	"Journal Entry": [
		{
			"fieldname": "custom_is_urgent",
			"label": "Urgent",
			"fieldtype": "Check",
			"insert_after": "total_debit",
			"default": "0",
			"description": "Marks this Journal Entry for urgent attention without changing its workflow state.",
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
			"description": "Reason entered when the Journal Entry was marked urgent.",
			"depends_on": "eval:doc.custom_is_urgent",
			"allow_on_submit": 1,
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1
		}
	]
}


def setup_journal_entry_urgency_fields():
	"""Install JE urgency fields and refresh only the metadata they require."""
	create_custom_fields(JOURNAL_ENTRY_URGENCY_FIELDS, update=True)

	# Rebuild the cached hooks from this checkout so the JE form/list scripts
	# become available without a migration or service restart.
	frappe.cache().delete_key("app_hooks")
	frappe.get_hooks()
	frappe.clear_cache(doctype="Journal Entry")

	return {
		"doctype": "Journal Entry",
		"fields": ["custom_is_urgent", "custom_urgent_reason"]
	}


@frappe.whitelist()
def get_urgent_journal_entries():
	"""Return urgent GL payments actionable by the current user's workflow roles."""
	if not frappe.get_meta("Journal Entry").has_field("custom_is_urgent"):
		return []

	if not get_workflow_name("Journal Entry"):
		return []

	workflow = get_workflow("Journal Entry")
	user_roles = set(_get_user_roles())
	allowed_states = []

	for state in workflow.states:
		if state.allow_edit in user_roles and state.state not in allowed_states:
			allowed_states.append(state.state)

	if not allowed_states:
		return []

	rows = frappe.get_list(
		"Journal Entry",
		filters=[
			["custom_is_urgent", "=", 1],
			["docstatus", "!=", 2],
			[workflow.workflow_state_field, "in", allowed_states]
		],
		fields=[
			"name", "company", "total_debit",
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
def set_journal_entry_urgency(je_name, urgent, reason=None):
	"""Set or clear a Journal Entry's urgency without changing its workflow."""
	if not je_name:
		frappe.throw(_("Journal Entry is required."))

	journal_entry = frappe.get_doc("Journal Entry", je_name)
	journal_entry.check_permission("write")

	if journal_entry.docstatus == 2:
		frappe.throw(_("A cancelled Journal Entry cannot be marked urgent."))

	urgent = cint(urgent)
	reason = (reason or "").strip()

	if urgent and not reason:
		frappe.throw(_("Urgency Reason is required."))
	if urgent and is_completed_workflow(journal_entry):
		frappe.throw(_("A completed document cannot be marked urgent."))

	if not urgent:
		reason = ""

	journal_entry.db_set({
		"custom_is_urgent": urgent,
		"custom_urgent_reason": reason
	}, notify=True)
	# db_set captures _doc_before_save but does not create a Version itself.
	# Use the native diff so urgency and reason changes appear in the timeline.
	journal_entry.save_version()

	return {
		"urgent": urgent,
		"reason": reason
	}


def _get_user_roles():
	return frappe.get_roles()


def _get_workflow_allowed_role(journal_entry):
	workflow_name = get_workflow_name(journal_entry.doctype)
	if not workflow_name:
		return None

	workflow = get_workflow(journal_entry.doctype)
	current_state = journal_entry.get(workflow.workflow_state_field)

	for state in workflow.states:
		if state.state == current_state:
			return state.allow_edit

	frappe.throw(_(
		"Workflow state {0} is not configured in the active Journal Entry workflow."
	).format(frappe.bold(current_state or "")))
