# Copyright (c) 2013, 	9t9it and contributors
# For license information, please see license.txt


import math

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)
	pricing_context = get_pricing_context()
	columns = get_columns(filters, pricing_context)
	data = get_data(filters, pricing_context)
	return columns, data


def validate_filters(filters):
	validate_numeric_filter(filters, 'months_to_arrive', _('Months to Arrive'))
	validate_numeric_filter(filters, 'percentage', _('Percentage'))
	validate_numeric_filter(filters, 'minimum_months', _('Min Stock Months'))
	if filters.get('end_date') and getdate(filters.end_date) > getdate(nowdate()):
		frappe.throw(_('End Date cannot be later than today.'))
	if filters.get('start_date') and filters.get('end_date') \
			and getdate(filters.start_date) > getdate(filters.end_date):
		frappe.throw(_('Start Date cannot be later than End Date.'))


def validate_numeric_filter(filters, fieldname, label):
	value = filters.get(fieldname)
	if value is None or value == '':
		frappe.throw(_('{0} is required.').format(label))
	try:
		value = float(value)
	except (TypeError, ValueError):
		frappe.throw(_('{0} must be a valid number.').format(label))
	if not math.isfinite(value):
		frappe.throw(_('{0} must be a finite number.').format(label))
	filters[fieldname] = value


def round_whole_qty(value):
	value = flt(value)
	return int(value + 0.5) if value >= 0 else -int(abs(value) + 0.5)


def get_rfq_report_filter_log(report_filters):
	if isinstance(report_filters, str):
		report_filters = frappe.parse_json(report_filters)
	if not isinstance(report_filters, dict):
		return ''

	filter_labels = [
		('start_date', _('Start Date')),
		('end_date', _('End Date')),
		('supplier', _('Supplier')),
		('supplier_group', _('Supplier Group')),
		('supplier_country', _('Supplier Country')),
		('item', _('Item')),
		('parent_item_group', _('Parent Item Groups')),
		('child_item_group', _('Child Item Groups')),
		('purchased_from', _('Item Purchase Country')),
		('country_of_origin', _('Item Country of Origin')),
		('months_to_arrive', _('Months to Arrive')),
		('percentage', _('Growth Percentage')),
		('minimum_months', _('Min Stock Months')),
		('include_repack_to_parent', _('Include Repack to Parent')),
		('include_out_of_stock_sales', _('Include Out of Stock Sales')),
		('disabled_items_only', _('Disabled Items Only'))
	]
	check_fields = set([
		'include_repack_to_parent',
		'include_out_of_stock_sales',
		'disabled_items_only'
	])
	filter_log = []
	for fieldname, label in filter_labels:
		value = report_filters.get(fieldname)
		if fieldname in check_fields:
			if not cint(value):
				continue
			value = _('Yes')
		elif isinstance(value, (list, tuple)):
			value = ', '.join(str(row) for row in value if row)
		if value is None or value == '':
			continue
		filter_log.append('{0}: {1}'.format(label, value))
	return '\n'.join(filter_log)


def get_pricing_context():
	price_list = frappe.db.get_single_value('Selling Settings', 'selling_price_list')
	price_list_values = frappe.db.get_value(
		'Price List', price_list, ['enabled', 'selling', 'currency'], as_dict=1
	) if price_list else None
	if not price_list_values or not price_list_values.enabled or not price_list_values.selling:
		price_list = None
		price_list_currency = None
	else:
		price_list_currency = price_list_values.currency

	company = frappe.defaults.get_user_default('Company') \
		or frappe.db.get_single_value('Global Defaults', 'default_company')
	company_currency = frappe.db.get_value('Company', company, 'default_currency') \
		if company else None
	return frappe._dict({
		'price_list': price_list,
		'price_list_currency': price_list_currency,
		'company': company,
		'company_currency': company_currency
	})


def resolve_rfq_purchase_country(supplier=None, supplier_country=None,
		item_purchase_country=None, item_origin_country=None, purchase_country=None):
	supplier_master_country = None
	if supplier:
		supplier_master_country = frappe.db.get_value(
			'Supplier',
			{'name': supplier, 'disabled': 0, 'prevent_rfqs': 0},
			'country'
		)
	return supplier_country or supplier_master_country \
		or item_purchase_country or item_origin_country or purchase_country


@frappe.whitelist()
def get_rfq_default_warehouse(supplier=None, supplier_country=None,
		item_purchase_country=None, item_origin_country=None, purchase_country=None):
	company = frappe.defaults.get_user_default('Company') \
		or frappe.db.get_single_value('Global Defaults', 'default_company')
	if not company:
		return None

	purchase_country = resolve_rfq_purchase_country(
		supplier=supplier,
		supplier_country=supplier_country,
		item_purchase_country=item_purchase_country,
		item_origin_country=item_origin_country,
		purchase_country=purchase_country
	)
	if not purchase_country:
		return None

	company_country = frappe.db.get_value('Company', company, 'country')
	settings_field = 'default_local_warehouse' \
		if company_country and purchase_country == company_country \
		else 'default_import_warehouse'
	warehouse = frappe.db.get_single_value('WS Settings', settings_field)
	if not warehouse:
		return None

	valid_warehouse = frappe.db.get_value(
		'Warehouse',
		{
			'name': warehouse,
			'is_group': 0,
			'disabled': 0,
			'company': company
		},
		'name'
	)
	return valid_warehouse


