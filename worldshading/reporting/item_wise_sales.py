from __future__ import unicode_literals

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe
from frappe.utils import cint, getdate


def to_decimal(value):
	if value in (None, ""):
		return Decimal("0")
	try:
		return Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		return Decimal("0")


def money_quantum(currency_precision):
	return Decimal("1").scaleb(-int(currency_precision))


def quantize_money(value, currency_precision=3):
	return to_decimal(value).quantize(
		money_quantum(currency_precision), rounding=ROUND_HALF_UP
	)


def append_warning(warnings, warning):
	if warning and warning not in warnings:
		warnings.append(warning)


def _base_output(row):
	result = dict(row or {})
	result["warnings"] = list(result.get("warnings") or [])
	return result


def _packed_weight(row, warnings):
	amount = row.get("amount")
	if amount not in (None, ""):
		return abs(to_decimal(amount))
	rate = row.get("rate")
	if rate not in (None, ""):
		append_warning(warnings, "packed_amount_from_rate")
		return abs(to_decimal(rate) * to_decimal(row.get("qty")))
	return Decimal("0")


def allocate_parent_pool(parent_rows, packed_rows, currency_precision=3):
	parent_rows = list(parent_rows or [])
	packed_rows = list(packed_rows or [])
	quantum = money_quantum(currency_precision)
	warnings = []
	for parent_row in parent_rows:
		for warning in parent_row.get("warnings") or []:
			append_warning(warnings, warning)
	if len(parent_rows) > 1:
		append_warning(warnings, "ambiguous_parent_rows")

	parent_value = sum(
		(to_decimal(row.get("base_net_amount")) for row in parent_rows),
		Decimal("0")
	)
	parent_magnitude = abs(parent_value)
	sign = Decimal("-1") if parent_value < 0 else Decimal("1")
	weights = []
	row_warnings = []
	for packed in packed_rows:
		packed_warnings = list(warnings)
		weight = _packed_weight(packed, packed_warnings)
		weights.append(weight)
		row_warnings.append(packed_warnings)

	total_weight = sum(weights, Decimal("0"))
	if not total_weight and packed_rows:
		weights = [abs(to_decimal(row.get("qty"))) for row in packed_rows]
		total_weight = sum(weights, Decimal("0"))
		for packed_warnings in row_warnings:
			append_warning(packed_warnings, "packed_value_from_quantity")

	if not parent_rows:
		allocated_magnitude = Decimal("0")
		for packed_warnings in row_warnings:
			append_warning(packed_warnings, "missing_parent_item")
	elif total_weight:
		allocated_magnitude = min(parent_magnitude, total_weight)
		if all(weight == 0 for weight in [
			_packed_weight(row, []) for row in packed_rows
		]):
			allocated_magnitude = parent_magnitude
	else:
		allocated_magnitude = Decimal("0")

	result = []
	allocated_total = Decimal("0")
	for index, packed in enumerate(packed_rows):
		packed_qty = to_decimal(packed.get("qty"))
		if parent_rows and packed_qty:
			packed_qty = abs(packed_qty) * sign
		if total_weight and index < len(packed_rows) - 1:
			allocated = quantize_money(
				sign * allocated_magnitude * weights[index] / total_weight,
				currency_precision
			)
		elif total_weight:
			allocated = quantize_money(
				sign * allocated_magnitude - allocated_total,
				currency_precision
			)
		else:
			allocated = Decimal("0").quantize(quantum)
		allocated_total += allocated
		row = _base_output(packed)
		row.update({
			"stock_qty": packed_qty,
			"direct_qty": Decimal("0"),
			"packed_qty": packed_qty,
			"direct_net_amount": Decimal("0").quantize(quantum),
			"packed_net_amount": allocated,
			"net_amount": allocated,
			"sales_basis": "Packed",
			"warnings": row_warnings[index]
		})
		if not row["stock_qty"] and allocated:
			append_warning(row["warnings"], "zero_qty_nonzero_value")
		row["net_rate"] = (
			quantize_money(allocated / row["stock_qty"], currency_precision)
			if row["stock_qty"] else None
		)
		result.append(row)

	residual = quantize_money(parent_value - allocated_total, currency_precision)
	if parent_rows and residual:
		row = _base_output(parent_rows[0])
		row.update({
			"stock_qty": sum(
				(to_decimal(parent.get("stock_qty")) for parent in parent_rows),
				Decimal("0")
			),
			"direct_qty": sum(
				(to_decimal(parent.get("stock_qty")) for parent in parent_rows),
				Decimal("0")
			),
			"packed_qty": Decimal("0"),
			"direct_net_amount": residual,
			"packed_net_amount": Decimal("0").quantize(quantum),
			"net_amount": residual,
			"sales_basis": "Direct",
			"warnings": list(warnings)
		})
		if not row["stock_qty"]:
			append_warning(row["warnings"], "zero_qty_nonzero_value")
		row["net_rate"] = (
			quantize_money(residual / row["stock_qty"], currency_precision)
			if row["stock_qty"] else None
		)
		result.append(row)

	return result


