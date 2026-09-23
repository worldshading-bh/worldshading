/* global frappe, __ */

function apply_pricing_strategy_filter_labels(report) {
	var page_form = report.page.main.find(".page-form");
	page_form.addClass("pricing-strategy-filter-form");
	(report.filters || []).forEach(function (filter) {
		var field = filter.df || {};
		var wrapper = $(filter.wrapper);
		if (!field.fieldname || !wrapper.length ||
			wrapper.children(".pricing-strategy-filter-label").length) {
			return;
		}
		wrapper.addClass("pricing-strategy-filter-control");
		var label = $("<label class='pricing-strategy-filter-label'></label>");
		if (field.fieldtype === "Check") {
			label.addClass("pricing-strategy-filter-label-spacer")
				.attr("aria-hidden", "true").html("&nbsp;");
		} else {
			label.text(__(field.label || field.fieldname));
			field.placeholder = "";
			wrapper.find("input").attr("placeholder", "");
		}
		wrapper.prepend(label);
	});
	if (!document.getElementById("pricing-strategy-filter-label-style")) {
		$("<style id='pricing-strategy-filter-label-style'>" +
			".pricing-strategy-filter-form{padding-top:4px;}" +
			".pricing-strategy-filter-form .pricing-strategy-filter-control{" +
				"box-sizing:border-box;height:50px;min-height:50px;" +
				"margin-top:0 !important;margin-bottom:0 !important;" +
				"padding-top:0 !important;padding-bottom:0 !important;}" +
			".pricing-strategy-filter-form .pricing-strategy-filter-control>.form-group{" +
				"margin-top:0 !important;margin-bottom:0 !important;}" +
			".pricing-strategy-filter-form .pricing-strategy-filter-control .checkbox{" +
				"margin-top:1px;margin-bottom:0;}" +
			".pricing-strategy-filter-form .pricing-strategy-filter-label{" +
				"display:block;height:13px;margin:0;overflow:hidden;color:#7c8793;font-size:10px;" +
				"font-weight:600;line-height:13px;text-overflow:ellipsis;white-space:nowrap;}" +
			".pricing-strategy-filter-form .pricing-strategy-filter-label-spacer{visibility:hidden;}" +
			"</style>").appendTo("head");
	}
}

var pricing_rule_strategy_fields = [
	"tier_1_qty_range", "tier_1_markup",
	"tier_2_qty_range", "tier_2_markup",
	"tier_3_qty_range", "tier_3_markup",
	"tier_4_qty_range", "tier_4_markup"
];

function toggle_pricing_rule_strategy_filters(report) {
	var show_strategy = Boolean(Number(report.get_filter_value("show_pricing_rule_strategy") || 0));
	(report.filters || []).forEach(function (filter) {
		if (pricing_rule_strategy_fields.indexOf(filter.df.fieldname) !== -1) {
			$(filter.wrapper).toggle(show_strategy);
		}
	});
}

function apply_pricing_strategy_column_colors(datatable) {
	var wrapper = datatable && datatable.wrapper;
	if (!wrapper) {
		return;
	}

	$(wrapper).addClass("pricing-strategy-result-columns");
	var price_field_colors = {
		"recommended_regular_net": "#e8f5e9",
		"recommended_b2b_net": "#e8f5e9",
		"recommended_regular_gross": "#eaf4ff",
		"recommended_b2b_gross": "#eaf4ff",
		"fully_loaded_cost": "#fff7e6",
		"current_normal_price": "#fff7e6",
		"current_b2b_price": "#fff7e6",
		"suggested_action": "#fff7e6",
		"warnings": "#fff0f0"
	};
	var report_columns = (frappe.query_report && frappe.query_report.columns) || [];
	var column_rules = [];

	$(wrapper).find(".dt-row-header .dt-cell").each(function (index) {
		var report_column = report_columns[index - 1] || {};
		var fieldname = report_column.fieldname || "";
		var background_color = price_field_colors[fieldname];
		if (/^tier_\d+_net$/.test(fieldname)) {
			background_color = "#e8f5e9";
		} else if (/^tier_\d+_gross$/.test(fieldname)) {
			background_color = "#eaf4ff";
		}
		var column_class = (this.className.match(/dt-cell--col-\d+/) || [])[0];
		if (background_color && column_class) {
			column_rules.push(
				".pricing-strategy-result-columns ." + column_class +
				"{background:" + background_color + " !important;}"
			);
		}
	});

	var style = $("#pricing-strategy-result-column-style");
	if (!style.length) {
		style = $("<style id='pricing-strategy-result-column-style'></style>").appendTo("head");
	}
	style.text(column_rules.join(""));
}

frappe.query_reports["Pricing Strategy Analysis"] = {
	"onload": function (report) {
		apply_pricing_strategy_filter_labels(report);
		toggle_pricing_rule_strategy_filters(report);
	},
	"after_datatable_render": function (datatable) {
		apply_pricing_strategy_column_colors(datatable);
	},
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
		{"fieldname": "regular_markup", "label": __("Regular Price Markup %"), "fieldtype": "Percent", "default": 43},
		{
			"fieldname": "b2b_price_list", "label": __("B2B Price List"),
			"fieldtype": "Link", "options": "Price List",
			"get_query": function () { return {"filters": {"selling": 1, "enabled": 1}}; }
		},
		{"fieldname": "b2b_markup", "label": __("B2B Price Markup %"), "fieldtype": "Percent", "default": 33},
		{
			"fieldname": "cost_source", "label": __("Cost Basis"), "fieldtype": "Select", "reqd": 1,
			"options": "Current Valuation Rate\nLatest Purchase Rate\nWeighted Average Purchase Rate",
			"default": "Current Valuation Rate"
		},
		{"fieldname": "vat_percent", "label": __("VAT %"), "fieldtype": "Percent", "default": 10},
		{
			"fieldname": "show_pricing_rule_strategy", "label": __("Show Pricing Rule Strategy"),
			"fieldtype": "Check", "default": 0,
			"on_change": function () {
				toggle_pricing_rule_strategy_filters(frappe.query_report);
				frappe.query_report.refresh();
			}
		},
		{"fieldname": "tier_1_qty_range", "label": __("Tier 1 Qty Range"), "fieldtype": "Data", "default": "5:9"},
		{"fieldname": "tier_1_markup", "label": __("Tier 1 Markup %"), "fieldtype": "Percent", "default": 31},
		{"fieldname": "tier_2_qty_range", "label": __("Tier 2 Qty Range"), "fieldtype": "Data", "default": "10:19"},
		{"fieldname": "tier_2_markup", "label": __("Tier 2 Markup %"), "fieldtype": "Percent", "default": 29},
		{"fieldname": "tier_3_qty_range", "label": __("Tier 3 Qty Range"), "fieldtype": "Data", "default": "20:39"},
		{"fieldname": "tier_3_markup", "label": __("Tier 3 Markup %"), "fieldtype": "Percent", "default": 27},
		{"fieldname": "tier_4_qty_range", "label": __("Tier 4 Qty Range"), "fieldtype": "Data", "default": "40+"},
		{"fieldname": "tier_4_markup", "label": __("Tier 4 Markup %"), "fieldtype": "Percent", "default": 25},
		{
			"fieldname": "exclude_items_without_sales", "label": __("Exclude Items Without Sales"),
			"fieldtype": "Check", "default": 0
		}
	]
};
