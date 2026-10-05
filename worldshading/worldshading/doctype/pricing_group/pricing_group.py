# -*- coding: utf-8 -*-
# Copyright (c) 2026, World Shading and Contributors
# See license.txt
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import cint
from frappe.model.document import Document


class PricingGroup(Document):
	def validate(self):
		validate_pricing_group_configuration(self)


def _get_strategy_configuration(pricing_strategy):
	strategy = frappe.db.get_value(
		"Pricing Strategy Template", pricing_strategy,
		["company", "enabled"], as_dict=True
	)
	if not strategy:
		frappe.throw(_("Pricing Strategy {0} does not exist").format(pricing_strategy))
	return strategy


def _validate_required_configuration(values):
	missing = [
		label for fieldname, label in (
			("company", _("Company")),
			("item_group", _("Item Group")),
			("pricing_strategy", _("Pricing Strategy"))
		) if not values.get(fieldname)
	]
	if missing:
		frappe.throw(
			_("Pricing Group configuration is incomplete. Set: {0}").format(", ".join(missing))
		)


def _validate_strategy(values):
	strategy = _get_strategy_configuration(values.get("pricing_strategy"))
	if not cint(strategy.get("enabled")):
		frappe.throw(_("Pricing Strategy {0} is not enabled").format(values.get("pricing_strategy")))
	if strategy.get("company") != values.get("company"):
		frappe.throw(
			_("Pricing Strategy {0} belongs to Company {1}, not {2}").format(
				values.get("pricing_strategy"), strategy.get("company"), values.get("company")
			)
		)


def validate_pricing_group_configuration(doc):
	_validate_required_configuration(doc)
	_validate_strategy(doc)
	if not doc.get("name"):
		return
	mismatched_items = frappe.get_all(
		"Item",
		filters={"pricing_group": doc.name, "item_group": ("!=", doc.item_group)},
		fields=["name"], order_by="name asc", limit_page_length=0
	)
	if mismatched_items:
		sample = ", ".join(row.name for row in mismatched_items[:5])
		frappe.throw(
			_("Items {0} do not belong to Item Group {1}. {2} Item(s) mismatch this Pricing Group.").format(
				sample, doc.item_group, len(mismatched_items)
			)
		)


@frappe.whitelist()
def get_pricing_group_configuration(pricing_group, check_permissions=True):
	if cint(check_permissions) and not frappe.has_permission("Pricing Group", "read", pricing_group):
		frappe.throw(
			_("You do not have permission to read Pricing Group {0}").format(pricing_group),
			frappe.PermissionError
		)
	values = frappe.db.get_value(
		"Pricing Group", pricing_group,
		["name", "company", "item_group", "pricing_strategy", "disabled"], as_dict=True
	)
	if not values:
		frappe.throw(_("Pricing Group {0} does not exist").format(pricing_group))
	_validate_required_configuration(values)
	if cint(values.get("disabled")):
		frappe.throw(_("Pricing Group {0} is disabled").format(pricing_group))
	_validate_strategy(values)
	return values


def validate_item_pricing_group(doc, method=None):
	if not doc.get("pricing_group"):
		return
	configuration = get_pricing_group_configuration(doc.pricing_group)
	if doc.get("item_group") != configuration.get("item_group"):
		frappe.throw(
			_("Item {0} cannot use Pricing Group {1} because it is limited to Item Group {2}. "
			  "This Item belongs to {3}.").format(
				doc.get("name") or _("New Item"), doc.pricing_group,
				configuration.get("item_group"), doc.get("item_group") or _("No Item Group")
			)
		)


@frappe.whitelist()
def get_pricing_group_items(pricing_group):
	if not frappe.has_permission("Pricing Group", "read", pricing_group):
		frappe.throw(
			_("You do not have permission to read Pricing Group {0}").format(pricing_group),
			frappe.PermissionError
		)
	if not frappe.has_permission("Item", "read"):
		frappe.throw(_("You do not have permission to read Items"), frappe.PermissionError)
	rows = frappe.get_all(
		"Item", filters={"pricing_group": pricing_group},
		fields=["name", "item_name", "item_group", "brand", "stock_uom", "disabled"],
		order_by="name asc", limit_page_length=0
	)
	return [{
		"item_code": row.name,
		"item_name": row.item_name,
		"item_group": row.item_group,
		"brand": row.brand,
		"stock_uom": row.stock_uom,
		"disabled": cint(row.disabled)
	} for row in rows]
