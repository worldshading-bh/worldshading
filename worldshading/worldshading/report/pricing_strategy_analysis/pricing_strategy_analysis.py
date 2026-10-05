from __future__ import unicode_literals

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
import hashlib
import json

import frappe
from frappe.utils import cint, escape_html, getdate, gzip_decompress

from worldshading.api.pricing_update_notifications import create_pricing_update_note
from worldshading.reporting.item_wise_sales import get_item_sales_aggregates
from worldshading.worldshading.doctype.pricing_group.pricing_group import (
	get_pricing_group_configuration,
)


MONEY_QUANTUM = Decimal("0.001")
PERCENT_QUANTUM = Decimal("0.001")
RATIO_QUANTUM = Decimal("0.000001")
INDIRECT_EXPENSE_ACCOUNT = "Indirect Expenses - WS"
ITEM_PRICE_UPDATE_LIMIT = 50
PRICING_RULE_UPDATE_LIMIT = 50

COST_SOURCES = (
	"Current Valuation Rate",
	"Latest Valuation Rate"
)
COST_SOURCE_ALIASES = {"Latest Purchase Rate": "Latest Valuation Rate"}


def _normalize_update_item_codes(item_codes):
	item_codes = frappe.parse_json(item_codes) if isinstance(item_codes, str) else item_codes
	result = []
	seen = set()
	for value in item_codes or []:
		item_code = value.get("item_code") if isinstance(value, dict) else value
		item_code = str(item_code or "").strip()
		if not item_code or item_code in seen:
			continue
		seen.add(item_code)
		result.append(item_code)
		if len(result) == ITEM_PRICE_UPDATE_LIMIT:
			break
	return result


def _pricing_rule_title(rule_set_name, tier_index, item_code=None, group_index=None):
	suffix = " - Tier {0}".format(tier_index)
	if item_code:
		suffix = " - {0}{1}".format(item_code, suffix)
	if group_index is not None:
		suffix += " - Group {0}".format(group_index)
	prefix = "PSA - "
	rule_set = str(rule_set_name or "Selected Items").strip()
	return "{0}{1}{2}".format(prefix, rule_set[:140 - len(prefix) - len(suffix)].rstrip(), suffix)


def _default_pricing_rule_set_name(prepared_report):
	filters = prepared_report.filters or {}
	return str(filters.get("pricing_group") or filters.get("item_group")
		or filters.get("brand") or filters.get("item")
		or "Selected Items").strip()


def _normalize_pricing_rule_mode(rule_mode):
	rule_mode = str(rule_mode or "combined").strip().lower()
	if rule_mode not in ("combined", "separate", "same_discount"):
		frappe.throw("Select a valid Pricing Rule creation mode")
	return rule_mode


def _legacy_pricing_rule_title(pricing_strategy, tier_index):
	identity = "{0}|{1}".format(pricing_strategy, tier_index)
	digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
	prefix = "PSA {0} Tier {1}".format(pricing_strategy, tier_index)
	return "{0} {1}".format(prefix[:126].rstrip(), digest)


def _build_pricing_rule_specs(prepared_report, item_codes, rows_by_item, items, currency,
		rule_mode="combined", rule_set_name=None, mixed_conditions=0):
	tiers = prepared_report.filters.get("tiers") or []
	if not tiers:
		frappe.throw("The saved Prepared Report has no quantity pricing tiers")
	strategy = prepared_report.filters.get("pricing_strategy") or "Legacy Strategy"
	rule_mode = _normalize_pricing_rule_mode(rule_mode)
	rule_set_name = str(rule_set_name or _default_pricing_rule_set_name(prepared_report)).strip()
	if not rule_set_name:
		frappe.throw("Rule Set Name is required")
	mixed_conditions = cint(mixed_conditions) if rule_mode != "separate" else 0
	selected_items = []
	for item_code in item_codes:
		row = rows_by_item.get(item_code)
		item = items.get(item_code)
		if not row or not item:
			frappe.throw("The Pricing Rule update no longer matches the Prepared Report")
		selected_items.append({"item_code": item_code, "uom": item.stock_uom})
	def make_spec(tier_index, tier, discount, spec_items, item_code=None, group_index=None):
		discount = quantize_percent(discount)
		return {
			"title": _pricing_rule_title(rule_set_name, tier_index, item_code, group_index),
			"legacy_title": [
				_pricing_rule_title(strategy, tier_index),
				_legacy_pricing_rule_title(strategy, tier_index)
			] if rule_mode == "combined" else [],
			"rule_key": "{0}|{1}|{2}".format(tier_index, item_code or "", group_index or ""),
			"tier_index": tier_index,
				"minimum_qty": to_decimal(tier.get("minimum")),
				"maximum_qty": None if tier.get("maximum") is None
					else to_decimal(tier.get("maximum")),
			"discount_percentage": discount,
			"items": list(spec_items),
			"currency": currency,
			"company": prepared_report.filters.get("company"),
			"pricing_strategy": strategy,
			"rule_set_name": rule_set_name,
			"rule_mode": rule_mode,
			"mixed_conditions": mixed_conditions
		}

	specs = []
	if rule_mode == "separate":
		for item in selected_items:
			for tier_index, tier in enumerate(tiers, 1):
				value = rows_by_item[item["item_code"]].get(
					"tier_{0}_discount_percent".format(tier_index))
				if value is None:
					frappe.throw("{0} has no valid Tier {1} discount".format(
						item["item_code"], tier_index))
				specs.append(make_spec(tier_index, tier, value, [item], item["item_code"]))
	elif rule_mode == "same_discount":
		for tier_index, tier in enumerate(tiers, 1):
			groups = {}
			for item in selected_items:
				value = rows_by_item[item["item_code"]].get(
					"tier_{0}_discount_percent".format(tier_index))
				if value is None:
					frappe.throw("{0} has no valid Tier {1} discount".format(
						item["item_code"], tier_index))
				discount = quantize_percent(value)
				groups.setdefault(discount, []).append(item)
			for group_index, discount in enumerate(sorted(groups), 1):
				specs.append(make_spec(
					tier_index, tier, discount, groups[discount], group_index=group_index
				))
	else:
		for tier_index, tier in enumerate(tiers, 1):
			discounts = []
			for item_code in item_codes:
				value = rows_by_item[item_code].get("tier_{0}_discount_percent".format(tier_index))
				if value is None:
					frappe.throw("{0} has no valid Tier {1} discount".format(item_code, tier_index))
				discounts.append(to_decimal(value))
			discount = sum(discounts, Decimal("0")) / Decimal(len(discounts))
			specs.append(make_spec(tier_index, tier, discount, selected_items))
	return specs


def _build_pricing_rule_specs_with_groups(prepared_report, item_codes, rows_by_item, items,
		currency, rule_mode="combined", rule_set_name=None, mixed_conditions=0):
	grouped = {}
	ungrouped = []
	for item_code in item_codes:
		group_name = (rows_by_item.get(item_code) or {}).get("pricing_group")
		if group_name:
			grouped.setdefault(group_name, []).append(item_code)
		else:
			ungrouped.append(item_code)

	specs = []
	tiers = prepared_report.filters.get("tiers") or []
	for group_name in sorted(grouped):
		group_codes = grouped[group_name]
		expected_codes = sorted(
			code for code, row in rows_by_item.items()
			if row.get("pricing_group") == group_name
		)
		status = rows_by_item[group_codes[0]].get("pricing_group_status")
		if sorted(group_codes) != expected_codes or status not in (
				"Ready", "Different Current Prices"):
			frappe.throw("Pricing Group {0} is not complete and updateable".format(group_name))
		spec_items = [
			{"item_code": code, "uom": items[code].stock_uom} for code in group_codes
		]
		reference_field = "group_recommended_b2b_net" \
			if prepared_report.filters.get("b2b_price_list") else "group_recommended_regular_net"
		reference_price = rows_by_item[group_codes[0]].get(reference_field)
		if not _valid_group_price(reference_price):
			frappe.throw("Pricing Group {0} has no valid reference price".format(group_name))
		for tier_index, tier in enumerate(tiers, 1):
			tier_price = rows_by_item[group_codes[0]].get(
				"group_tier_{0}_net".format(tier_index)
			)
			if not _valid_group_price(tier_price):
				frappe.throw("Pricing Group {0} has no valid Tier {1} price".format(
					group_name, tier_index
				))
			discount = _percentage_difference(reference_price, tier_price)
			specs.append({
				"title": _pricing_rule_title(group_name, tier_index),
				"legacy_title": [],
				"rule_key": "pricing_group|{0}|{1}".format(group_name, tier_index),
				"tier_index": tier_index,
				"minimum_qty": to_decimal(tier.get("minimum")),
				"maximum_qty": None if tier.get("maximum") is None
					else to_decimal(tier.get("maximum")),
				"discount_percentage": quantize_percent(discount),
				"items": spec_items,
				"currency": currency,
				"company": prepared_report.filters.get("company"),
				"pricing_strategy": prepared_report.filters.get("pricing_strategy")
					or "Legacy Strategy",
				"rule_set_name": group_name,
				"rule_mode": "pricing_group",
				"mixed_conditions": cint(mixed_conditions)
			})

	if ungrouped:
		specs.extend(_build_pricing_rule_specs(
			prepared_report, ungrouped, rows_by_item, items, currency,
			rule_mode, rule_set_name, mixed_conditions
		))
	return specs


def _apply_pricing_rule_spec(doc, spec, prepared_report_name):
	doc.title = spec["title"]
	doc.apply_on = "Item Code"
	doc.price_or_product_discount = "Price"
	doc.selling = 1
	doc.buying = 0
	doc.company = spec["company"]
	doc.currency = spec["currency"]
	doc.min_qty = spec["minimum_qty"]
	doc.max_qty = spec["maximum_qty"]
	doc.rate_or_discount = "Discount Percentage"
	doc.discount_percentage = spec["discount_percentage"]
	doc.mixed_conditions = cint(spec.get("mixed_conditions"))
	doc.for_price_list = ""
	doc.disable = 0
	doc.rule_description = (
		"[Pricing Strategy Analysis] Rule Set: {0}; Mode: {1}; Strategy: {2}; "
		"Tier: {3}; Prepared Report: {4}"
	).format(spec.get("rule_set_name") or "Selected Items", spec.get("rule_mode") or "combined",
		spec["pricing_strategy"], spec["tier_index"], prepared_report_name)
	doc.set("items", [])
	for item in spec["items"]:
		doc.append("items", item)
	if doc.meta.has_field("pricing_prepared_report"):
		doc.pricing_prepared_report = prepared_report_name


def _pricing_rule_preview_cache_key(user, token):
	return "pricing-strategy-pricing-rule-preview:{0}:{1}".format(user, token)


def _get_pricing_rule_target(title, legacy_title=None):
	target_name = title if frappe.db.exists("Pricing Rule", title) else None
	legacy_titles = legacy_title if isinstance(legacy_title, (list, tuple)) else [legacy_title]
	for old_title in legacy_titles:
		if not target_name and old_title and frappe.db.exists("Pricing Rule", old_title):
			target_name = old_title
			break
	if not target_name:
		return None
	doc = frappe.get_doc("Pricing Rule", target_name)
	doc.check_permission("read")
	if not (doc.rule_description or "").startswith("[Pricing Strategy Analysis]"):
		frappe.throw("Pricing Rule title is already used by a rule outside this workflow: {0}".format(title))
	items = doc.get("items") or []
	return {
		"name": doc.name,
		"modified": str(doc.modified or ""),
		"discount_percentage": quantize_percent(doc.discount_percentage),
		"minimum_qty": to_decimal(doc.min_qty),
		"maximum_qty": None if doc.max_qty in (None, "", 0) else to_decimal(doc.max_qty),
		"items": sorted((row.item_code, row.uom or "") for row in items),
		"disable": cint(doc.disable),
		"mixed_conditions": cint(doc.mixed_conditions)
	}


def _pricing_rule_target_matches(target, spec):
	return bool(target) and target["discount_percentage"] == spec["discount_percentage"] \
		and target["minimum_qty"] == spec["minimum_qty"] \
		and target["maximum_qty"] == spec["maximum_qty"] \
		and target["items"] == sorted(
			(item["item_code"], item.get("uom") or "") for item in spec["items"]
		) \
		and target.get("mixed_conditions", 0) == cint(spec.get("mixed_conditions")) \
		and not target["disable"]


def _ranges_overlap(first_minimum, first_maximum, second_minimum, second_maximum):
	first_maximum = first_maximum if first_maximum is not None else Decimal("Infinity")
	second_maximum = second_maximum if second_maximum is not None else Decimal("Infinity")
	return first_minimum <= second_maximum and second_minimum <= first_maximum


def _find_pricing_rule_conflicts(specs):
	item_codes = sorted(set(
		item["item_code"] for spec in specs for item in spec["items"]
	))
	if not item_codes:
		return []
	children = frappe.get_all(
		"Pricing Rule Item Code", filters={"item_code": ["in", item_codes]},
		fields=["parent", "item_code"], limit_page_length=0
	)
	items_by_rule = {}
	for child in children:
		items_by_rule.setdefault(child.parent, set()).add(child.item_code)
	parents = list(items_by_rule)
	if not parents:
		return []
	rules = frappe.get_all(
		"Pricing Rule",
		filters={"name": ["in", parents], "disable": 0, "selling": 1, "apply_on": "Item Code"},
		fields=[
			"name", "company", "price_or_product_discount", "min_qty", "max_qty",
			"applicable_for"
		], limit_page_length=0
	)
	target_titles = set()
	for spec in specs:
		target_titles.add(spec["title"])
		for legacy_title in spec.get("legacy_title") or []:
			target_titles.add(legacy_title)
	conflicts = []
	for spec in specs:
		spec_item_codes = set(item["item_code"] for item in spec["items"])
		for rule in rules:
			common_items = spec_item_codes.intersection(items_by_rule.get(rule.name, set()))
			if rule.name in target_titles or not common_items:
				continue
			if rule.company and rule.company != spec["company"]:
				continue
			if rule.price_or_product_discount != "Price" or rule.applicable_for:
				continue
			rule_minimum = to_decimal(rule.min_qty)
			rule_maximum = None if rule.max_qty in (None, "", 0) else to_decimal(rule.max_qty)
			if _ranges_overlap(
				spec["minimum_qty"], spec["maximum_qty"], rule_minimum, rule_maximum
			):
				conflicts.append("{0} conflicts with {1}".format(
					", ".join(sorted(common_items)), rule.name
				))
	return sorted(set(conflicts))


