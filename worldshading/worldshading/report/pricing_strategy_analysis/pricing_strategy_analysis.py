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
		for prefix in ["recommended_regular", "recommended_b2b"] + [
			"tier_{0}".format(index) for index in range(1, 5)
		]:
			for suffix in ("net", "gross", "profit", "actual_markup_percent", "gross_margin_percent"):
				row[prefix + "_" + suffix] = None
		row["b2b_discount_percent"] = None
		row["change_from_current_normal"] = None
		row["change_from_current_normal_percent"] = None
		for index in range(1, 5):
			row["tier_{0}_discount_percent".format(index)] = None
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


def get_items(filters):
	item_filters = {"disabled": 0, "is_stock_item": 1}
	if filters.get("item"):
		item_filters["name"] = filters["item"]
	if filters.get("brand"):
		item_filters["brand"] = filters["brand"]
	if filters.get("item_group"):
		group = frappe.db.get_value(
			"Item Group", filters["item_group"], ["lft", "rgt"], as_dict=True
		)
		if not group:
			return []
		groups = frappe.get_all(
			"Item Group",
			filters={"lft": (">=", group.lft), "rgt": ("<=", group.rgt)},
			pluck="name"
		)
		item_filters["item_group"] = ("in", groups)
	return frappe.get_all(
		"Item", filters=item_filters,
		fields=["name as item_code", "item_name", "item_group", "brand", "stock_uom"],
		order_by="name asc"
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
	warehouse_condition = " and warehouse = %(warehouse)s" if filters.get("warehouse") else ""
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
	""".format(warehouse_condition=warehouse_condition), values, as_dict=True)
	positive_items = set(
		row.get("item_code") for row in bin_rows if to_decimal(row.get("positive_qty")) > 0
	)
	fallback_items = tuple(code for code in item_codes if code not in positive_items)
	sle_rows = []
	if fallback_items:
		values["fallback_items"] = fallback_items
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
		""".format(warehouse_condition=warehouse_condition), values, as_dict=True)
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
		"company": filters["company"], "from_date": filters["from_date"],
		"to_date": filters["to_date"], "item_codes": tuple(item_codes)
	}
	average_rows = frappe.db.sql("""
		select pri.item_code, sum(pri.stock_qty) as purchase_qty,
			sum(pri.base_net_amount) as purchase_value
		from `tabPurchase Receipt Item` pri
		inner join `tabPurchase Receipt` pr on pr.name = pri.parent
		where pr.docstatus = 1 and pr.company = %(company)s
			and pr.posting_date between %(from_date)s and %(to_date)s
			and pri.item_code in %(item_codes)s
		group by pri.item_code
	""", values, as_dict=True)
	latest_rows = frappe.db.sql("""
		select pri.item_code,
			case when pri.stock_qty = 0 then null else pri.base_net_amount / pri.stock_qty end as latest_purchase_rate
		from `tabPurchase Receipt Item` pri
		inner join `tabPurchase Receipt` pr on pr.name = pri.parent
		where pr.docstatus = 1 and pr.company = %(company)s
			and pr.posting_date <= %(to_date)s
			and pri.item_code in %(item_codes)s and pri.stock_qty > 0
		order by pri.item_code, pr.posting_date desc, pr.posting_time desc, pr.creation desc, pri.idx desc
	""", values, as_dict=True)
	return normalize_purchase_rows(average_rows, latest_rows)


def normalize_purchase_rows(average_rows, latest_rows):
	result = {}
	for row in average_rows or []:
		qty = to_decimal(row.get("purchase_qty"))
		entry = result.setdefault(row.get("item_code"), {"warnings": []})
		entry["weighted_average_purchase_rate"] = None
		if qty > 0:
			entry["weighted_average_purchase_rate"] = quantize_money(
				to_decimal(row.get("purchase_value")) / qty
			)
		else:
			entry["warnings"].append("Purchase returns equal or exceed purchases")
	for row in latest_rows or []:
		entry = result.setdefault(row.get("item_code"), {"warnings": []})
		if "latest_purchase_rate" not in entry:
			entry["latest_purchase_rate"] = quantize_money(row.get("latest_purchase_rate"))
	for entry in result.values():
		entry.setdefault("latest_purchase_rate", None)
		entry.setdefault("weighted_average_purchase_rate", None)
	return result


def get_sales_data(filters, item_codes):
	if not item_codes:
		return {}
	rows = frappe.db.sql("""
		select sii.item_code, sum(sii.stock_qty) as sales_qty,
			sum(sii.base_net_amount) as sales_value,
			count(distinct si.name) as invoice_count,
			max(si.posting_date) as last_sale_date,
			min(case when sii.stock_qty > 0 then sii.base_net_amount / sii.stock_qty end) as lowest_sold_rate,
			max(case when sii.stock_qty > 0 then sii.base_net_amount / sii.stock_qty end) as highest_sold_rate
		from `tabSales Invoice Item` sii
		inner join `tabSales Invoice` si on si.name = sii.parent
		where si.docstatus = 1 and si.company = %(company)s
			and si.posting_date between %(from_date)s and %(to_date)s
			and sii.item_code in %(item_codes)s
		group by sii.item_code
	""", {
		"company": filters["company"], "from_date": filters["from_date"],
		"to_date": filters["to_date"], "item_codes": tuple(item_codes)
	}, as_dict=True)
	return normalize_sales_rows(rows)


def normalize_sales_rows(rows):
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
	return result


