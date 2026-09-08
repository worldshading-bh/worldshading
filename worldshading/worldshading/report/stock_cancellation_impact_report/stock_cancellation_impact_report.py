from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, getdate


SUPPORTED_VOUCHERS = {
	"Delivery Note": {
		"child_doctype": "Delivery Note Item",
		"stock_direction": -1,
		"requires_update_stock": False,
	},
	"Sales Invoice": {
		"child_doctype": "Sales Invoice Item",
		"stock_direction": -1,
		"requires_update_stock": True,
	},
	"Purchase Receipt": {
		"child_doctype": "Purchase Receipt Item",
		"stock_direction": 1,
		"requires_update_stock": False,
	},
	"Purchase Invoice": {
		"child_doctype": "Purchase Invoice Item",
		"stock_direction": 1,
		"requires_update_stock": True,
	},
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)
	check_permission()

	movements = get_cancelled_movements(filters)
	reconciliations = get_reconciliations(movements)
	current_balances = get_current_balances(movements)
	business_references = get_business_references(movements)
	data = build_rows(movements, reconciliations, current_balances, filters)
	add_business_references(data, business_references)
	add_later_stock_activity(data)
	add_physical_review_totals(data)
	message = get_message(data, filters)
	report_summary = get_report_summary(data)

	return get_columns(), data, message, None, report_summary


def validate_filters(filters):
	if not filters.get("cancelled_from") or not filters.get("cancelled_to"):
		frappe.throw(_("Cancelled From and Cancelled To are required."))

	if getdate(filters.cancelled_from) > getdate(filters.cancelled_to):
		frappe.throw(_("Cancelled From cannot be after Cancelled To."))

	if (getdate(filters.cancelled_to) - getdate(filters.cancelled_from)).days >= 1095:
		frappe.throw(_("Please select a cancellation period of less than 3 years."))

	if filters.get("voucher_type") and filters.voucher_type not in get_supported_voucher_types():
		frappe.throw(_("Unsupported document type."))


def check_permission():
	if not frappe.has_permission("Stock Ledger Entry", "read"):
		frappe.throw(_("You do not have permission to view stock ledger information."), frappe.PermissionError)


def get_supported_voucher_types():
	return [
		"Delivery Note",
		"Stock Entry",
		"Sales Invoice",
		"Purchase Receipt",
		"Purchase Invoice",
	]


def get_cancelled_movements(filters):
	movements = []
	voucher_types = [filters.voucher_type] if filters.get("voucher_type") else get_supported_voucher_types()

	for voucher_type in voucher_types:
		parents = get_cancelled_parents(voucher_type, filters)
		if not parents:
			continue

		if voucher_type == "Stock Entry":
			movements.extend(get_stock_entry_movements(parents, filters))
		else:
			movements.extend(get_transaction_movements(voucher_type, parents, filters))

	return movements


def get_cancelled_parents(voucher_type, filters):
	parent_filters = {
		"docstatus": 2,
		"modified": ["between", [
			str(getdate(filters.cancelled_from)) + " 00:00:00",
			str(add_days(getdate(filters.cancelled_to), 1)) + " 00:00:00",
		]],
	}

	if filters.get("company"):
		parent_filters["company"] = filters.company
	if filters.get("voucher_no"):
		parent_filters["name"] = filters.voucher_no
	if SUPPORTED_VOUCHERS.get(voucher_type, {}).get("requires_update_stock"):
		parent_filters["update_stock"] = 1

	return frappe.get_list(
		voucher_type,
		filters=parent_filters,
		fields=["name", "posting_date", "posting_time", "modified", "company"],
		order_by="modified desc",
		limit_page_length=0,
	)