@frappe.whitelist()
def make_request_for_quotation(source_name=None):
	if not frappe.has_permission('Request for Quotation', 'create'):
		frappe.throw(
			_('You do not have permission to create a Request for Quotation.'),
			frappe.PermissionError
		)

	args = frappe.flags.args or frappe._dict()
	item_values = frappe.parse_json(args.get('item_values')) \
		if isinstance(args.get('item_values'), str) else args.get('item_values')
	items_by_code = {}
	for row in item_values or []:
		item_code = row.get('item_code') if isinstance(row, dict) else None
		qty = round_whole_qty(row.get('qty')) if isinstance(row, dict) else 0
		if item_code and qty > 0:
			items_by_code[item_code] = qty

	if not items_by_code:
		frappe.throw(_('There are no report Items with a purchase requirement.'))
	if len(items_by_code) > 1000:
		frappe.throw(_(
			'A maximum of 1000 Items can be added to one RFQ. Apply Purchase Plan filters first.'
		))

	items = frappe.get_list(
		'Item',
		filters={
			'name': ['in', list(items_by_code)],
			'disabled': 0,
			'is_stock_item': 1,
			'is_fixed_asset': 0
		},
		fields=['name', 'item_name', 'description', 'stock_uom'],
		limit_page_length=0
	)
	valid_item_codes = set(row.name for row in items)
	invalid_item_codes = sorted(set(items_by_code) - valid_item_codes)
	if invalid_item_codes:
		frappe.throw(_(
			'These Items are unavailable or you do not have permission to use them: {0}'
		).format(', '.join(invalid_item_codes)))

	supplier = args.get('supplier')
	supplier_group = args.get('supplier_group')
	supplier_country = args.get('supplier_country')
	item_purchase_country = args.get('item_purchase_country')
	item_origin_country = args.get('item_origin_country')
	purchase_country = args.get('purchase_country')
	supplier_master_country = None
	supplier_values = None
	if supplier:
		supplier_values = frappe.get_list(
			'Supplier',
			filters={
				'name': supplier,
				'disabled': 0,
				'prevent_rfqs': 0
			},
			fields=['name', 'supplier_name', 'supplier_group', 'country'],
			limit_page_length=1
		)
		if not supplier_values:
			frappe.throw(_('The selected Supplier cannot be used for an RFQ.'))
		supplier_group = supplier_values[0].supplier_group
		supplier_master_country = supplier_values[0].country
	elif supplier_group and not frappe.db.exists('Supplier Group', supplier_group):
		frappe.throw(_('The selected Supplier Group does not exist.'))

	purchase_country = supplier_country or supplier_master_country \
		or item_purchase_country or item_origin_country or purchase_country

	if purchase_country and not frappe.db.exists('Country', purchase_country):
		frappe.throw(_('The selected Country of Purchase does not exist.'))

	company = frappe.defaults.get_user_default('Company') \
		or frappe.db.get_single_value('Global Defaults', 'default_company')
	if not company:
		frappe.throw(_('Please set a default Company before creating the RFQ.'))

	warehouse = args.get('warehouse')
	if not warehouse:
		frappe.throw(_('Please select a Warehouse for the RFQ Items.'))
	warehouse_values = frappe.get_list(
		'Warehouse',
		filters={
			'name': warehouse,
			'is_group': 0,
			'disabled': 0,
			'company': company
		},
		fields=['name'],
		limit_page_length=1
	)
	if not warehouse_values:
		frappe.throw(_(
			'The selected Warehouse is unavailable or does not belong to {0}.'
		).format(company))

	rfq = frappe.new_doc('Request for Quotation')
	rfq.company = company
	rfq.transaction_date = nowdate()
	rfq.status = 'Draft'
	rfq.supplier_group = supplier_group
	rfq.country_of_purchase = purchase_country
	if frappe.get_meta('Request for Quotation').has_field('report_filter'):
		rfq.report_filter = get_rfq_report_filter_log(args.get('report_filters'))
	rfq.message_for_supplier = _(
		'Please quote your best price and delivery schedule for the following items.'
	)

	if supplier_values:
		party_details = frappe.get_attr(
			'erpnext.accounts.party.get_party_details'
		)(party=supplier_values[0].name, party_type='Supplier') or {}
		rfq.append('suppliers', {
			'supplier': supplier_values[0].name,
			'supplier_name': supplier_values[0].supplier_name,
			'contact': party_details.get('contact_person'),
			'email_id': party_details.get('contact_email')
		})

	items_by_name = dict((row.name, row) for row in items)
	for item_code in sorted(items_by_code):
		item = items_by_name[item_code]
		rfq.append('items', {
			'item_code': item.name,
			'item_name': item.item_name,
			'description': item.description or item.item_name or item.name,
			'qty': items_by_code[item_code],
			'uom': item.stock_uom,
			'stock_uom': item.stock_uom,
			'conversion_factor': 1,
			'schedule_date': nowdate(),
			'warehouse': warehouse_values[0].name
		})

	return rfq


def validate_reorder_warehouses(warehouse_group, warehouse):
	warehouse_group_values = frappe.db.get_value(
		'Warehouse', warehouse_group, ['is_group', 'disabled', 'company'], as_dict=1
	)
	warehouse_values = frappe.db.get_value(
		'Warehouse', warehouse, ['is_group', 'disabled', 'company'], as_dict=1
	)
	if not warehouse_group_values or not warehouse_group_values.is_group \
			or warehouse_group_values.disabled:
		frappe.throw(_('Please select an enabled warehouse group.'))
	if not warehouse_values or warehouse_values.is_group or warehouse_values.disabled:
		frappe.throw(_('Please select an enabled request warehouse.'))
	if warehouse_group_values.company != warehouse_values.company:
		frappe.throw(_('Warehouse Group and Request for Warehouse must belong to the same company.'))


def get_valid_reorder_items(item_values, item_groups=None, allow_empty=False):
	item_values = frappe.parse_json(item_values) if isinstance(item_values, str) else item_values
	item_groups = frappe.parse_json(item_groups) if isinstance(item_groups, str) else item_groups
	if isinstance(item_groups, str):
		item_groups = [item_groups]
	item_groups = [group for group in (item_groups or []) if group]
	if not item_groups:
		frappe.throw(_('Please select at least one Item Group.'))
	allowed_item_groups = get_item_groups_with_children(item_groups)
	items_by_code = {}
	for row in item_values or []:
		item_code = row.get('item') if isinstance(row, dict) else None
		minimum_qty = round_whole_qty(row.get('minimum_qty')) if isinstance(row, dict) else 0
		if item_code and minimum_qty > 0:
			items_by_code[item_code] = minimum_qty

	if not items_by_code:
		frappe.throw(_('There are no report items with Min greater than zero.'))
	if len(items_by_code) > 5000:
		frappe.throw(_('A maximum of 5000 items can be updated at one time.'))

	existing_items = frappe.get_all(
		'Item',
		filters={
			'name': ['in', list(items_by_code)],
			'item_group': ['in', allowed_item_groups]
		},
		fields=['name']
	)
	existing_item_codes = set(row.name for row in existing_items)
	if not existing_item_codes:
		if allow_empty:
			return []
		frappe.throw(_('No report Items with Min greater than zero belong to the selected Item Group.'))

	return [
		{'item': item_code, 'minimum_qty': items_by_code[item_code]}
		for item_code in sorted(existing_item_codes)
	]


@frappe.whitelist()
def get_item_reorder_selection_count(item_values, item_groups):
	if not frappe.has_permission('Item', 'write'):
		frappe.throw(_('You do not have permission to update Item reorder levels.'), frappe.PermissionError)
	return len(get_valid_reorder_items(item_values, item_groups, allow_empty=True))


def validate_reorder_row_conflicts(item_values, warehouse_group, warehouse):
	item_codes = [row.get('item') for row in item_values]
	existing_rows = frappe.get_all(
		'Item Reorder',
		filters={
			'parent': ['in', item_codes],
			'warehouse': warehouse
		},
		fields=['parent', 'warehouse_group', 'material_request_type']
	)
	conflicting_items = sorted(set(
		row.parent for row in existing_rows
		if row.warehouse_group != warehouse_group
		or row.material_request_type != 'Purchase'
	))
	if conflicting_items:
		frappe.throw(_(
			'These Items already use {0} in a different reorder rule: {1}. '
			'No Items were queued or changed.'
		).format(warehouse, ', '.join(conflicting_items)))


