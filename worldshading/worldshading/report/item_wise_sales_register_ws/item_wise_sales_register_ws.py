from __future__ import unicode_literals

import json
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint

from worldshading.reporting.item_wise_sales import (
	append_warning,
	filter_transaction_rows,
	get_transaction_contributions,
	quantize_money,
	to_decimal,
)


WARNING_LABELS = {
	"ambiguous_parent_rows": _("Ambiguous parent rows"),
	"missing_parent_item": _("Missing parent Sales Invoice Item"),
	"missing_parent_link": _("Packed Item has no parent row link; parent Item fallback used"),
	"invalid_parent_link_fallback": _("Packed Item parent row link is invalid; parent Item fallback used"),
	"packed_amount_from_rate": _("Packed amount calculated from rate"),
	"packed_value_from_quantity": _("Packed value allocated by quantity"),
	"zero_qty_nonzero_value": _("Zero quantity with non-zero value"),
}


def execute(filters=None):
	filters = dict(filters or {})
	contributions = get_transaction_contributions(filters)
	tax_context = get_tax_context(contributions)
	apply_tax_values(contributions, tax_context)
	rows = filter_transaction_rows(contributions, filters)
	item_codes = sorted(set(row.get("item_code") for row in rows if row.get("item_code")))
	item_context = get_item_context(
		item_codes, filters.get("company"), filters.get("warehouse")
	)
	detail_context = get_detail_context(rows) if cint(filters.get("show_detailed_report")) else {}

	for row in rows:
		invoice_currency = row.get("currency")
		row.update(item_context.get(row.get("item_code"), {}))
		row["invoice_currency"] = invoice_currency
		row["currency"] = row.get("company_currency") or invoice_currency
		row["reconciliation_warning"] = "; ".join(row.get("warnings") or [])
		if cint(filters.get("show_detailed_report")):
			row.update(detail_context.get(row.get("invoice"), {}))
			row["invoice_count"] = 1
			row["last_sold_date"] = row.get("posting_date")

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
		_column("Warnings", "reconciliation_warning", "Data", 180),
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
		_column("Invoice Currency", "invoice_currency", "Link", 100, "Currency"),
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
	])
	return columns


def get_item_context(item_codes, company, warehouse=None):
	if not item_codes:
		return {}
	warehouse_condition = " and bin.warehouse = %(warehouse)s" if warehouse else ""
	rows = frappe.db.sql("""
		select
			item.name as item_code, item.item_name, item.item_group,
			item.brand, item.stock_uom, max(company.default_currency) as company_currency,
			max(item_default.default_supplier) as default_supplier,
			max(supplier.supplier_name) as supplier_name,
			coalesce(max(stock.actual_qty), 0) as current_stock_qty
		from `tabItem` item
		left join `tabItem Default` item_default
			on item_default.parent = item.name
			and item_default.company = %(company)s
		left join `tabSupplier` supplier
			on supplier.name = item_default.default_supplier
		inner join `tabCompany` company on company.name = %(company)s
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
		select parent as invoice, account_head, description, item_wise_tax_detail,
			charge_type, base_tax_amount_after_discount_amount
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
		if not details and tax_row.charge_type == "Actual":
			key = (tax_row.invoice, "__actual__")
			entry = result.setdefault(key, {"amount": Decimal("0"), "accounts": []})
			entry["amount"] += to_decimal(tax_row.base_tax_amount_after_discount_amount)
			account = tax_row.account_head or tax_row.description
			if account and account not in entry["accounts"]:
				entry["accounts"].append(account)
	for entry in result.values():
		entry["accounts"] = ", ".join(entry["accounts"])
	return result


def apply_tax_values(rows, tax_context):
	for row in rows:
		row["tax"] = Decimal("0.000")
		row["tax_accounts"] = ""
	for key, context in tax_context.items():
		invoice, source_item = key
		weighted_rows = []
		for row in rows:
			if row.get("invoice") != invoice:
				continue
			if source_item == "__actual__":
				weight = abs(to_decimal(row.get("net_amount")))
			else:
				weight = Decimal("0")
				if row.get("item_code") == source_item:
					weight += abs(to_decimal(row.get("direct_net_amount")))
				if row.get("parent_item") == source_item:
					weight += abs(to_decimal(row.get("packed_net_amount")))
			if weight:
				weighted_rows.append((row, weight))
		total_weight = sum((value for unused_row, value in weighted_rows), Decimal("0"))
		allocated = Decimal("0")
		for index, (row, weight) in enumerate(weighted_rows):
			if index == len(weighted_rows) - 1:
				row_tax = quantize_money(to_decimal(context.get("amount")) - allocated)
			else:
				row_tax = quantize_money(to_decimal(context.get("amount")) * weight / total_weight)
			allocated += row_tax
			row["tax"] += row_tax
			accounts = [value for value in row.get("tax_accounts", "").split(", ") if value]
			if context.get("accounts") and context["accounts"] not in accounts:
				accounts.append(context["accounts"])
			row["tax_accounts"] = ", ".join(accounts)
	for row in rows:
		row["tax"] = quantize_money(row.get("tax"))
		row["total"] = quantize_money(to_decimal(row.get("net_amount")) + row["tax"])


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
