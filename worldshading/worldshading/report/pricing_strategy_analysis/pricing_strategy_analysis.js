/* global frappe, __, flt, format_currency */

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

var pricing_strategy_controlled_fields = [
	"regular_price_list", "regular_markup", "b2b_price_list", "b2b_markup",
	"cost_source", "indirect_expense_account", "vat_percent",
	"exclude_expense_from_pricing", "show_pricing_rule_strategy", "pricing_tiers_json"
];

function load_pricing_strategy_settings(report) {
	var strategy_name = report.get_filter_value("pricing_strategy");
	if (!strategy_name) {
		return;
	}
	if (report.raw_data && report.raw_data.doc && report.raw_data.doc.name) {
		return;
	}
	frappe.call({
		method: "worldshading.worldshading.report.pricing_strategy_analysis." +
			"pricing_strategy_analysis.get_pricing_strategy_settings",
		freeze: true,
		freeze_message: __("Loading Pricing Strategy..."),
		args: {
			pricing_strategy: strategy_name,
			company: report.get_filter_value("company")
		},
		callback: function (response) {
			var settings = response.message || {};
			var values = {};
			pricing_strategy_controlled_fields.forEach(function (fieldname) {
				if (report.get_filter(fieldname) &&
					Object.prototype.hasOwnProperty.call(settings, fieldname)) {
					values[fieldname] = settings[fieldname];
				}
			});
			report.set_filter_value(values);
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

function get_expense_per_unit_tooltip(data) {
	if (!data || data.expense_per_unit === null || data.expense_per_unit === undefined) {
		return "";
	}
	var source = data.expense_source || __("Unavailable");
	var lines = [__("Expense allocation basis") + ": " + __(source)];
	var allocated_expense = flt(data.allocated_expense);
	var sales_value = flt(data.sales_value);
	var sales_qty = flt(data.sales_qty);
	var expense_per_unit = flt(data.expense_per_unit);

	if (source === "Actual period sales" && sales_value > 0 && sales_qty > 0) {
		var sales_ratio = allocated_expense / sales_value * 100;
		lines.push(__("Sales Value") + ": " + format_currency(sales_value));
		lines.push(__("Company Expense Ratio") + ": " + sales_ratio.toFixed(3) + "%");
		lines.push(__("Allocated Expense") + ": " + format_currency(allocated_expense));
		lines.push(__("Sales Quantity") + ": " + sales_qty);
		lines.push(
			__("Expense / Unit") + ": " + format_currency(allocated_expense) +
			" / " + sales_qty + " = " + format_currency(expense_per_unit)
		);
	} else if (source === "Regular Item Price fallback" && flt(data.current_normal_price) > 0) {
		var regular_price = flt(data.current_normal_price);
		var fallback_ratio = expense_per_unit / regular_price * 100;
		lines.push(__("Regular Item Price") + ": " + format_currency(regular_price));
		lines.push(__("Company Expense Ratio") + ": " + fallback_ratio.toFixed(3) + "%");
		lines.push(
			__("Expense / Unit") + ": " + format_currency(regular_price) +
			" x " + fallback_ratio.toFixed(3) + "% = " + format_currency(expense_per_unit)
		);
	} else {
		lines.push(__("Expense / Unit") + ": " + format_currency(expense_per_unit));
	}
	return lines.join("\n");
}

function get_pricing_update_item_codes(report) {
	var item_codes = [];
	var seen = {};
	var report_rows = report.data || [];
	if (report.raw_data && report.raw_data.add_total_row && report_rows.length) {
		report_rows = report_rows.slice(0, -1);
	}
	report_rows.forEach(function (row) {
		var item_code = row && row.item_code ? String(row.item_code).trim() : "";
		if (!item_code || seen[item_code]) {
			return;
		}
		seen[item_code] = true;
		item_codes.push(item_code);
	});
	return {
		item_codes: item_codes.slice(0, 50),
		total_count: item_codes.length
	};
}

function show_pricing_rule_update_notice() {
	frappe.msgprint(__(
		"Pricing Rule update configuration is pending. No Pricing Rules were changed."
	));
}

function show_item_price_update_dialog(report) {
	var prepared_report_name = report.raw_data && report.raw_data.doc &&
		report.raw_data.doc.name;
	if (!prepared_report_name) {
		frappe.msgprint(__(
			"Open a completed Pricing Strategy Analysis Prepared Report before updating Item Prices."
		));
		return;
	}
	var selection = get_pricing_update_item_codes(report);
	if (!selection.item_codes.length) {
		frappe.msgprint(__("There are no item rows available for Item Price update."));
		return;
	}

	frappe.call({
		method: "worldshading.worldshading.report.pricing_strategy_analysis." +
			"pricing_strategy_analysis.preview_item_price_update",
		freeze: true,
		freeze_message: __("Preparing Item Price update preview..."),
		args: {
			prepared_report_name: prepared_report_name,
			item_codes: JSON.stringify(selection.item_codes)
		},
		callback: function (response) {
			var preview = response.message;
			if (!preview || !preview.entries || !preview.entries.length) {
				frappe.msgprint(__("There are no Item Price changes to preview."));
				return;
			}
			var limit_notice = selection.total_count > 50
				? '<p class="text-warning"><strong>' +
					__("Only the first 50 Items are included from {0} displayed Items.", [
						selection.total_count
					]) + '</strong></p>'
				: "";
			var summary = '<p><strong>' + __("Prepared Report") + ':</strong> ' +
				frappe.utils.escape_html(prepared_report_name) + '</p>' + limit_notice +
				'<p>' + __("Create: {0}, Update: {1}, Unchanged: {2}", [
					preview.counts.create, preview.counts.update, preview.counts.unchanged
				]) + '</p>';
			var dialog = new frappe.ui.Dialog({
				title: __("Update Item Price"),
				fields: [
					{fieldtype: "HTML", options: summary},
					{
						fieldname: "price_updates",
						fieldtype: "Table",
						label: __("Item Price Changes"),
						cannot_add_rows: true,
						cannot_delete_rows: true,
						in_place_edit: false,
						data: preview.entries,
						get_data: function () { return preview.entries; },
						fields: [
							{fieldname: "item_code", fieldtype: "Data", label: __("Item Code"),
								in_list_view: 1, read_only: 1, columns: 2},
							{fieldname: "item_name", fieldtype: "Data", label: __("Item Name"),
								in_list_view: 1, read_only: 1, columns: 2},
							{fieldname: "price_list", fieldtype: "Data", label: __("Price List"),
								in_list_view: 1, read_only: 1, columns: 2},
							{fieldname: "currency", fieldtype: "Data", label: __("Currency"),
								in_list_view: 1, read_only: 1, columns: 1},
							{fieldname: "current_rate", fieldtype: "Currency", label: __("Current Price"),
								in_list_view: 1, read_only: 1, columns: 1},
							{fieldname: "new_rate", fieldtype: "Currency", label: __("New Price"),
								in_list_view: 1, read_only: 1, columns: 1},
							{fieldname: "action", fieldtype: "Data", label: __("Action"),
								in_list_view: 1, read_only: 1, columns: 1},
							{fieldname: "warning", fieldtype: "Data", label: __("Warning"),
								in_list_view: 1, read_only: 1, columns: 2}
						]
					}
				],
				primary_action_label: __("Continue"),
				primary_action: function () {
					frappe.confirm(
						__("Apply these Item Price changes from Prepared Report {0}?", [
							prepared_report_name
						]),
						function () {
							dialog.get_primary_btn().prop("disabled", true);
							frappe.call({
								method: "worldshading.worldshading.report.pricing_strategy_analysis." +
									"pricing_strategy_analysis.execute_item_price_update",
								freeze: true,
								freeze_message: __("Updating Item Prices..."),
								args: {preview_token: preview.token},
								callback: function (update_response) {
									var result = update_response.message || {};
									dialog.hide();
									frappe.msgprint(__(
										"Item Price update completed. Created: {0}, Updated: {1}, Unchanged: {2}.",
										[result.created || 0, result.updated || 0, result.unchanged || 0]
									));
								},
								error: function () {
									dialog.get_primary_btn().prop("disabled", false);
								}
							});
						}
					);
				}
			});
			dialog.show();
			dialog.$wrapper.find(".modal-dialog").css({width: "1200px", "max-width": "96vw"});
		}
	});
}

frappe.query_reports["Pricing Strategy Analysis"] = {
	"onload": function (report) {
		apply_pricing_strategy_filter_labels(report);
		report.page.add_inner_button(__("Update Item Price"), function () {
			show_item_price_update_dialog(report);
		});
		report.page.add_inner_button(__("Update Pricing Rule"), function () {
			show_pricing_rule_update_notice();
		});
	},
	"after_datatable_render": function (datatable) {
		apply_pricing_strategy_column_colors(datatable);
	},
	"formatter": function (value, row, column, data, default_formatter) {
		var formatted_value = default_formatter(value, row, column, data);
		if (column.fieldname === "expense_per_unit") {
			var tooltip = get_expense_per_unit_tooltip(data);
			if (tooltip) {
				return '<span title="' + frappe.utils.escape_html(tooltip) + '">' +
					formatted_value + '</span>';
			}
		}
		return formatted_value;
	},
	"filters": [
		{
			"fieldname": "company", "label": __("Company"), "fieldtype": "Link",
			"options": "Company", "reqd": 1, "default": frappe.defaults.get_user_default("Company")
		},
		{
			"fieldname": "pricing_strategy", "label": __("Pricing Strategy"),
			"fieldtype": "Link", "options": "Pricing Strategy Template", "reqd": 1,
			"get_query": function () {
				return {"filters": {
					"company": frappe.query_report.get_filter_value("company"), "enabled": 1
				}};
			},
			"on_change": function () {
				load_pricing_strategy_settings(frappe.query_report);
			}
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
			"fieldtype": "Link", "options": "Price List", "reqd": 1, "read_only": 1,
			"get_query": function () { return {"filters": {"selling": 1, "enabled": 1}}; }
		},
		{"fieldname": "regular_markup", "label": __("Regular Price Markup %"), "fieldtype": "Percent", "read_only": 1},
		{
			"fieldname": "b2b_price_list", "label": __("B2B Price List"),
			"fieldtype": "Link", "options": "Price List", "read_only": 1,
			"get_query": function () { return {"filters": {"selling": 1, "enabled": 1}}; }
		},
		{"fieldname": "b2b_markup", "label": __("B2B Price Markup %"), "fieldtype": "Percent", "read_only": 1},
		{
			"fieldname": "cost_source", "label": __("Cost Basis"), "fieldtype": "Select", "reqd": 1,
			"options": "Current Valuation Rate\nLatest Purchase Rate\nWeighted Average Purchase Rate",
			"read_only": 1
		},
		{
			"fieldname": "indirect_expense_account", "label": __("Indirect Expense Account"),
			"fieldtype": "Link", "options": "Account", "read_only": 1
		},
		{"fieldname": "vat_percent", "label": __("VAT %"), "fieldtype": "Percent", "read_only": 1},
		{
			"fieldname": "exclude_expense_from_pricing",
			"label": __("Exclude Expense"),
			"fieldtype": "Check", "default": 0, "read_only": 1
		},
		{
			"fieldname": "show_pricing_rule_strategy", "label": __("Show Pricing Rule Strategy"),
			"fieldtype": "Check", "default": 0, "read_only": 1
		},
		{"fieldname": "pricing_tiers_json", "label": __("Pricing Tiers"), "fieldtype": "Data", "hidden": 1},
		{
			"fieldname": "exclude_items_without_sales", "label": __("Exclude Items Without Sales"),
			"fieldtype": "Check", "default": 0
		}
	]
};