@frappe.whitelist()
def queue_item_reorder_update(item_values, warehouse_group, warehouse, item_groups, reorder_qty=1):
	if not frappe.has_permission('Item', 'write'):
		frappe.throw(_('You do not have permission to update Item reorder levels.'), frappe.PermissionError)

	reorder_qty = flt(reorder_qty)
	if reorder_qty <= 0:
		frappe.throw(_('Re-order Qty must be greater than zero.'))
	validate_reorder_warehouses(warehouse_group, warehouse)
	valid_items = get_valid_reorder_items(item_values, item_groups)
	validate_reorder_row_conflicts(valid_items, warehouse_group, warehouse)
	frappe.enqueue(
		'worldshading.worldshading.report.purchase_plan.purchase_plan.apply_item_reorder_update',
		queue='long',
		timeout=1500,
		item_values=valid_items,
		warehouse_group=warehouse_group,
		warehouse=warehouse,
		item_groups=item_groups,
		reorder_qty=reorder_qty
	)
	return {'queued_items': len(valid_items)}


def apply_item_reorder_update(item_values, warehouse_group, warehouse, item_groups, reorder_qty=1):
	reorder_qty = flt(reorder_qty)
	if reorder_qty <= 0:
		frappe.throw(_('Re-order Qty must be greater than zero.'))
	validate_reorder_warehouses(warehouse_group, warehouse)
	valid_items = get_valid_reorder_items(item_values, item_groups)
	validate_reorder_row_conflicts(valid_items, warehouse_group, warehouse)
	created = 0
	updated = 0

	for value in valid_items:
		item = frappe.get_doc('Item', value.get('item'))
		minimum_qty = flt(value.get('minimum_qty'))
		matching_rows = [
			row for row in item.get('reorder_levels')
			if row.warehouse_group == warehouse_group
			and row.warehouse == warehouse
			and row.material_request_type == 'Purchase'
		]
		if matching_rows:
			for row in matching_rows:
				row.warehouse_reorder_level = minimum_qty
				row.warehouse_reorder_qty = reorder_qty
			updated += 1
		else:
			item.append('reorder_levels', {
				'warehouse_group': warehouse_group,
				'warehouse': warehouse,
				'warehouse_reorder_level': minimum_qty,
				'warehouse_reorder_qty': reorder_qty,
				'material_request_type': 'Purchase'
			})
			created += 1
		item.save()

	return {'created': created, 'updated': updated}

def get_columns(filters, pricing_context):
	columns = [
		{
			'fieldname': 'item',
			'label': _('Item'),
			'fieldtype': 'Link',
			'options': 'Item',
			'width': 80
		},
		{
			'fieldname': 'item_name',
			'label': _('Item Name'),
			'fieldtype': 'Data',
			'width': 200
		},
		{
			'fieldname': 'unit',
			'label': _('Unit'),
			'fieldtype':'Link',
			'options': 'UOM'
		},
		{
			'fieldname': 'last_purchase_invoice_date',
			'label': _('Last Purchase Date'),
			'fieldtype':'Date',

		},
		{
			'fieldname': 'last_sales_invoice_date',
			'label': _('Last Sale Date'),
			'fieldtype':'Date',

		},
		{
			'fieldname': 'sales_invoice_count',
			'label': _('No. of Sales Invoices'),
			'fieldtype': 'Int',
			'width': 100
		},
		{
			'fieldname': 'total_sales',
			'label': _('Direct Sales'),
			'fieldtype':'Float/1:60',

		}
	]
	if filters and filters.get('include_out_of_stock_sales'):
		columns.extend([
			{
				'fieldname': 'out_of_stock_days',
				'label': _('Out of Stock Days'),
				'fieldtype': 'Int'
			},
			{
				'fieldname': 'estimated_out_of_stock_sales_qty',
				'label': _('Estimated Out of Stock Sales Qty'),
				'fieldtype': 'Float'
			}
		])
	if filters and filters.get('include_repack_to_parent'):
		columns.extend([
			{
				'fieldname': 'converted_repack_demand',
				'label': _('Converted Repack Sales'),
				'fieldtype': 'Int'
			},
			{
				'fieldname': 'repack_demand_from',
				'label': _('Repack From'),
				'fieldtype': 'Data',
				'width': 260
			}
		])
	columns.extend([
		{
			'fieldname': 'percentage',
			'label': _('Percentage %'),
			'fieldtype':'Float/1:60',

		},
		{
			'fieldname': 'expected_total_sales',
			'label': _('Expected Total Sale'),
			'fieldtype':'Float/1:60',

		},
		{
			'fieldname': 'min',
			'label': _('Min'),
			'fieldtype':'Int',

		},
		{
			'fieldname': 'available_quantity',
			'label': _('Available Quantity'),
			'fieldtype':'Float/1:60',

		},
	] + ([
		{
			'fieldname': 'converted_repack_available',
			'label': _('Converted Repack Available'),
			'fieldtype': 'Float'
		}
	] if filters and filters.get('include_repack_to_parent') else []) + [
		{
			'fieldname': 'on_purchase',
			'label': _('On Purchase'),
			'fieldtype':'Float/1:60',

		},
		{
			'fieldname': 'on_purchase_po',
			'label': _('On Purchase PO'),
			'fieldtype': 'Data',
			'width': 180
		},
		{
			'fieldname': 'available_total_qty',
			'label': _('Available Total Qty'),
			'fieldtype':'Float/1:60',

		},
		{
			'fieldname': 'monthy_sales',
			'label': _('Monthy Sales'),
			'fieldtype':'Int',

		},
		{
			'fieldname': 'annual_sales',
			'label': _('Annual Sales'),
			'fieldtype':'Int',

		},
		{
			'fieldname': 'period_expected_sales',
			'label': _('Period Expected Sales'),
			'fieldtype':'Int',

		},
		{
			'fieldname': 'shortage_happened',
			'label': _('Shortage Happend'),
			'fieldtype':'Int',

		},
		{
			'fieldname': 'minimum_purchase_qty',
			'label': _('Re-Order Level'),
			'fieldtype': 'Int'
		},
		{
			'fieldname': 'reorder_quantity',
			'label': _('Re-Order quantity'),
			'fieldtype':'Int',

		},
		{
			'fieldname': 'expected_order_quantity',
			'label': _('Expected Order Quantity'),
			'fieldtype':'Int',

		},
		{
			'fieldname': 'rfq_order_quantity',
			'label': _('RFQ Order Qty'),
			'fieldtype': 'Int',
			'width': 130
		},
		{
			'fieldname': 'priority_month',
			'label': _('Priority Month'),
			'fieldtype': 'Int',
		},
		{
			'fieldname': 'item_suppliers',
			'label': _('Item Suppliers'),
			'fieldtype': 'Data',
			'width': 260
		},
		{
			'fieldname': 'least_supplier_cost',
			'label': _('Last Purchase Cost'),
			'fieldtype': 'Currency',
			'options': pricing_context.company_currency,
			'width': 130
		},
		{
			'fieldname': 'selling_price',
			'label': _('Selling Price'),
			'fieldtype': 'Currency',
			'options': pricing_context.price_list_currency,
			'width': 100
		},
		{
			'fieldname': 'priced_supplier_count',
			'label': _('Priced Supplier Count'),
			'fieldtype': 'Int',
			'hidden': 1
		},
		{
			'fieldname': 'supplier_purchase_details',
			'label': _('Supplier Purchase Details'),
			'fieldtype': 'Data',
			'hidden': 1
		}

	])

	return columns


