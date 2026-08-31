# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import cint, cstr


MAX_SUFFIX_ATTEMPTS = 1000


def autoname_repack_production_rule(doc, method=None):
	"""Name rules as Type-FinalItem-small_number, avoiding format hash counters."""
	rule_type = cstr(doc.get("type")).strip()
	final_item_code = cstr(doc.get("final_item_code")).strip()

	if not rule_type:
		frappe.throw(_("Type is required to name Repack Production Rule."))
	if not final_item_code:
		frappe.throw(_("Final Item Code is required to name Repack Production Rule."))

	base_name = _get_rule_name_base(rule_type, final_item_code)
	doc.name = _get_next_rule_name(base_name, rule_type, final_item_code)


def _get_rule_name_base(rule_type, final_item_code):
	return "{0}-{1}".format(rule_type, final_item_code)


def _get_next_rule_name(base_name, rule_type, final_item_code):
	existing_count = cint(frappe.db.count("Repack Production Rule", {
		"type": rule_type,
		"final_item_code": final_item_code
	}))

	next_number = max(existing_count, 1)
	for _attempt in range(MAX_SUFFIX_ATTEMPTS):
		candidate = "{0}-{1}".format(base_name, next_number)
		if not frappe.db.exists("Repack Production Rule", candidate):
			return candidate
		next_number += 1

	frappe.throw(_(
		"Could not find an available name for Repack Production Rule {0}."
	).format(base_name))