def _legacy_preview_pricing_rule_update(prepared_report_name=None, item_codes=None):
	prepared_report = _get_prepared_pricing_report(prepared_report_name)
	raw_item_codes = frappe.parse_json(item_codes) if isinstance(item_codes, str) else item_codes
	normalized_item_codes = _normalize_update_item_codes(raw_item_codes)
	if not normalized_item_codes:
		frappe.throw("There are no report Items available for Pricing Rule update")
	if not frappe.has_permission("Pricing Rule", "read"):
		frappe.throw("You do not have permission to preview Pricing Rules", frappe.PermissionError)
	prepared_rows = _get_prepared_pricing_rows(prepared_report.name)
	rows_by_item = {row.get("item_code"): row for row in prepared_rows if row.get("item_code")}
	missing = [item_code for item_code in normalized_item_codes if item_code not in rows_by_item]
	if missing:
		frappe.throw("These Items are not present in the saved Prepared Report: {0}".format(
			", ".join(missing)
		))
	items = _get_update_items(normalized_item_codes)
	currency = frappe.db.get_value("Company", prepared_report.filters.get("company"), "default_currency")
	if not currency:
		frappe.throw("Company currency is required for Pricing Rule update")
	specs = _build_pricing_rule_specs(
		prepared_report, normalized_item_codes, rows_by_item, items, currency
	)
	conflicts = _find_pricing_rule_conflicts(specs)
	if conflicts:
		frappe.throw("Conflicting active Pricing Rules must be resolved first: {0}".format(
			"; ".join(conflicts)
		))
	entries = []
	counts = {"create": 0, "update": 0, "unchanged": 0}
	for spec in specs:
		target = _get_pricing_rule_target(spec["title"], spec.get("legacy_title"))
		action = "Create" if target is None else (
			"Unchanged" if _pricing_rule_target_matches(target, spec) else "Update"
		)
		counts[action.lower()] += 1
		entry = dict(spec)
		entry.update({
			"action": action,
			"pricing_rule_name": target["name"] if target else None,
			"target_modified": target["modified"] if target else None,
			"current_rate": float(target["rate"]) if target else None,
			"rate": float(spec["rate"]),
			"minimum_qty": float(spec["minimum_qty"]),
			"maximum_qty": float(spec["maximum_qty"]) if spec["maximum_qty"] is not None else None
		})
		entries.append(entry)
	token = frappe.generate_hash(length=32)
	frappe.cache().set_value(
		_pricing_rule_preview_cache_key(frappe.session.user, token),
		{"prepared_report": prepared_report.name, "user": frappe.session.user, "entries": entries},
		expires_in_sec=600
	)
	return {
		"token": token, "prepared_report": prepared_report.name, "entries": entries,
		"counts": counts, "requested_item_count": len(normalized_item_codes),
		"limited_to_first_50": len(raw_item_codes or []) > PRICING_RULE_UPDATE_LIMIT
	}


def _legacy_execute_pricing_rule_update(preview_token=None):
	preview_token = str(preview_token or "").strip()
	cache = frappe.cache()
	cache_key = _pricing_rule_preview_cache_key(frappe.session.user, preview_token)
	payload = cache.get_value(cache_key) if preview_token else None
	payload = frappe.parse_json(payload) if isinstance(payload, str) else payload
	if not isinstance(payload, dict) or payload.get("user") != frappe.session.user:
		frappe.throw("The Pricing Rule update preview is invalid or expired")
	prepared_report = _get_prepared_pricing_report(payload.get("prepared_report"))
	entries = payload.get("entries") or []
	item_codes = _normalize_update_item_codes([entry.get("item_code") for entry in entries])
	prepared_rows = _get_prepared_pricing_rows(prepared_report.name)
	rows_by_item = {row.get("item_code"): row for row in prepared_rows if row.get("item_code")}
	items = _get_update_items(item_codes)
	currency = frappe.db.get_value("Company", prepared_report.filters.get("company"), "default_currency")
	specs = _build_pricing_rule_specs(prepared_report, item_codes, rows_by_item, items, currency)
	if len(entries) != len(specs):
		frappe.throw("The Pricing Rule update preview no longer matches the Prepared Report")
	conflicts = _find_pricing_rule_conflicts(specs)
	if conflicts:
		frappe.throw("Conflicting active Pricing Rules must be resolved first: {0}".format(
			"; ".join(conflicts)
		))
	if any(entry.get("action") == "Create" for entry in entries) \
			and not frappe.has_permission("Pricing Rule", "create"):
		frappe.throw("You do not have permission to create Pricing Rules", frappe.PermissionError)
	created = updated = unchanged = 0
	affected = []
	for entry, spec in zip(entries, specs):
		if entry.get("title") != spec["title"] or quantize_money(entry.get("rate")) != spec["rate"]:
			frappe.throw("The recommended Pricing Rule changed after preview")
		target = _get_pricing_rule_target(spec["title"])
		expected_action = "Create" if target is None else (
			"Unchanged" if _pricing_rule_target_matches(target, spec) else "Update"
		)
		if entry.get("action") != expected_action or (target and target["modified"] != entry.get("target_modified")):
			frappe.throw("Pricing Rule changed after preview; preview again")
		if expected_action == "Unchanged":
			unchanged += 1
			continue
		if expected_action == "Create":
			doc = frappe.new_doc("Pricing Rule")
			_apply_pricing_rule_spec(doc, spec, prepared_report.name)
			doc.insert()
			created += 1
		else:
			doc = frappe.get_doc("Pricing Rule", target["name"])
			doc.check_permission("write")
			_apply_pricing_rule_spec(doc, spec, prepared_report.name)
			doc.save()
			updated += 1
		_add_pricing_rule_update_comment(doc, prepared_report.name, spec)
		affected.append(doc.name)
	cache.delete_value(cache_key)
	return {"prepared_report": prepared_report.name, "created": created,
		"updated": updated, "unchanged": unchanged, "pricing_rules": affected}


def _add_pricing_rule_update_comment(doc, prepared_report_name, spec):
	link = '<a href="#Form/Prepared Report/{0}">{1}</a>'.format(
		escape_html(prepared_report_name), escape_html(prepared_report_name)
	)
	doc.add_comment("Comment", (
		"<b>Pricing Strategy Rule Update</b><br>Prepared Report: {0}<br>"
		"Pricing Strategy: {1}<br>Quantity: {2} to {3}<br>Discount: {4}%"
	).format(link, escape_html(spec["pricing_strategy"]), spec["minimum_qty"],
		spec["maximum_qty"] if spec["maximum_qty"] is not None else "No limit",
		spec["discount_percentage"]))


def _get_bulk_pricing_rule_context(prepared_report, item_codes):
	prepared_rows = _get_prepared_pricing_rows(prepared_report.name)
	rows_by_item = {row.get("item_code"): row for row in prepared_rows if row.get("item_code")}
	missing = [item_code for item_code in item_codes if item_code not in rows_by_item]
	if missing:
		frappe.throw("These Items are not present in the saved Prepared Report: {0}".format(
			", ".join(missing)
		))
	items = _get_update_items(item_codes)
	currency = frappe.db.get_value("Company", prepared_report.filters.get("company"), "default_currency")
	if not currency:
		frappe.throw("Company currency is required for Pricing Rule update")
	return rows_by_item, items, currency


def _get_bulk_pricing_rule_summary(prepared_report, item_codes, rule_mode="combined",
		rule_set_name=None, mixed_conditions=0):
	rows_by_item, items, currency = _get_bulk_pricing_rule_context(prepared_report, item_codes)
	group_entries = [
		{"item_code": item_code, "group_key": rows_by_item[item_code].get("pricing_group")}
		for item_code in item_codes if rows_by_item[item_code].get("pricing_group")
	]
	validate_live_pricing_group_entries(group_entries, rows_by_item, items)
	specs = _build_pricing_rule_specs_with_groups(
		prepared_report, item_codes, rows_by_item, items, currency,
		rule_mode, rule_set_name, mixed_conditions
	)
	conflicts = _find_pricing_rule_conflicts(specs)
	if conflicts:
		frappe.throw("Conflicting active Pricing Rules must be resolved first: {0}".format(
			"; ".join(conflicts)
		))
	entries = []
	counts = {"create": 0, "update": 0, "unchanged": 0}
	for spec in specs:
		target = _get_pricing_rule_target(spec["title"], spec.get("legacy_title"))
		action = "Create" if target is None else (
			"Unchanged" if _pricing_rule_target_matches(target, spec) else "Update"
		)
		counts[action.lower()] += 1
		entries.append({
			"included": 1, "title": spec["title"], "rule_key": spec["rule_key"],
			"tier_index": spec["tier_index"], "item_count": len(spec["items"]),
			"minimum_qty": float(spec["minimum_qty"]),
			"maximum_qty": float(spec["maximum_qty"]) if spec["maximum_qty"] is not None else None,
			"suggested_average_discount": float(spec["discount_percentage"]),
			"final_discount_percentage": float(spec["discount_percentage"]),
			"current_discount_percentage": float(target["discount_percentage"]) if target else None,
			"action": action, "pricing_rule_name": target["name"] if target else None,
			"target_modified": target["modified"] if target else None
		})
	return specs, entries, counts


def _apply_final_tier_discounts(specs, provided):
	values = {}
	for row in provided or []:
		index = cint(row.get("tier_index")) if isinstance(row, dict) else 0
		key = str(row.get("rule_key") or index) if isinstance(row, dict) else ""
		value = to_decimal(row.get("final_discount_percentage")) \
			if isinstance(row, dict) else Decimal("-1")
		if key in values or value < 0 or value > 100:
			frappe.throw("Each final Tier Discount must be between 0 and 100")
		values[key] = quantize_percent(value)
	valid_keys = set(str(spec.get("rule_key") or spec["tier_index"]) for spec in specs)
	if not values or not set(values).issubset(valid_keys):
		frappe.throw("Select at least one valid quantity tier")
	specs[:] = [spec for spec in specs
		if str(spec.get("rule_key") or spec["tier_index"]) in values]
	for spec in specs:
		spec["discount_percentage"] = values[str(spec.get("rule_key") or spec["tier_index"])]


@frappe.whitelist()
def preview_bulk_pricing_rule_update(prepared_report_name=None, item_codes=None):
	prepared_report = _get_prepared_pricing_report(prepared_report_name)
	raw_item_codes = frappe.parse_json(item_codes) if isinstance(item_codes, str) else item_codes
	item_codes = _normalize_update_item_codes(raw_item_codes)
	if not item_codes:
		frappe.throw("There are no report Items available for Pricing Rule update")
	if not frappe.has_permission("Pricing Rule", "read"):
		frappe.throw("You do not have permission to preview Pricing Rules", frappe.PermissionError)
	rows_by_item, items, currency = _get_bulk_pricing_rule_context(prepared_report, item_codes)
	tiers = prepared_report.filters.get("tiers") or []
	if not tiers:
		frappe.throw("The saved Prepared Report has no quantity pricing tiers")
	classification = classify_updateable_pricing_groups(
		list(rows_by_item.values()), item_codes, PRICING_RULE_UPDATE_LIMIT
	)
	blocked_groups = classification["blocked_groups"]
	blocked_codes = set(
		item_code for item_code, row in rows_by_item.items()
		if row.get("pricing_group") in blocked_groups
	)
	item_codes = [item_code for item_code in item_codes if item_code not in blocked_codes]
	item_entries, eligible_item_codes, skipped = _build_pricing_rule_item_preview(
		item_codes, rows_by_item, items, prepared_report.filters
	)
	skipped.extend([
		{"pricing_group": group_name, "reason": reason}
		for group_name, reason in sorted(blocked_groups.items())
	])
	if not item_entries:
		frappe.throw("None of the selected Items has valid discounts for every quantity tier")
	token = frappe.generate_hash(length=32)
	frappe.cache().set_value(
		_pricing_rule_preview_cache_key(frappe.session.user, token),
		{"prepared_report": prepared_report.name, "user": frappe.session.user,
		 "eligible_item_codes": eligible_item_codes}, expires_in_sec=600
	)
	return {"token": token, "prepared_report": prepared_report.name,
		"items": item_entries, "tiers": len(tiers), "skipped": skipped,
		"blocked_groups": blocked_groups,
		"default_rule_set_name": _default_pricing_rule_set_name(prepared_report),
		"limited_to_first_50": len(raw_item_codes or []) > PRICING_RULE_UPDATE_LIMIT}