def get_item_groups_with_children(selected_groups):
	all_groups = set(selected_groups or [])
	groups_to_check = list(all_groups)

	while groups_to_check:
		parent_group = groups_to_check.pop(0)
		children = frappe.get_all(
			'Item Group',
			filters={'parent_item_group': parent_group},
			fields=['name']
		)
		for child in children:
			if child.name not in all_groups:
				all_groups.add(child.name)
				groups_to_check.append(child.name)

	return list(all_groups)


@frappe.whitelist()
def get_child_item_group_options(txt='', parent_groups=None):
	parent_groups = frappe.parse_json(parent_groups) if parent_groups else []
	filters = [
		['Item Group', 'is_group', '=', 0],
		['Item Group', 'disabled', '=', 0]
	]
	if parent_groups:
		descendant_groups = get_item_groups_with_children(parent_groups)
		filters.append(['Item Group', 'name', 'in', descendant_groups])
	if txt:
		filters.append(['Item Group', 'name', 'like', '%{0}%'.format(txt)])

	groups = frappe.get_all(
		'Item Group',
		filters=filters,
		fields=['name', 'parent_item_group'],
		order_by='name asc',
		limit_page_length=50
	)
	return [
		{
			'value': group.name,
			'description': group.parent_item_group or ''
		}
		for group in groups
	]


def get_selling_prices(items, pricing_context):
	prices = {}
	item_by_code = dict((item.item_code, item) for item in items)
	item_codes = list(item_by_code)
	if pricing_context.price_list and item_codes:
		price_rows = frappe.get_all(
			'Item Price',
			filters={
				'item_code': ['in', item_codes],
				'price_list': pricing_context.price_list,
				'selling': 1
			},
			fields=[
				'item_code', 'uom', 'price_list_rate', 'valid_from', 'valid_upto',
				'modified'
			],
			order_by='valid_from desc, modified desc',
			limit_page_length=0
		)
		today = getdate(nowdate())
		for row in price_rows:
			if row.item_code in prices:
				continue
			if row.valid_from and getdate(row.valid_from) > today:
				continue
			if row.valid_upto and getdate(row.valid_upto) < today:
				continue
			item = item_by_code.get(row.item_code)
			if row.uom and item and row.uom != item.stock_uom:
				continue
			prices[row.item_code] = flt(row.price_list_rate)

	# This legacy site stores Regular Price values in Item.standard_rate when no
	# Item Price exists. Keep that fallback item-specific and read-only.
	for item in items:
		if item.item_code not in prices and flt(item.standard_rate):
			prices[item.item_code] = flt(item.standard_rate)
	return prices


def get_supplier_costs(item_codes, pricing_context):
	suppliers_by_item = dict((item_code, set()) for item_code in item_codes)
	configured_rows = frappe.get_all(
		'Item Supplier',
		filters={'parent': ['in', item_codes]},
		fields=['parent', 'supplier'],
		limit_page_length=0
	) if item_codes else []
	configured_suppliers = set(
		row.supplier for row in configured_rows if row.supplier
	)
	active_configured_suppliers = set()
	if configured_suppliers:
		active_configured_suppliers = set(
			row.name for row in frappe.get_all(
				'Supplier',
				filters={'name': ['in', list(configured_suppliers)], 'disabled': 0},
				fields=['name'],
				limit_page_length=0
			)
		)
	for row in configured_rows:
		if row.supplier in active_configured_suppliers:
			suppliers_by_item.setdefault(row.parent, set()).add(row.supplier)

	if not item_codes:
		return {}
	company_condition = ''
	query_values = {'item_codes': tuple(item_codes)}
	if pricing_context.company:
		company_condition = 'AND pi.company = %(company)s'
		query_values['company'] = pricing_context.company
	history_rows = frappe.db.sql("""
		SELECT
			pii.item_code,
			pi.supplier,
			pi.name AS purchase_invoice,
			pi.posting_date,
			pii.base_net_rate,
			pii.conversion_factor
		FROM `tabPurchase Invoice Item` pii
		INNER JOIN `tabPurchase Invoice` pi
			ON pi.name = pii.parent
		INNER JOIN `tabSupplier` supplier
			ON supplier.name = pi.supplier
		WHERE
			pi.docstatus = 1
			AND supplier.disabled = 0
			AND pii.item_code IN %(item_codes)s
			{company_condition}
		ORDER BY
			pii.item_code ASC,
			pi.posting_date DESC,
			pi.creation DESC,
			pii.idx DESC,
			pi.supplier ASC
	""".format(company_condition=company_condition), query_values, as_dict=1)

	latest_detail_by_pair = {}
	latest_cost_by_item = {}
	for row in history_rows:
		if not row.item_code or not row.supplier:
			continue
		suppliers_by_item.setdefault(row.item_code, set()).add(row.supplier)
		pair = (row.item_code, row.supplier)
		conversion_factor = flt(row.conversion_factor)
		cost = flt(row.base_net_rate) / conversion_factor if conversion_factor else 0
		if not conversion_factor:
			continue
		detail = {
			'cost': cost,
			'currency': pricing_context.company_currency,
			'purchase_invoice': row.purchase_invoice,
			'posting_date': str(row.posting_date)
		}
		if row.item_code not in latest_cost_by_item:
			latest_cost_by_item[row.item_code] = cost
		if pair not in latest_detail_by_pair:
			latest_detail_by_pair[pair] = detail

	result = {}
	for item_code in item_codes:
		supplier_names = suppliers_by_item.get(item_code, set())
		ranked_suppliers = sorted(
			supplier_names,
			key=lambda supplier: (
				0 if (item_code, supplier) in latest_detail_by_pair else 1,
				latest_detail_by_pair.get((item_code, supplier), {}).get('cost', 0),
				supplier
			)
		)
		priced_supplier_count = len([
			supplier for supplier in ranked_suppliers
			if (item_code, supplier) in latest_detail_by_pair
		])
		supplier_details = []
		for supplier in ranked_suppliers:
			detail = latest_detail_by_pair.get((item_code, supplier), {})
			supplier_details.append(dict(detail, supplier=supplier))
		result[item_code] = {
			'suppliers': ', '.join(ranked_suppliers),
			'priced_supplier_count': priced_supplier_count,
			'last_purchase_cost': latest_cost_by_item.get(item_code),
			'supplier_purchase_details': frappe.as_json(supplier_details)
		}
	return result