def _direct_output(row, currency_precision):
	quantum = money_quantum(currency_precision)
	result = _base_output(row)
	qty = to_decimal(row.get("stock_qty"))
	amount = quantize_money(row.get("base_net_amount"), currency_precision)
	result.update({
		"stock_qty": qty,
		"direct_qty": qty,
		"packed_qty": Decimal("0"),
		"direct_net_amount": amount,
		"packed_net_amount": Decimal("0").quantize(quantum),
		"net_amount": amount,
		"net_rate": quantize_money(amount / qty, currency_precision) if qty else None,
		"sales_basis": "Direct"
	})
	if not qty and amount:
		append_warning(result["warnings"], "zero_qty_nonzero_value")
	return result


def _merge_rows(rows, currency_precision):
	merged = {}
	order = []
	for row in rows:
		key = (row.get("invoice") or row.get("parent"), row.get("item_code"))
		if key not in merged:
			merged[key] = _base_output(row)
			order.append(key)
			continue
		target = merged[key]
		for fieldname in (
			"stock_qty", "direct_qty", "packed_qty", "direct_net_amount",
			"packed_net_amount", "net_amount", "tax", "total"
		):
			if fieldname in target or fieldname in row:
				target[fieldname] = to_decimal(target.get(fieldname)) + to_decimal(row.get(fieldname))
		if row.get("tax_accounts"):
			accounts = [value for value in str(target.get("tax_accounts") or "").split(", ") if value]
			for account in str(row.get("tax_accounts")).split(", "):
				if account and account not in accounts:
					accounts.append(account)
			target["tax_accounts"] = ", ".join(accounts)
		for warning in row.get("warnings") or []:
			append_warning(target["warnings"], warning)
		if to_decimal(target.get("direct_qty")) and to_decimal(target.get("packed_qty")):
			target["sales_basis"] = "Direct + Packed"
		elif to_decimal(target.get("packed_qty")):
			target["sales_basis"] = "Packed"
		else:
			target["sales_basis"] = "Direct"

	result = []
	for key in order:
		row = merged[key]
		qty = to_decimal(row.get("stock_qty"))
		row["net_amount"] = quantize_money(row.get("net_amount"), currency_precision)
		row["net_rate"] = (
			quantize_money(row["net_amount"] / qty, currency_precision)
			if qty else None
		)
		result.append(row)
	return result


def normalize_transaction_rows(direct_rows, packed_rows, currency_precision=3, merge=True):
	direct_rows = list(direct_rows or [])
	packed_rows = list(packed_rows or [])
	parents_by_pool = {}
	parents_by_name = {}
	packed_by_pool = {}
	for row in direct_rows:
		invoice = row.get("invoice") or row.get("parent")
		parents_by_pool.setdefault((invoice, row.get("item_code")), []).append(row)
		if row.get("name"):
			parents_by_name[(invoice, row.get("name"))] = row
	for row in packed_rows:
		invoice = row.get("invoice") or row.get("parent")
		link = row.get("parent_detail_docname") if row.get("parent_link_valid") else None
		packed_by_pool.setdefault((invoice, link or row.get("parent_item")), []).append(row)

	output = []
	consumed_parent_pools = set()
	for pool_key in sorted(packed_by_pool, key=lambda value: (str(value[0]), str(value[1]))):
		first_packed = packed_by_pool[pool_key][0]
		if first_packed.get("parent_link_valid"):
			parent = parents_by_name.get(pool_key)
			parents = [parent] if parent else []
		else:
			parents = parents_by_pool.get((pool_key[0], first_packed.get("parent_item")), [])
		if parents:
			for parent in parents:
				consumed_parent_pools.add((pool_key[0], parent.get("item_code"), parent.get("name")))
		output.extend(allocate_parent_pool(
			parents, packed_by_pool[pool_key], currency_precision
		))
	for pool_key in sorted(parents_by_pool, key=lambda value: (str(value[0]), str(value[1]))):
		for row in parents_by_pool[pool_key]:
			if (pool_key[0], row.get("item_code"), row.get("name")) in consumed_parent_pools:
				continue
			output.append(_direct_output(row, currency_precision))

	return _merge_rows(output, currency_precision) if merge else output


