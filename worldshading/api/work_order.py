import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_required_items_stock(work_order):
	"""Return warehouse-wise stock for a Work Order's required items."""
	if not work_order:
		frappe.throw(_("Work Order is required."))

	if not frappe.has_permission("Work Order", "read", work_order):
		frappe.throw(_("You are not permitted to read this Work Order."), frappe.PermissionError)

	doc = frappe.get_doc("Work Order", work_order)
	item_codes = list(set([
		row.item_code for row in doc.get("required_items") if row.item_code
	]))

	if not item_codes:
		return []

	warehouse_rows = frappe.get_all(
		"Warehouse",
		filters={"disabled": 0},
		fields=["name"]
	)
	enabled_warehouses = [row.name for row in warehouse_rows]

	if not enabled_warehouses:
		return []

	bins = frappe.get_all(
		"Bin",
		filters={
			"item_code": ["in", item_codes],
			"warehouse": ["in", enabled_warehouses],
			"actual_qty": [">", 0]
		},
		fields=[
			"item_code",
			"warehouse",
			"actual_qty",
			"reserved_qty",
			"reserved_qty_for_production",
			"reserved_qty_for_sub_contract",
			"projected_qty"
		],
		order_by="item_code, warehouse"
	)

	item_names = dict(frappe.get_all(
		"Item",
		filters={"name": ["in", item_codes]},
		fields=["name", "item_name"],
		as_list=True
	))

	stock = []
	for row in bins:
		reserved_qty = (
			flt(row.reserved_qty)
			+ flt(row.reserved_qty_for_production)
			+ flt(row.reserved_qty_for_sub_contract)
		)
		stock.append({
			"item_code": row.item_code,
			"item_name": item_names.get(row.item_code) or row.item_code,
			"warehouse": row.warehouse,
			"actual_qty": flt(row.actual_qty),
			"reserved_qty": reserved_qty,
			"available_qty": flt(row.actual_qty) - reserved_qty,
			"projected_qty": flt(row.projected_qty)
		})

	return stock