def get_data(filters, pricing_context):
	data = []
	item_filters = {
		'disabled': 1 if cint(filters.get('disabled_items_only')) else 0,
		'is_stock_item': 1,
		'is_fixed_asset': 0
	}
	if filters.get('item'):
		item_filters.update({'item_code': filters.get('item')})
	if filters.get('supplier') or filters.get('supplier_group') or filters.get('supplier_country'):
		supplier_item_codes = get_supplier_item_codes(
			filters.get('supplier'),
			filters.get('supplier_group'),
			filters.get('supplier_country')
		)
		if filters.get('item') and filters.get('item') not in supplier_item_codes:
			return data
		if not filters.get('item'):
			if not supplier_item_codes:
				return data
			item_filters.update({'item_code': ['in', supplier_item_codes]})
	if filters.get('child_item_group'):
		item_filters.update({'item_group': ['in', filters.get('child_item_group')]})
	elif filters.get('parent_item_group'):
		item_groups = get_item_groups_with_children(filters.get('parent_item_group'))
		item_filters.update({'item_group': ['in', item_groups]})
	elif filters.get('item_group'):
		item_groups = get_item_groups_with_children(filters.get('item_group'))
		item_filters.update({'item_group': ['in', item_groups]})
	if filters.get('purchased_from'):
		item_filters.update({'purchased_from': filters.get('purchased_from')})
	if filters.get('country_of_origin'):
		item_filters.update({'country_of_origin': filters.get('country_of_origin')})

	filtered_items = frappe.get_all(
		'Item',
		filters=item_filters,
		fields=['name', 'item_code', 'item_name', 'stock_uom']
	)
	filtered_item_codes = [item.item_code for item in filtered_items]
	if not filtered_item_codes:
		return data

	repack_context = (
		get_repack_context(filtered_item_codes)
		if filters.get('include_repack_to_parent')
		else {
			'calculation_item_codes': filtered_item_codes,
			'purchase_item_codes': filtered_item_codes,
			'target_to_sources': {},
			'repack_rules': []
		}
	)
	item_codes = repack_context.get('calculation_item_codes')
	purchase_item_codes = repack_context.get('purchase_item_codes')
	items = frappe.get_all(
		'Item',
		filters={
			'item_code': ['in', purchase_item_codes],
			'is_stock_item': 1,
			'is_fixed_asset': 0
		},
		fields=['name', 'item_code', 'item_name', 'stock_uom', 'standard_rate'],
		order_by='item_code asc'
	)
	selling_prices_by_item = get_selling_prices(items, pricing_context)
	supplier_costs_by_item = get_supplier_costs(purchase_item_codes, pricing_context)

	stock_by_item = get_stock_by_item(item_codes)
	total_sales_by_item = get_total_sales_by_item(item_codes, filters)
	sales_invoice_count_by_item = get_sales_invoice_count_by_item(item_codes, filters)
	if filters.get('include_out_of_stock_sales'):
		out_of_stock_by_item = get_out_of_stock_values(
			item_codes,
			filters,
			total_sales_by_item,
			sales_invoice_count_by_item
		)
	else:
		out_of_stock_by_item = {}
	converted_repack_values = get_converted_repack_values(
		item_codes,
		repack_context.get('repack_rules'),
		total_sales_by_item,
		out_of_stock_by_item,
		stock_by_item
	)
	reorder_quantity_by_item, reorder_level_by_item = get_reorder_values(purchase_item_codes)
	last_sales_date_by_item = get_effective_last_sales_dates(
		item_codes,
		repack_context.get('target_to_sources')
	)
	last_purchase_date_by_item = get_last_purchase_dates(purchase_item_codes)
	for item in items:
		total_sales = total_sales_by_item.get(item.item_code, 0)
		out_of_stock_values = out_of_stock_by_item.get(item.item_code, {})
		estimated_out_of_stock_sales_qty = out_of_stock_values.get('estimated_sales_qty', 0)
		converted_repack_demand = converted_repack_values.get(
			'demand_by_source', {}
		).get(item.item_code, 0)
		raw_converted_repack_available = converted_repack_values.get(
			'available_by_source', {}
		).get(item.item_code, 0)
		repack_demand_from = converted_repack_values.get(
			'detail_by_source', {}
		).get(item.item_code, '')
		stock = stock_by_item.get(item.item_code, {})
		on_purchase = stock.get('ordered_qty', 0)
		on_purchase_po = ', '.join(stock.get('purchase_orders', []))
		available_qty = stock.get('actual_qty', 0)
		last_purchase_invoice_date = last_purchase_date_by_item.get(item.item_code, '')
		last_sales_invoice_date = last_sales_date_by_item.get(item.item_code, '')
		sales_invoice_count = sales_invoice_count_by_item.get(item.item_code, 0)
		reorder_quantity = reorder_quantity_by_item.get(item.item_code, 0)
		minimum_purchase_qty = reorder_level_by_item.get(item.item_code, 0)
		adjusted_total_sales = (
			total_sales + estimated_out_of_stock_sales_qty + converted_repack_demand
		)
		expected_sales = adjusted_total_sales + (adjusted_total_sales * float(filters.percentage) / 100)
		total_months_in_report = date_diff(filters.end_date, filters.start_date) / 30 if date_diff(filters.end_date, filters.start_date) >= 30 else 0
		monthly_sales = int(expected_sales) / int(total_months_in_report) if total_months_in_report != 0 else 0
		converted_expected_sales = converted_repack_demand \
			+ (converted_repack_demand * float(filters.percentage) / 100)
		converted_monthly_sales = (
			converted_expected_sales / int(total_months_in_report)
			if int(total_months_in_report) > 0 else 0
		)
		converted_planning_requirement = converted_monthly_sales * (
			float(filters.months_to_arrive) + (2 * float(filters.minimum_months))
		)
		converted_repack_available = min(
			raw_converted_repack_available,
			max(converted_planning_requirement, 0)
		)
		planning_available_qty = available_qty + converted_repack_available
		annual_sales = monthly_sales * 12
		period_expected_sales = monthly_sales * float(filters.months_to_arrive)
		shortage_happened = (planning_available_qty + on_purchase) - period_expected_sales
		minimum_qty = round_whole_qty(monthly_sales * float(filters.minimum_months))
		usable_balance_after_arrival = max(shortage_happened, 0)
		expected_order_quantity = (
			usable_balance_after_arrival - minimum_qty - minimum_qty - minimum_purchase_qty
		)
		priority_month = (planning_available_qty + on_purchase) / monthly_sales if monthly_sales > 0 else 0
		pricing_values = supplier_costs_by_item.get(item.item_code, {})
		selling_price = selling_prices_by_item.get(item.item_code)
		last_purchase_cost = pricing_values.get('last_purchase_cost')
		row = [
			item.name, item.item_name, item.stock_uom, last_purchase_invoice_date,
			last_sales_invoice_date, sales_invoice_count, total_sales
		]
		if filters.get('include_out_of_stock_sales'):
			row.extend([
				out_of_stock_values.get('days', 0),
				estimated_out_of_stock_sales_qty
			])
		if filters.get('include_repack_to_parent'):
			row.extend([
				converted_repack_demand,
				repack_demand_from
			])
		row.extend([
			float(filters.percentage), expected_sales,
			minimum_qty, available_qty
		])
		if filters.get('include_repack_to_parent'):
			row.append(converted_repack_available)
		row.extend([
			on_purchase, on_purchase_po,
			planning_available_qty + on_purchase,
			monthly_sales, annual_sales, period_expected_sales,
			shortage_happened, minimum_purchase_qty, reorder_quantity, expected_order_quantity,
			round_whole_qty(abs(expected_order_quantity)) if expected_order_quantity < 0 else 0,
			priority_month, pricing_values.get('suppliers', ''), last_purchase_cost,
			selling_price, pricing_values.get('priced_supplier_count', 0),
			pricing_values.get('supplier_purchase_details', '[]')
		])
		data.append(row)

	return data


