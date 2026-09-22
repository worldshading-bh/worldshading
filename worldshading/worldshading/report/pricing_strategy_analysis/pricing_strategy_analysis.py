from __future__ import unicode_literals

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import frappe
from frappe.utils import cint, getdate


MONEY_QUANTUM = Decimal("0.001")
PERCENT_QUANTUM = Decimal("0.001")

COST_SOURCES = (
	"Current Valuation Rate",
	"Latest Purchase Rate",
	"Weighted Average Purchase Rate"
)
ROUNDING_METHODS = ("Nearest", "Up", "Down")


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


def round_to_increment(value, increment, method):
	value = to_decimal(value)
	increment = to_decimal(increment)
	if increment <= 0:
		frappe.throw("Rounding Increment must be greater than zero")
	if method not in ROUNDING_METHODS:
		frappe.throw("Unsupported Rounding Method: {0}".format(method))

	units = value / increment
	if method == "Nearest":
		rounded_units = units.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
	elif method == "Up":
		rounded_units = units.quantize(Decimal("1"), rounding=ROUND_CEILING)
	else:
		rounded_units = units.quantize(Decimal("1"), rounding=ROUND_FLOOR)
	return rounded_units * increment


def calculate_price(loaded_cost, markup_percent, vat_percent, increment, method):
	loaded_cost = to_decimal(loaded_cost)
	markup_percent = to_decimal(markup_percent)
	vat_percent = to_decimal(vat_percent)
	if loaded_cost <= 0:
		return None

	raw_net_price = loaded_cost * (Decimal("1") + markup_percent / Decimal("100"))
	raw_gross_price = raw_net_price * (Decimal("1") + vat_percent / Decimal("100"))
	rounded_gross_price = round_to_increment(raw_gross_price, increment, method)
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
		"gross_margin_percent": quantize_percent(gross_margin)
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


def validate_and_normalize_filters(filters):
	filters = dict(filters or {})
	result = dict(filters)

	for fieldname in ("company", "from_date", "to_date", "regular_price_list"):
		if not filters.get(fieldname):
			frappe.throw("{0} is required".format(fieldname.replace("_", " ").title()))

	result["from_date"] = getdate(filters.get("from_date"))
	result["to_date"] = getdate(filters.get("to_date"))
	if result["from_date"] > result["to_date"]:
		frappe.throw("From Date cannot be after To Date")

	result["cost_source"] = filters.get("cost_source") or "Current Valuation Rate"
	if result["cost_source"] not in COST_SOURCES:
		frappe.throw("Unsupported Cost Source: {0}".format(result["cost_source"]))

	result["rounding_method"] = filters.get("rounding_method") or "Nearest"
	if result["rounding_method"] not in ROUNDING_METHODS:
		frappe.throw("Unsupported Rounding Method: {0}".format(result["rounding_method"]))

	numeric_defaults = {
		"expense_burden": "0",
		"vat_percent": "10",
		"rounding_increment": "1",
		"regular_markup": "43",
		"b2b_markup": "33"
	}
	for fieldname, default in numeric_defaults.items():
		value = filters.get(fieldname)
		result[fieldname] = to_decimal(default if value in (None, "") else value)

	for fieldname in ("expense_burden", "vat_percent", "regular_markup", "b2b_markup"):
		if result[fieldname] < 0:
			frappe.throw("{0} cannot be negative".format(fieldname.replace("_", " ").title()))
	if result["rounding_increment"] <= 0:
		frappe.throw("Rounding Increment must be greater than zero")

	result["include_items_without_sales"] = bool(cint(filters.get("include_items_without_sales", 1)))
	result["tiers"] = _normalize_tiers(filters)
	result["gap_messages"] = _validate_tiers(result["tiers"])
	return result


def _normalize_tiers(filters):
	defaults = (
		("5", "9", "31"),
		("10", "19", "29"),
		("20", "39", "27"),
		("40", None, "25")
	)
	tiers = []
	for index, default_values in enumerate(defaults, 1):
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
	base_cost = to_decimal(row.get("selected_base_cost"))
	if base_cost <= 0:
		row.update({
			"selected_base_cost": None,
			"expense_amount": None,
			"fully_loaded_cost": None,
			"suggested_action": "",
			"warnings": compose_warnings(warnings + ["Missing cost"])
		})
		return row

	expense_amount = base_cost * context["expense_burden"] / Decimal("100")
	loaded_cost = base_cost + expense_amount
	row["selected_base_cost"] = quantize_money(base_cost)
	row["expense_amount"] = quantize_money(expense_amount)
	row["fully_loaded_cost"] = quantize_money(loaded_cost)

	regular = calculate_price(
		loaded_cost, context["regular_markup"], context["vat_percent"],
		context["rounding_increment"], context["rounding_method"]
	)
	b2b = calculate_price(
		loaded_cost, context["b2b_markup"], context["vat_percent"],
		context["rounding_increment"], context["rounding_method"]
	)
	_apply_price_result(row, "recommended_regular", regular)
	_apply_price_result(row, "recommended_b2b", b2b)
	row["b2b_discount_percent"] = _percentage_difference(regular["net_price"], b2b["net_price"])

	for index, tier in enumerate(context["tiers"], 1):
		tier_result = calculate_price(
			loaded_cost, tier["markup"], context["vat_percent"],
			context["rounding_increment"], context["rounding_method"]
		)
		_apply_price_result(row, "tier_{0}".format(index), tier_result)
		row["tier_{0}_discount_percent".format(index)] = _percentage_difference(
			b2b["net_price"], tier_result["net_price"]
		)

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
		current_price, regular["net_price"], context["rounding_increment"]
	)
	row["warnings"] = compose_warnings(warnings)
	return row


def _apply_price_result(row, prefix, result):
	row[prefix + "_net"] = result["net_price"]
	row[prefix + "_gross"] = result["gross_price"]
	row[prefix + "_profit"] = result["profit"]
	row[prefix + "_actual_markup_percent"] = result["actual_markup_percent"]
	row[prefix + "_gross_margin_percent"] = result["gross_margin_percent"]


def _percentage_difference(base_value, lower_value):
	base_value = to_decimal(base_value)
	if not base_value:
		return None
	return quantize_percent(
		(base_value - to_decimal(lower_value)) / base_value * Decimal("100")
	)