def _get_filter(filters, fieldname, default=None):
	if hasattr(filters, "get"):
		return filters.get(fieldname, default)
	return default


def validate_filters(filters):
	filters = dict(filters or {})
	for fieldname in ("company", "from_date", "to_date"):
		if not filters.get(fieldname):
			frappe.throw("{0} is required".format(fieldname.replace("_", " ").title()))
	filters["from_date"] = getdate(filters["from_date"])
	filters["to_date"] = getdate(filters["to_date"])
	if filters["from_date"] > filters["to_date"]:
		frappe.throw("From Date cannot be after To Date")
	filters["include_returns"] = cint(filters.get("include_returns", 1))
	filters["sales_basis"] = filters.get("sales_basis") or "All"
	if filters["sales_basis"] not in ("All", "Direct", "Packed"):
		frappe.throw("Unsupported Sales Basis: {0}".format(filters["sales_basis"]))
	if filters.get("item_name"):
		filters["item_name"] = "%{0}%".format(filters["item_name"])
	return filters


def _invoice_conditions(filters):
	conditions = [
		"si.docstatus = 1",
		"si.company = %(company)s",
		"si.posting_date between %(from_date)s and %(to_date)s"
	]
	if filters.get("customer"):
		conditions.append("si.customer = %(customer)s")
	if filters.get("project"):
		conditions.append("si.project = %(project)s")
	if not filters.get("include_returns"):
		conditions.append("ifnull(si.is_return, 0) = 0")
	return conditions


def _item_conditions(filters, row_alias, item_alias):
	conditions = []
	if filters.get("_item_codes"):
		conditions.append("{0}.item_code in %(_item_codes)s".format(row_alias))
	if filters.get("item_code"):
		conditions.append("{0}.item_code = %(item_code)s".format(row_alias))
	if filters.get("item_name"):
		conditions.append("{0}.item_name like %(item_name)s".format(item_alias))
	if filters.get("item_group"):
		conditions.append("{0}.item_group = %(item_group)s".format(item_alias))
	if filters.get("brand"):
		conditions.append("{0}.brand = %(brand)s".format(item_alias))
	if filters.get("warehouse"):
		conditions.append("{0}.warehouse = %(warehouse)s".format(row_alias))
	return conditions


def _sql_conditions(conditions):
	return " and ".join(conditions or ["1 = 1"])


def _get_direct_rows(filters):
	conditions = _invoice_conditions(filters)
	conditions.extend(_item_conditions(filters, "sii", "item"))
	return frappe.db.sql("""
		select
			si.name as invoice, si.posting_date, si.posting_time,
			si.customer, si.customer_name, si.customer_group, si.territory,
			si.project, si.company, si.currency, si.conversion_rate, si.is_return,
			sii.name, sii.idx, sii.item_code, sii.item_name, sii.description,
			item.item_group, item.brand, item.stock_uom,
			sii.qty, sii.uom, sii.conversion_factor, sii.stock_qty,
			sii.rate, sii.amount, sii.net_rate, sii.net_amount,
			sii.base_net_rate, sii.base_net_amount, sii.price_list_rate,
			sii.discount_percentage, sii.discount_amount, sii.warehouse,
			sii.sales_order, sii.delivery_note, sii.income_account, sii.cost_center
		from `tabSales Invoice Item` sii
		inner join `tabSales Invoice` si on si.name = sii.parent
		inner join `tabItem` item on item.name = sii.item_code
		where {conditions}
		order by si.posting_date desc, si.posting_time desc, si.name, sii.idx
	""".format(conditions=_sql_conditions(conditions)), filters, as_dict=True)


