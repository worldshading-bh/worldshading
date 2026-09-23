from __future__ import unicode_literals

import json
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint

from worldshading.reporting.item_wise_sales import (
	append_warning,
	get_transaction_rows,
	quantize_money,
	to_decimal,
)


WARNING_LABELS = {
	"ambiguous_parent_rows": _("Ambiguous parent rows"),
	"missing_parent_item": _("Missing parent Sales Invoice Item"),
	"packed_amount_from_rate": _("Packed amount calculated from rate"),
	"packed_value_from_quantity": _("Packed value allocated by quantity"),
	"zero_qty_nonzero_value": _("Zero quantity with non-zero value"),
}


def execute(filters=None):
	filters = dict(filters or {})
	rows = get_transaction_rows(filters)
	item_codes = sorted(set(row.get("item_code") for row in rows if row.get("item_code")))
	item_context = get_item_context(
		item_codes, filters.get("company"), filters.get("warehouse")
	)
	tax_context = get_tax_context(rows)
	detail_context = get_detail_context(rows) if cint(filters.get("show_detailed_report")) else {}
	apply_tax_values(rows, tax_context)

	for row in rows:
		row.update(item_context.get(row.get("item_code"), {}))
		if cint(filters.get("show_detailed_report")):
			row.update(detail_context.get(row.get("invoice"), {}))
			row["invoice_count"] = 1
			row["last_sold_date"] = row.get("posting_date")
			row["reconciliation_warning"] = "; ".join(row.get("warnings") or [])

	message = get_warning_message(rows)
	return get_columns(filters), rows, message, None


def _column(label, fieldname, fieldtype="Data", width=110, options=None):
	column = {
		"label": _(label), "fieldname": fieldname,
		"fieldtype": fieldtype, "width": width
	}
	if options:
		column["options"] = options
	return column


def get_columns(filters):
	columns = [
		_column("Posting Date", "posting_date", "Date", 95),
		_column("Sales Invoice", "invoice", "Link", 130, "Sales Invoice"),
		_column("Item Code", "item_code", "Link", 130, "Item"),
		_column("Item Name", "item_name", "Data", 180),
		_column("Item Group", "item_group", "Link", 120, "Item Group"),
		_column("Brand", "brand", "Link", 100, "Brand"),
		_column("Sales Basis", "sales_basis", "Data", 105),
		_column("Stock UOM", "stock_uom", "Link", 85, "UOM"),
		_column("Sold Stock Qty", "stock_qty", "Float", 110),
		_column("Net Rate", "net_rate", "Currency", 105, "currency"),
		_column("Net Amount", "net_amount", "Currency", 115, "currency"),
		_column("Tax", "tax", "Currency", 100, "currency"),
		_column("Total", "total", "Currency", 115, "currency"),
		_column("Current Stock Qty", "current_stock_qty", "Float", 120),
		_column("Default Supplier", "default_supplier", "Link", 130, "Supplier"),
		_column("Supplier Name", "supplier_name", "Data", 160),
	]
	if not cint((filters or {}).get("show_detailed_report")):
		return columns
	columns.extend([
		_column("Customer", "customer", "Link", 120, "Customer"),
		_column("Customer Name", "customer_name", "Data", 160),
		_column("Customer Group", "customer_group", "Link", 120, "Customer Group"),
		_column("Territory", "territory", "Link", 110, "Territory"),
		_column("Project", "project", "Link", 120, "Project"),
		_column("Sales Order", "sales_order", "Link", 120, "Sales Order"),
		_column("Delivery Note", "delivery_note", "Link", 120, "Delivery Note"),
		_column("Parent / Bundle Item", "parent_item", "Link", 130, "Item"),
		_column("Warehouse", "warehouse", "Link", 140, "Warehouse"),
		_column("Income Account", "income_account", "Link", 140, "Account"),
		_column("Cost Center", "cost_center", "Link", 130, "Cost Center"),
		_column("Mode of Payment", "mode_of_payment", "Data", 130),
		_column("Currency", "currency", "Link", 85, "Currency"),
		_column("Invoice Qty", "qty", "Float", 95),
		_column("Invoice UOM", "uom", "Link", 95, "UOM"),
		_column("Conversion Factor", "conversion_factor", "Float", 110),
		_column("Price List Rate", "price_list_rate", "Currency", 110, "currency"),
		_column("Gross Amount", "amount", "Currency", 110, "currency"),
		_column("Discount %", "discount_percentage", "Percent", 90),
		_column("Discount Amount", "discount_amount", "Currency", 115, "currency"),
		_column("Tax Accounts", "tax_accounts", "Data", 180),
		_column("Sales Person", "sales_person", "Data", 130),
		_column("Employee", "employee", "Link", 120, "Employee"),
		_column("Direct Qty", "direct_qty", "Float", 95),
		_column("Packed Qty", "packed_qty", "Float", 95),
		_column("Direct Net Value", "direct_net_amount", "Currency", 120, "currency"),
		_column("Packed Net Value", "packed_net_amount", "Currency", 125, "currency"),
		_column("Invoice Count", "invoice_count", "Int", 95),
		_column("Last Sold Date", "last_sold_date", "Date", 105),
		_column("Reconciliation Warning", "reconciliation_warning", "Data", 220),
	])
	return columns