def _build_pricing_rule_item_preview(item_codes, rows_by_item, items, filters):
	item_entries = []
	eligible_item_codes = []
	skipped = []
	tier_count = len(filters.get("tiers") or [])
	for item_code in item_codes:
		row = rows_by_item[item_code]
		pricing_group = row.get("pricing_group") or ""
		entry = {
			"item_code": item_code,
			"item_name": row.get("item_name") or items[item_code].item_name,
			"pricing_group": pricing_group,
			"group_key": pricing_group
		}
		invalid_reason = None
		for tier_index in range(1, tier_count + 1):
			if pricing_group:
				reference_field = "group_recommended_b2b_net" \
					if filters.get("b2b_price_list") else "group_recommended_regular_net"
				value = _percentage_difference(
					row.get(reference_field), row.get("group_tier_{0}_net".format(tier_index))
				) if _valid_group_price(row.get(reference_field)) and _valid_group_price(
					row.get("group_tier_{0}_net".format(tier_index))) else None
			else:
				value = row.get("tier_{0}_discount_percent".format(tier_index))
			if value is None:
				invalid_reason = "No valid Tier {0} discount".format(tier_index)
				break
			entry["tier_{0}_discount_percent".format(tier_index)] = float(quantize_percent(value))
		if invalid_reason:
			skipped.append({"item_code": item_code, "reason": invalid_reason})
			continue
		item_entries.append(entry)
		eligible_item_codes.append(item_code)
	return item_entries, eligible_item_codes, skipped


@frappe.whitelist()
def preview_bulk_pricing_rule_summary(preview_token=None, item_codes=None, rule_mode="combined",
		rule_set_name=None, mixed_conditions=0):
	cache = frappe.cache()
	cache_key = _pricing_rule_preview_cache_key(frappe.session.user, str(preview_token or ""))
	payload = cache.get_value(cache_key)
	payload = frappe.parse_json(payload) if isinstance(payload, str) else payload
	if not isinstance(payload, dict) or payload.get("user") != frappe.session.user:
		frappe.throw("The Pricing Rule update preview is invalid or expired")
	selected = _normalize_update_item_codes(item_codes)
	eligible = payload.get("eligible_item_codes") or []
	if not selected or any(item_code not in eligible for item_code in selected):
		frappe.throw("Select at least one valid Item for Pricing Rule update")
	prepared_report = _get_prepared_pricing_report(payload.get("prepared_report"))
	rule_mode = _normalize_pricing_rule_mode(rule_mode)
	rule_set_name = str(rule_set_name or "").strip()
	if not rule_set_name:
		frappe.throw("Rule Set Name is required")
	mixed_conditions = cint(mixed_conditions) if rule_mode != "separate" else 0
	specs, entries, counts = _get_bulk_pricing_rule_summary(
		prepared_report, selected, rule_mode, rule_set_name, mixed_conditions
	)
	payload["selected_item_codes"] = selected
	payload["summary_entries"] = entries
	payload["rule_config"] = {"rule_mode": rule_mode, "rule_set_name": rule_set_name,
		"mixed_conditions": mixed_conditions}
	cache.set_value(cache_key, payload, expires_in_sec=600)
	return {"token": preview_token, "prepared_report": prepared_report.name,
		"entries": entries, "counts": counts, "selected_item_count": len(selected),
		"rule_mode": rule_mode, "rule_set_name": rule_set_name,
		"mixed_conditions": mixed_conditions}


@frappe.whitelist()
def execute_bulk_pricing_rule_update(preview_token=None, tier_discounts=None):
	cache = frappe.cache()
	cache_key = _pricing_rule_preview_cache_key(frappe.session.user, str(preview_token or ""))
	payload = cache.get_value(cache_key)
	payload = frappe.parse_json(payload) if isinstance(payload, str) else payload
	if not isinstance(payload, dict) or payload.get("user") != frappe.session.user:
		frappe.throw("The Pricing Rule update preview is invalid or expired")
	selected = payload.get("selected_item_codes") or []
	if not selected:
		frappe.throw("Review the selected Items before updating Pricing Rules")
	prepared_report = _get_prepared_pricing_report(payload.get("prepared_report"))
	config = payload.get("rule_config") or {}
	specs, entries, counts = _get_bulk_pricing_rule_summary(
		prepared_report, selected, config.get("rule_mode"), config.get("rule_set_name"),
		config.get("mixed_conditions")
	)
	provided = frappe.parse_json(tier_discounts) if isinstance(tier_discounts, str) else tier_discounts
	_apply_final_tier_discounts(specs, provided)
	conflicts = _find_pricing_rule_conflicts(specs)
	if conflicts:
		frappe.throw("Conflicting active Pricing Rules must be resolved first: {0}".format(
			"; ".join(conflicts)
		))
	if any(_get_pricing_rule_target(spec["title"], spec.get("legacy_title")) is None for spec in specs) \
			and not frappe.has_permission("Pricing Rule", "create"):
		frappe.throw("You do not have permission to create Pricing Rules", frappe.PermissionError)
	created = updated = unchanged = 0
	affected = []
	notification_changes = []
	preview_by_key = {str(row.get("rule_key") or row["tier_index"]): row
		for row in payload.get("summary_entries") or []}
	for spec in specs:
		target = _get_pricing_rule_target(spec["title"], spec.get("legacy_title"))
		preview = preview_by_key.get(str(spec.get("rule_key") or spec["tier_index"]))
		if not preview or (target and target["modified"] != preview.get("target_modified")):
			frappe.throw("Pricing Rule changed after preview; preview again")
		if target and _pricing_rule_target_matches(target, spec):
			unchanged += 1
			continue
		if not notification_changes and not frappe.has_permission("Note", "create"):
			frappe.throw("You do not have permission to create the pricing announcement", frappe.PermissionError)
		if target is None:
			doc = frappe.new_doc("Pricing Rule")
			_apply_pricing_rule_spec(doc, spec, prepared_report.name)
			doc.insert()
			created += 1
		else:
			target_name = target["name"]
			if target_name != spec["title"]:
				target_name = frappe.rename_doc("Pricing Rule", target_name, spec["title"])
			doc = frappe.get_doc("Pricing Rule", target_name)
			doc.check_permission("write")
			_apply_pricing_rule_spec(doc, spec, prepared_report.name)
			doc.save()
			updated += 1
		_add_pricing_rule_update_comment(doc, prepared_report.name, spec)
		affected.append(doc.name)
		notification_changes.append({
			"rule_name": doc.name,
			"item_codes": [row.item_code for row in doc.get("items")],
			"minimum_qty": doc.min_qty, "maximum_qty": doc.max_qty,
			"discount_percentage": doc.discount_percentage,
			"disabled": doc.disable, "mixed_conditions": doc.mixed_conditions
		})
	notification_note = create_pricing_update_note(
		"pricing_rule", prepared_report.name, notification_changes
	) if notification_changes else None
	cache.delete_value(cache_key)
	return {"prepared_report": prepared_report.name, "created": created,
		"updated": updated, "unchanged": unchanged, "pricing_rules": affected,
		"notification_note": notification_note}


def _get_prepared_pricing_report(prepared_report_name):
	if not prepared_report_name:
		frappe.throw("Completed Pricing Strategy Analysis Prepared Report is required")
	prepared_report = frappe.db.get_value(
		"Prepared Report", prepared_report_name,
		["name", "report_name", "status", "owner", "filters"], as_dict=1
	)
	prepared_report = frappe._dict(prepared_report or {})
	if prepared_report.report_name != "Pricing Strategy Analysis" \
			or prepared_report.status != "Completed":
		frappe.throw("The Pricing Strategy Analysis Prepared Report is invalid or incomplete")
	if prepared_report.owner != frappe.session.user \
			and "System Manager" not in frappe.get_roles():
		frappe.throw(
			"You do not have permission to use this Prepared Report",
			frappe.PermissionError
		)
	try:
		filters = frappe.parse_json(prepared_report.filters) \
			if isinstance(prepared_report.filters, str) else prepared_report.filters
	except (TypeError, ValueError):
		frappe.throw("The Prepared Report filters are invalid")
	if not isinstance(filters, dict):
		frappe.throw("The Prepared Report filters are invalid")
	prepared_report.saved_filters = filters
	prepared_report.filters = _normalize_prepared_report_filters(filters)
	return prepared_report


@frappe.whitelist()
def get_prepared_pricing_strategy_filters(prepared_report_name=None):
	prepared_report = _get_prepared_pricing_report(prepared_report_name)
	return prepared_report.saved_filters


def _normalize_prepared_report_filters(filters):
	normalized = validate_and_normalize_filters(filters, apply_strategy=False)
	if not normalized.get("tiers") and normalized.get("pricing_strategy"):
		settings = _get_pricing_strategy_settings(
			normalized.get("pricing_strategy"), normalized.get("company")
		)
		if settings.get("show_pricing_rule_strategy") and settings.get("tiers"):
			normalized["show_pricing_rule_strategy"] = True
			normalized["tiers"] = settings["tiers"]
			normalized["gap_messages"] = _validate_tiers(normalized["tiers"])
	return normalized


def _get_pricing_strategy_settings(strategy_name, company=None):
	if not strategy_name:
		frappe.throw("Pricing Strategy is required")
	strategy = frappe.get_doc("Pricing Strategy Template", strategy_name)
	strategy.check_permission("read")
	if not cint(strategy.enabled):
		frappe.throw("Pricing Strategy {0} is disabled".format(strategy_name))
	if company and strategy.company != company:
		frappe.throw("Pricing Strategy must belong to the selected Company")
	tiers = []
	if cint(strategy.enable_quantity_pricing):
		for row in strategy.pricing_tiers or []:
			tiers.append({
				"minimum": to_decimal(row.minimum_qty),
				"maximum": None if row.maximum_qty in (None, "", 0) else to_decimal(row.maximum_qty),
				"markup": to_decimal(row.markup_percent)
			})
	return {
		"pricing_strategy": strategy.name,
		"company": strategy.company,
		"exclude_expense_from_pricing": strategy.expense_treatment == "Exclude Expense",
		"indirect_expense_account": strategy.indirect_expense_account,
		"expense_allocation_method": strategy.expense_allocation_method,
		"vat_percent": to_decimal(strategy.vat_percent),
		"regular_price_list": strategy.regular_price_list,
		"regular_markup": to_decimal(strategy.regular_markup),
		"enable_b2b_pricing": bool(strategy.b2b_price_list),
		"b2b_price_list": strategy.b2b_price_list or None,
		"b2b_markup": to_decimal(strategy.b2b_markup) if strategy.b2b_price_list else Decimal("0"),
		"show_pricing_rule_strategy": bool(cint(strategy.enable_quantity_pricing)),
		"tiers": tiers
	}


@frappe.whitelist()
def get_pricing_strategy_settings(pricing_strategy=None, company=None):
	settings = _get_pricing_strategy_settings(pricing_strategy, company)
	result = dict(settings)
	result["pricing_tiers_json"] = frappe.as_json([
		{
			"minimum": float(row["minimum"]),
			"maximum": float(row["maximum"]) if row["maximum"] is not None else None,
			"markup": float(row["markup"])
		} for row in settings["tiers"]
	])
	result.pop("tiers", None)
	for fieldname in ("vat_percent", "regular_markup", "b2b_markup"):
		result[fieldname] = float(result[fieldname])
	return result


def _get_prepared_pricing_rows(prepared_report_name):
	prepared_report = _get_prepared_pricing_report(prepared_report_name)
	attachment_name = frappe.db.get_value(
		"File",
		{"attached_to_doctype": "Prepared Report", "attached_to_name": prepared_report.name},
		"name"
	)
	if not attachment_name:
		frappe.throw("The Prepared Report result attachment is missing or invalid")
	try:
		file_doc = frappe.get_doc("File", attachment_name)
		content = gzip_decompress(file_doc.get_content())
		rows = json.loads(frappe.safe_decode(content))
	except (TypeError, ValueError, IOError):
		frappe.throw("The Prepared Report result attachment cannot be read")
	if not isinstance(rows, list):
		frappe.throw("The Prepared Report result attachment is invalid")
	return [row for row in rows if isinstance(row, dict)]


def _get_update_items(item_codes):
	fields = ["name", "item_name", "item_group", "stock_uom"]
	if frappe.get_meta("Item").has_field("pricing_group"):
		fields.append("pricing_group")
	rows = frappe.get_list(
		"Item", filters={"name": ["in", item_codes], "disabled": 0},
		fields=fields, limit_page_length=0
	)
	items = {row.name: row for row in rows}
	missing = [item_code for item_code in item_codes if item_code not in items]
	if missing:
		frappe.throw(
			"These Items are unavailable or disabled: {0}".format(", ".join(missing))
		)
	return items


def _get_update_price_lists(filters):
	if not frappe.has_permission("Price List", "read") \
			or not frappe.has_permission("Item Price", "read"):
		frappe.throw("You do not have permission to preview Item Prices", frappe.PermissionError)
	regular_price_list = filters.get("regular_price_list")
	b2b_price_list = filters.get("b2b_price_list")
	if not regular_price_list:
		frappe.throw("Regular Price List is required")
	if b2b_price_list and b2b_price_list == regular_price_list:
		frappe.throw("Regular and B2B Price Lists must be different")
	definitions = [
		(regular_price_list, "Regular", "recommended_regular_net")
	]
	if b2b_price_list:
		definitions.append((b2b_price_list, "B2B", "recommended_b2b_net"))
	result = []
	for price_list_name, kind, recommendation_field in definitions:
		values = frappe.db.get_value(
			"Price List", price_list_name,
			["name", "enabled", "selling", "currency", "price_not_uom_dependent"],
			as_dict=1
		)
		values = frappe._dict(values or {})
		if not values.name or not cint(values.enabled) or not cint(values.selling) \
				or not values.currency:
			frappe.throw("Price List {0} is unavailable for selling".format(price_list_name))
		values.kind = kind
		values.recommendation_field = recommendation_field
		result.append(values)
	return result