def get_transaction_movements(voucher_type, parents, filters):
	settings = SUPPORTED_VOUCHERS[voucher_type]
	parent_map = dict((d.name, d) for d in parents)
	child_filters = {"parent": ["in", list(parent_map.keys())]}
	if filters.get("item_code"):
		child_filters["item_code"] = filters.item_code
	if filters.get("warehouse"):
		child_filters["warehouse"] = filters.warehouse

	children = frappe.get_all(
		settings["child_doctype"],
		filters=child_filters,
		fields=["parent", "item_code", "warehouse", "stock_qty"],
		order_by="parent, idx",
		limit_page_length=0,
	)
	stock_items = get_stock_items([d.item_code for d in children])
	movements = []

	for child in children:
		if child.item_code not in stock_items or not child.warehouse:
			continue
		parent = parent_map[child.parent]
		original_change = flt(child.stock_qty) * settings["stock_direction"]
		movements.append(make_movement(voucher_type, parent, child.item_code,
			child.warehouse, original_change))

	if voucher_type == "Delivery Note":
		movements.extend(get_packed_item_movements(parents, filters))

	return movements


def get_packed_item_movements(parents, filters):
	parent_map = dict((d.name, d) for d in parents)
	packed_filters = {
		"parent": ["in", list(parent_map.keys())],
		"parenttype": "Delivery Note",
	}
	if filters.get("item_code"):
		packed_filters["item_code"] = filters.item_code
	if filters.get("warehouse"):
		packed_filters["warehouse"] = filters.warehouse

	packed_items = frappe.get_all(
		"Packed Item",
		filters=packed_filters,
		fields=["parent", "item_code", "warehouse", "qty"],
		order_by="parent, idx",
		limit_page_length=0,
	)

	return [make_movement("Delivery Note", parent_map[d.parent], d.item_code,
		d.warehouse, -flt(d.qty)) for d in packed_items if d.warehouse]


def get_stock_entry_movements(parents, filters):
	parent_map = dict((d.name, d) for d in parents)
	children = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": ["in", list(parent_map.keys())]},
		fields=["parent", "item_code", "s_warehouse", "t_warehouse", "transfer_qty"],
		order_by="parent, idx",
		limit_page_length=0,
	)
	movements = []

	for child in children:
		if filters.get("item_code") and child.item_code != filters.item_code:
			continue
		parent = parent_map[child.parent]
		if child.s_warehouse and (not filters.get("warehouse") or child.s_warehouse == filters.warehouse):
			movements.append(make_movement("Stock Entry", parent, child.item_code,
				child.s_warehouse, -flt(child.transfer_qty)))
		if child.t_warehouse and (not filters.get("warehouse") or child.t_warehouse == filters.warehouse):
			movements.append(make_movement("Stock Entry", parent, child.item_code,
				child.t_warehouse, flt(child.transfer_qty)))

	return movements


def make_movement(voucher_type, parent, item_code, warehouse, original_change):
	return frappe._dict({
		"voucher_type": voucher_type,
		"voucher_no": parent.name,
		"posting_datetime": combine_datetime(parent.posting_date, parent.posting_time),
		"cancelled_on": get_datetime(parent.modified),
		"company": parent.company,
		"item_code": item_code,
		"warehouse": warehouse,
		"original_change": original_change,
		"reversal_quantity": -original_change,
	})


def combine_datetime(posting_date, posting_time):
	return get_datetime(str(posting_date) + " " + str(posting_time or "00:00:00"))


def get_stock_items(item_codes):
	item_codes = list(set([d for d in item_codes if d]))
	if not item_codes:
		return set()
	return set([d.name for d in frappe.get_all(
		"Item",
		filters={"name": ["in", item_codes], "is_stock_item": 1},
		fields=["name"],
		limit_page_length=0,
	)])


