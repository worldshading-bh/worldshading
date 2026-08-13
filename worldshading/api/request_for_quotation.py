from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import cint


SUPPLIER_ITEM_GROUP_FIELD = "supplier_item_group"
SUPPLIER_ITEM_GROUP_DOCTYPE = "Supplier Item Group"


def _as_list(value):
	if not value:
		return []
	if isinstance(value, (list, tuple)):
		return list(value)
	return frappe.parse_json(value) or []


def _get_item_groups(item_codes):
	item_codes = list(set([code for code in _as_list(item_codes) if code]))
	if not item_codes:
		return []

	items = frappe.get_all(
		"Item",
		filters={"name": ["in", item_codes]},
		fields=["item_group"]
	)
	item_groups = set([row.item_group for row in items if row.item_group])
	return list(_with_parent_item_groups(item_groups))


def _get_direct_item_groups(item_codes):
	item_codes = list(set([code for code in _as_list(item_codes) if code]))
	if not item_codes:
		return []

	items = frappe.get_all(
		"Item",
		filters={"name": ["in", item_codes]},
		fields=["item_group"]
	)
	return sorted(set([row.item_group for row in items if row.item_group]))


def _with_parent_item_groups(item_groups):
	"""Return the selected Item Groups together with every ancestor group."""
	groups = set(item_groups or [])
	frontier = set(groups)

	while frontier:
		parents = frappe.get_all(
			"Item Group",
			filters={"name": ["in", list(frontier)]},
			fields=["parent_item_group"]
		)
		frontier = set([
			row.parent_item_group for row in parents
			if row.parent_item_group and row.parent_item_group not in groups
		])
		groups.update(frontier)

	return groups


def _get_matching_suppliers(item_codes):
	item_groups = _get_item_groups(item_codes)
	if not item_groups:
		return [], item_groups

	rows = frappe.get_all(
		SUPPLIER_ITEM_GROUP_DOCTYPE,
		filters={
			"parenttype": "Supplier",
			"parentfield": SUPPLIER_ITEM_GROUP_FIELD,
			"item_group": ["in", item_groups]
		},
		fields=["parent", "priority"]
	)

	priority_by_supplier = {}
	for row in rows:
		priority = cint(row.priority)
		priority = priority if priority > 0 else 999999
		if row.parent not in priority_by_supplier:
			priority_by_supplier[row.parent] = priority
		else:
			priority_by_supplier[row.parent] = min(
				priority_by_supplier[row.parent], priority)

	if not priority_by_supplier:
		return [], item_groups

	# get_list is intentional: unlike get_all, it applies the current user's
	# Supplier permission query conditions.
	suppliers = frappe.get_list(
		"Supplier",
		filters={
			"name": ["in", list(priority_by_supplier)],
			"disabled": 0,
			"prevent_rfqs": 0
		},
		fields=["name", "supplier_name"],
		limit_page_length=0
	)

	for supplier in suppliers:
		supplier.priority = priority_by_supplier.get(supplier.name, 999999)

	suppliers.sort(key=lambda row: (
		row.priority,
		(row.supplier_name or row.name).lower()
	))
	return suppliers, item_groups


@frappe.whitelist()
def get_suppliers_for_items(item_codes=None):
	suppliers, item_groups = _get_matching_suppliers(item_codes)
	return {
		"suppliers": suppliers,
		"item_groups": item_groups
	}


def validate_supplier_item_groups(doc, method=None):
	"""Block RFQ save when a supplier cannot supply any RFQ Item Group."""
	item_codes = [row.item_code for row in (doc.items or []) if row.item_code]
	direct_item_groups = _get_direct_item_groups(item_codes)
	matching_item_groups = set(_with_parent_item_groups(direct_item_groups))
	supplier_names = list(set([
		row.supplier for row in (doc.suppliers or []) if row.supplier
	]))

	# Core RFQ validation handles missing items and suppliers. Avoid replacing its
	# standard messages when this custom rule has nothing meaningful to compare.
	if not direct_item_groups or not supplier_names:
		return

	specializations = frappe.get_all(
		SUPPLIER_ITEM_GROUP_DOCTYPE,
		filters={
			"parenttype": "Supplier",
			"parentfield": SUPPLIER_ITEM_GROUP_FIELD,
			"parent": ["in", supplier_names]
		},
		fields=["parent", "item_group"]
	)
	groups_by_supplier = {}
	for row in specializations:
		groups_by_supplier.setdefault(row.parent, set()).add(row.item_group)

	invalid_suppliers = []
	for supplier in supplier_names:
		configured_groups = groups_by_supplier.get(supplier, set())
		if configured_groups.intersection(matching_item_groups):
			continue

		supplier_name = frappe.db.get_value(
			"Supplier", supplier, "supplier_name") or supplier
		configured_text = ", ".join(sorted(configured_groups)) \
			if configured_groups else _("None configured")
		invalid_suppliers.append({
			"supplier_id": supplier,
			"supplier": supplier_name,
			"rfq_item_groups": ", ".join(direct_item_groups),
			"configured_groups": configured_text
		})

	if invalid_suppliers:
		message = [
			_("The supplier(s) below cannot provide the items in this RFQ:")
		]
		for index, invalid in enumerate(invalid_suppliers, 1):
			supplier_link = frappe.utils.get_link_to_form(
				"Supplier", invalid["supplier_id"], invalid["supplier"])
			message.append(
				"{0}. <b>{1}:</b> {2}<br>"
				"&nbsp;&nbsp;&nbsp;<b>{3}:</b> {4}<br>"
				"&nbsp;&nbsp;&nbsp;<b>{5}:</b> {6}".format(
					index,
					_("Supplier"),
					supplier_link,
					_("Supplier Specialization"),
					invalid["configured_groups"],
					_("RFQ Item Groups"),
					invalid["rfq_item_groups"]
				)
			)
		message.append(
			_("To allow this supplier, open Supplier &gt; Supplier Item Groups "
			  "and add a matching Item Group or one of its parent groups.")
		)
		frappe.throw(
			"<br><br>".join(message),
			title=_("Supplier Item Group Mismatch")
		)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def supplier_query(doctype, txt, searchfield, start, page_len, filters):
	filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	suppliers, _item_groups = _get_matching_suppliers(filters.get("item_codes"))

	# With no configured match, retain the normal Supplier lookup so users can
	# still select a legitimate one-time supplier manually.
	if not suppliers:
		return frappe.get_list(
			"Supplier",
			filters={
				"disabled": 0,
				"prevent_rfqs": 0,
				"name": ["like", "%%%s%%" % txt]
			},
			fields=["name", "supplier_name"],
			limit_start=start,
			limit_page_length=page_len,
			as_list=True
		)

	txt = (txt or "").lower()
	matched = [row for row in suppliers if
		txt in row.name.lower() or txt in (row.supplier_name or "").lower()]
	return [[row.name, row.supplier_name] for row in matched[start:start + page_len]]