def _resolve_item_price_target(item, price_list, report_to_date):
	rows = frappe.get_list(
		"Item Price",
		filters={
			"item_code": item.name, "price_list": price_list.name, "selling": 1
		},
		fields=[
			"name", "price_list_rate", "uom", "valid_from", "valid_upto",
			"creation", "modified"
		],
		limit_page_length=0
	)
	report_to_date = getdate(report_to_date)
	applicable = []
	for row in rows:
		row = frappe._dict(row)
		if row.valid_from and getdate(row.valid_from) > report_to_date:
			continue
		if row.valid_upto and getdate(row.valid_upto) < report_to_date:
			continue
		if not cint(price_list.price_not_uom_dependent) \
				and row.uom and row.uom != item.stock_uom:
			continue
		applicable.append(row)
	applicable.sort(key=lambda row: (
		str(row.valid_from or ""), str(row.creation or ""), str(row.name or "")
	), reverse=True)
	create_uom = "" if cint(price_list.price_not_uom_dependent) else item.stock_uom
	if not applicable:
		return {
			"name": None, "rate": None, "modified": None,
			"uom": create_uom, "duplicate_count": 0
		}
	target = applicable[0]
	return {
		"name": target.name,
		"rate": quantize_money(target.price_list_rate),
		"modified": str(target.modified or ""),
		"uom": target.uom or create_uom,
		"duplicate_count": len(applicable)
	}


def _item_price_preview_cache_key(user, token):
	return "pricing-strategy-item-price-preview:{0}:{1}".format(user, token)


@frappe.whitelist()
def preview_item_price_update(prepared_report_name=None, item_codes=None):
	prepared_report = _get_prepared_pricing_report(prepared_report_name)
	raw_item_codes = frappe.parse_json(item_codes) if isinstance(item_codes, str) else item_codes
	unique_requested = []
	seen = set()
	for value in raw_item_codes or []:
		item_code = value.get("item_code") if isinstance(value, dict) else value
		item_code = str(item_code or "").strip()
		if item_code and item_code not in seen:
			seen.add(item_code)
			unique_requested.append(item_code)
	normalized_item_codes = _normalize_update_item_codes(raw_item_codes)
	if not normalized_item_codes:
		frappe.throw("There are no report Items available for Item Price update")

	prepared_rows = _get_prepared_pricing_rows(prepared_report_name)
	rows_by_item = {
		row.get("item_code"): row for row in prepared_rows if row.get("item_code")
	}
	missing_rows = [
		item_code for item_code in normalized_item_codes if item_code not in rows_by_item
	]
	if missing_rows:
		frappe.throw(
			"These Items are not present in the saved Prepared Report: {0}".format(
				", ".join(missing_rows)
			)
		)

	classification = classify_updateable_pricing_groups(
		prepared_rows, normalized_item_codes, ITEM_PRICE_UPDATE_LIMIT
	)
	blocked_groups = classification["blocked_groups"]
	blocked_codes = set(
		row.get("item_code") for row in prepared_rows
		if row.get("pricing_group") in blocked_groups
	)
	normalized_item_codes = [
		item_code for item_code in normalized_item_codes if item_code not in blocked_codes
	]
	if not normalized_item_codes:
		frappe.throw("None of the selected Items belongs to a complete updateable Pricing Group")

	items = _get_update_items(normalized_item_codes)
	price_lists = _get_update_price_lists(prepared_report.filters)
	entries = []
	skipped = [
		{"pricing_group": group_name, "reason": reason}
		for group_name, reason in sorted(blocked_groups.items())
	]
	counts = {"create": 0, "update": 0, "unchanged": 0}
	for item_code in normalized_item_codes:
		item = items[item_code]
		saved_row = rows_by_item[item_code]
		for price_list in price_lists:
			pricing_group = saved_row.get("pricing_group") or ""
			group_field = {
				"recommended_regular_net": "group_recommended_regular_net",
				"recommended_b2b_net": "group_recommended_b2b_net"
			}.get(price_list.recommendation_field)
			individual_rate = quantize_money(saved_row.get(price_list.recommendation_field))
			group_rate = quantize_money(saved_row.get(group_field)) \
				if pricing_group and group_field else None
			new_rate = group_rate if group_rate and group_rate > 0 else individual_rate
			if new_rate <= 0:
				skipped.append({
					"item_code": item_code, "price_kind": price_list.kind,
					"reason": "No valid recommended {0} price".format(price_list.kind)
				})
				continue
			target = _resolve_item_price_target(
				item, price_list, prepared_report.filters["to_date"]
			)
			if target["name"] is None:
				action = "Create"
			elif target["rate"] == new_rate:
				action = "Unchanged"
			else:
				action = "Update"
			counts[action.lower()] += 1
			warning = ""
			if target["duplicate_count"] > 1:
				warning = "{0} applicable Item Prices; latest record will be updated".format(
					target["duplicate_count"]
				)
			entries.append({
				"item_code": item_code,
				"item_name": saved_row.get("item_name") or item.item_name,
				"stock_uom": item.stock_uom,
				"price_list": price_list.name,
				"price_kind": price_list.kind,
				"currency": price_list.currency,
				"current_rate": float(target["rate"]) if target["rate"] is not None else None,
				"new_rate": float(new_rate),
				"individual_rate": float(individual_rate) if individual_rate > 0 else None,
				"group_rate": float(group_rate) if group_rate and group_rate > 0 else None,
				"pricing_group": pricing_group,
				"group_key": pricing_group,
				"action": action,
				"item_price_name": target["name"],
				"target_modified": target["modified"],
				"uom": target["uom"],
				"warning": warning
			})

	if not entries:
		frappe.throw("None of the selected Items has a valid recommended Item Price")
	token = frappe.generate_hash(length=32)
	payload = {
		"prepared_report": prepared_report.name,
		"user": frappe.session.user,
		"entries": entries,
		"created_at": frappe.utils.now()
	}
	frappe.cache().set_value(
		_item_price_preview_cache_key(frappe.session.user, token),
		payload, expires_in_sec=600
	)
	return {
		"token": token,
		"prepared_report": prepared_report.name,
		"requested_item_count": len(normalized_item_codes),
		"source_row_count": len(rows_by_item),
		"limited_to_first_50": len(unique_requested) > ITEM_PRICE_UPDATE_LIMIT,
		"entries": entries,
		"skipped": skipped,
		"blocked_groups": blocked_groups,
		"counts": counts
	}


def _filter_item_price_preview_entries(entries, selected_rows=None):
	if selected_rows is None:
		return entries
	selected_rows = frappe.parse_json(selected_rows) if isinstance(selected_rows, str) else selected_rows
	if not isinstance(selected_rows, list):
		frappe.throw("Select valid Item Price rows")
	requested = []
	seen = set()
	for value in selected_rows:
		key = str(value or "").strip()
		if not key or key in seen:
			frappe.throw("Select valid Item Price rows")
		seen.add(key)
		requested.append(key)
	available = {
		"{0}|{1}".format(entry.get("item_code"), entry.get("price_list")): entry
		for entry in entries if isinstance(entry, dict)
	}
	if not requested or any(key not in available for key in requested):
		frappe.throw("Select at least one valid Item Price row")
	selected = [available[key] for key in requested]
	selected_groups = set(entry.get("group_key") for entry in selected if entry.get("group_key"))
	for group_key in selected_groups:
		available_keys = set(
			"{0}|{1}".format(entry.get("item_code"), entry.get("price_list"))
			for entry in entries if entry.get("group_key") == group_key
		)
		selected_keys = set(
			"{0}|{1}".format(entry.get("item_code"), entry.get("price_list"))
			for entry in selected if entry.get("group_key") == group_key
		)
		if available_keys != selected_keys:
			frappe.throw(
				"Keep or remove every Item Price row for Pricing Group {0}.".format(group_key)
			)
	return selected


def validate_live_pricing_group_entries(entries, rows_by_item, items):
	group_names = sorted(set(
		entry.get("group_key") for entry in entries if entry.get("group_key")
	))
	if not group_names:
		return
	live_membership = get_pricing_group_membership(group_names)
	for group_name in group_names:
		definition = live_membership.get(group_name) or {"disabled": 1, "item_codes": []}
		if cint(definition.get("disabled")):
			frappe.throw("Pricing Group {0} is disabled; preview again".format(group_name))
		snapshot_codes = set(
			item_code for item_code, row in rows_by_item.items()
			if row.get("pricing_group") == group_name
		)
		entry_codes = set(
			entry.get("item_code") for entry in entries
			if entry.get("group_key") == group_name
		)
		live_codes = set(definition.get("item_codes") or [])
		if not snapshot_codes or snapshot_codes != entry_codes or snapshot_codes != live_codes:
			frappe.throw(
				"Pricing Group {0} membership changed after preview; rebuild and preview again".format(
					group_name
				)
			)
		for item_code in snapshot_codes:
			item = items.get(item_code)
			if not item or getattr(item, "pricing_group", None) != group_name:
				frappe.throw(
					"Pricing Group {0} membership changed after preview; rebuild and preview again".format(
						group_name
					)
				)


@frappe.whitelist()
def execute_item_price_update(preview_token=None, selected_rows=None):
	preview_token = str(preview_token or "").strip()
	if not preview_token:
		frappe.throw("Item Price update preview token is required")
	cache = frappe.cache()
	cache_key = _item_price_preview_cache_key(frappe.session.user, preview_token)
	payload = cache.get_value(cache_key)
	payload = frappe.parse_json(payload) if isinstance(payload, str) else payload
	if not isinstance(payload, dict):
		frappe.throw("The Item Price update preview has expired; preview the changes again")
	if payload.get("user") != frappe.session.user:
		frappe.throw("The Item Price update preview belongs to another user", frappe.PermissionError)
	entries = payload.get("entries")
	if not isinstance(entries, list) or not entries:
		frappe.throw("The Item Price update preview is invalid")
	entries = _filter_item_price_preview_entries(entries, selected_rows)

	prepared_report = _get_prepared_pricing_report(payload.get("prepared_report"))
	prepared_rows = _get_prepared_pricing_rows(prepared_report.name)
	rows_by_item = {
		row.get("item_code"): row for row in prepared_rows if row.get("item_code")
	}
	item_codes = _normalize_update_item_codes([
		entry.get("item_code") for entry in entries if isinstance(entry, dict)
	])
	if not item_codes or len(entries) > ITEM_PRICE_UPDATE_LIMIT * 2:
		frappe.throw("The Item Price update preview exceeds the allowed limit")
	items = _get_update_items(item_codes)
	validate_live_pricing_group_entries(entries, rows_by_item, items)
	price_lists = _get_update_price_lists(prepared_report.filters)
	price_lists_by_name = {price_list.name: price_list for price_list in price_lists}

	if any(entry.get("action") == "Create" for entry in entries) \
			and not frappe.has_permission("Item Price", "create"):
		frappe.throw("You do not have permission to create Item Prices", frappe.PermissionError)

	update_docs = {}
	for entry in entries:
		if not isinstance(entry, dict):
			frappe.throw("The Item Price update preview is invalid")
		item_code = entry.get("item_code")
		price_list = price_lists_by_name.get(entry.get("price_list"))
		item = items.get(item_code)
		saved_row = rows_by_item.get(item_code)
		if not item or not price_list or not saved_row:
			frappe.throw("The Item Price update preview no longer matches the Prepared Report")
		new_rate = quantize_money(entry.get("new_rate"))
		group_field = {
			"recommended_regular_net": "group_recommended_regular_net",
			"recommended_b2b_net": "group_recommended_b2b_net"
		}.get(price_list.recommendation_field)
		saved_rate = quantize_money(
			saved_row.get(group_field) if entry.get("group_key") and group_field
			else saved_row.get(price_list.recommendation_field)
		)
		if new_rate <= 0 or new_rate != saved_rate:
			frappe.throw("The recommended Item Price changed after preview")
		if entry.get("currency") != price_list.currency:
			frappe.throw("The Price List currency changed after preview")

		current_target = _resolve_item_price_target(
			item, price_list, prepared_report.filters["to_date"]
		)
		preview_name = entry.get("item_price_name")
		preview_rate = entry.get("current_rate")
		preview_rate = quantize_money(preview_rate) if preview_rate is not None else None
		if current_target["name"] != preview_name \
				or current_target["rate"] != preview_rate \
				or str(current_target["modified"] or "") != str(entry.get("target_modified") or ""):
			frappe.throw(
				"Item Price for {0} in {1} changed after preview; preview again".format(
					item_code, price_list.name
				)
			)
		action = entry.get("action")
		expected_action = "Create" if current_target["name"] is None \
			else ("Unchanged" if current_target["rate"] == new_rate else "Update")
		if action != expected_action:
			frappe.throw("The Item Price update action changed after preview")
		if action == "Update":
			item_price = frappe.get_doc("Item Price", preview_name)
			item_price.check_permission("write")
			update_docs[(item_code, price_list.name)] = item_price

	if any(entry["action"] != "Unchanged" for entry in entries) \
			and not frappe.has_permission("Note", "create"):
		frappe.throw("You do not have permission to create the pricing announcement", frappe.PermissionError)

	created = 0
	updated = 0
	unchanged = 0
	affected_item_prices = []
	notification_changes = []
	for entry in entries:
		action = entry["action"]
		new_rate = quantize_money(entry["new_rate"])
		if action == "Unchanged":
			unchanged += 1
			continue
		if action == "Update":
			item_price = update_docs[(entry["item_code"], entry["price_list"])]
			previous_rate = entry.get("current_rate")
			item_price.price_list_rate = new_rate
			item_price.pricing_prepared_report = prepared_report.name
			item_price.save()
			updated += 1
		else:
			previous_rate = None
			item = items[entry["item_code"]]
			item_price = frappe.new_doc("Item Price")
			item_price.item_code = entry["item_code"]
			item_price._item_group = item.item_group
			item_price.price_list = entry["price_list"]
			item_price.price_list_rate = new_rate
			item_price.selling = 1
			item_price.currency = entry["currency"]
			item_price.uom = entry.get("uom") or ""
			item_price.pricing_prepared_report = prepared_report.name
			item_price.insert()
			created += 1
		_add_item_price_update_comment(
			item_price, prepared_report.name, entry["price_list"], previous_rate, new_rate,
			prepared_report.filters.get("pricing_strategy")
		)
		affected_item_prices.append(item_price.name)
		notification_changes.append({
			"item_code": item_price.item_code,
			"item_name": item_price.item_name or items[entry["item_code"]].item_name,
			"price_list": item_price.price_list, "uom": item_price.uom,
			"price_kind": entry.get("price_kind"),
			"currency": item_price.currency, "old_rate": previous_rate,
			"new_rate": item_price.price_list_rate,
			"workflow_state": item_price.get("workflow_state")
		})

	notification_note = create_pricing_update_note(
		"item_price", prepared_report.name, notification_changes
	) if notification_changes else None
	cache.delete_value(cache_key)
	return {
		"prepared_report": prepared_report.name,
		"created": created,
		"updated": updated,
		"unchanged": unchanged,
		"item_prices": affected_item_prices,
		"notification_note": notification_note
	}