def _get_packed_rows(filters):
	selection_conditions = _invoice_conditions(filters)
	selection_conditions.extend(_item_conditions(filters, "pi", "item"))
	return frappe.db.sql("""
		select
			si.name as invoice, si.posting_date, si.posting_time,
			si.customer, si.customer_name, si.customer_group, si.territory,
			si.project, si.company, si.currency, si.conversion_rate, si.is_return,
			packed.name, packed.idx, packed.parent_item,
			packed.parent_detail_docname, packed.item_code,
			packed.item_name, packed.description, packed.qty, packed.uom,
			packed.rate, packed.amount, packed.warehouse,
			packed_item.item_group, packed_item.brand, packed_item.stock_uom,
			sum(parent_line.base_net_amount) as parent_base_net_amount,
			sum(parent_line.stock_qty) as parent_stock_qty,
			sum(parent_line.qty) as parent_qty,
			count(parent_line.name) as parent_row_count,
			max(parent_line.item_name) as parent_item_name,
			max(parent_line.stock_uom) as parent_stock_uom,
			max(parent_line.warehouse) as parent_warehouse,
			max(parent_line.sales_order) as parent_sales_order,
			max(parent_line.delivery_note) as parent_delivery_note,
			max(parent_line.income_account) as parent_income_account,
			max(parent_line.cost_center) as parent_cost_center,
			max(case when parent_line.name = packed.parent_detail_docname then 1 else 0 end) as parent_link_valid
		from (
			select distinct pi.parent, pi.parent_item
			from `tabPacked Item` pi
			inner join `tabSales Invoice` si on si.name = pi.parent
			inner join `tabItem` item on item.name = pi.item_code
			where pi.parenttype = 'Sales Invoice'
				and pi.docstatus = 1
				and {selection_conditions}
		) selected_pool
		inner join `tabPacked Item` packed
			on packed.parent = selected_pool.parent
			and packed.parent_item = selected_pool.parent_item
			and packed.parenttype = 'Sales Invoice'
			and packed.docstatus = 1
		inner join `tabSales Invoice` si on si.name = packed.parent
		inner join `tabItem` packed_item on packed_item.name = packed.item_code
		left join `tabSales Invoice Item` parent_line
			on parent_line.parent = packed.parent
			and parent_line.docstatus = 1
			and (
				parent_line.name = packed.parent_detail_docname
				or (((packed.parent_detail_docname is null or packed.parent_detail_docname = '')
					or not exists (
						select 1 from `tabSales Invoice Item` linked_parent
						where linked_parent.name = packed.parent_detail_docname
							and linked_parent.parent = packed.parent
					))
					and parent_line.item_code = packed.parent_item)
			)
		group by packed.name
		order by si.posting_date desc, si.posting_time desc, si.name, packed.idx
	""".format(selection_conditions=_sql_conditions(selection_conditions)), filters, as_dict=True)


def _parent_rows_from_packed(packed_rows):
	result = []
	seen = set()
	for packed in packed_rows:
		key = (packed.get("invoice"), packed.get("parent_detail_docname")
			if packed.get("parent_link_valid") else packed.get("parent_item"))
		if key in seen or packed.get("parent_base_net_amount") is None:
			continue
		seen.add(key)
		warnings = []
		if not packed.get("parent_detail_docname"):
			warnings.append("missing_parent_link")
		elif not packed.get("parent_link_valid"):
			warnings.append("invalid_parent_link_fallback")
		if to_decimal(packed.get("parent_row_count")) > 1:
			warnings.append("ambiguous_parent_rows")
		result.append({
			"invoice": packed.get("invoice"),
			"posting_date": packed.get("posting_date"),
			"posting_time": packed.get("posting_time"),
			"item_code": packed.get("parent_item"),
			"item_name": packed.get("parent_item_name"),
			"stock_uom": packed.get("parent_stock_uom"),
			"stock_qty": packed.get("parent_stock_qty"),
			"qty": packed.get("parent_qty"),
			"base_net_amount": packed.get("parent_base_net_amount"),
			"warehouse": packed.get("parent_warehouse"),
			"sales_order": packed.get("parent_sales_order"),
			"delivery_note": packed.get("parent_delivery_note"),
			"income_account": packed.get("parent_income_account"),
			"cost_center": packed.get("parent_cost_center"),
			"parent_row_count": packed.get("parent_row_count"),
			"name": packed.get("parent_detail_docname") if packed.get("parent_link_valid") else None,
			"warnings": warnings,
			"customer": packed.get("customer"),
			"customer_name": packed.get("customer_name"),
			"customer_group": packed.get("customer_group"),
			"territory": packed.get("territory"),
			"project": packed.get("project"),
			"company": packed.get("company"),
			"currency": packed.get("currency"),
			"conversion_rate": packed.get("conversion_rate"),
			"is_return": packed.get("is_return")
		})
	return result


