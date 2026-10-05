# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import json

import frappe
from frappe.utils import flt


RULE_FIELDS = [
	"name",
	"price_or_product_discount",
	"rate_or_discount",
	"rate",
	"discount_amount",
	"discount_percentage",
	"mixed_conditions",
	"is_cumulative",
	"apply_on",
	"applicable_for",
	"min_qty",
	"max_qty",
	"min_amt",
	"max_amt"
]


def set_discount_calculation_details(doc, method=None):
	"""Store an informational breakdown of discounts already calculated by ERPNext."""
	if doc.get("doctype") != "Quotation":
		return

	items = doc.get("items") or []
	item_rule_names = {}
	all_rule_names = []
	for item in items:
		rule_names = _parse_pricing_rules(item.get("pricing_rules"))
		item_rule_names[id(item)] = rule_names
		for rule_name in rule_names:
			if rule_name not in all_rule_names:
				all_rule_names.append(rule_name)

	rules_by_name = {}
	if all_rule_names:
		rules = frappe.get_all(
			"Pricing Rule",
			filters={"name": ["in", all_rule_names]},
			fields=RULE_FIELDS
		)
		rules_by_name = dict((rule.get("name"), rule) for rule in rules)

	rule_contexts = _get_rule_contexts(items, item_rule_names)
	doc.set("discount_calculation_details", [])

	for item in items:
		rule_names = item_rule_names.get(id(item), [])
		special_discount = _percentage_reduction(
			item.get("regular_price_list_rate"),
			item.get("price_list_rate")
		)
		if not rule_names and special_discount <= 0:
			continue

		pricing_rule_discount = _get_pricing_rule_discount(item, rule_names)
		explanation = _build_explanation(
			doc,
			item,
			rule_names,
			rules_by_name,
			rule_contexts,
			special_discount,
			pricing_rule_discount
		)
		doc.append("discount_calculation_details", {
			"item_code": item.get("item_code"),
			"qty": flt(item.get("qty"), 3),
			"special_price_list_discount": special_discount,
			"pricing_rule_discount": pricing_rule_discount,
			"explanation": explanation
		})


def _parse_pricing_rules(value):
	if not value:
		return []
	if isinstance(value, (list, tuple)):
		return [rule for rule in value if rule]

	try:
		parsed = json.loads(value)
		if isinstance(parsed, list):
			return [rule for rule in parsed if rule]
	except (TypeError, ValueError):
		pass

	return [rule.strip() for rule in value.split(",") if rule.strip()]


def _percentage_reduction(original_rate, reduced_rate):
	original_rate = flt(original_rate)
	reduced_rate = flt(reduced_rate)
	if original_rate <= 0 or reduced_rate >= original_rate:
		return 0
	return flt((original_rate - reduced_rate) * 100 / original_rate, 3)


def _get_pricing_rule_discount(item, rule_names):
	if not rule_names:
		return 0

	discount_percentage = flt(item.get("discount_percentage"))
	if discount_percentage > 0:
		return flt(discount_percentage, 3)

	return _percentage_reduction(item.get("price_list_rate"), item.get("rate"))


def _get_rule_contexts(items, item_rule_names):
	contexts = {}
	for item in items:
		for rule_name in item_rule_names.get(id(item), []):
			context = contexts.setdefault(rule_name, {
				"quantity": 0,
				"item_codes": []
			})
			context["quantity"] += flt(item.get("qty"))
			item_code = item.get("item_code")
			if item_code and item_code not in context["item_codes"]:
				context["item_codes"].append(item_code)
	return contexts


def _build_explanation(
	doc,
	item,
	rule_names,
	rules_by_name,
	rule_contexts,
	special_discount,
	pricing_rule_discount
):
	parts = []
	if special_discount > 0:
		parts.append(
			'Price List "{0}" reduced the regular unit price by {1}%.'.format(
				doc.get("selling_price_list") or "Selected Price List",
				_format_number(special_discount)
			)
		)

	for rule_name in rule_names:
		rule = rules_by_name.get(rule_name)
		parts.append(_describe_rule(
			doc,
			item,
			rule_name,
			rule,
			rule_contexts,
			pricing_rule_discount,
			special_discount > 0
		))

	if special_discount > 0 and rule_names:
		combined_discount = _percentage_reduction(
			item.get("regular_price_list_rate"),
			item.get("rate")
		)
		if combined_discount > 0:
			parts.append(
				"The combined effective discount is {0}%.".format(
					_format_number(combined_discount)
				)
			)

	return " ".join(parts)