def get_supplier_item_codes(supplier=None, supplier_group=None, supplier_country=None):
	supplier_filters = {}
	if supplier:
		supplier_filters['name'] = supplier
	if supplier_group:
		supplier_filters['supplier_group'] = [
			'in', get_supplier_groups_with_children(supplier_group)
		]
	if supplier_country:
		supplier_filters['country'] = supplier_country

	suppliers = frappe.get_all(
		'Supplier',
		filters=supplier_filters,
		fields=['name'],
		limit_page_length=0
	)
	supplier_names = [row.name for row in suppliers]
	if not supplier_names:
		return []

	rows = frappe.db.sql("""
		SELECT DISTINCT
			pii.item_code
		FROM `tabPurchase Invoice Item` pii
		INNER JOIN `tabPurchase Invoice` pi
			ON pi.name = pii.parent
		WHERE
			pi.docstatus = 1
			AND pi.supplier IN %(suppliers)s
			AND pii.item_code IS NOT NULL
			AND pii.item_code != ''
	""", {'suppliers': tuple(supplier_names)}, as_dict=1)
	return [row.item_code for row in rows]


def get_supplier_groups_with_children(supplier_group):
	all_groups = set([supplier_group])
	groups_to_check = [supplier_group]
	while groups_to_check:
		parent_group = groups_to_check.pop(0)
		children = frappe.get_all(
			'Supplier Group',
			filters={'parent_supplier_group': parent_group},
			fields=['name'],
			limit_page_length=0
		)
		for child in children:
			if child.name not in all_groups:
				all_groups.add(child.name)
				groups_to_check.append(child.name)

	return list(all_groups)


def get_repack_context(filtered_item_codes):
	rules = frappe.get_all(
		'Repack Production Rule',
		filters={'type': 'Repack'},
		fields=['name']
	)
	rule_names = [row.name for row in rules]
	if not rule_names:
		return {
			'calculation_item_codes': list(filtered_item_codes),
			'purchase_item_codes': list(filtered_item_codes),
			'target_to_sources': {},
			'repack_rules': []
		}

	source_rows = frappe.get_all(
		'Source Item',
		filters={'parent': ['in', rule_names]},
		fields=['parent', 'item_code', 'qty']
	)
	target_rows = frappe.get_all(
		'Target Item',
		filters={'parent': ['in', rule_names]},
		fields=['parent', 'item_code', 'qty']
	)
	sources_by_rule = {}
	targets_by_rule = {}
	for row in source_rows:
		sources_by_rule.setdefault(row.parent, []).append(row)
	for row in target_rows:
		targets_by_rule.setdefault(row.parent, []).append(row)

	target_to_sources = {}
	source_to_targets = {}
	repack_rules = []
	for rule_name in rule_names:
		sources = sources_by_rule.get(rule_name, [])
		targets = targets_by_rule.get(rule_name, [])
		if not targets or not sources:
			frappe.throw(_(
				'Repack Production Rule {0} must have at least one source and one target.'
			).format(rule_name))

		mapped_sources = []
		for source in sources:
			if not source.item_code or flt(source.qty) <= 0:
				frappe.throw(_('Repack Production Rule {0} has an invalid source quantity.').format(rule_name))
			mapped_sources.append({
				'item_code': source.item_code,
				'qty': flt(source.qty),
				'rule': rule_name
			})

		mapped_targets = []
		for target in targets:
			if not target.item_code or flt(target.qty) <= 0:
				frappe.throw(_('Repack Production Rule {0} has an invalid target quantity.').format(rule_name))
			if target.item_code in target_to_sources:
				frappe.throw(_(
					'Repack target Item {0} is used in more than one Repack Production Rule.'
				).format(target.item_code))
			mapped_targets.append({
				'item_code': target.item_code,
				'qty': flt(target.qty)
			})
			target_to_sources[target.item_code] = [
				{
					'item_code': source.get('item_code'),
					'ratio': source.get('qty') / flt(target.qty),
					'rule': rule_name
				}
				for source in mapped_sources
			]
			for source in mapped_sources:
				source_to_targets.setdefault(
					source.get('item_code'), []).append(target.item_code)

		repack_rules.append({
			'name': rule_name,
			'sources': mapped_sources,
			'targets': mapped_targets
		})

	connected_items = set(filtered_item_codes)
	items_to_check = list(filtered_item_codes)
	while items_to_check:
		item_code = items_to_check.pop(0)
		neighbours = [
			source.get('item_code')
			for source in target_to_sources.get(item_code, [])
		] + source_to_targets.get(item_code, [])
		for neighbour in neighbours:
			if neighbour and neighbour not in connected_items:
				connected_items.add(neighbour)
				items_to_check.append(neighbour)

	purchase_item_codes = sorted(
		item_code for item_code in connected_items
		if item_code not in target_to_sources
	)
	if not purchase_item_codes:
		frappe.throw(_('The selected Repack rules do not lead to a purchase/source Item.'))
	relevant_rules = [
		rule for rule in repack_rules
		if any(
			row.get('item_code') in connected_items
			for row in rule.get('sources', []) + rule.get('targets', [])
		)
	]

	return {
		'calculation_item_codes': sorted(connected_items),
		'purchase_item_codes': purchase_item_codes,
		'target_to_sources': target_to_sources,
		'repack_rules': relevant_rules
	}


def propagate_repack_value(item_code, value, target_to_sources, values_by_source,
		trace_by_source=None, origin_item=None, path=None):
	path = list(path or [])
	if item_code in path:
		frappe.throw(_('A cycle exists in Repack Production Rules involving Item {0}.').format(item_code))
	path.append(item_code)
	for source in target_to_sources.get(item_code, []):
		source_item = source.get('item_code')
		converted_value = value * source.get('ratio')
		values_by_source[source_item] = (
			values_by_source.get(source_item, 0) + converted_value
		)
		if trace_by_source is not None and origin_item:
			origin_values = trace_by_source.setdefault(source_item, {})
			origin_values[origin_item] = (
				origin_values.get(origin_item, 0) + converted_value
			)
		propagate_repack_value(
			source_item,
			converted_value,
			target_to_sources,
			values_by_source,
			trace_by_source,
			origin_item,
			path
		)