def _matches_output_filters(row, filters, include_sales_basis=True):
	if filters.get("item_code") and row.get("item_code") != filters.get("item_code"):
		return False
	if filters.get("_item_codes") and row.get("item_code") not in set(filters.get("_item_codes")):
		return False
	if filters.get("warehouse") and row.get("warehouse") != filters.get("warehouse"):
		return False
	if filters.get("item_name"):
		needle = str(filters.get("item_name")).strip("%").lower()
		if needle not in str(row.get("item_name") or "").lower():
			return False
	if filters.get("item_group") and row.get("item_group") != filters.get("item_group"):
		return False
	if filters.get("brand") and row.get("brand") != filters.get("brand"):
		return False
	if include_sales_basis:
		basis = filters.get("sales_basis") or "All"
		if basis == "Direct" and not to_decimal(row.get("direct_qty")):
			return False
		if basis == "Packed" and not to_decimal(row.get("packed_qty")):
			return False
	return True


def get_transaction_contributions(filters):
	filters = validate_filters(filters)
	direct_rows = _get_direct_rows(filters)
	packed_rows = _get_packed_rows(filters)
	allocation_parents = _parent_rows_from_packed(packed_rows)
	fallback_pool_keys = set(
		(row.get("invoice"), row.get("item_code")) for row in allocation_parents
		if not row.get("name")
	)
	linked_parent_keys = set(
		(row.get("invoice"), row.get("name")) for row in allocation_parents if row.get("name")
	)
	all_direct_rows = [
		row for row in direct_rows
		if (row.get("invoice"), row.get("item_code")) not in fallback_pool_keys
		and (row.get("invoice"), row.get("name")) not in linked_parent_keys
	]
	all_direct_rows.extend(allocation_parents)
	return normalize_transaction_rows(all_direct_rows, packed_rows, merge=False)


def filter_transaction_rows(rows, filters):
	filters = validate_filters(filters)
	filtered_rows = [
		row for row in rows
		if _matches_output_filters(row, filters, include_sales_basis=False)
	]
	merged_rows = _merge_rows(filtered_rows, 3)
	return [row for row in merged_rows if _matches_output_filters(row, filters)]


def get_transaction_rows(filters):
	return filter_transaction_rows(get_transaction_contributions(filters), filters)


def get_item_sales_aggregates(filters, item_codes=None):
	query_filters = dict(filters or {})
	if item_codes:
		query_filters["_item_codes"] = tuple(item_codes)
	rows = get_transaction_rows(query_filters)
	allowed_items = set(item_codes or [])
	result = {}
	invoice_sets = {}
	latest_keys = {}
	for row in rows:
		item_code = row.get("item_code")
		if allowed_items and item_code not in allowed_items:
			continue
		entry = result.setdefault(item_code, {
			"sales_qty": Decimal("0"),
			"sales_value": Decimal("0"),
			"weighted_average_sold_rate": None,
			"invoice_count": 0,
			"last_sale_date": None,
			"last_sold_rate": None,
			"lowest_sold_rate": None,
			"highest_sold_rate": None,
			"warnings": []
		})
		qty = to_decimal(row.get("stock_qty"))
		value = to_decimal(row.get("net_amount"))
		entry["sales_qty"] += qty
		entry["sales_value"] += value
		invoice_sets.setdefault(item_code, set()).add(row.get("invoice"))
		posting_date = row.get("posting_date")
		entry["last_sale_date"] = max(
			[value for value in (entry.get("last_sale_date"), posting_date) if value]
		) if (entry.get("last_sale_date") or posting_date) else None
		for warning in row.get("warnings") or []:
			append_warning(entry["warnings"], warning)
		if qty > 0:
			rate = quantize_money(value / qty)
			entry["lowest_sold_rate"] = (
				rate if entry["lowest_sold_rate"] is None
				else min(entry["lowest_sold_rate"], rate)
			)
			entry["highest_sold_rate"] = (
				rate if entry["highest_sold_rate"] is None
				else max(entry["highest_sold_rate"], rate)
			)
			latest_key = (str(posting_date or ""), str(row.get("posting_time") or ""), str(row.get("invoice") or ""))
			if latest_key >= latest_keys.get(item_code, ("", "", "")):
				latest_keys[item_code] = latest_key
				entry["last_sold_rate"] = rate

	for item_code, entry in result.items():
		entry["sales_value"] = quantize_money(entry["sales_value"])
		entry["invoice_count"] = len(invoice_sets.get(item_code, set()))
		if entry["sales_qty"] > 0:
			entry["weighted_average_sold_rate"] = quantize_money(
				entry["sales_value"] / entry["sales_qty"]
			)
		else:
			append_warning(entry["warnings"], "Sales returns equal or exceed sales")
	return result
