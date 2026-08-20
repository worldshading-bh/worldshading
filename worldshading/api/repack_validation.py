# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import flt


QUANTITY_TOLERANCE = 0.000001
SUPPORTED_STOCK_ENTRY_TYPES = ("Repack", "Production")


def validate_repack_quantities(doc, method=None):
	"""Require custom Repack/Production Stock Entries to follow configured rule batches."""
	stock_entry_type = _get_rule_stock_entry_type(doc)
	if not stock_entry_type:
		return

	actual_sources, actual_targets = _get_stock_entry_quantities(doc)
	if not actual_sources or not actual_targets:
		frappe.throw(_(
			"A {0} Stock Entry must contain source and target items before it can be saved."
		).format(stock_entry_type))

	rules = _get_repack_production_rules(stock_entry_type)
	if not rules:
		frappe.throw(_(
			"No {0} Production Rule exists. Create the rule before saving this {0} Stock Entry."
		).format(stock_entry_type))

	matched_rules = find_matching_rules(actual_sources, actual_targets, rules)
	if matched_rules:
		return

	candidates = _get_applicable_rules(actual_targets, rules)
	if not candidates:
		frappe.throw(_(
			"<b>Problem:</b> No {0} Production Rule matches target item(s):<br>{1}<br><br>"
			"Create the correct rule, then save this Stock Entry again."
		).format(stock_entry_type, _format_items(actual_targets)),
			title=_("{0} Rule Not Found").format(stock_entry_type))

	frappe.throw(
		_build_mismatch_message(actual_sources, actual_targets, candidates),
		title=_("Invalid Repack Quantity")
	)


def find_matching_rule(actual_sources, actual_targets, rules):
	"""Backward-compatible helper for callers checking a single Repack rule."""
	matches = find_matching_rules(actual_sources, actual_targets, rules)
	return matches[0] if len(matches) == 1 else None


def find_matching_rules(actual_sources, actual_targets, rules):
	"""Return all rules when a Stock Entry is the exact sum of whole rule batches."""
	applicable_rules = _get_applicable_rules(actual_targets, rules)
	if not applicable_rules:
		return []

	covered_targets = set()
	expected_sources = {}
	expected_targets = {}
	for rule in applicable_rules:
		rule_targets = set(rule["targets"])
		if covered_targets.intersection(rule_targets):
			return []
		covered_targets.update(rule_targets)

		actual_rule_targets = dict(
			(key, actual_targets[key]) for key in rule["targets"])
		multiplier = _get_whole_multiplier(actual_rule_targets, rule["targets"])
		if not multiplier:
			return []

		_merge_quantities(expected_sources, rule["sources"], multiplier)
		_merge_quantities(expected_targets, rule["targets"], multiplier)

	if covered_targets != set(actual_targets):
		return []
	if set(expected_sources) != set(actual_sources):
		return []
	if set(expected_targets) != set(actual_targets):
		return []
	if not _matches_multiplier(actual_sources, expected_sources, 1):
		return []
	if not _matches_multiplier(actual_targets, expected_targets, 1):
		return []
	return [rule["name"] for rule in applicable_rules]


def _get_applicable_rules(actual_targets, rules):
	actual_keys = set(actual_targets)
	return [
		rule for rule in rules
		if rule["targets"] and set(rule["targets"]).issubset(actual_keys)
	]


def _merge_quantities(total, quantities, multiplier):
	for key, qty in quantities.items():
		total[key] = total.get(key, 0) + (flt(qty) * multiplier)


def _get_rule_stock_entry_type(doc):
	stock_entry_type = doc.get("stock_entry_type")
	if stock_entry_type in SUPPORTED_STOCK_ENTRY_TYPES:
		return stock_entry_type
	return None


def _get_stock_entry_quantities(doc):
	sources = {}
	targets = {}
	for row in doc.get("items") or []:
		key = (row.get("item_code"), row.get("uom"))
		qty = flt(row.get("qty"))
		if row.get("s_warehouse"):
			sources[key] = sources.get(key, 0) + qty
		if row.get("t_warehouse"):
			targets[key] = targets.get(key, 0) + qty
	return sources, targets


def _get_repack_rules():
	return _get_repack_production_rules("Repack")


def _get_repack_production_rules(rule_type):
	rule_rows = frappe.get_all(
		"Repack Production Rule",
		filters={"type": rule_type},
		fields=["name"],
		limit_page_length=0
	)
	rule_names = [row.name for row in rule_rows]
	if not rule_names:
		return []

	source_rows = frappe.get_all(
		"Source Item",
		filters={"parent": ["in", rule_names], "parentfield": "from_item"},
		fields=["parent", "item_code", "uom", "qty"],
		limit_page_length=0
	)
	target_rows = frappe.get_all(
		"Target Item",
		filters={"parent": ["in", rule_names], "parentfield": "to_item"},
		fields=["parent", "item_code", "uom", "qty"],
		limit_page_length=0
	)

	rules_by_name = {}
	for rule_name in rule_names:
		rules_by_name[rule_name] = {
			"name": rule_name,
			"sources": {},
			"targets": {}
		}

	for row in source_rows:
		_add_quantity(rules_by_name[row.parent]["sources"], row.item_code, row.uom, row.qty)
	for row in target_rows:
		_add_quantity(rules_by_name[row.parent]["targets"], row.item_code, row.uom, row.qty)

	return [
		rule for rule in rules_by_name.values()
		if rule["sources"] and rule["targets"]
	]


