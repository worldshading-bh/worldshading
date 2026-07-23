from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import flt
from worldshading.api.production_bom import get_global_default_price_list_name, get_price_list_rate_for_item


def validate_transaction_bom(doc, method=None):
	if not doc.meta.has_field("production_bom_items"):
		return

	_sync_parent_details(doc)
	calculate_transaction_bom_total(doc)


def create_order_specific_boms(doc, method=None):
	if not doc.meta.has_field("production_bom_items"):
		return

	if not doc.get("production_bom_items"):
		return

	grouped_rows = _group_production_bom_rows(doc)
	if not grouped_rows:
		return

	for key in grouped_rows:
		rows = grouped_rows[key]
		sales_order_item = _get_sales_order_item(doc, key)

		if not sales_order_item:
			continue

		existing_bom = _get_existing_transaction_bom(rows)
		if existing_bom:
			_set_transaction_bom(rows, existing_bom)
			continue

		if _matches_master_bom(sales_order_item, rows):
			continue

		bom = _make_order_specific_bom(doc, sales_order_item, rows)
		_set_transaction_bom(rows, bom.name)


def calculate_transaction_bom_total(doc):
	total = 0

	for row in doc.get("production_bom_items") or []:
		row.amount = flt(row.qty) * flt(row.rate)
		total += flt(row.amount)

	if doc.meta.has_field("total_raw_materials_price"):
		doc.total_raw_materials_price = total


def _group_production_bom_rows(doc):
	grouped_rows = {}

	for row in doc.get("production_bom_items") or []:
		if not row.parent_item or not row.item_code or not flt(row.qty):
			continue

		key = (row.parent_item_row, row.parent_detail, row.parent_item)
		grouped_rows.setdefault(key, []).append(row)

	return grouped_rows


def _get_sales_order_item(doc, key):
	parent_item_row, parent_detail, parent_item = key

	for item in doc.get("items") or []:
		if item.name == parent_detail and item.item_code == parent_item:
			return item

	for item in doc.get("items") or []:
		if item.idx == parent_item_row and item.item_code == parent_item:
			return item

	return None


def _get_existing_transaction_bom(rows):
	for row in rows:
		if row.transaction_bom and frappe.db.exists("BOM", row.transaction_bom):
			return row.transaction_bom

	return None


def _make_order_specific_bom(doc, sales_order_item, rows):
	bom = frappe.new_doc("BOM")
	bom.item = sales_order_item.item_code
	bom.company = doc.company
	bom.currency = doc.currency
	bom.quantity = flt(sales_order_item.qty) or 1
	bom.is_active = 1
	bom.is_default = 0
	bom.rm_cost_as_per = "Price List"
	bom.buying_price_list = get_global_default_price_list_name()
	if not bom.buying_price_list:
		frappe.throw(_("Please set a Global Default Price List, or enable the Regular Price price list."))

	bom.price_list_currency = frappe.db.get_value("Price List", bom.buying_price_list, "currency")
	bom.plc_conversion_rate = 1
	bom.conversion_rate = flt(doc.conversion_rate) or 1
	bom.transfer_material_against = "Work Order"

	if bom.meta.has_field("is_order_specific"):
		bom.is_order_specific = 1

	if doc.get("project"):
		bom.project = doc.project

	for row in rows:
		rate = get_price_list_rate_for_item(
			row.item_code,
			row.uom,
			qty=row.qty,
			company=doc.company,
			currency=doc.currency
		)

		bom.append("items", {
			"item_code": row.item_code,
			"item_name": row.item_name,
			"description": row.description,
			"qty": flt(row.qty),
			"uom": row.uom,
			"rate": rate,
			"amount": rate * flt(row.qty),
			"source_warehouse": row.source_warehouse,
			"include_item_in_manufacturing": "1" if row.include_item_in_manufacturing else "0"
		})

	bom.flags.ignore_permissions = True
	bom.insert(ignore_permissions=True)
	bom.flags.ignore_permissions = True
	bom.submit()

	_restore_order_bom_default_state(bom, rows)

	return bom


def _restore_order_bom_default_state(bom, rows):
	master_bom = None

	for row in rows:
		if row.master_bom:
			master_bom = row.master_bom
			break

	frappe.db.set_value("BOM", bom.name, "is_default", 0, update_modified=False)

	if frappe.db.get_value("Item", bom.item, "default_bom") == bom.name:
		frappe.db.set_value("Item", bom.item, "default_bom", master_bom, update_modified=False)

	bom.is_default = 0


def _matches_master_bom(sales_order_item, rows):
	master_bom = _get_master_bom(rows)
	if not master_bom or not frappe.db.exists("BOM", master_bom):
		return False

	bom = frappe.get_doc("BOM", master_bom)
	multiplier = flt(sales_order_item.qty) / (flt(bom.quantity) or 1)

	transaction_rows = [_get_compare_key(row) for row in rows]
	master_rows = []

	for row in bom.get("items") or []:
		master_rows.append((
			row.item_code,
			flt(row.qty) * multiplier,
			row.uom,
			row.source_warehouse or "",
			1 if row.include_item_in_manufacturing else 0
		))

	return _sorted_compare_rows(transaction_rows) == _sorted_compare_rows(master_rows)


def _get_master_bom(rows):
	for row in rows:
		if row.master_bom:
			return row.master_bom

	return None


def _get_compare_key(row):
	return (
		row.item_code,
		flt(row.qty),
		row.uom,
		row.source_warehouse or "",
		1 if row.include_item_in_manufacturing else 0
	)


def _sorted_compare_rows(rows):
	return sorted([
		(row[0], flt(row[1], 6), row[2] or "", row[3] or "", row[4])
		for row in rows
	])


def _set_transaction_bom(rows, bom_name):
	for row in rows:
		row.transaction_bom = bom_name
		if row.name:
			frappe.db.set_value(
				"Production BOM Item",
				row.name,
				"transaction_bom",
				bom_name,
				update_modified=False
			)


def _sync_parent_details(doc):
	item_by_row = {}

	for item in doc.get("items") or []:
		if not item.idx or not item.item_code:
			continue

		item_by_row[item.idx] = item

	clean_rows = []

	for row in doc.get("production_bom_items") or []:
		if not row.parent_item_row:
			continue

		parent_item = item_by_row.get(row.parent_item_row)
		if not parent_item:
			continue

		if row.parent_item and row.parent_item != parent_item.item_code:
			continue

		row.parent_item = parent_item.item_code
		row.parent_detail = parent_item.name
		clean_rows.append(row)

	if len(clean_rows) == len(doc.get("production_bom_items") or []):
		return

	doc.set("production_bom_items", [])
	for row in clean_rows:
		row_data = row.as_dict()
		for fieldname in ("name", "parent", "parentfield", "parenttype", "idx", "doctype"):
			row_data.pop(fieldname, None)

		doc.append("production_bom_items", row_data)