def convert_repack_batch_values(direct_values, repack_rules):
	"""Combine target quantities and convert them to their Repack sources."""
	converted_values = {}
	origins_by_item = {}
	for item_code, value in direct_values.items():
		if flt(value) > 0:
			origins_by_item[item_code] = set([item_code])

	rules_by_name = dict((rule.get('name'), rule) for rule in repack_rules)
	rule_by_target = {}
	for rule in repack_rules:
		for target in rule.get('targets', []):
			rule_by_target[target.get('item_code')] = rule.get('name')

	upstream_rules = dict((rule_name, set()) for rule_name in rules_by_name)
	downstream_count = dict((rule_name, 0) for rule_name in rules_by_name)
	for rule_name, rule in rules_by_name.items():
		for source in rule.get('sources', []):
			upstream_rule = rule_by_target.get(source.get('item_code'))
			if upstream_rule and upstream_rule != rule_name \
					and upstream_rule not in upstream_rules[rule_name]:
				upstream_rules[rule_name].add(upstream_rule)
				downstream_count[upstream_rule] += 1

	rules_to_process = sorted([
		rule_name for rule_name, count in downstream_count.items()
		if count == 0
	])
	processed_rules = 0
	while rules_to_process:
		rule_name = rules_to_process.pop(0)
		rule = rules_by_name.get(rule_name)
		total_required_qty = 0
		total_target_qty = 0
		target_origins = set()
		for target in rule.get('targets', []):
			target_item = target.get('item_code')
			target_qty = flt(target.get('qty'))
			required_qty = (
				flt(direct_values.get(target_item))
				+ flt(converted_values.get(target_item))
			)
			total_required_qty += required_qty
			total_target_qty += target_qty
			target_origins.update(origins_by_item.get(target_item, set()))
		batch_multiplier = (
			total_required_qty / total_target_qty
			if total_target_qty else 0
		)

		if batch_multiplier > 0:
			for source in rule.get('sources', []):
				source_item = source.get('item_code')
				converted_values[source_item] = (
					converted_values.get(source_item, 0)
					+ (flt(source.get('qty')) * batch_multiplier)
				)
				origins_by_item.setdefault(source_item, set()).update(target_origins)

		processed_rules += 1
		for upstream_rule in sorted(upstream_rules.get(rule_name, set())):
			downstream_count[upstream_rule] -= 1
			if downstream_count[upstream_rule] == 0:
				rules_to_process.append(upstream_rule)
		rules_to_process.sort()

	if processed_rules != len(rules_by_name):
		frappe.throw(_('A cycle exists in the selected Repack Production Rules.'))

	return converted_values, origins_by_item


def get_converted_repack_values(item_codes, repack_rules, total_sales_by_item,
		out_of_stock_by_item, stock_by_item):
	direct_demand_by_item = {}
	direct_available_by_item = {}
	for item_code in item_codes:
		direct_demand = (
			total_sales_by_item.get(item_code, 0)
			+ out_of_stock_by_item.get(item_code, {}).get('estimated_sales_qty', 0)
		)
		direct_demand_by_item[item_code] = direct_demand
		direct_available_by_item[item_code] = max(
			flt(stock_by_item.get(item_code, {}).get('actual_qty')), 0
		)

	demand_by_source, origins_by_source = convert_repack_batch_values(
		direct_demand_by_item, repack_rules or [])
	available_by_source, unused_origins = convert_repack_batch_values(
		direct_available_by_item, repack_rules or [])

	item_rows = frappe.get_all(
		'Item',
		filters={'item_code': ['in', item_codes]},
		fields=['item_code', 'stock_uom']
	)
	uom_by_item = dict((row.item_code, row.stock_uom or '') for row in item_rows)
	detail_by_source = {}
	for source_item, origin_items in origins_by_source.items():
		if not demand_by_source.get(source_item):
			continue
		details = []
		for origin_item in sorted(origin_items):
			if origin_item == source_item:
				continue
			details.append(_('{0}: {1:.3f} {2}').format(
				origin_item,
				direct_demand_by_item.get(origin_item, 0),
				uom_by_item.get(origin_item, '')
			))
		details.append(_('Converted total: {0:.3f} {1}').format(
			demand_by_source.get(source_item, 0),
			uom_by_item.get(source_item, '')
		))
		detail_by_source[source_item] = '; '.join(details)

	return {
		'demand_by_source': dict(
			(source_item, round_whole_qty(value))
			for source_item, value in demand_by_source.items()
		),
		'available_by_source': available_by_source,
		'detail_by_source': detail_by_source
	}


def get_stock_by_item(item_codes):
	stock_by_item = {}
	rows = frappe.get_all(
		'Bin',
		filters={'item_code': ['in', item_codes]},
		fields=['item_code', 'actual_qty']
	)
	for row in rows:
		stock = stock_by_item.setdefault(
			row.item_code,
			{'actual_qty': 0, 'ordered_qty': 0, 'purchase_orders': []}
		)
		stock['actual_qty'] += row.actual_qty or 0

	ordered_rows = frappe.db.sql("""
		SELECT
			poi.item_code,
			po.name AS purchase_order,
			SUM((poi.qty - poi.received_qty) * poi.conversion_factor) AS ordered_qty
		FROM `tabPurchase Order Item` poi
		INNER JOIN `tabPurchase Order` po
			ON po.name = poi.parent
		WHERE
			po.docstatus = 1
			AND po.status NOT IN ('Closed', 'Delivered')
			AND poi.qty > poi.received_qty
			AND poi.delivered_by_supplier = 0
			AND poi.item_code IN %(item_codes)s
		GROUP BY poi.item_code, po.name
		ORDER BY poi.item_code, po.transaction_date, po.name
	""", {'item_codes': tuple(item_codes)}, as_dict=1)
	for row in ordered_rows:
		stock = stock_by_item.setdefault(
			row.item_code,
			{'actual_qty': 0, 'ordered_qty': 0, 'purchase_orders': []}
		)
		stock['ordered_qty'] += row.ordered_qty or 0
		stock['purchase_orders'].append(row.purchase_order)
	return stock_by_item


def get_total_sales_by_item(item_codes, filters):
	total_sales_by_item = {}
	date_filter = ['between', [filters.start_date, filters.end_date]]

	sales_invoice_rows = frappe.get_all(
		'Sales Invoice Item',
		filters={
			'docstatus': 1,
			'item_code': ['in', item_codes],
			'creation': date_filter
		},
		fields=['item_code', 'sum(qty) as qty'],
		group_by='item_code'
	)
	packed_item_rows = frappe.get_all(
		'Packed Item',
		filters={
			'parenttype': 'Sales Invoice',
			'docstatus': 1,
			'item_code': ['in', item_codes],
			'creation': date_filter
		},
		fields=['item_code', 'sum(qty) as qty'],
		group_by='item_code'
	)

	for row in sales_invoice_rows + packed_item_rows:
		total_sales_by_item[row.item_code] = (
			total_sales_by_item.get(row.item_code, 0) + (row.qty or 0)
		)
	return total_sales_by_item