def _add_quantity(quantities, item_code, uom, qty):
	key = (item_code, uom)
	quantities[key] = quantities.get(key, 0) + flt(qty)


def _matches_multiplier(actual, configured, multiplier):
	for key, rule_qty in configured.items():
		if flt(rule_qty) <= 0:
			return False
		if not _quantities_equal(actual[key], flt(rule_qty) * multiplier):
			return False
	return True


def _quantities_equal(first, second):
	allowed_difference = max(
		QUANTITY_TOLERANCE,
		abs(flt(second)) * QUANTITY_TOLERANCE
	)
	return abs(flt(first) - flt(second)) <= allowed_difference


def _build_mismatch_message(actual_sources, actual_targets, candidates):
	sections = []

	for rule in candidates:
		rule_link = frappe.utils.get_link_to_form(
			"Repack Production Rule", rule["name"], rule["name"])
		actual_rule_sources = dict(
			(key, actual_sources[key]) for key in rule["sources"] if key in actual_sources)
		actual_rule_targets = dict(
			(key, actual_targets[key]) for key in rule["targets"] if key in actual_targets)
		expected_sources = rule["sources"]
		expected_targets = rule["targets"]
		multiplier = _get_whole_multiplier(actual_rule_sources, rule["sources"])
		if not multiplier:
			multiplier = _get_nearest_multiplier(actual_rule_targets, rule["targets"])
		if multiplier:
			expected_sources = _multiply_quantities(rule["sources"], multiplier)
			expected_targets = _multiply_quantities(rule["targets"], multiplier)

		sections.append(_(
			"<b>Applicable rule:</b> {0}<br>"
			"<b>Required quantities:</b><br>Source: {1}<br>Target: {2}<br>"
			"<b>Problem:</b> {3}"
		).format(
			rule_link,
			_format_items(expected_sources),
			_format_items(expected_targets),
			_describe_mismatch(actual_rule_sources, actual_rule_targets,
				expected_sources, expected_targets)
		))

	return "<br><br>".join(sections)


def _get_whole_multiplier(actual, configured):
	if set(actual) != set(configured) or not configured:
		return None

	multiplier = None
	for key, configured_qty in configured.items():
		if flt(configured_qty) <= 0:
			return None
		current_multiplier = flt(actual[key]) / flt(configured_qty)
		if multiplier is None:
			multiplier = current_multiplier
		elif not _quantities_equal(current_multiplier, multiplier):
			return None

	whole_multiplier = round(multiplier)
	if whole_multiplier < 1 or not _quantities_equal(multiplier, whole_multiplier):
		return None
	return whole_multiplier


def _multiply_quantities(quantities, multiplier):
	return dict((key, flt(qty) * multiplier) for key, qty in quantities.items())


def _get_nearest_multiplier(actual, configured):
	if set(actual) != set(configured) or not configured:
		return 1
	first_key = next(iter(configured))
	if flt(configured[first_key]) <= 0:
		return 1
	return max(1, round(flt(actual[first_key]) / flt(configured[first_key])))


def _describe_mismatch(actual_sources, actual_targets, expected_sources, expected_targets):
	problems = []
	if set(actual_sources) != set(expected_sources):
		problems.append(_("The source item or UOM does not match the rule."))
	else:
		problems.extend(_quantity_problems("Source", actual_sources, expected_sources))

	if set(actual_targets) != set(expected_targets):
		problems.append(_("The target item or UOM does not match the rule."))
	else:
		problems.extend(_quantity_problems("Target", actual_targets, expected_targets))

	return "<br>".join(problems) or _(
		"The source and target quantities are not the same whole-number rule multiple."
	)


def _quantity_problems(label, actual, expected):
	problems = []
	for key in expected:
		if not _quantities_equal(actual[key], expected[key]):
			problems.append(_(
				"{0} quantity for {1} is {2} {3}; it must be {4} {3}."
			).format(label, key[0], flt(actual[key]), key[1] or "", flt(expected[key])))
	return problems


def _format_items(quantities):
	return "<br>".join([
		_("&bull; {0}: {1} {2}").format(key[0], flt(quantities[key]), key[1] or "")
		for key in sorted(quantities, key=lambda value: (value[0] or "", value[1] or ""))
	])
