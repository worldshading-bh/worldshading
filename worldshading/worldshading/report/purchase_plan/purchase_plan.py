# Copyright (c) 2013, 	9t9it and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, getdate, nowdate

def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)
	columns = get_columns(filters)
	data = get_data(filters)
	return columns, data


def validate_filters(filters):
	if filters.get('end_date') and getdate(filters.end_date) > getdate(nowdate()):
		frappe.throw(_('End Date cannot be later than today.'))
	if filters.get('start_date') and filters.get('end_date') \
			and getdate(filters.start_date) > getdate(filters.end_date):
		frappe.throw(_('Start Date cannot be later than End Date.'))


def round_whole_qty(value):
	value = flt(value)
	return int(value + 0.5) if value >= 0 else -int(abs(value) + 0.5)


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

def get_columns(filters):
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
			'fieldname': 'total_months_in_report',
			'label': _('Total Months In report'),
			'fieldtype':'Int',

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
			'fieldname': 'months_to_arrive',
			'label': _('Months To Arrive'),
			'fieldtype':'Float/1:60',

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
			'fieldname': 'priority_month',
			'label': _('Priority Month'),
			'fieldtype': 'Int',
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
	filters = [['Item Group', 'is_group', '=', 0]]
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


def get_data(filters):
	data = []
	item_filters = {
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
			'target_to_sources': {}
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
		fields=['name', 'item_code', 'item_name', 'stock_uom'],
		order_by='item_code asc'
	)

	stock_by_item = get_stock_by_item(item_codes)
	total_sales_by_item = get_total_sales_by_item(item_codes, filters)
	if filters.get('include_out_of_stock_sales'):
		out_of_stock_by_item = get_out_of_stock_values(
			item_codes,
			filters,
			total_sales_by_item
		)
	else:
		out_of_stock_by_item = {}
	converted_repack_values = get_converted_repack_values(
		item_codes,
		repack_context.get('target_to_sources'),
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
		row = [
			item.name, item.item_name, item.stock_uom, last_purchase_invoice_date,
			last_sales_invoice_date, total_sales
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
			planning_available_qty + on_purchase, total_months_in_report,
			monthly_sales, annual_sales, float(filters.months_to_arrive), period_expected_sales,
			shortage_happened, minimum_purchase_qty, reorder_quantity, expected_order_quantity,
			priority_month
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
			'target_to_sources': {}
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
	for rule_name in rule_names:
		sources = sources_by_rule.get(rule_name, [])
		targets = targets_by_rule.get(rule_name, [])
		if len(targets) != 1 or not sources:
			frappe.throw(_(
				'Repack Production Rule {0} must have at least one source and exactly one target.'
			).format(rule_name))
		target = targets[0]
		if not target.item_code or flt(target.qty) <= 0:
			frappe.throw(_('Repack Production Rule {0} has an invalid target quantity.').format(rule_name))
		if target.item_code in target_to_sources:
			frappe.throw(_(
				'Repack target Item {0} is used in more than one Repack Production Rule.'
			).format(target.item_code))

		mapped_sources = []
		for source in sources:
			if not source.item_code or flt(source.qty) <= 0:
				frappe.throw(_('Repack Production Rule {0} has an invalid source quantity.').format(rule_name))
			mapped_sources.append({
				'item_code': source.item_code,
				'ratio': flt(source.qty) / flt(target.qty),
				'rule': rule_name
			})
			source_to_targets.setdefault(source.item_code, []).append(target.item_code)
		target_to_sources[target.item_code] = mapped_sources

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

	return {
		'calculation_item_codes': sorted(connected_items),
		'purchase_item_codes': purchase_item_codes,
		'target_to_sources': target_to_sources
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


def get_converted_repack_values(item_codes, target_to_sources, total_sales_by_item,
		out_of_stock_by_item, stock_by_item):
	demand_by_source = {}
	available_by_source = {}
	trace_by_source = {}
	direct_demand_by_item = {}
	for item_code in item_codes:
		direct_demand = (
			total_sales_by_item.get(item_code, 0)
			+ out_of_stock_by_item.get(item_code, {}).get('estimated_sales_qty', 0)
		)
		direct_demand_by_item[item_code] = direct_demand
		if direct_demand:
			propagate_repack_value(
				item_code,
				direct_demand,
				target_to_sources,
				demand_by_source,
				trace_by_source,
				item_code
			)

		available_qty = max(
			flt(stock_by_item.get(item_code, {}).get('actual_qty')), 0
		)
		if available_qty:
			propagate_repack_value(
				item_code,
				available_qty,
				target_to_sources,
				available_by_source
			)

	item_rows = frappe.get_all(
		'Item',
		filters={'item_code': ['in', item_codes]},
		fields=['item_code', 'stock_uom']
	)
	uom_by_item = dict((row.item_code, row.stock_uom or '') for row in item_rows)
	detail_by_source = {}
	for source_item, origin_values in trace_by_source.items():
		details = []
		for origin_item in sorted(origin_values):
			details.append(_('{0}: {1:.3f} {2} = {3:.3f} {4}').format(
				origin_item,
				direct_demand_by_item.get(origin_item, 0),
				uom_by_item.get(origin_item, ''),
				origin_values.get(origin_item, 0),
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


def get_out_of_stock_values(item_codes, filters, total_sales_by_item):
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
		'item_codes': tuple(item_codes)
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
		'item_codes': tuple(item_codes)
	}, as_dict=1)

	opening_by_item = dict(
		(row.item_code, row.opening_qty or 0) for row in opening_rows
	)
	movements_by_item = {}
	for row in movement_rows:
		movements_by_item.setdefault(row.item_code, {})[getdate(row.posting_date)] = row.actual_qty or 0

	start_date = getdate(filters.start_date)
	total_days = date_diff(filters.end_date, filters.start_date) + 1
	result = {}
	for item_code in item_codes:
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