def get_reconciliations(movements):
	if not movements:
		return {}

	earliest_posting = min([d.posting_datetime for d in movements])
	latest_cancellation = max([d.cancelled_on for d in movements])
	headers = frappe.get_list(
		"Stock Reconciliation",
		filters={
			"docstatus": 1,
			"posting_date": ["between", [earliest_posting.date(), latest_cancellation.date()]],
		},
		fields=["name", "posting_date", "posting_time"],
		order_by="posting_date, posting_time",
		limit_page_length=0,
	)
	if not headers:
		return {}

	header_map = dict((d.name, d) for d in headers)
	item_codes = list(set([d.item_code for d in movements]))
	warehouses = list(set([d.warehouse for d in movements]))
	children = frappe.get_all(
		"Stock Reconciliation Item",
		filters={
			"parent": ["in", list(header_map.keys())],
			"item_code": ["in", item_codes],
			"warehouse": ["in", warehouses],
		},
		fields=["parent", "item_code", "warehouse", "current_qty", "qty"],
		limit_page_length=0,
	)
	reconciliations = {}

	for child in children:
		header = header_map[child.parent]
		row = frappe._dict({
			"name": child.parent,
			"posting_datetime": combine_datetime(header.posting_date, header.posting_time),
			"current_qty": flt(child.current_qty),
			"qty": flt(child.qty),
		})
		key = (child.item_code, child.warehouse)
		reconciliations.setdefault(key, []).append(row)

	for rows in reconciliations.values():
		rows.sort(key=lambda d: d.posting_datetime)

	return reconciliations


def get_current_balances(movements):
	if not movements:
		return {}

	item_codes = list(set([d.item_code for d in movements]))
	warehouses = list(set([d.warehouse for d in movements]))
	bins = frappe.get_all(
		"Bin",
		filters={
			"item_code": ["in", item_codes],
			"warehouse": ["in", warehouses],
		},
		fields=["item_code", "warehouse", "actual_qty"],
		limit_page_length=0,
	)
	return dict(((d.item_code, d.warehouse), flt(d.actual_qty)) for d in bins)


def get_business_references(movements):
	references = {}
	vouchers_by_type = {}
	for movement in movements:
		vouchers_by_type.setdefault(movement.voucher_type, set()).add(movement.voucher_no)

	reference_fields = {
		"Delivery Note": ("Delivery Note Item", ["against_sales_order"]),
		"Sales Invoice": ("Sales Invoice Item", ["sales_order", "delivery_note"]),
		"Purchase Receipt": ("Purchase Receipt Item", ["purchase_order"]),
		"Purchase Invoice": ("Purchase Invoice Item", ["purchase_order", "purchase_receipt"]),
	}

	for voucher_type, settings in reference_fields.items():
		voucher_names = list(vouchers_by_type.get(voucher_type, []))
		if not voucher_names:
			continue
		child_doctype, fields = settings
		children = frappe.get_all(
			child_doctype,
			filters={"parent": ["in", voucher_names]},
			fields=["parent"] + fields,
			limit_page_length=0,
		)
		for child in children:
			key = (voucher_type, child.parent)
			entry = references.setdefault(key, {
				"sales_orders": set(),
				"purchase_orders": set(),
				"delivery_notes": set(),
				"purchase_receipts": set(),
			})
			if child.get("against_sales_order"):
				entry["sales_orders"].add(child.against_sales_order)
			if child.get("sales_order"):
				entry["sales_orders"].add(child.sales_order)
			if child.get("purchase_order"):
				entry["purchase_orders"].add(child.purchase_order)
			if child.get("delivery_note"):
				entry["delivery_notes"].add(child.delivery_note)
			if child.get("purchase_receipt"):
				entry["purchase_receipts"].add(child.purchase_receipt)

	stock_entry_names = list(vouchers_by_type.get("Stock Entry", []))
	if stock_entry_names:
		stock_entries = frappe.get_all(
			"Stock Entry",
			filters={"name": ["in", stock_entry_names]},
			fields=["name", "purchase_order"],
			limit_page_length=0,
		)
		for stock_entry in stock_entries:
			if stock_entry.purchase_order:
				references[("Stock Entry", stock_entry.name)] = {
					"sales_orders": set(),
					"purchase_orders": set([stock_entry.purchase_order]),
					"delivery_notes": set(),
					"purchase_receipts": set(),
				}

	return references


