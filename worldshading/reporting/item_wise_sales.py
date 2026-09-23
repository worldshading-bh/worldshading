from __future__ import unicode_literals

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


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
			"stock_qty": to_decimal(packed.get("qty")),
			"direct_qty": Decimal("0"),
			"packed_qty": to_decimal(packed.get("qty")),
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
			"packed_net_amount", "net_amount"
		):
			target[fieldname] = to_decimal(target.get(fieldname)) + to_decimal(row.get(fieldname))
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


def normalize_transaction_rows(direct_rows, packed_rows, currency_precision=3):
	direct_rows = list(direct_rows or [])
	packed_rows = list(packed_rows or [])
	parents_by_pool = {}
	packed_by_pool = {}
	for row in direct_rows:
		invoice = row.get("invoice") or row.get("parent")
		parents_by_pool.setdefault((invoice, row.get("item_code")), []).append(row)
	for row in packed_rows:
		invoice = row.get("invoice") or row.get("parent")
		packed_by_pool.setdefault((invoice, row.get("parent_item")), []).append(row)

	output = []
	consumed_parent_pools = set()
	for pool_key in sorted(packed_by_pool, key=lambda value: (str(value[0]), str(value[1]))):
		parents = parents_by_pool.get(pool_key, [])
		if parents:
			consumed_parent_pools.add(pool_key)
		output.extend(allocate_parent_pool(
			parents, packed_by_pool[pool_key], currency_precision
		))
	for pool_key in sorted(parents_by_pool, key=lambda value: (str(value[0]), str(value[1]))):
		if pool_key in consumed_parent_pools:
			continue
		for row in parents_by_pool[pool_key]:
			output.append(_direct_output(row, currency_precision))

	return _merge_rows(output, currency_precision)