def get_item_context(item_codes, company, warehouse=None):
	if not item_codes:
		return {}
	warehouse_condition = " and bin.warehouse = %(warehouse)s" if warehouse else ""
	rows = frappe.db.sql("""
		select
			item.name as item_code, item.item_name, item.item_group,
			item.brand, item.stock_uom,
			max(item_default.default_supplier) as default_supplier,
			max(supplier.supplier_name) as supplier_name,
			coalesce(max(stock.actual_qty), 0) as current_stock_qty
		from `tabItem` item
		left join `tabItem Default` item_default
			on item_default.parent = item.name
			and item_default.company = %(company)s
		left join `tabSupplier` supplier
			on supplier.name = item_default.default_supplier
		left join (
			select bin.item_code, sum(bin.actual_qty) as actual_qty
			from `tabBin` bin
			inner join `tabWarehouse` warehouse on warehouse.name = bin.warehouse
			where warehouse.company = %(company)s and warehouse.disabled = 0
				{warehouse_condition}
			group by bin.item_code
		) stock on stock.item_code = item.name
		where item.name in %(item_codes)s
		group by item.name, item.item_name, item.item_group, item.brand, item.stock_uom
	""".format(warehouse_condition=warehouse_condition), {
		"company": company, "warehouse": warehouse, "item_codes": tuple(item_codes)
	}, as_dict=True)
	return dict((row.item_code, dict(row)) for row in rows)


def get_tax_context(rows):
	invoices = sorted(set(row.get("invoice") for row in rows if row.get("invoice")))
	if not invoices:
		return {}
	tax_rows = frappe.db.sql("""
		select parent as invoice, account_head, description, item_wise_tax_detail
		from `tabSales Taxes and Charges`
		where parenttype = 'Sales Invoice' and docstatus = 1
			and parent in %(invoices)s
		order by parent, idx
	""", {"invoices": tuple(invoices)}, as_dict=True)
	result = {}
	for tax_row in tax_rows:
		try:
			details = json.loads(tax_row.item_wise_tax_detail or "{}")
		except (TypeError, ValueError):
			details = {}
		for item_code, tax_data in details.items():
			amount = tax_data[1] if isinstance(tax_data, list) and len(tax_data) > 1 else 0
			key = (tax_row.invoice, item_code)
			entry = result.setdefault(key, {"amount": Decimal("0"), "accounts": []})
			entry["amount"] += to_decimal(amount)
			account = tax_row.account_head or tax_row.description
			if account and account not in entry["accounts"]:
				entry["accounts"].append(account)
	for entry in result.values():
		entry["accounts"] = ", ".join(entry["accounts"])
	return result


