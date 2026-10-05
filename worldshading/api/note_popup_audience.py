from __future__ import unicode_literals

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


AUDIENCE_FIELD = "custom_popup_audience_roles"
ROLE_TABLE = "Workflow Assignment Role"


def setup_note_popup_audience():
	"""Reuse the site's role-only child table without changing public Note access."""
	meta = frappe.get_meta(ROLE_TABLE)
	role = meta.get_field("role")
	if not meta.istable or not role or role.fieldtype != "Link" or role.options != "Role":
		frappe.throw("Workflow Assignment Role must be a child table with a Role link")
	field = frappe.get_meta("Note").get_field(AUDIENCE_FIELD)
	if field and (field.fieldtype not in ("Table", "Table MultiSelect") or field.options != ROLE_TABLE):
		frappe.throw("The existing Note popup audience field has an incompatible definition")
	create_custom_fields({"Note": [{
		"fieldname": AUDIENCE_FIELD,
		"label": "Popup Audience Roles",
		"fieldtype": "Table MultiSelect",
		"options": ROLE_TABLE,
		"insert_after": "expire_notification_on",
		"depends_on": "notify_on_login",
		"description": "Leave empty for everyone. Otherwise, users with any selected role receive the login popup. Public Note access is unchanged.",
		"print_hide": 1
	}]})
	return {"doctype": "Note", "fieldname": AUDIENCE_FIELD, "options": ROLE_TABLE}


def filter_note_popups(bootinfo):
	"""Run after native Note expiry/seen filtering on every Desk boot."""
	notes = bootinfo.get("notes") or []
	if not notes:
		return
	rows = frappe.get_all(ROLE_TABLE, filters={
		"parenttype": "Note", "parentfield": AUDIENCE_FIELD,
		"parent": ["in", [note.get("name") for note in notes]]
	}, fields=["parent", "role"], limit_page_length=0)
	audiences = {}
	for row in rows:
		audiences.setdefault(row.parent, set()).add(row.role)
	user_roles = set(frappe.get_roles())
	bootinfo["notes"] = [note for note in notes
		if note.get("name") not in audiences
		or audiences[note.get("name")].intersection(user_roles)]