def add_business_references(data, references):
	for row in data:
		entry = references.get((row.voucher_type, row.voucher_no), {})
		row.sales_order = ", ".join(sorted(entry.get("sales_orders", [])))
		row.purchase_order = ", ".join(sorted(entry.get("purchase_orders", [])))
		row.source_delivery_note = ", ".join(sorted(entry.get("delivery_notes", [])))
		row.source_purchase_receipt = ", ".join(sorted(entry.get("purchase_receipts", [])))
		row.business_reference_type = None
		row.business_reference = None
		for reference_type, reference_names in [
			("Sales Order", entry.get("sales_orders", [])),
			("Purchase Order", entry.get("purchase_orders", [])),
			("Delivery Note", entry.get("delivery_notes", [])),
			("Purchase Receipt", entry.get("purchase_receipts", [])),
		]:
			if reference_names:
				row.business_reference_type = reference_type
				row.business_reference = sorted(reference_names)[0]
				break


def add_later_stock_activity(data):
	warning_rows = [d for d in data if d.get("reconciliation_date")]
	if not warning_rows:
		return

	pair_dates = set()
	for row in warning_rows:
		pair_dates.add((row.item_code, row.warehouse, row.reconciliation_date))

	activity = {}
	pairs = list(pair_dates)
	for offset in range(0, len(pairs), 100):
		queries = []
		values = {}
		for index, pair in enumerate(pairs[offset:offset + 100]):
			item_code, warehouse, reconciliation_date = pair
			key = str(index)
			queries.append(
				"SELECT %(key_{0})s AS activity_key, COUNT(name) AS movement_count, "
				"MAX(TIMESTAMP(posting_date, posting_time)) AS last_movement_date "
				"FROM `tabStock Ledger Entry` WHERE is_cancelled = 'No' "
				"AND item_code = %(item_{0})s AND warehouse = %(warehouse_{0})s "
				"AND TIMESTAMP(posting_date, posting_time) > %(date_{0})s".format(key))
			values["key_" + key] = key
			values["item_" + key] = item_code
			values["warehouse_" + key] = warehouse
			values["date_" + key] = reconciliation_date

		rows = frappe.db.sql(
			" UNION ALL ".join(queries),
			values,
			as_dict=1,
		)
		for row in rows:
			pair = pairs[offset + cint(row.activity_key)]
			activity[pair] = row

	for row in data:
		entry = activity.get((row.item_code, row.warehouse, row.reconciliation_date), {})
		row.later_movement_count = cint(entry.get("movement_count"))
		row.last_movement_date = entry.get("last_movement_date")
		if row.later_movement_count:
			row.later_activity = _("{0} movement(s); last {1}").format(
				row.later_movement_count, row.last_movement_date)
		else:
			row.later_activity = _("No later movements")


def add_physical_review_totals(data):
	totals = {}
	for row in data:
		if row.risk_status != "ACTION REQUIRED":
			continue
		key = (row.item_code, row.warehouse)
		if key not in totals:
			totals[key] = {"quantity": 0, "row_count": 0}
		totals[key]["quantity"] += flt(row.reversal_quantity)
		totals[key]["row_count"] += 1

	for key in sorted(totals):
		item_code, warehouse = key
		total = totals[key]
		data.append(frappe._dict({
			"is_total_row": 1,
			"risk_status": _("PHYSICAL REVIEW TOTAL"),
			"item_code": item_code,
			"warehouse": warehouse,
			"reversal_quantity": total["quantity"],
			"later_activity": _("{0} warning row(s)").format(total["row_count"]),
		}))