def _add_item_price_update_comment(item_price, prepared_report_name, price_list,
		previous_rate, new_rate, pricing_strategy=None):
	prepared_report_link = '<a href="#Form/Prepared Report/{0}">{1}</a>'.format(
		escape_html(prepared_report_name), escape_html(prepared_report_name)
	)
	previous_value = "Not set" if previous_rate in (None, "") \
		else str(quantize_money(previous_rate))
	content = (
		"<b>Pricing Strategy Item Price Update</b><br>"
		"Prepared Report: {0}<br>"
		"Pricing Strategy: {1}<br>"
		"Price List: {2}<br>"
		"Previous Price: {3}<br>"
		"New Price: {4}"
	).format(
		prepared_report_link,
		escape_html(pricing_strategy or "Legacy manual settings"),
		escape_html(price_list),
		escape_html(previous_value),
		escape_html(str(quantize_money(new_rate)))
	)
	item_price.add_comment("Comment", content)


def to_decimal(value):
	if value in (None, ""):
		return Decimal("0")
	try:
		return Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw("Invalid numeric value: {0}".format(value))


def quantize_money(value):
	return to_decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def quantize_percent(value):
	return to_decimal(value).quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP)


def round_to_increment(value, increment):
	value = to_decimal(value)
	increment = to_decimal(increment)
	if increment <= 0:
		frappe.throw("Rounding Increment must be greater than zero")
	units = value / increment
	rounded_units = units.quantize(Decimal("1"), rounding=ROUND_CEILING)
	return rounded_units * increment


def get_rounding_increment(gross_price):
	gross_price = to_decimal(gross_price)
	if gross_price < Decimal("0.100"):
		return Decimal("0.005")
	if gross_price < Decimal("30"):
		return Decimal("0.100")
	if gross_price < Decimal("100"):
		return Decimal("0.500")
	if gross_price < Decimal("1000"):
		return Decimal("1.000")
	return Decimal("10.000")


def calculate_price(loaded_cost, markup_percent, vat_percent):
	loaded_cost = to_decimal(loaded_cost)
	markup_percent = to_decimal(markup_percent)
	vat_percent = to_decimal(vat_percent)
	if loaded_cost <= 0:
		return None

	raw_net_price = loaded_cost * (Decimal("1") + markup_percent / Decimal("100"))
	raw_gross_price = raw_net_price * (Decimal("1") + vat_percent / Decimal("100"))
	increment = get_rounding_increment(raw_gross_price)
	rounded_gross_price = round_to_increment(raw_gross_price, increment)
	vat_factor = Decimal("1") + vat_percent / Decimal("100")
	if vat_factor <= 0:
		frappe.throw("VAT percentage produces an invalid price divisor")

	net_price = rounded_gross_price / vat_factor
	profit = net_price - loaded_cost
	actual_markup = profit / loaded_cost * Decimal("100")
	gross_margin = Decimal("0")
	if net_price:
		gross_margin = profit / net_price * Decimal("100")

	return {
		"net_price": quantize_money(net_price),
		"gross_price": quantize_money(rounded_gross_price),
		"profit": quantize_money(profit),
		"actual_markup_percent": quantize_percent(actual_markup),
		"gross_margin_percent": quantize_percent(gross_margin),
		"rounding_increment": increment,
		"net_rounding_increment": quantize_money(increment / vat_factor)
	}


def compose_warnings(values):
	result = []
	seen = set()
	for value in values or []:
		if not value or value in seen:
			continue
		seen.add(value)
		result.append(value)
	return "; ".join(result)


def get_suggested_action(current_price, recommended_price, increment):
	if recommended_price is None:
		return ""
	if current_price is None or to_decimal(current_price) <= 0:
		return "Set Initial Price"
	difference = to_decimal(recommended_price) - to_decimal(current_price)
	if difference >= to_decimal(increment):
		return "Increase Price"
	if difference <= -to_decimal(increment):
		return "Reduce Price"
	return "Keep Price"


def calculate_expense_allocation(sales_qty, net_cogs, selected_base_cost, expense_ratio):
	sales_qty = to_decimal(sales_qty)
	net_cogs = to_decimal(net_cogs)
	expense_ratio = to_decimal(expense_ratio)
	result = {"allocated_expense": None, "expense_per_unit": None, "expense_source": "", "warnings": []}
	if expense_ratio <= 0:
		result.update({
			"allocated_expense": Decimal("0.000"),
			"expense_per_unit": Decimal("0.000"),
			"expense_source": "No indirect expense"
		})
		return result
	if sales_qty > 0 and net_cogs > 0:
		allocated_expense = net_cogs * expense_ratio
		result.update({
			"allocated_expense": quantize_money(allocated_expense),
			"expense_per_unit": quantize_money(allocated_expense / sales_qty),
			"expense_source": "Actual period COGS"
		})
		return result
	if selected_base_cost is not None and to_decimal(selected_base_cost) > 0:
		result.update({
			"expense_per_unit": quantize_money(to_decimal(selected_base_cost) * expense_ratio),
			"expense_source": "Base Cost fallback"
		})
		return result
	result["warnings"].append("No basis for indirect expense allocation")
	return result


def apply_pricing_group_filter_configuration(filters):
	result = dict(filters or {})
	pricing_group = result.get("pricing_group")
	if not pricing_group:
		return result
	if result.get("purchase_receipt"):
		frappe.throw("Pricing Group and Purchase Receipt cannot be used together")
	configuration = get_pricing_group_configuration(pricing_group)
	for fieldname in ("company", "item_group", "pricing_strategy"):
		configured_value = configuration.get(fieldname)
		if result.get(fieldname) and result.get(fieldname) != configured_value:
			frappe.throw(
				"{0} conflicts with Pricing Group {1}".format(
					fieldname.replace("_", " ").title(), pricing_group
				)
			)
		result[fieldname] = configured_value
	return result


def validate_and_normalize_filters(filters, apply_strategy=True):
	filters = apply_pricing_group_filter_configuration(filters) if apply_strategy else dict(filters or {})
	strategy_settings = None
	if apply_strategy and filters.get("pricing_strategy"):
		strategy_settings = _get_pricing_strategy_settings(
			filters.get("pricing_strategy"), filters.get("company")
		)
		filters.update(strategy_settings)
	result = dict(filters)

	for fieldname in ("company", "from_date", "to_date", "regular_price_list"):
		if not filters.get(fieldname):
			frappe.throw("{0} is required".format(fieldname.replace("_", " ").title()))

	result["from_date"] = getdate(filters.get("from_date"))
	result["to_date"] = getdate(filters.get("to_date"))
	if result["from_date"] > result["to_date"]:
		frappe.throw("From Date cannot be after To Date")

	result["cost_source"] = COST_SOURCE_ALIASES.get(
		filters.get("cost_source"), filters.get("cost_source")
	) or "Latest Valuation Rate"
	if result["cost_source"] not in COST_SOURCES:
		frappe.throw("Unsupported Cost Source: {0}".format(result["cost_source"]))

	numeric_defaults = {
		"vat_percent": "10",
		"regular_markup": "43",
		"b2b_markup": "33"
	}
	for fieldname, default in numeric_defaults.items():
		value = filters.get(fieldname)
		result[fieldname] = to_decimal(default if value in (None, "") else value)

	for fieldname in ("vat_percent", "regular_markup", "b2b_markup"):
		if result[fieldname] < 0:
			frappe.throw("{0} cannot be negative".format(fieldname.replace("_", " ").title()))
	if "exclude_items_without_sales" in filters:
		result["exclude_items_without_sales"] = bool(cint(filters.get("exclude_items_without_sales")))
	elif "include_items_without_sales" in filters:
		result["exclude_items_without_sales"] = not bool(cint(filters.get("include_items_without_sales")))
	else:
		result["exclude_items_without_sales"] = False
	result["exclude_expense_from_pricing"] = bool(
		cint(filters.get("exclude_expense_from_pricing", 0))
	)
	result["enable_b2b_pricing"] = bool(
		cint(filters.get("enable_b2b_pricing", 1 if filters.get("b2b_price_list") else 0))
	)
	result["show_pricing_rule_strategy"] = bool(cint(filters.get("show_pricing_rule_strategy", 0)))
	if result["show_pricing_rule_strategy"]:
		if strategy_settings is not None:
			result["tiers"] = strategy_settings["tiers"]
		elif filters.get("pricing_tiers_json"):
			result["tiers"] = _normalize_strategy_tiers(filters.get("pricing_tiers_json"))
		else:
			result["tiers"] = _normalize_tiers(filters)
		result["gap_messages"] = _validate_tiers(result["tiers"])
	else:
		result["tiers"] = []
		result["gap_messages"] = []
	return result


def _normalize_strategy_tiers(value):
	rows = frappe.parse_json(value) if isinstance(value, str) else value
	if not isinstance(rows, list):
		frappe.throw("Pricing Strategy tiers are invalid")
	tiers = []
	for index, row in enumerate(rows, 1):
		if not isinstance(row, dict):
			frappe.throw("Pricing Strategy tier {0} is invalid".format(index))
		maximum = row.get("maximum")
		tiers.append({
			"minimum": to_decimal(row.get("minimum")),
			"maximum": None if maximum in (None, "") else to_decimal(maximum),
			"markup": to_decimal(row.get("markup"))
		})
	return tiers


def _normalize_tiers(filters):
	defaults = (
		("5", "9", "31"),
		("10", "19", "29"),
		("20", "39", "27"),
		("40", None, "25")
	)
	tiers = []
	for index, default_values in enumerate(defaults, 1):
		range_fieldname = "tier_{0}_qty_range".format(index)
		if range_fieldname in filters:
			minimum, maximum = _parse_qty_range(filters.get(range_fieldname), index)
			markup_value = filters.get("tier_{0}_markup".format(index))
			markup = to_decimal(default_values[2] if markup_value in (None, "") else markup_value)
			tiers.append({"minimum": minimum, "maximum": maximum, "markup": markup})
			continue
		minimum_value = filters.get("tier_{0}_minimum".format(index))
		maximum_fieldname = "tier_{0}_maximum".format(index)
		maximum_value = filters.get(maximum_fieldname)
		markup_value = filters.get("tier_{0}_markup".format(index))
		minimum = to_decimal(default_values[0] if minimum_value in (None, "") else minimum_value)
		if maximum_fieldname in filters and maximum_value in (None, ""):
			maximum = None
		elif maximum_value in (None, ""):
			maximum = None if default_values[1] is None else to_decimal(default_values[1])
		else:
			maximum = to_decimal(maximum_value)
		markup = to_decimal(default_values[2] if markup_value in (None, "") else markup_value)
		tiers.append({
			"minimum": minimum,
			"maximum": maximum,
			"markup": markup
		})
	return tiers


def _parse_qty_range(value, index):
	text = str(value or "").strip().replace(" ", "")
	try:
		if text.endswith("+"):
			return to_decimal(text[:-1]), None
		parts = text.split(":")
		if len(parts) == 2 and parts[0] and parts[1]:
			return to_decimal(parts[0]), to_decimal(parts[1])
	except (InvalidOperation, TypeError, ValueError):
		pass
	frappe.throw(
		"Tier {0} Qty Range must use From:To or From+ format, for example 5:9 or 40+".format(index)
	)


def _validate_tiers(tiers):
	gap_messages = []
	previous = None
	for index, tier in enumerate(tiers):
		if tier["minimum"] <= 0:
			frappe.throw("Tier {0} Minimum Qty must be greater than zero".format(index + 1))
		if tier["markup"] < 0:
			frappe.throw("Tier {0} Markup cannot be negative".format(index + 1))
		if tier["maximum"] is not None and tier["maximum"] < tier["minimum"]:
			frappe.throw("Tier {0} Maximum Qty cannot be below Minimum Qty".format(index + 1))
		if tier["maximum"] is None and index != len(tiers) - 1:
			frappe.throw("Only the final quantity tier may have no maximum")
		if previous:
			if previous["maximum"] is None:
				frappe.throw("An open-ended tier must be the final tier")
			if tier["minimum"] <= previous["maximum"]:
				frappe.throw("Quantity tiers cannot overlap or be unordered")
			if tier["minimum"] > previous["maximum"] + Decimal("1"):
				gap_messages.append(
					"Quantity tier gap between {0} and {1}".format(
						_format_decimal(previous["maximum"]),
						_format_decimal(tier["minimum"])
					)
				)
		previous = tier
	return gap_messages