def _describe_rule(
	doc,
	item,
	rule_name,
	rule,
	rule_contexts,
	effective_discount,
	has_prior_discount
):
	if not rule:
		return 'Pricing Rule "{0}" {1}{2}% discount{3}.'.format(
			rule_name,
			"then applied a " if has_prior_discount else "applied a ",
			_format_number(effective_discount),
			" to the reduced price" if has_prior_discount else ""
		)

	if rule.get("price_or_product_discount") == "Product":
		adjustment = "applied a promotional product offer"
	elif rule.get("rate_or_discount") == "Rate":
		adjustment = "set the unit price to {0} {1}".format(
			doc.get("currency") or "",
			_format_number(rule.get("rate"))
		).replace("  ", " ").strip()
	elif rule.get("rate_or_discount") == "Discount Amount":
		adjustment = "applied a discount of {0} {1} per {2}".format(
			doc.get("currency") or "",
			_format_number(rule.get("discount_amount")),
			item.get("uom") or "unit"
		).replace("  ", " ").strip()
	else:
		discount = effective_discount or flt(rule.get("discount_percentage"), 3)
		adjustment = "{0}a {1}% discount{2}".format(
			"then applied " if has_prior_discount else "applied ",
			_format_number(discount),
			" to the reduced price" if has_prior_discount else ""
		)

	reason = _get_rule_reason(doc, item, rule_name, rule, rule_contexts)
	return 'Pricing Rule "{0}" {1}{2}.'.format(rule_name, adjustment, reason)


def _get_rule_reason(doc, item, rule_name, rule, rule_contexts):
	has_quantity_condition = flt(rule.get("min_qty")) or flt(rule.get("max_qty"))
	has_amount_condition = flt(rule.get("min_amt")) or flt(rule.get("max_amt"))

	if rule.get("is_cumulative") and has_quantity_condition:
		return " because the applicable cumulative quantity threshold was reached"
	if rule.get("mixed_conditions") and has_quantity_condition:
		context = rule_contexts.get(rule_name) or {}
		quantity = context.get("quantity", 0)
		item_codes = _join_item_codes(context.get("item_codes") or [])
		return " because the combined quantity of {0} was {1} {2}{3}".format(
			item_codes or "qualifying items",
			_format_number(quantity),
			_plural_uom(item.get("uom"), quantity),
			_get_tier_text(rule, item.get("uom"))
		)
	if rule.get("apply_on") == "Transaction" and has_quantity_condition:
		quantity = sum(flt(row.get("qty")) for row in (doc.get("items") or []))
		return " because the total order quantity was {0} units{1}".format(
			_format_number(quantity),
			_get_tier_text(rule, "unit")
		)
	if has_quantity_condition:
		quantity = flt(item.get("qty"))
		return " because the ordered quantity was {0} {1}{2}".format(
			_format_number(quantity),
			_plural_uom(item.get("uom"), quantity),
			_get_tier_text(rule, item.get("uom"))
		)
	if has_amount_condition:
		return " because the applicable order-value threshold was reached"
	if rule.get("applicable_for") in ("Customer", "Customer Group", "Territory"):
		return " for the applicable customer pricing terms"
	return " under the applicable pricing terms"


def _get_tier_text(rule, uom):
	minimum = flt(rule.get("min_qty"))
	maximum = flt(rule.get("max_qty"))
	unit = uom or "unit"

	if minimum and maximum and minimum == maximum:
		return ", meeting the required quantity of {0} {1}".format(
			_format_number(minimum),
			_plural_uom(unit, minimum)
		)
	if minimum and maximum:
		return ", falling within the {0}–{1} {2} tier".format(
			_format_number(minimum),
			_format_number(maximum),
			unit
		)
	if minimum:
		return ", meeting the minimum tier of {0} {1} or more".format(
			_format_number(minimum),
			_plural_uom(unit, minimum)
		)
	if maximum:
		return ", falling within the tier of up to {0} {1}".format(
			_format_number(maximum),
			_plural_uom(unit, maximum)
		)
	return ""


def _join_item_codes(item_codes):
	if len(item_codes) < 2:
		return "".join(item_codes)
	if len(item_codes) == 2:
		return "{0} and {1}".format(item_codes[0], item_codes[1])
	return "{0}, and {1}".format(", ".join(item_codes[:-1]), item_codes[-1])


def _plural_uom(uom, quantity):
	uom = uom or "unit"
	if flt(quantity) == 1:
		return uom
	if uom == "Each":
		return "units"
	if uom.endswith("s"):
		return uom
	return "{0}s".format(uom)


def _format_number(value):
	value = flt(value, 3)
	if value == int(value):
		return "{0:,}".format(int(value))
	return ("{0:,.3f}".format(value)).rstrip("0").rstrip(".")