def get_item_prices(filters, item_codes):
	if not item_codes:
		return {}
	price_lists = [filters["regular_price_list"]]
	if filters.get("b2b_price_list"):
		price_lists.append(filters["b2b_price_list"])
	rows = frappe.db.sql("""
		select name, item_code, price_list, price_list_rate, uom, valid_from, valid_upto, creation
		from `tabItem Price`
		where selling = 1 and item_code in %(item_codes)s and price_list in %(price_lists)s
			and (valid_from is null or valid_from <= %(to_date)s)
			and (valid_upto is null or valid_upto >= %(to_date)s)
			and (min_qty is null or min_qty <= 1)
		order by item_code, price_list, valid_from desc, creation desc, name desc
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
	item_codes = [row.get("item_code") for row in items]
	stock_data = get_stock_data(filters, item_codes)
	purchase_data = get_purchase_data(filters, item_codes)
	sales_data = get_sales_data(filters, item_codes)
	price_data = get_item_prices(filters, item_codes)

	data = []
	for item in items:
		item_code = item.get("item_code")
		sales = sales_data.get(item_code)
		if not filters["include_items_without_sales"] and not sales:
			continue
		stock = stock_data.get(item_code, {})
		purchase = purchase_data.get(item_code, {})
		prices = price_data.get(item_code, {})
		row = dict(item)
		row.update({
			"available_qty": stock.get("available_qty", Decimal("0.000")),
			"valuation_rate": stock.get("valuation_rate"),
			"latest_purchase_rate": purchase.get("latest_purchase_rate"),
			"weighted_average_purchase_rate": purchase.get("weighted_average_purchase_rate"),
			"current_normal_price": prices.get("current_normal_price"),
			"current_b2b_price": prices.get("current_b2b_price")
		})
		if sales:
			row.update(sales)
		warnings = []
		for source in (stock, purchase, sales or {}, prices):
			warnings.extend(source.get("warnings") or [])
		if not sales:
			warnings.append("No recent sales")
		row["warnings"] = warnings
		_set_selected_cost(row, filters["cost_source"])
		row = calculate_item_row(row, filters)
		_add_analysis_warnings(row)
		data.append(_serialize_row(row))

	message = None
	if filters["gap_messages"]:
		message = "<br>".join(filters["gap_messages"])
	return get_columns(filters), data, message, None


def _set_selected_cost(row, cost_source):
	field_by_source = {
		"Current Valuation Rate": "valuation_rate",
		"Latest Purchase Rate": "latest_purchase_rate",
		"Weighted Average Purchase Rate": "weighted_average_purchase_rate"
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
		_column("Item Name", "item_name", "Data", 200),
		_column("Item Group", "item_group", "Link", 130, "Item Group"),
		_column("Brand", "brand", "Link", 100, "Brand"),
		_column("Stock UOM", "stock_uom", "Link", 90, "UOM"),
		_column("Available Qty", "available_qty", "Float", 100),
		_column("Valuation Rate", "valuation_rate", "Currency", 110),
		_column("Latest Purchase Rate", "latest_purchase_rate", "Currency", 125),
		_column("Average Purchase Rate", "weighted_average_purchase_rate", "Currency", 130),
		_column("Selected Base Cost", "selected_base_cost", "Currency", 120),
		_column("Cost Source", "cost_source_detail", "Data", 150),
		_column("Expense Amount", "expense_amount", "Currency", 110),
		_column("Fully Loaded Cost", "fully_loaded_cost", "Currency", 120),
		_column("Sales Qty", "sales_qty", "Float", 90),
		_column("Sales Value", "sales_value", "Currency", 105),
		_column("Invoice Count", "invoice_count", "Int", 95),
		_column("Last Sale Date", "last_sale_date", "Date", 105),
		_column("Last Sold Rate", "last_sold_rate", "Currency", 105),
		_column("Average Sold Rate", "weighted_average_sold_rate", "Currency", 115),
		_column("Lowest Sold Rate", "lowest_sold_rate", "Currency", 110),
		_column("Highest Sold Rate", "highest_sold_rate", "Currency", 110),
		_column("Current Normal Price", "current_normal_price", "Currency", 125),
		_column("Current B2B Price", "current_b2b_price", "Currency", 115)
	]
	columns.extend(_price_columns("Regular", "recommended_regular", True))
	columns.extend([
		_column("Change from Current", "change_from_current_normal", "Currency", 120),
		_column("Change from Current %", "change_from_current_normal_percent", "Percent", 130)
	])
	columns.extend(_price_columns("B2B", "recommended_b2b", False))
	columns.append(_column("B2B Discount from Regular %", "b2b_discount_percent", "Percent", 155))
	for index, tier in enumerate(filters["tiers"], 1):
		label = _tier_label(tier)
		prefix = "tier_{0}".format(index)
		columns.extend([
			_column(label + " Net", prefix + "_net", "Currency", 105),
			_column(label + " Incl. VAT", prefix + "_gross", "Currency", 115),
			_column(label + " Discount %", prefix + "_discount_percent", "Percent", 120),
			_column(label + " Profit/Unit", prefix + "_profit", "Currency", 115),
			_column(label + " Gross Margin %", prefix + "_gross_margin_percent", "Percent", 135)
		])
	columns.extend([
		_column("Suggested Action", "suggested_action", "Data", 110),
		_column("Warnings", "warnings", "Data", 280)
	])
	return columns


def _price_columns(label, prefix, include_markup):
	columns = [
		_column("Recommended {0} Net".format(label), prefix + "_net", "Currency", 130),
		_column("Recommended {0} Incl. VAT".format(label), prefix + "_gross", "Currency", 145),
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