def _format_decimal(value):
	return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")


def calculate_item_row(item, context):
	row = dict(item)
	warnings = list(row.get("warnings") or [])
	vat_factor = Decimal("1") + to_decimal(context.get("vat_percent")) / Decimal("100")
	for net_fieldname, gross_fieldname in (
		("current_normal_price", "current_normal_gross"),
		("current_b2b_price", "current_b2b_gross")
	):
		current_price = row.get(net_fieldname)
		row[gross_fieldname] = (
			quantize_money(to_decimal(current_price) * vat_factor)
			if current_price is not None else None
		)
	base_cost = to_decimal(row.get("selected_base_cost"))
	if base_cost <= 0:
		row.update({
			"selected_base_cost": None,
			"expense_per_unit": row.get("expense_per_unit"),
			"fully_loaded_cost": None,
			"suggested_action": "",
			"warnings": compose_warnings(warnings + ["Missing cost"])
		})
		for prefix in ["recommended_regular", "recommended_b2b"] + [
			"tier_{0}".format(index) for index in range(1, len(context["tiers"]) + 1)
		]:
			for suffix in ("net", "gross", "profit", "actual_markup_percent", "gross_margin_percent"):
				row[prefix + "_" + suffix] = None
		row["b2b_discount_percent"] = None
		row["average_actual_markup_percent"] = None
		row["average_gross_margin_percent"] = None
		row["average_discount_percent"] = None
		row["change_from_current_normal"] = None
		row["change_from_current_normal_percent"] = None
		for index in range(1, len(context["tiers"]) + 1):
			row["tier_{0}_discount_percent".format(index)] = None
		return row

	expense_per_unit = row.get("expense_per_unit")
	loaded_cost = base_cost + to_decimal(expense_per_unit)
	row["selected_base_cost"] = quantize_money(base_cost)
	row["expense_per_unit"] = quantize_money(expense_per_unit) if expense_per_unit is not None else None
	row["fully_loaded_cost"] = quantize_money(loaded_cost)
	pricing_cost = loaded_cost
	if context.get("exclude_expense_from_pricing"):
		pricing_cost = base_cost
		warnings.append("Expense excluded from price calculation")

	regular = calculate_price(
		pricing_cost, context["regular_markup"], context["vat_percent"]
	)
	_apply_price_result(row, "recommended_regular", regular)
	b2b = None
	if context.get("enable_b2b_pricing"):
		b2b = calculate_price(
			pricing_cost, context["b2b_markup"], context["vat_percent"]
		)
		_apply_price_result(row, "recommended_b2b", b2b)
		row["b2b_discount_percent"] = _percentage_difference(
			regular["net_price"], b2b["net_price"]
		)
	else:
		for suffix in ("net", "gross", "profit", "actual_markup_percent", "gross_margin_percent"):
			row["recommended_b2b_" + suffix] = None
		row["b2b_discount_percent"] = None

	for index, tier in enumerate(context["tiers"], 1):
		tier_result = calculate_price(
			pricing_cost, tier["markup"], context["vat_percent"]
		)
		_apply_price_result(row, "tier_{0}".format(index), tier_result)
		discount_base = b2b["net_price"] if b2b else regular["net_price"]
		row["tier_{0}_discount_percent".format(index)] = _percentage_difference(
			discount_base, tier_result["net_price"]
		)

	markup_values = [row.get("recommended_regular_actual_markup_percent")]
	margin_values = [row.get("recommended_regular_gross_margin_percent")]
	discount_values = []
	if b2b:
		markup_values.append(row.get("recommended_b2b_actual_markup_percent"))
		margin_values.append(row.get("recommended_b2b_gross_margin_percent"))
		discount_values.append(row.get("b2b_discount_percent"))
	for index in range(1, len(context["tiers"]) + 1):
		markup_values.append(row.get("tier_{0}_actual_markup_percent".format(index)))
		margin_values.append(row.get("tier_{0}_gross_margin_percent".format(index)))
		discount_values.append(row.get("tier_{0}_discount_percent".format(index)))
	row["average_actual_markup_percent"] = _average_percentages(markup_values)
	row["average_gross_margin_percent"] = _average_percentages(margin_values)
	row["average_discount_percent"] = _average_percentages(discount_values)

	current_price = row.get("current_normal_price")
	row["change_from_current_normal"] = None
	row["change_from_current_normal_percent"] = None
	if current_price is not None and to_decimal(current_price) > 0:
		change = regular["net_price"] - to_decimal(current_price)
		row["change_from_current_normal"] = quantize_money(change)
		row["change_from_current_normal_percent"] = quantize_percent(
			change / to_decimal(current_price) * Decimal("100")
		)
	row["suggested_action"] = get_suggested_action(
		current_price, regular["net_price"], regular["net_rounding_increment"]
	)
	row["warnings"] = compose_warnings(warnings)
	return row


def _apply_price_result(row, prefix, result):
	row[prefix + "_net"] = result["net_price"]
	row[prefix + "_gross"] = result["gross_price"]
	row[prefix + "_profit"] = result["profit"]
	row[prefix + "_actual_markup_percent"] = result["actual_markup_percent"]
	row[prefix + "_gross_margin_percent"] = result["gross_margin_percent"]


def _average_percentages(values):
	values = [to_decimal(value) for value in values if value is not None]
	if not values:
		return None
	return quantize_percent(sum(values, Decimal("0")) / Decimal(len(values)))


def _percentage_difference(base_value, lower_value):
	base_value = to_decimal(base_value)
	if not base_value:
		return None
	return quantize_percent(
		(base_value - to_decimal(lower_value)) / base_value * Decimal("100")
	)


def validate_pricing_group_setup(filters=None):
	filters = filters or {}
	has_field = frappe.get_meta("Item").has_field("pricing_group")
	if filters.get("pricing_group") and not has_field:
		frappe.throw(
			"Create the Item custom field pricing_group (Link to Pricing Group) "
			"before using Pricing Groups."
		)
	return bool(has_field)


def get_pricing_group_membership(group_names):
	group_names = sorted(set(group_name for group_name in (group_names or []) if group_name))
	if not group_names:
		return {}
	groups = frappe.get_all(
		"Pricing Group", filters={"name": ("in", group_names)},
		fields=["name", "disabled"], limit_page_length=0
	)
	result = {
		row.name: {"disabled": cint(row.disabled), "item_codes": []}
		for row in groups
	}
	items = frappe.get_all(
		"Item",
		filters={
			"pricing_group": ("in", group_names), "disabled": 0, "is_stock_item": 1
		},
		fields=["name", "pricing_group"], order_by="name asc", limit_page_length=0
	)
	for item in items:
		result.setdefault(
			item.pricing_group, {"disabled": 1, "item_codes": []}
		)["item_codes"].append(item.name)
	for group_name in group_names:
		result.setdefault(group_name, {"disabled": 1, "item_codes": []})
	return result


def _valid_group_price(value):
	return value not in (None, "") and to_decimal(value) > 0


def _pricing_group_reference_row(group_rows, valid_rows):
	total_sales_qty = sum(
		max(to_decimal(row.get("sales_qty")), Decimal("0"))
		for row in group_rows
	)
	if total_sales_qty > 0:
		return max(valid_rows, key=lambda row: (
			max(to_decimal(row.get("sales_qty")), Decimal("0")),
			to_decimal(row.get("recommended_regular_net")),
			row.get("item_code") or ""
		)), total_sales_qty, "Highest Sales Qty"
	return max(valid_rows, key=lambda row: (
		to_decimal(row.get("recommended_regular_net")),
		row.get("item_code") or ""
	)), total_sales_qty, "No Sales - Highest Price"


def _set_group_sales_contributions(group_rows, reference_row, total_sales_qty):
	if total_sales_qty <= 0:
		for row in group_rows:
			row["sales_contribution_percent"] = Decimal("0.000")
		return
	total_percentage = Decimal("0.000")
	for row in group_rows:
		contribution = quantize_percent(
			max(to_decimal(row.get("sales_qty")), Decimal("0")) /
			total_sales_qty * Decimal("100")
		)
		row["sales_contribution_percent"] = contribution
		total_percentage += contribution
	reference_row["sales_contribution_percent"] += Decimal("100.000") - total_percentage


def _pricing_group_summary_row(group_name, status, reference_row, price_fields,
		selection_reason):
	summary = {
		"item_code": "",
		"item_name": "",
		"group_summary_label": "Group Strategy Price",
		"pricing_group": group_name,
		"pricing_group_status": status,
		"is_pricing_group_summary": 1,
		"group_reference_item_code": reference_row.get("item_code"),
		"group_reference_sales_qty": reference_row.get("sales_qty"),
		"group_reference_sales_contribution_percent": reference_row.get(
			"sales_contribution_percent"
		),
		"group_selection_reason": selection_reason,
		"selected_base_cost": reference_row.get("selected_base_cost"),
		"cost_source_detail": reference_row.get("cost_source_detail")
	}
	for fieldname in price_fields:
		summary[fieldname] = (
			quantize_money(reference_row.get(fieldname))
			if _valid_group_price(reference_row.get(fieldname)) else None
		)
		gross_fieldname = fieldname[:-4] + "_gross" if fieldname.endswith("_net") else ""
		if gross_fieldname:
			summary[gross_fieldname] = reference_row.get(gross_fieldname)
	return summary


def apply_pricing_group_recommendations(rows, membership, filters):
	rows = rows or []
	membership = membership or {}
	filters = filters or {}
	groups = {}
	for row in rows:
		group_name = row.get("pricing_group")
		if group_name:
			groups.setdefault(group_name, []).append(row)
		else:
			row["pricing_group_status"] = ""
			row["pricing_group_member_count"] = 0
			row["sales_contribution_percent"] = None
			row["group_recommended_regular_net"] = None
			row["group_recommended_b2b_net"] = None
			for index in range(1, len(filters.get("tiers") or []) + 1):
				row["group_tier_{0}_net".format(index)] = None

	price_fields = ["recommended_regular_net"]
	if filters.get("b2b_price_list"):
		price_fields.append("recommended_b2b_net")
	price_fields.extend([
		"tier_{0}_net".format(index)
		for index in range(1, len(filters.get("tiers") or []) + 1)
	])

	summaries = {}
	for group_name, group_rows in groups.items():
		definition = membership.get(group_name) or {"disabled": 1, "item_codes": []}
		expected_codes = set(definition.get("item_codes") or [])
		present_codes = set(row.get("item_code") for row in group_rows if row.get("item_code"))
		valid_rows = [
			row for row in group_rows
			if all(_valid_group_price(row.get(fieldname)) for fieldname in price_fields)
		]
		if cint(definition.get("disabled")):
			status = "Disabled Group"
		elif expected_codes != present_codes:
			status = "Incomplete Group"
		elif not valid_rows:
			status = "Missing Cost"
		else:
			current_fields = ["current_normal_price"]
			if filters.get("b2b_price_list"):
				current_fields.append("current_b2b_price")
			different = any(len(set(
				str(row.get(fieldname)) for row in group_rows
			)) > 1 for fieldname in current_fields)
			status = "Different Current Prices" if different else "Ready"

		reference_candidates = valid_rows or group_rows
		reference_row, total_sales_qty, selection_reason = _pricing_group_reference_row(
			group_rows, reference_candidates
		)
		_set_group_sales_contributions(group_rows, reference_row, total_sales_qty)
		for row in group_rows:
			row["is_pricing_group_reference"] = int(row is reference_row)
		shared = {
			fieldname: (
				quantize_money(reference_row.get(fieldname))
				if _valid_group_price(reference_row.get(fieldname)) else None
			)
			for fieldname in price_fields
		}
		for row in group_rows:
			row["pricing_group_status"] = status
			row["pricing_group_member_count"] = len(expected_codes)
			row["group_recommended_regular_net"] = shared.get("recommended_regular_net")
			row["group_recommended_b2b_net"] = shared.get("recommended_b2b_net")
			for index in range(1, len(filters.get("tiers") or []) + 1):
				row["group_tier_{0}_net".format(index)] = shared.get(
					"tier_{0}_net".format(index)
				)
		summaries[group_name] = _pricing_group_summary_row(
			group_name, status, reference_row, price_fields, selection_reason
		)
	last_group_indexes = {}
	for index, row in enumerate(rows):
		if row.get("pricing_group"):
			last_group_indexes[row.get("pricing_group")] = index
	result = []
	for index, row in enumerate(rows):
		result.append(row)
		group_name = row.get("pricing_group")
		if group_name and last_group_indexes.get(group_name) == index:
			result.append(summaries[group_name])
	return result


def classify_updateable_pricing_groups(rows, requested_codes, limit=ITEM_PRICE_UPDATE_LIMIT):
	requested = set(list(requested_codes or [])[:limit])
	groups = {}
	ungrouped_items = []
	for row in rows or []:
		item_code = row.get("item_code")
		group_name = row.get("pricing_group")
		if group_name:
			groups.setdefault(group_name, []).append(row)
		elif item_code in requested:
			ungrouped_items.append(item_code)
	allowed_groups = []
	blocked_groups = {}
	for group_name, group_rows in groups.items():
		all_codes = set(row.get("item_code") for row in group_rows if row.get("item_code"))
		selected_codes = all_codes.intersection(requested)
		if not selected_codes:
			continue
		status = group_rows[0].get("pricing_group_status") or "Incomplete Group"
		if selected_codes != all_codes:
			blocked_groups[group_name] = "Incomplete Group"
		elif status not in ("Ready", "Different Current Prices"):
			blocked_groups[group_name] = status
		else:
			allowed_groups.append(group_name)
	return {
		"allowed_groups": sorted(allowed_groups),
		"blocked_groups": blocked_groups,
		"ungrouped_items": ungrouped_items
	}