def apply_tax_values(rows, tax_context):
	direct_totals = {}
	packed_totals = {}
	for row in rows:
		direct_key = (row.get("invoice"), row.get("item_code"))
		packed_key = (row.get("invoice"), row.get("parent_item"))
		direct_totals[direct_key] = direct_totals.get(direct_key, Decimal("0")) + abs(
			to_decimal(row.get("direct_net_amount"))
		)
		if row.get("parent_item"):
			packed_totals[packed_key] = packed_totals.get(packed_key, Decimal("0")) + abs(
				to_decimal(row.get("packed_net_amount"))
			)
	for row in rows:
		tax = Decimal("0")
		accounts = []
		direct_key = (row.get("invoice"), row.get("item_code"))
		direct_context = tax_context.get(direct_key, {})
		direct_total = direct_totals.get(direct_key, Decimal("0"))
		if direct_total:
			tax += to_decimal(direct_context.get("amount")) * abs(
				to_decimal(row.get("direct_net_amount"))
			) / direct_total
		if direct_context.get("accounts"):
			accounts.append(direct_context["accounts"])
		packed_key = (row.get("invoice"), row.get("parent_item"))
		packed_context = tax_context.get(packed_key, {})
		packed_total = packed_totals.get(packed_key, Decimal("0"))
		if packed_total:
			tax += to_decimal(packed_context.get("amount")) * abs(
				to_decimal(row.get("packed_net_amount"))
			) / packed_total
		if packed_context.get("accounts") and packed_context.get("accounts") not in accounts:
			accounts.append(packed_context["accounts"])
		row["tax"] = quantize_money(tax)
		row["total"] = quantize_money(to_decimal(row.get("net_amount")) + row["tax"])
		row["tax_accounts"] = ", ".join(accounts)


def get_detail_context(rows):
	invoices = sorted(set(row.get("invoice") for row in rows if row.get("invoice")))
	if not invoices:
		return {}
	payment_rows = frappe.db.sql("""
		select parent as invoice, mode_of_payment
		from `tabSales Invoice Payment`
		where parent in %(invoices)s and ifnull(mode_of_payment, '') != ''
		order by parent, idx
	""", {"invoices": tuple(invoices)}, as_dict=True)
	sales_rows = frappe.db.sql("""
		select si.name as invoice, si.pb_sales_employee as employee,
			group_concat(distinct sales_team.sales_person order by sales_team.idx separator ', ') as sales_person
		from `tabSales Invoice` si
		left join `tabSales Team` sales_team on sales_team.parent = si.name
		where si.name in %(invoices)s
		group by si.name, si.pb_sales_employee
	""", {"invoices": tuple(invoices)}, as_dict=True)
	result = {}
	for row in payment_rows:
		entry = result.setdefault(row.invoice, {"mode_of_payments": []})
		if row.mode_of_payment not in entry["mode_of_payments"]:
			entry["mode_of_payments"].append(row.mode_of_payment)
	for row in sales_rows:
		entry = result.setdefault(row.invoice, {"mode_of_payments": []})
		entry["sales_person"] = row.sales_person
		entry["employee"] = row.employee
	for entry in result.values():
		entry["mode_of_payment"] = ", ".join(entry.pop("mode_of_payments", []))
	return result


def get_warning_message(rows):
	warnings = []
	for row in rows:
		for warning in row.get("warnings") or []:
			append_warning(warnings, warning)
	if not warnings:
		return None
	labels = [WARNING_LABELS.get(warning, warning) for warning in warnings]
	return _("{0} reconciliation warning types: {1}").format(
		len(warnings), "; ".join(labels)
	)


@frappe.whitelist()
def get_prepared_report_filters(prepared_report_name=None):
	if not prepared_report_name:
		frappe.throw(_("Prepared Report is required."))
	prepared = frappe.db.get_value(
		"Prepared Report", prepared_report_name,
		["report_name", "status", "owner"], as_dict=True
	)
	if not prepared \
			or prepared.report_name != "Item-wise Sales Register WS" \
			or prepared.status != "Completed":
		frappe.throw(_("The Prepared Report is invalid or incomplete."))
	if prepared.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("You do not have permission to read this Prepared Report."), frappe.PermissionError)
	raw_filters = frappe.db.get_value("Prepared Report", prepared_report_name, "filters")
	filters = frappe.parse_json(raw_filters) if isinstance(raw_filters, str) else raw_filters
	return filters if isinstance(filters, dict) else {}
