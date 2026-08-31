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
	candidate_matches = _get_candidate_matches(actual_sources, actual_targets, rules)
	if not candidate_matches:
		return []

	return _find_exact_rule_combination(
		candidate_matches, actual_sources, actual_targets)


def _get_candidate_matches(actual_sources, actual_targets, rules):
	candidate_matches = []
	for rule in _get_applicable_rules(actual_targets, rules):
		actual_rule_targets = dict(
			(key, actual_targets[key]) for key in rule["targets"])
		multiplier = _get_whole_multiplier(actual_rule_targets, rule["targets"])
		if not multiplier:
			continue

		expected_sources = _multiply_quantities(rule["sources"], multiplier)
		expected_targets = _multiply_quantities(rule["targets"], multiplier)
		if not _quantities_fit(expected_sources, actual_sources):
			continue
		if not _quantities_fit(expected_targets, actual_targets):
			continue

		candidate_matches.append({
			"name": rule["name"],
			"sources": expected_sources,
			"targets": expected_targets
		})
	return candidate_matches


def _find_exact_rule_combination(candidate_matches, actual_sources, actual_targets):
	return _find_exact_rule_combination_from_index(
		candidate_matches, 0, {}, {}, [], actual_sources, actual_targets)


def _find_exact_rule_combination_from_index(candidate_matches, index,
		current_sources, current_targets, current_rule_names,
		actual_sources, actual_targets):
	if _quantities_match(current_sources, actual_sources) and \
			_quantities_match(current_targets, actual_targets):
		return current_rule_names
	if index >= len(candidate_matches):
		return []

	for candidate_index in range(index, len(candidate_matches)):
		candidate = candidate_matches[candidate_index]
		next_sources = dict(current_sources)
		next_targets = dict(current_targets)
		_merge_quantities(next_sources, candidate["sources"], 1)
		_merge_quantities(next_targets, candidate["targets"], 1)

		if not _quantities_fit(next_sources, actual_sources):
			continue
		if not _quantities_fit(next_targets, actual_targets):
			continue

		matched = _find_exact_rule_combination_from_index(
			candidate_matches, candidate_index + 1, next_sources, next_targets,
			current_rule_names + [candidate["name"]], actual_sources, actual_targets)
		if matched:
			return matched

	return []


def _get_applicable_rules(actual_targets, rules):
	actual_keys = set(actual_targets)
	return [
		rule for rule in rules
		if rule["targets"] and set(rule["targets"]).issubset(actual_keys)
	]


def _merge_quantities(total, quantities, multiplier):
	for key, qty in quantities.items():
		total[key] = total.get(key, 0) + (flt(qty) * multiplier)


def _quantities_fit(expected, actual):
	for key, expected_qty in expected.items():
		if key not in actual:
			return False
		if flt(expected_qty) - flt(actual[key]) > _allowed_difference(actual[key]):
			return False
	return True


def _quantities_match(expected, actual):
	if set(expected) != set(actual):
		return False
	for key, actual_qty in actual.items():
		if not _quantities_equal(expected[key], actual_qty):
			return False
	return True


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
	return abs(flt(first) - flt(second)) <= _allowed_difference(second)


def _allowed_difference(qty):
	return max(QUANTITY_TOLERANCE, abs(flt(qty)) * QUANTITY_TOLERANCE)


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