def get_sales_invoice_count_by_item(item_codes, filters):
	if not item_codes:
		return {}

	rows = frappe.db.sql("""
		SELECT invoice_items.item_code, COUNT(DISTINCT invoice_items.parent) AS invoice_count
		FROM (
			SELECT sii.item_code, sii.parent
			FROM `tabSales Invoice Item` sii
			WHERE sii.docstatus = 1
				AND sii.item_code IN %(item_codes)s
				AND sii.creation BETWEEN %(start_date)s AND %(end_date)s
			UNION
			SELECT pi.item_code, pi.parent
			FROM `tabPacked Item` pi
			WHERE pi.parenttype = 'Sales Invoice'
				AND pi.docstatus = 1
				AND pi.item_code IN %(item_codes)s
				AND pi.creation BETWEEN %(start_date)s AND %(end_date)s
		) invoice_items
		GROUP BY invoice_items.item_code
	""", {
		'item_codes': tuple(item_codes),
		'start_date': filters.start_date,
		'end_date': filters.end_date
	}, as_dict=1)

	return dict((row.item_code, row.invoice_count or 0) for row in rows)


def get_out_of_stock_values(
		item_codes, filters, total_sales_by_item, sales_invoice_count_by_item):
	total_report_days = date_diff(filters.end_date, filters.start_date)
	completed_report_months = int(total_report_days / 30) if total_report_days >= 30 else 0
	result = {}
	items_for_stock_check = []
	for item_code in item_codes:
		sales_invoice_count = sales_invoice_count_by_item.get(item_code, 0)
		average_monthly_invoices = (
			sales_invoice_count / completed_report_months
			if completed_report_months > 0 else sales_invoice_count
		)
		if average_monthly_invoices <= 5:
			result[item_code] = {
				'days': None,
				'estimated_sales_qty': 0
			}
		else:
			items_for_stock_check.append(item_code)

	if not items_for_stock_check:
		return result

	working_day_rows = frappe.db.sql("""
		SELECT DISTINCT
			DATE(creation) AS working_date
		FROM `tabSales Invoice`
		WHERE
			docstatus = 1
			AND DATE(creation) BETWEEN %(start_date)s AND %(end_date)s
	""", {
		'start_date': filters.start_date,
		'end_date': filters.end_date
	}, as_dict=1)
	working_dates = set(
		getdate(row.working_date) for row in working_day_rows
		if row.working_date
	)

	opening_rows = frappe.db.sql("""
		SELECT
			item_code,
			SUM(actual_qty) AS opening_qty
		FROM `tabStock Ledger Entry`
		WHERE
			posting_date < %(start_date)s
			AND item_code IN %(item_codes)s
		GROUP BY item_code
	""", {
		'start_date': filters.start_date,
		'item_codes': tuple(items_for_stock_check)
	}, as_dict=1)

	movement_rows = frappe.db.sql("""
		SELECT
			item_code,
			posting_date,
			SUM(actual_qty) AS actual_qty
		FROM `tabStock Ledger Entry`
		WHERE
			posting_date BETWEEN %(start_date)s AND %(end_date)s
			AND item_code IN %(item_codes)s
		GROUP BY item_code, posting_date
		ORDER BY item_code, posting_date
	""", {
		'start_date': filters.start_date,
		'end_date': filters.end_date,
		'item_codes': tuple(items_for_stock_check)
	}, as_dict=1)

	opening_by_item = dict(
		(row.item_code, row.opening_qty or 0) for row in opening_rows
	)
	movements_by_item = {}
	for row in movement_rows:
		movements_by_item.setdefault(row.item_code, {})[getdate(row.posting_date)] = row.actual_qty or 0

	start_date = getdate(filters.start_date)
	total_days = date_diff(filters.end_date, filters.start_date) + 1
	for item_code in items_for_stock_check:
		balance = opening_by_item.get(item_code, 0)
		movements = movements_by_item.get(item_code, {})
		out_of_stock_days = 0
		selling_days = 0
		current_date = start_date
		for unused_day in range(total_days):
			balance += movements.get(current_date, 0)
			if current_date in working_dates:
				selling_days += 1
				if balance <= 0:
					out_of_stock_days += 1
			current_date = add_days(current_date, 1)

		in_stock_days = selling_days - out_of_stock_days
		total_sales = total_sales_by_item.get(item_code, 0)
		estimated_sales_qty = (
			(total_sales / in_stock_days) * out_of_stock_days
			if in_stock_days > 0 else 0
		)
		result[item_code] = {
			'days': out_of_stock_days,
			'estimated_sales_qty': estimated_sales_qty
		}

	return result


def get_reorder_values(item_codes):
	reorder_quantity_by_item = {}
	reorder_level_by_item = {}
	company = frappe.defaults.get_user_default('Company')
	company_abbr = frappe.db.get_value('Company', company, 'abbr') if company else None
	warehouse_group = 'All Warehouses - {0}'.format(company_abbr) if company_abbr else None

	rows = frappe.get_all(
		'Item Reorder',
		filters={
			'parent': ['in', item_codes],
			'material_request_type': 'Purchase'
		},
		fields=['parent', 'warehouse_group', 'warehouse_reorder_level', 'warehouse_reorder_qty']
	)
	for row in rows:
		reorder_quantity_by_item[row.parent] = (
			reorder_quantity_by_item.get(row.parent, 0) + (row.warehouse_reorder_qty or 0)
		)
		if warehouse_group and row.warehouse_group == warehouse_group and row.parent not in reorder_level_by_item:
			reorder_level_by_item[row.parent] = row.warehouse_reorder_level or 0

	return reorder_quantity_by_item, reorder_level_by_item


def get_last_sales_dates(item_codes):
	rows = frappe.db.sql("""
		SELECT
			item_code,
			MAX(posting_date) AS posting_date
		FROM `tabStock Ledger Entry`
		WHERE
			voucher_type IN ('Sales Invoice', 'Delivery Note')
			AND actual_qty < 0
			AND item_code IN %(item_codes)s
		GROUP BY item_code
	""", {'item_codes': tuple(item_codes)}, as_dict=1)
	return dict((row.item_code, row.posting_date) for row in rows)


def get_effective_last_sales_dates(item_codes, target_to_sources):
	direct_dates = get_last_sales_dates(item_codes)
	effective_dates = dict(direct_dates)
	for item_code, sale_date in direct_dates.items():
		propagate_repack_date(
			item_code,
			sale_date,
			target_to_sources,
			effective_dates
		)
	return effective_dates


def propagate_repack_date(item_code, sale_date, target_to_sources,
		effective_dates, path=None):
	path = list(path or [])
	if item_code in path:
		frappe.throw(_('A cycle exists in Repack Production Rules involving Item {0}.').format(item_code))
	path.append(item_code)
	for source in target_to_sources.get(item_code, []):
		source_item = source.get('item_code')
		if not effective_dates.get(source_item) \
				or sale_date > effective_dates.get(source_item):
			effective_dates[source_item] = sale_date
		propagate_repack_date(
			source_item,
			sale_date,
			target_to_sources,
			effective_dates,
			path
		)


def get_last_purchase_dates(item_codes):
	rows = frappe.db.sql("""
		SELECT
			item_code,
			MAX(posting_date) AS posting_date
		FROM `tabStock Ledger Entry`
		WHERE
			voucher_type IN ('Purchase Invoice', 'Purchase Receipt')
			AND actual_qty > 0
			AND item_code IN %(item_codes)s
		GROUP BY item_code
	""", {'item_codes': tuple(item_codes)}, as_dict=1)
	return dict((row.item_code, row.posting_date) for row in rows)