def build_rows(movements, reconciliations, current_balances, filters):
	grouped = {}
	for movement in movements:
		key = (
			movement.voucher_type,
			movement.voucher_no,
			movement.item_code,
			movement.warehouse,
			movement.original_change < 0,
		)
		if key not in grouped:
			grouped[key] = movement.copy()
		else:
			grouped[key].original_change += movement.original_change
			grouped[key].reversal_quantity += movement.reversal_quantity

	data = []
	for movement in grouped.values():
		reconciliation = find_crossed_reconciliation(
			movement, reconciliations.get((movement.item_code, movement.warehouse), []))
		if cint(filters.get("only_crossed_reconciliation")) and not reconciliation:
			continue

		row = movement.copy()
		row.current_qty = current_balances.get((movement.item_code, movement.warehouse), 0)
		if reconciliation:
			row.reconciliation = reconciliation.name
			row.reconciliation_date = reconciliation.posting_datetime
			row.quantity_before_reconciliation = reconciliation.current_qty
			row.reconciled_quantity = reconciliation.qty
			row.reconciliation_adjustment = reconciliation.qty - reconciliation.current_qty
			row.reconciliation_change = "{0} → {1}".format(
				flt(reconciliation.current_qty), flt(reconciliation.qty))
			row.risk_status = "ACTION REQUIRED"
			row.next_step = _("Physically count this item in this warehouse. If the count differs from ERPNext, submit a current-date Stock Reconciliation with manager approval.")
		else:
			row.risk_status = "NO RECONCILIATION CROSSED"
			row.next_step = _("Confirm that the physical stock movement matched the cancellation. No later Stock Reconciliation was found in the crossed period.")

		data.append(row)

	data.sort(key=lambda d: (d.cancelled_on, d.voucher_type, d.voucher_no, d.item_code, d.warehouse), reverse=True)
	return data


def find_crossed_reconciliation(movement, reconciliations):
	for reconciliation in reconciliations:
		if movement.posting_datetime < reconciliation.posting_datetime <= movement.cancelled_on:
			return reconciliation
	return None


def get_message(data, filters):
	warnings = len([d for d in data if d.risk_status == "ACTION REQUIRED"])
	if warnings:
		return _("{0} item/warehouse movement(s) crossed a later Stock Reconciliation. These rows require a physical count; the report does not prove that goods physically returned.").format(warnings)
	if cint(filters.get("only_crossed_reconciliation")):
		return _("No cancelled stock movements crossing a later Stock Reconciliation were found for these filters.")
	return _("No reconciliation warnings were found. Always confirm that cancelled stock movements match the physical movement of goods.")


def get_report_summary(data):
	detail_rows = [d for d in data if not d.get("is_total_row")]
	warnings = [d for d in detail_rows if d.risk_status == "ACTION REQUIRED"]
	return [
		{
			"value": len(set([(d.voucher_type, d.voucher_no) for d in detail_rows])),
			"label": _("Affected Documents"),
			"datatype": "Int",
			"indicator": "Blue",
		},
		{
			"value": len(warnings),
			"label": _("Warning Rows"),
			"datatype": "Int",
			"indicator": "Red" if warnings else "Green",
		},
		{
			"value": len(set([d.item_code for d in detail_rows])),
			"label": _("Unique Items"),
			"datatype": "Int",
			"indicator": "Orange" if warnings else "Green",
		},
		{
			"value": len(set([d.warehouse for d in detail_rows])),
			"label": _("Warehouses"),
			"datatype": "Int",
			"indicator": "Blue",
		},
	]


def get_columns():
	return [
		{"label": _("Risk"), "fieldname": "risk_status", "fieldtype": "Data", "width": 145},
		{"label": _("Document"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 145},
		{"label": _("Business Reference"), "fieldname": "business_reference", "fieldtype": "Dynamic Link", "options": "business_reference_type", "width": 175},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 105},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 180},
		{"label": _("Original Posting"), "fieldname": "posting_datetime", "fieldtype": "Datetime", "width": 145},
		{"label": _("Crossed Reconciliation"), "fieldname": "reconciliation", "fieldtype": "Link", "options": "Stock Reconciliation", "width": 190},
		{"label": _("Reconciliation Date"), "fieldname": "reconciliation_date", "fieldtype": "Datetime", "width": 145},
		{"label": _("Reconciliation Change"), "fieldname": "reconciliation_change", "fieldtype": "Data", "width": 145},
		{"label": _("Cancelled On"), "fieldname": "cancelled_on", "fieldtype": "Datetime", "width": 145},
		{"label": _("Cancellation Reversal"), "fieldname": "reversal_quantity", "fieldtype": "Float", "width": 145},
		{"label": _("Current System Qty"), "fieldname": "current_qty", "fieldtype": "Float", "width": 135},
		{"label": _("Later Activity"), "fieldname": "later_activity", "fieldtype": "Data", "width": 220},
	]