def validate_master_filters(filters):
	company_currency = frappe.db.get_value("Company", filters["company"], "default_currency")
	if not company_currency:
		frappe.throw("Company {0} has no default currency".format(filters["company"]))

	for fieldname in ("regular_price_list", "b2b_price_list"):
		price_list = filters.get(fieldname)
		if not price_list:
			continue
		details = frappe.db.get_value(
			"Price List", price_list, ["enabled", "selling", "currency"], as_dict=True
		)
		if not details or not details.enabled or not details.selling:
			frappe.throw("Price List {0} must be enabled and marked as Selling".format(price_list))
		if details.currency != company_currency:
			frappe.throw(
				"Price List {0} must use company currency {1}".format(price_list, company_currency)
			)

	warehouse = filters.get("warehouse")
	if warehouse:
		warehouse_company = frappe.db.get_value("Warehouse", warehouse, "company")
		if warehouse_company != filters["company"]:
			frappe.throw("Warehouse must belong to the selected Company")
	return company_currency


def get_purchase_receipt_item_scope(filters, allow_empty=False):
	receipt_name = filters.get("purchase_receipt")
	if not receipt_name:
		return []
	receipt = frappe.db.get_value(
		"Purchase Receipt", receipt_name,
		["company", "docstatus", "is_return"], as_dict=True
	)
	if not receipt:
		frappe.throw("Purchase Receipt {0} does not exist".format(receipt_name))
	if not frappe.has_permission("Purchase Receipt", "read", receipt_name):
		frappe.throw(
			"You do not have permission to read Purchase Receipt {0}".format(receipt_name),
			frappe.PermissionError
		)
	if cint(receipt.docstatus) != 1:
		frappe.throw("Purchase Receipt {0} must be submitted".format(receipt_name))
	if cint(receipt.is_return):
		frappe.throw("A return Purchase Receipt cannot be used for pricing analysis")
	if receipt.company != filters.get("company"):
		frappe.throw("Purchase Receipt must belong to the selected Company")

	receipt_rows = frappe.get_all(
		"Purchase Receipt Item", filters={"parent": receipt_name},
		fields=["item_code"], order_by="idx asc", limit_page_length=0
	)
	direct_codes = []
	seen = set()
	for row in receipt_rows:
		item_code = row.get("item_code")
		if item_code and item_code not in seen:
			seen.add(item_code)
			direct_codes.append(item_code)
	if not direct_codes:
		frappe.throw("Purchase Receipt has no stock Items for pricing analysis")

	has_pricing_group = frappe.get_meta("Item").has_field("pricing_group")
	fields = ["name"]
	if has_pricing_group:
		fields.append("pricing_group")
	direct_items = frappe.get_all(
		"Item",
		filters={"name": ("in", direct_codes), "disabled": 0, "is_stock_item": 1},
		fields=fields, limit_page_length=0
	)
	direct_by_code = {row.name: row for row in direct_items}
	result = [item_code for item_code in direct_codes if item_code in direct_by_code]
	if not result:
		if allow_empty:
			return []
		frappe.throw("Purchase Receipt has no active stock Items for pricing analysis")

	group_names = sorted(set(
		row.get("pricing_group") for row in direct_items if row.get("pricing_group")
	))
	if group_names:
		group_items = frappe.get_all(
			"Item",
			filters={
				"pricing_group": ("in", group_names), "disabled": 0, "is_stock_item": 1
			},
			fields=["name", "pricing_group"], order_by="name asc", limit_page_length=0
		)
		for row in group_items:
			if row.name not in seen:
				seen.add(row.name)
				result.append(row.name)
	return result


@frappe.whitelist()
def get_purchase_receipt_pricing_eligibility(purchase_receipt=None, company=None):
	item_codes = get_purchase_receipt_item_scope({
		"purchase_receipt": purchase_receipt,
		"company": company
	}, allow_empty=True)
	if not item_codes:
		return {
			"eligible": False,
			"eligible_item_count": 0,
			"message": (
				"Purchase Receipt {0} has no active stock Items for pricing analysis. "
				"Its Items are disabled or do not maintain stock."
			).format(purchase_receipt)
		}
	return {
		"eligible": True,
		"eligible_item_count": len(item_codes),
		"message": None
	}


def get_items(filters):
	item_filters = {"disabled": 0, "is_stock_item": 1}
	has_pricing_group = validate_pricing_group_setup(filters)
	if filters.get("purchase_receipt"):
		item_scope = get_purchase_receipt_item_scope(filters, allow_empty=True)
		if not item_scope:
			return []
		item_filters["name"] = ("in", item_scope)
	elif filters.get("item"):
		item_filters["name"] = filters["item"]
	if not filters.get("purchase_receipt") and filters.get("pricing_group"):
		item_filters["pricing_group"] = filters["pricing_group"]
	if not filters.get("purchase_receipt") and filters.get("brand"):
		item_filters["brand"] = filters["brand"]
	if not filters.get("purchase_receipt") and filters.get("stock_uom"):
		item_filters["stock_uom"] = filters["stock_uom"]
	if not filters.get("purchase_receipt") and filters.get("item_group"):
		group = frappe.db.get_value(
			"Item Group", filters["item_group"], ["lft", "rgt"], as_dict=True
		)
		if not group:
			return []
		group_rows = frappe.get_all(
			"Item Group",
			filters={"lft": (">=", group.lft), "rgt": ("<=", group.rgt)},
			fields=["name"], limit_page_length=0
		)
		groups = [row.name for row in group_rows]
		item_filters["item_group"] = ("in", groups)
	fields = ["name as item_code", "item_name", "item_group", "brand", "stock_uom"]
	if has_pricing_group:
		fields.append("pricing_group")
	return frappe.get_list(
		"Item", filters=item_filters,
		fields=fields,
		order_by="name asc", limit_page_length=0
	)


def get_stock_data(filters, item_codes):
	if not item_codes:
		return {}
	values = {
		"company": filters["company"],
		"warehouse": filters.get("warehouse"),
		"item_codes": tuple(item_codes),
		"to_date": filters["to_date"]
	}
	bin_warehouse_condition = " and bin.warehouse = %(warehouse)s" if filters.get("warehouse") else ""
	bin_rows = frappe.db.sql("""
		select
			bin.item_code,
			sum(bin.actual_qty) as actual_qty,
			sum(case when bin.actual_qty > 0 then bin.actual_qty else 0 end) as positive_qty,
			sum(case when bin.actual_qty > 0 then bin.actual_qty * bin.valuation_rate else 0 end) as valuation_value
		from `tabBin` bin
		inner join `tabWarehouse` warehouse on warehouse.name = bin.warehouse
		where warehouse.company = %(company)s
			and warehouse.disabled = 0
			and bin.item_code in %(item_codes)s
			{warehouse_condition}
		group by bin.item_code
	""".format(warehouse_condition=bin_warehouse_condition), values, as_dict=True)
	positive_items = set(
		row.get("item_code") for row in bin_rows if to_decimal(row.get("positive_qty")) > 0
	)
	fallback_items = tuple(code for code in item_codes if code not in positive_items)
	sle_rows = []
	if fallback_items:
		values["fallback_items"] = fallback_items
		sle_warehouse_condition = " and sle.warehouse = %(warehouse)s" if filters.get("warehouse") else ""
		sle_rows = frappe.db.sql("""
			select sle.item_code, sle.valuation_rate
			from `tabStock Ledger Entry` sle
			inner join `tabWarehouse` warehouse on warehouse.name = sle.warehouse
			where sle.docstatus < 2
				and warehouse.company = %(company)s
				and sle.item_code in %(fallback_items)s
				and sle.posting_date <= %(to_date)s
				{warehouse_condition}
			order by sle.item_code, sle.posting_date desc, sle.posting_time desc, sle.creation desc
		""".format(warehouse_condition=sle_warehouse_condition), values, as_dict=True)
	return normalize_stock_rows(bin_rows, sle_rows)


def normalize_stock_rows(bin_rows, sle_rows):
	result = {}
	for row in bin_rows or []:
		item_code = row.get("item_code")
		positive_qty = to_decimal(row.get("positive_qty", row.get("actual_qty")))
		valuation_rate = None
		if positive_qty > 0:
			valuation_rate = quantize_money(to_decimal(row.get("valuation_value")) / positive_qty)
		result[item_code] = {
			"available_qty": quantize_money(row.get("actual_qty")),
			"valuation_rate": valuation_rate,
			"warnings": []
		}
	for row in sle_rows or []:
		item_code = row.get("item_code")
		entry = result.setdefault(item_code, {
			"available_qty": Decimal("0.000"), "valuation_rate": None, "warnings": []
		})
		if entry["valuation_rate"] is None and to_decimal(row.get("valuation_rate")) > 0:
			entry["valuation_rate"] = quantize_money(row.get("valuation_rate"))
			entry["warnings"].append("Valuation uses latest Stock Ledger rate")
	return result


def get_purchase_data(filters, item_codes):
	if not item_codes:
		return {}
	values = {
		"company": filters["company"],
		"to_date": filters["to_date"], "item_codes": tuple(item_codes)
	}
	pr_warehouse_condition = " and pri.warehouse = %(warehouse)s" \
		if filters.get("warehouse") else ""
	pi_warehouse_condition = " and pii.warehouse = %(warehouse)s" \
		if filters.get("warehouse") else ""
	if filters.get("warehouse"):
		values["warehouse"] = filters["warehouse"]
	latest_rows = frappe.db.sql("""
		select receipt.item_code, receipt.valuation_rate as latest_purchase_rate
		from (
			select pri.item_code, pri.valuation_rate, pr.posting_date,
				pr.posting_time, pr.creation, pri.idx
			from `tabPurchase Receipt Item` pri
			inner join `tabPurchase Receipt` pr on pr.name = pri.parent
			where pr.docstatus = 1 and pr.company = %(company)s
				and pr.posting_date <= %(to_date)s
				and pri.item_code in %(item_codes)s and pri.stock_qty > 0
				and pri.valuation_rate > 0
				{pr_warehouse_condition}
			union all
			select pii.item_code, pii.valuation_rate, pi.posting_date,
				pi.posting_time, pi.creation, pii.idx
			from `tabPurchase Invoice Item` pii
			inner join `tabPurchase Invoice` pi on pi.name = pii.parent
			where pi.docstatus = 1 and pi.company = %(company)s and pi.update_stock = 1
				and pi.posting_date <= %(to_date)s
				and pii.item_code in %(item_codes)s and pii.stock_qty > 0
				and pii.valuation_rate > 0
				{pi_warehouse_condition}
		) receipt
		order by receipt.item_code, receipt.posting_date desc,
			receipt.posting_time desc, receipt.creation desc, receipt.idx desc
	""".format(
		pr_warehouse_condition=pr_warehouse_condition,
		pi_warehouse_condition=pi_warehouse_condition
	), values, as_dict=True)
	return normalize_purchase_rows(latest_rows)


def normalize_purchase_rows(latest_rows):
	result = {}
	for row in latest_rows or []:
		entry = result.setdefault(row.get("item_code"), {"warnings": []})
		if "latest_purchase_rate" not in entry:
			entry["latest_purchase_rate"] = quantize_money(row.get("latest_purchase_rate"))
	for entry in result.values():
		entry.setdefault("latest_purchase_rate", None)
	return result


def get_sales_data(filters, item_codes):
	if not item_codes:
		return {}
	sales_filters = {
		"company": filters.get("company"),
		"from_date": filters.get("from_date"),
		"to_date": filters.get("to_date"),
		"warehouse": filters.get("warehouse"),
		"include_returns": 1,
		"sales_basis": "All"
	}
	return get_item_sales_aggregates(sales_filters, item_codes)


def get_item_cogs(filters, item_codes):
	if not item_codes:
		return {}
	values = {
		"company": filters.get("company"),
		"from_date": filters.get("from_date"),
		"to_date": filters.get("to_date"),
		"item_codes": tuple(item_codes),
		"warehouse": filters.get("warehouse")
	}
	warehouse_condition = " and sle.warehouse = %(warehouse)s" \
		if filters.get("warehouse") else ""
	rows = frappe.db.sql("""
		select sle.item_code, coalesce(sum(-sle.stock_value_difference), 0) as net_cogs
		from `tabStock Ledger Entry` sle
		inner join `tabWarehouse` warehouse on warehouse.name = sle.warehouse
		where sle.docstatus < 2 and warehouse.company = %(company)s
			and sle.posting_date between %(from_date)s and %(to_date)s
			and sle.voucher_type in ('Delivery Note', 'Sales Invoice')
			and sle.item_code in %(item_codes)s
			{warehouse_condition}
		group by sle.item_code
	""".format(warehouse_condition=warehouse_condition), values, as_dict=True)
	return dict(
		(row.get("item_code"), quantize_money(row.get("net_cogs")))
		for row in rows or []
	)


