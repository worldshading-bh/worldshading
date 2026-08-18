from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.desk.form.utils import validate_link as frappe_validate_link
from frappe.utils import cint


GROUP_FIELD_BY_DOCTYPE = {
	"Item": "item_group",
	"Supplier": "supplier_group"
}

DISABLED_GROUP_DOCTYPES = ("Item Group", "Supplier Group")

GROUP_SETTINGS = {
	"Item Group": {
		"parent_field": "parent_item_group",
		"linked_doctype": "Item",
		"link_field": "item_group"
	},
	"Supplier Group": {
		"parent_field": "parent_supplier_group",
		"linked_doctype": "Supplier",
		"link_field": "supplier_group"
	}
}


@frappe.whitelist()
def validate_link():
	"""Reject disabled Item/Supplier Groups pasted into any Desk Link field."""
	options = frappe.form_dict.get("options")
	value = frappe.form_dict.get("value")

	if options in DISABLED_GROUP_DOCTYPES and value:
		disabled = frappe.db.get_value(options, value, "disabled")
		if disabled:
			frappe.msgprint(
				_("{0} {1} is disabled").format(_(options), frappe.bold(value)),
				title=_("Disabled {0}").format(_(options)),
				indicator="red"
			)
			return

	return frappe_validate_link()


def validate_active_group_assignment(doc, method=None):
	"""Prevent a disabled group from being newly assigned; retain old assignments."""
	group_field = GROUP_FIELD_BY_DOCTYPE.get(doc.doctype)
	if not group_field or not doc.get(group_field):
		return

	old_doc = doc.get_doc_before_save()
	if old_doc and old_doc.get(group_field) == doc.get(group_field):
		return

	group_doctype = "Item Group" if doc.doctype == "Item" else "Supplier Group"
	if frappe.db.get_value(group_doctype, doc.get(group_field), "disabled"):
		frappe.throw(
			_("{0} {1} is disabled and cannot be assigned.").format(
				_(group_doctype), frappe.bold(doc.get(group_field))
			)
		)


def validate_group_state(doc, method=None):
	"""Keep enabled/disabled group trees and active linked masters consistent."""
	settings = GROUP_SETTINGS.get(doc.doctype)
	if not settings:
		return

	old_doc = doc.get_doc_before_save()
	old_disabled = cint(old_doc.get("disabled")) if old_doc else 0
	if old_doc and old_disabled == cint(doc.disabled):
		return

	if cint(doc.disabled):
		validate_group_can_be_disabled(doc, settings)
	else:
		validate_group_can_be_enabled(doc, settings)


def validate_group_can_be_disabled(doc, settings):
	descendants = get_group_descendants(
		doc.doctype, doc.name, settings["parent_field"]
	)
	enabled_children = [row.name for row in descendants if not cint(row.disabled)]
	if enabled_children:
		frappe.throw(
			_("Disable all child groups before disabling {0}. Enabled child groups: {1}").format(
				frappe.bold(doc.name), format_name_list(enabled_children)
			)
		)

	group_names = [doc.name] + [row.name for row in descendants]
	linked_filters = {
		settings["link_field"]: ["in", group_names],
		"disabled": 0
	}
	linked_count = frappe.db.count(settings["linked_doctype"], linked_filters)
	if linked_count:
		linked_names = frappe.get_all(
			settings["linked_doctype"],
			filters=linked_filters,
			fields=["name"],
			order_by="name asc",
			limit_page_length=50
		)
		frappe.throw(
			_("Move or disable the active {0} linked to this group tree before disabling {1}. "
			  "Active records: {2}.<br><br>{3}").format(
				_(settings["linked_doctype"]),
				frappe.bold(doc.name),
				linked_count,
				format_record_links(
					settings["linked_doctype"], linked_names, linked_count
				)
			)
		)


def validate_group_can_be_enabled(doc, settings):
	parent_name = doc.get(settings["parent_field"])
	visited = set()

	while parent_name and parent_name not in visited:
		visited.add(parent_name)
		parent = frappe.db.get_value(
			doc.doctype,
			parent_name,
			[settings["parent_field"], "disabled"],
			as_dict=1
		)
		if not parent:
			break
		if cint(parent.disabled):
			frappe.throw(
				_("Enable parent group {0} before enabling {1}.").format(
					frappe.bold(parent_name), frappe.bold(doc.name)
				)
			)
		parent_name = parent.get(settings["parent_field"])


def get_group_descendants(group_doctype, group_name, parent_field):
	descendants = []
	groups_to_check = [group_name]
	visited = set()

	while groups_to_check:
		parent_name = groups_to_check.pop(0)
		if parent_name in visited:
			continue
		visited.add(parent_name)
		children = frappe.get_all(
			group_doctype,
			filters={parent_field: parent_name},
			fields=["name", "disabled"],
			order_by="name asc"
		)
		descendants.extend(children)
		groups_to_check.extend([row.name for row in children])

	return descendants


def format_name_list(names):
	names = names or []
	formatted_names = [frappe.bold(name) for name in names[:5]]
	if len(names) > 5:
		formatted_names.append(_("and {0} more").format(len(names) - 5))
	return ", ".join(formatted_names)


def format_record_links(doctype, records, total_count):
	links = [
		frappe.utils.get_link_to_form(doctype, row.name, frappe.bold(row.name))
		for row in records
	]
	if total_count > len(records):
		links.append(
			_("and {0} more...").format(total_count - len(records))
		)
	return "<br>".join(links)
