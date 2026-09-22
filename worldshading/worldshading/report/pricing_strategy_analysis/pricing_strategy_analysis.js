/* global frappe, __ */

frappe.query_reports["Pricing Strategy Analysis"] = {
	"filters": [
		{
			"fieldname": "company", "label": __("Company"), "fieldtype": "Link",
			"options": "Company", "reqd": 1, "default": frappe.defaults.get_user_default("Company")
		},
		{
			"fieldname": "from_date", "label": __("From Date"), "fieldtype": "Date",
			"reqd": 1, "default": frappe.datetime.add_months(frappe.datetime.get_today(), -12)
		},
		{
			"fieldname": "to_date", "label": __("To Date"), "fieldtype": "Date",
			"reqd": 1, "default": frappe.datetime.get_today()
		},
		{"fieldname": "item", "label": __("Item"), "fieldtype": "Link", "options": "Item"},
		{"fieldname": "item_group", "label": __("Item Group"), "fieldtype": "Link", "options": "Item Group"},
		{"fieldname": "brand", "label": __("Brand"), "fieldtype": "Link", "options": "Brand"},
		{
			"fieldname": "warehouse", "label": __("Warehouse"), "fieldtype": "Link", "options": "Warehouse",
			"get_query": function () {
				return {"filters": {"company": frappe.query_report.get_filter_value("company"), "disabled": 0}};
			}
		},
		{
			"fieldname": "regular_price_list", "label": __("Regular Price List"),
			"fieldtype": "Link", "options": "Price List", "reqd": 1,
			"default": frappe.defaults.get_default("selling_price_list"),
			"get_query": function () { return {"filters": {"selling": 1, "enabled": 1}}; }
		},
		{
			"fieldname": "b2b_price_list", "label": __("B2B Price List"),
			"fieldtype": "Link", "options": "Price List",
			"get_query": function () { return {"filters": {"selling": 1, "enabled": 1}}; }
		},
		{
			"fieldname": "include_items_without_sales", "label": __("Include Items Without Sales"),
			"fieldtype": "Check", "default": 1
		},
		{
			"fieldname": "cost_source", "label": __("Cost Source"), "fieldtype": "Select", "reqd": 1,
			"options": "Current Valuation Rate\nLatest Purchase Rate\nWeighted Average Purchase Rate",
			"default": "Current Valuation Rate"
		},
		{"fieldname": "expense_burden", "label": __("Expense Burden %"), "fieldtype": "Percent", "default": 0},
		{"fieldname": "vat_percent", "label": __("VAT %"), "fieldtype": "Percent", "default": 10},
		{
			"fieldname": "rounding_method", "label": __("Rounding Method"), "fieldtype": "Select",
			"options": "Nearest\nUp\nDown", "default": "Nearest", "reqd": 1
		},
		{"fieldname": "rounding_increment", "label": __("Rounding Increment"), "fieldtype": "Float", "default": 1, "reqd": 1},
		{"fieldname": "regular_markup", "label": __("Regular Markup %"), "fieldtype": "Percent", "default": 43},
		{"fieldname": "b2b_markup", "label": __("B2B Markup %"), "fieldtype": "Percent", "default": 33},
		{"fieldname": "tier_1_minimum", "label": __("Tier 1 Min Qty"), "fieldtype": "Float", "default": 5},
		{"fieldname": "tier_1_maximum", "label": __("Tier 1 Max Qty"), "fieldtype": "Float", "default": 9},
		{"fieldname": "tier_1_markup", "label": __("Tier 1 Markup %"), "fieldtype": "Percent", "default": 31},
		{"fieldname": "tier_2_minimum", "label": __("Tier 2 Min Qty"), "fieldtype": "Float", "default": 10},
		{"fieldname": "tier_2_maximum", "label": __("Tier 2 Max Qty"), "fieldtype": "Float", "default": 19},
		{"fieldname": "tier_2_markup", "label": __("Tier 2 Markup %"), "fieldtype": "Percent", "default": 29},
		{"fieldname": "tier_3_minimum", "label": __("Tier 3 Min Qty"), "fieldtype": "Float", "default": 20},
		{"fieldname": "tier_3_maximum", "label": __("Tier 3 Max Qty"), "fieldtype": "Float", "default": 39},
		{"fieldname": "tier_3_markup", "label": __("Tier 3 Markup %"), "fieldtype": "Percent", "default": 27},
		{"fieldname": "tier_4_minimum", "label": __("Tier 4 Min Qty"), "fieldtype": "Float", "default": 40},
		{"fieldname": "tier_4_maximum", "label": __("Tier 4 Max Qty (blank = no limit)"), "fieldtype": "Float"},
		{"fieldname": "tier_4_markup", "label": __("Tier 4 Markup %"), "fieldtype": "Percent", "default": 25}
	]
};