def get_indirect_expense_context(filters):
	expense_account = filters.get("indirect_expense_account") or INDIRECT_EXPENSE_ACCOUNT
	account = frappe.db.get_value(
		"Account", expense_account, ["lft", "rgt"], as_dict=True
	)
	if not account:
		return {
			"expense_total": Decimal("0.000"), "net_cogs": Decimal("0.000"),
			"expense_ratio": Decimal("0.000000"),
			"warnings": ["Indirect expense account not found: {0}".format(expense_account)]
		}
	values = {
		"company": filters["company"], "from_date": filters["from_date"],
		"to_date": filters["to_date"], "lft": account.lft, "rgt": account.rgt
	}
	expense_rows = frappe.db.sql("""
		select coalesce(sum(gle.debit - gle.credit), 0) as expense_total
		from `tabGL Entry` gle
		inner join `tabAccount` account on account.name = gle.account
		where gle.docstatus = 1 and gle.company = %(company)s
			and gle.posting_date between %(from_date)s and %(to_date)s
			and account.company = %(company)s
			and account.lft between %(lft)s and %(rgt)s
			and gle.voucher_type != 'Period Closing Voucher'
	""", values, as_dict=True)
	cogs_rows = frappe.db.sql("""
		select coalesce(sum(-sle.stock_value_difference), 0) as net_cogs
		from `tabStock Ledger Entry` sle
		inner join `tabWarehouse` warehouse on warehouse.name = sle.warehouse
		where sle.docstatus < 2 and warehouse.company = %(company)s
			and sle.posting_date between %(from_date)s and %(to_date)s
			and sle.voucher_type in ('Delivery Note', 'Sales Invoice')
	""", values, as_dict=True)
	expense_total = to_decimal(expense_rows[0].get("expense_total") if expense_rows else 0)
	net_cogs = to_decimal(cogs_rows[0].get("net_cogs") if cogs_rows else 0)
	warnings = []
	expense_ratio = Decimal("0")
	if net_cogs > 0:
		expense_ratio = expense_total / net_cogs
	elif expense_total > 0:
		warnings.append("Indirect expenses cannot be allocated because company net COGS is zero")
	return {
		"expense_total": quantize_money(expense_total),
		"net_cogs": quantize_money(net_cogs),
		"expense_ratio": expense_ratio.quantize(RATIO_QUANTUM, rounding=ROUND_HALF_UP),
		"warnings": warnings
	}


def normalize_sales_rows(rows, latest_rows=None):
	result = {}
	for row in rows or []:
		qty = to_decimal(row.get("sales_qty"))
		entry = dict(row)
		entry["warnings"] = list(entry.get("warnings") or [])
		entry["sales_qty"] = quantize_money(qty)
		entry["sales_value"] = quantize_money(row.get("sales_value"))
		entry["weighted_average_sold_rate"] = None
		if qty > 0:
			entry["weighted_average_sold_rate"] = quantize_money(
				to_decimal(row.get("sales_value")) / qty
			)
		else:
			entry["warnings"].append("Sales returns equal or exceed sales")
		for fieldname in ("last_sold_rate", "lowest_sold_rate", "highest_sold_rate"):
			if entry.get(fieldname) is not None:
				entry[fieldname] = quantize_money(entry[fieldname])
		result[row.get("item_code")] = entry
	for row in latest_rows or []:
		entry = result.get(row.get("item_code"))
		if entry is not None and entry.get("last_sold_rate") is None:
			entry["last_sold_rate"] = quantize_money(row.get("last_sold_rate"))
	return result


def get_item_prices(filters, item_codes):
	if not item_codes:
		return {}
	price_lists = [filters["regular_price_list"]]
	if filters.get("b2b_price_list"):
		price_lists.append(filters["b2b_price_list"])
	rows = frappe.db.sql("""
		select ip.name, ip.item_code, ip.price_list, ip.price_list_rate, ip.uom,
			ip.valid_from, ip.valid_upto, ip.creation
		from `tabItem Price` ip
		inner join `tabPrice List` price_list on price_list.name = ip.price_list
		inner join `tabItem` item on item.name = ip.item_code
		where ip.selling = 1 and ip.item_code in %(item_codes)s
			and ip.price_list in %(price_lists)s
			and (ip.valid_from is null or ip.valid_from <= %(to_date)s)
			and (ip.valid_upto is null or ip.valid_upto >= %(to_date)s)
			and (price_list.price_not_uom_dependent = 1 or ifnull(ip.uom, '') = '' or ip.uom = item.stock_uom)
		order by ip.item_code, ip.price_list, ip.valid_from desc, ip.creation desc, ip.name desc
	""", {
		"item_codes": tuple(item_codes), "price_lists": tuple(price_lists),
		"to_date": filters["to_date"]
	}, as_dict=True)
	return normalize_item_prices(
		rows, filters["regular_price_list"], filters.get("b2b_price_list")
	)


def normalize_item_prices(rows, regular_price_list, b2b_price_list):
	result = {}
	grouped = {}
	for row in rows or []:
		key = (row.get("item_code"), row.get("price_list"))
		grouped.setdefault(key, []).append(row)
	for key, price_rows in grouped.items():
		item_code, price_list = key
		price_rows.sort(key=lambda row: (
			str(row.get("valid_from") or ""), str(row.get("creation") or ""),
			str(row.get("name") or "")
		), reverse=True)
		entry = result.setdefault(item_code, {"warnings": []})
		if price_list == regular_price_list:
			entry["current_normal_price"] = quantize_money(price_rows[0].get("price_list_rate"))
			if len(price_rows) > 1:
				entry["warnings"].append("Multiple valid normal Item Prices")
		elif b2b_price_list and price_list == b2b_price_list:
			entry["current_b2b_price"] = quantize_money(price_rows[0].get("price_list_rate"))
			if len(price_rows) > 1:
				entry["warnings"].append("Multiple valid B2B Item Prices")
	for entry in result.values():
		entry.setdefault("current_normal_price", None)
		entry.setdefault("current_b2b_price", None)
	return result


def execute(filters=None):
	filters = validate_and_normalize_filters(filters)
	validate_master_filters(filters)
	items = get_items(filters)
	if filters.get("purchase_receipt") and not items:
		return (
			get_columns(filters), [],
			"Purchase Receipt {0} has no active stock Items for pricing analysis.".format(
				filters.get("purchase_receipt")
			),
			None
		)
	item_codes = [row.get("item_code") for row in items]
	stock_data = get_stock_data(filters, item_codes)
	purchase_data = get_purchase_data(filters, item_codes)
	sales_data = get_sales_data(filters, item_codes)
	item_cogs = get_item_cogs(filters, item_codes)
	price_data = get_item_prices(filters, item_codes)
	expense_context = get_indirect_expense_context(filters)

	data = []
	for item in items:
		item_code = item.get("item_code")
		sales = sales_data.get(item_code)
		if filters["exclude_items_without_sales"] and not sales:
			continue
		stock = stock_data.get(item_code, {})
		purchase = purchase_data.get(item_code, {})
		prices = price_data.get(item_code, {})
		row = dict(item)
		row.update({
			"available_qty": stock.get("available_qty", Decimal("0.000")),
			"valuation_rate": stock.get("valuation_rate"),
			"latest_purchase_rate": purchase.get("latest_purchase_rate"),
			"current_normal_price": prices.get("current_normal_price"),
			"current_b2b_price": prices.get("current_b2b_price")
		})
		if sales:
			row.update(sales)
		row["net_cogs"] = item_cogs.get(item_code, Decimal("0.000"))
		_set_selected_cost(row, filters["cost_source"])
		allocation = calculate_expense_allocation(
			row.get("sales_qty"), row.get("net_cogs"),
			row.get("selected_base_cost"), expense_context["expense_ratio"]
		)
		row.update({
			"allocated_expense": allocation["allocated_expense"],
			"expense_per_unit": allocation["expense_per_unit"],
			"expense_source": allocation["expense_source"],
			"company_expense_total": expense_context["expense_total"],
			"company_net_cogs": expense_context["net_cogs"],
			"company_expense_ratio": expense_context["expense_ratio"]
		})
		warnings = []
		for source in (stock, purchase, sales or {}, prices):
			warnings.extend(source.get("warnings") or [])
		warnings.extend(allocation["warnings"])
		if not sales:
			warnings.append("No recent sales")
		row["warnings"] = warnings
		row = calculate_item_row(row, filters)
		_add_analysis_warnings(row)
		data.append(row)

	group_names = set(row.get("pricing_group") for row in data if row.get("pricing_group"))
	group_membership = get_pricing_group_membership(group_names) if group_names else {}
	data = apply_pricing_group_recommendations(data, group_membership, filters)
	data = [_serialize_row(row) for row in data]

	messages = list(filters["gap_messages"])
	if expense_context["expense_total"] > 0:
		messages.append(
			"Indirect expense allocation: {0} / {1} net COGS = {2}%".format(
				expense_context["expense_total"], expense_context["net_cogs"],
				(expense_context["expense_ratio"] * Decimal("100")).quantize(PERCENT_QUANTUM)
			)
		)
	messages.extend(expense_context["warnings"])
	message = "<br>".join(messages) if messages else None
	return get_columns(filters), data, message, None


def _set_selected_cost(row, cost_source):
	field_by_source = {
		"Current Valuation Rate": "valuation_rate",
		"Latest Valuation Rate": "latest_purchase_rate"
	}
	fieldname = field_by_source[cost_source]
	row["selected_base_cost"] = row.get(fieldname)
	row["cost_source_detail"] = cost_source


def _add_analysis_warnings(row):
	warnings = []
	if row.get("warnings"):
		warnings.extend(str(row["warnings"]).split("; "))
	loaded_cost = row.get("fully_loaded_cost")
	current_price = row.get("current_normal_price")
	average_rate = row.get("weighted_average_sold_rate")
	recommended = row.get("recommended_regular_net")
	if loaded_cost is not None and current_price is not None:
		if to_decimal(current_price) < to_decimal(loaded_cost):
			warnings.append("Current normal price is below loaded cost")
	if recommended is not None and average_rate is not None:
		if to_decimal(recommended) < to_decimal(average_rate):
			warnings.append("Recommended regular price is below historical average")
	row["warnings"] = compose_warnings(warnings)


def _serialize_row(row):
	result = {}
	for key, value in row.items():
		result[key] = float(value) if isinstance(value, Decimal) else value
	return result


def get_columns(filters):
	columns = [
		_column("Item Code", "item_code", "Link", 130, "Item"),
		_column("Item Group", "item_group", "Link", 130, "Item Group"),
		_column("Pricing Group", "pricing_group", "Link", 145, "Pricing Group"),
		_column("Brand", "brand", "Link", 100, "Brand"),
		_column("Stock UOM", "stock_uom", "Link", 90, "UOM"),
		_column("Available Qty", "available_qty", "Float", 100),
		_column("Base Cost", "selected_base_cost", "Currency", 120),
		_column("Expense / Unit", "expense_per_unit", "Currency", 110),
		_column("Cost + Expense", "fully_loaded_cost", "Currency", 120),
		_column("Sales Qty", "sales_qty", "Float", 90),
		_column("Sales Contribution %", "sales_contribution_percent", "Percent", 135),
		_column("Last Sold Rate", "last_sold_rate", "Currency", 105),
		_column("Average Sold Rate", "weighted_average_sold_rate", "Currency", 115),
		_column("Current Regular Price", "current_normal_price", "Currency", 125)
	]
	columns.extend(_compact_price_columns("Regular", "recommended_regular"))
	columns.extend([
		_column("Change from Current Regular %", "change_from_current_normal_percent", "Percent", 155)
	])
	if filters.get("enable_b2b_pricing"):
		columns.append(_column("Current B2B Price", "current_b2b_price", "Currency", 115))
		columns.extend(_compact_price_columns("B2B", "recommended_b2b"))
		columns.append(_column("B2B Discount from Regular %", "b2b_discount_percent", "Percent", 155))
	for index, tier in enumerate(filters["tiers"], 1):
		label = _tier_label(tier)
		prefix = "tier_{0}".format(index)
		columns.extend([
			_column(label + " Net", prefix + "_net", "Currency", 105),
			_column(label + " Discount %", prefix + "_discount_percent", "Percent", 120),
			_column(label + " Gross Margin %", prefix + "_gross_margin_percent", "Percent", 135)
		])
	columns.extend([
		_column("Average Actual Markup %", "average_actual_markup_percent", "Percent", 165),
		_column("Average Gross Margin %", "average_gross_margin_percent", "Percent", 155),
		_column("Average Discount %", "average_discount_percent", "Percent", 145)
	])
	return columns


def _compact_price_columns(label, prefix):
	return [
		_column("Strategy {0} Net".format(label), prefix + "_net", "Currency", 130),
		_column(label + " Gross Margin %", prefix + "_gross_margin_percent", "Percent", 130)
	]


def _price_columns(label, prefix, include_markup):
	columns = [
		_column("Strategy {0} Net".format(label), prefix + "_net", "Currency", 130),
		_column("Strategy {0} Incl. VAT".format(label), prefix + "_gross", "Currency", 145),
		_column(label + " Profit/Unit", prefix + "_profit", "Currency", 115)
	]
	if include_markup:
		columns.append(_column(label + " Actual Markup %", prefix + "_actual_markup_percent", "Percent", 130))
	columns.append(_column(label + " Gross Margin %", prefix + "_gross_margin_percent", "Percent", 130))
	return columns


def _tier_label(tier):
	minimum = _format_decimal(tier["minimum"])
	if tier["maximum"] is None:
		return "Qty {0}+".format(minimum)
	return "Qty {0}-{1}".format(minimum, _format_decimal(tier["maximum"]))


def _column(label, fieldname, fieldtype, width, options=None):
	column = {
		"label": label, "fieldname": fieldname, "fieldtype": fieldtype, "width": width
	}
	if options:
		column["options"] = options
	return column
