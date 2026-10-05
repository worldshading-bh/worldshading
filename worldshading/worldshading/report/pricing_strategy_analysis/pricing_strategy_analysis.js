/* global frappe, __, flt, format_currency */

function is_pricing_strategy_highlighted_filter(fieldname) {
	return fieldname === "pricing_group";
}

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
		if (is_pricing_strategy_highlighted_filter(field.fieldname)) {
			wrapper.addClass("pricing-strategy-highlighted-filter");
		}
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
			".pricing-strategy-filter-form .pricing-strategy-highlighted-filter .form-control{" +
				"background:#fffdf4 !important;}" +
			"</style>").appendTo("head");
	}
}

var pricing_strategy_controlled_fields = [
	"regular_price_list", "regular_markup", "b2b_price_list", "b2b_markup",
	"indirect_expense_account", "vat_percent",
	"exclude_expense_from_pricing", "show_pricing_rule_strategy", "pricing_tiers_json"
];

function apply_prepared_pricing_strategy_filters(report, filters) {
	report.pricing_strategy_restoring_prepared_filters = true;
	try {
		(report.filters || []).forEach(function (field) {
			var fieldname = field.df.fieldname;
			if (Object.prototype.hasOwnProperty.call(filters || {}, fieldname)) {
				field.set_input(filters[fieldname]);
			}
		});
	} finally {
		report.pricing_strategy_restoring_prepared_filters = false;
	}
}

function clear_purchase_receipt_item_scope_filters(report) {
	if (!report || report.pricing_strategy_restoring_prepared_filters ||
		!report.get_filter_value("purchase_receipt")) {
		return;
	}
	report.set_filter_value({
		"item": "",
		"item_group": "",
		"pricing_group": "",
		"brand": "",
		"stock_uom": ""
	});
}

function validate_purchase_receipt_filter(report) {
	clear_purchase_receipt_item_scope_filters(report);
	if (!report || report.pricing_strategy_restoring_prepared_filters) {
		return;
	}
	var purchase_receipt = report.get_filter_value("purchase_receipt");
	if (!purchase_receipt) {
		return;
	}
	frappe.call({
		method: "worldshading.worldshading.report.pricing_strategy_analysis." +
			"pricing_strategy_analysis.get_purchase_receipt_pricing_eligibility",
		args: {
			purchase_receipt: purchase_receipt,
			company: report.get_filter_value("company")
		},
		callback: function (response) {
			var result = response.message || {};
			if (result.eligible) {
				return;
			}
			frappe.msgprint({
				title: __("Purchase Receipt Not Eligible"),
				indicator: "orange",
				message: __(result.message ||
					"This Purchase Receipt has no active stock Items for pricing analysis.")
			});
			report.set_filter_value({purchase_receipt: ""});
		}
	});
}

function restore_prepared_pricing_strategy_filters(report) {
	var query_params = report.get_query_params ? report.get_query_params() : {};
	var prepared_report_name = query_params.prepared_report_name;
	if (!prepared_report_name) {
		return Promise.resolve();
	}
	return frappe.call({
		method: "worldshading.worldshading.report.pricing_strategy_analysis." +
			"pricing_strategy_analysis.get_prepared_pricing_strategy_filters",
		args: {prepared_report_name: prepared_report_name}
	}).then(function (response) {
		apply_prepared_pricing_strategy_filters(report, response.message || {});
	});
}

function load_pricing_strategy_settings(report) {
	if (report.pricing_strategy_restoring_prepared_filters) {
		return;
	}
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

function load_pricing_group_configuration(report) {
	if (!report || report.pricing_strategy_restoring_prepared_filters) {
		return;
	}
	var pricing_group = report.get_filter_value("pricing_group");
	if (!pricing_group) {
		return;
	}
	frappe.call({
		method: "worldshading.worldshading.doctype.pricing_group.pricing_group." +
			"get_pricing_group_configuration",
		args: {pricing_group: pricing_group},
		freeze: true,
		freeze_message: __("Loading Pricing Group..."),
		callback: function (response) {
			var configuration = response.message || {};
			report.pricing_group_applying_configuration = true;
			try {
				report.set_filter_value({
					company: configuration.company,
					item_group: configuration.item_group,
					pricing_strategy: configuration.pricing_strategy,
					purchase_receipt: ""
				});
			} finally {
				report.pricing_group_applying_configuration = false;
			}
			load_pricing_strategy_settings(report);
		}
	});
}

function get_pricing_strategy_header_tooltip(fieldname) {
	var tooltips = {
		"available_qty": "Current stock quantity for the selected warehouse, or across all warehouses when no warehouse is selected.",
		"selected_base_cost": "Base cost used to calculate the recommended prices. Hover a value to see the strategy cost basis.",
		"expense_per_unit": "Allocated indirect expense for one sold unit during the selected period.",
		"expense_source": "The COGS or Base Cost basis used to allocate indirect expense to this item.",
		"fully_loaded_cost": "Selected base cost plus allocated expense per unit.",
		"sales_qty": "Quantity sold during the selected period, including packed items.",
		"last_sold_rate": "Net selling rate from the latest sale in the selected period.",
		"weighted_average_sold_rate": "Average historical net selling rate weighted by quantity sold.",
		"current_normal_price": "Current Item Price in the Regular Price List.",
		"current_b2b_price": "Current Item Price in the B2B Price List.",
		"change_from_current_normal": "Amount to increase or reduce the current Regular Item Price.",
		"change_from_current_normal_percent": "Percentage change from the current Regular Item Price to the recommended price.",
		"suggested_action": "Suggested action based on the difference between current and recommended Regular prices.",
		"b2b_discount_percent": "How much lower this price is than its reference price.",
		"warnings": "Checks that may require attention before updating prices.",
		"average_actual_markup_percent": "Simple average of the Actual Markup % for Regular, B2B and all quantity prices.",
		"average_gross_margin_percent": "Simple average of the Gross Margin % for Regular, B2B and all quantity prices.",
		"average_discount_percent": "Simple average of the B2B and quantity-price discounts.",
		"sales_contribution_percent": "This Item's Sales Qty as a percentage of the total Sales Qty of its Pricing Group. Group members total 100%.",
		"pricing_group_status": "Whether every active Item in the Pricing Group can be updated together.",
		"group_recommended_regular_net": "Shared Regular price: the highest valid Regular recommendation in this Pricing Group.",
		"group_recommended_b2b_net": "Shared B2B price: the highest valid B2B recommendation in this Pricing Group."
	};
	if (tooltips[fieldname]) {
		return __(tooltips[fieldname]);
	}
	if (/^(recommended_regular|recommended_b2b|tier_\d+)_net$/.test(fieldname)) {
		return __("Recommended selling price before VAT, after commercial rounding.");
	}
	if (/^(recommended_regular|recommended_b2b|tier_\d+)_gross$/.test(fieldname)) {
		return __("Recommended customer price including VAT and commercial rounding.");
	}
	if (/^(recommended_regular|recommended_b2b|tier_\d+)_actual_markup_percent$/.test(fieldname)) {
		return __("Profit added on top of the item cost. Formula: (Net Price - Cost) / Cost.");
	}
	if (/^(recommended_regular|recommended_b2b|tier_\d+)_gross_margin_percent$/.test(fieldname)) {
		return __("The part of the net selling price that remains as profit after covering the item cost. Formula: (Net Price - Cost) / Net Price.");
	}
	if (/^tier_\d+_discount_percent$/.test(fieldname)) {
		return __("How much lower this price is than its reference price.");
	}
	return "";
}

function get_pricing_group_status_tooltip(data) {
	var messages = {
		"Ready": "All active group Items are present and have valid recommendations.",
		"Different Current Prices": "Group Items currently have different prices and can be aligned to one shared price.",
		"Incomplete Group": "One or more active group Items are missing from this Prepared Report.",
		"Missing Cost": "One or more group Items cannot produce every required recommended price.",
		"Disabled Group": "This Pricing Group is disabled and cannot be updated."
	};
	return __((data && messages[data.pricing_group_status]) || "");
}

function get_pricing_group_summary_tooltip(fieldname, data) {
	if (!data || !data.is_pricing_group_summary) {
		return "";
	}
	var item = data.group_reference_item_code || "";
	var explanation;
	if (data.group_selection_reason === "No Sales - Highest Price") {
		explanation = __("Shared group price follows {0} because the group has no sales and this Item has the highest recommended Regular price.", [item]);
	} else {
		explanation = __("Shared group price follows {0} because it has the highest Sales Qty among Items with valid pricing. Sales Qty: {1}; group contribution: {2}%.", [
			item, String(data.group_reference_sales_qty || 0),
			String(data.group_reference_sales_contribution_percent || 0)
		]);
	}
	var gross_fieldname = /_net$/.test(fieldname || "") ?
		fieldname.replace(/_net$/, "_gross") : "";
	var gross_value = gross_fieldname ? data[gross_fieldname] : null;
	return gross_value === null || gross_value === undefined ? explanation :
		__("Price including VAT") + ": " + format_currency(gross_value) + "\n" + explanation;
}

function get_pricing_group_reference_row_indexes(rows) {
	var indexes = [];
	(rows || []).forEach(function (row, index) {
		if (row && row.pricing_group && row.is_pricing_group_reference &&
				!row.is_pricing_group_summary) {
			indexes.push(index);
		}
	});
	return indexes;
}

function should_blank_pricing_group_summary_field(fieldname, data) {
	if (!data || !data.is_pricing_group_summary) {
		return false;
	}
	return ["item_name", "pricing_group", "selected_base_cost",
		"recommended_regular_net", "recommended_b2b_net"].indexOf(fieldname) === -1 &&
		!/^tier_\d+_net$/.test(fieldname || "");
}

function get_pricing_strategy_sticky_column_config() {
	return [
		{index: 0, offset_variable: null, fallback_width: 50},
		{index: 1, offset_variable: "--psa-row-index-width", fallback_width: 130}
	];
}

function get_pricing_group_summary_label(fieldname, data) {
	return data && data.is_pricing_group_summary && fieldname === "item_code" ?
		(data.group_summary_label || "Group Strategy Price") : "";
}

function get_base_cost_tooltip(data) {
	if (!data || data.selected_base_cost === null || data.selected_base_cost === undefined) {
		return "";
	}
	return __("Cost basis") + ": " + __(data.cost_source_detail || "Unavailable") +
		". " + __("Base cost") + ": " + format_currency(data.selected_base_cost);
}

function get_recommended_price_tooltip(fieldname, data) {
	var current_fields = {
		"current_normal_price": {
			gross: "current_normal_gross",
			explanation: "Current Item Price in the Regular Price List."
		},
		"current_b2b_price": {
			gross: "current_b2b_gross",
			explanation: "Current Item Price in the B2B Price List."
		}
	};
	if (current_fields[fieldname] && data) {
		var current_gross = data[current_fields[fieldname].gross];
		return current_gross === null || current_gross === undefined ? "" :
			__("Price including VAT") + ": " + format_currency(current_gross) + "\n" +
			__(current_fields[fieldname].explanation);
	}
	var match = (fieldname || "").match(/^(recommended_regular|recommended_b2b|tier_\d+)_net$/);
	if (!match || !data) {
		return "";
	}
	var gross_value = data[match[1] + "_gross"];
	if (gross_value === null || gross_value === undefined) {
		return "";
	}
	return __("Price including VAT") + ": " + format_currency(gross_value);
}

function get_pricing_strategy_simple_view_fields(columns) {
	return (columns || []).map(function (column) {
		return column.fieldname || "";
	}).filter(function (fieldname) {
		return ["item_code", "pricing_group", "stock_uom",
			"selected_base_cost", "expense_per_unit", "fully_loaded_cost",
			"sales_contribution_percent", "current_normal_price",
			"recommended_regular_net", "current_b2b_price",
			"recommended_b2b_net"].indexOf(fieldname) !== -1 ||
			/^tier_\d+_net$/.test(fieldname);
	});
}

function apply_pricing_strategy_simple_view(datatable, enabled) {
	var wrapper = datatable && datatable.wrapper;
	if (!wrapper) {
		return;
	}
	var report_columns = (frappe.query_report && frappe.query_report.columns) || [];
	var visible_fields = get_pricing_strategy_simple_view_fields(report_columns);
	var hidden_rules = [];
	$(wrapper).find(".dt-row-header .dt-cell").each(function (index) {
		var report_column = report_columns[index - 1] || {};
		var fieldname = report_column.fieldname || "";
		var column_class = (this.className.match(/dt-cell--col-\d+/) || [])[0];
		if (fieldname && column_class && visible_fields.indexOf(fieldname) === -1) {
			hidden_rules.push(
				".pricing-strategy-simple-view ." + column_class +
				"{display:none !important;}"
			);
		}
	});
	var style = $("#pricing-strategy-simple-view-style");
	if (!style.length) {
		style = $("<style id='pricing-strategy-simple-view-style'></style>").appendTo("head");
	}
	style.text(hidden_rules.join(""));
	$(wrapper).toggleClass("pricing-strategy-simple-view", Boolean(enabled));
}

function is_pricing_strategy_key_price_field(fieldname) {
	return fieldname === "recommended_regular_net" ||
		fieldname === "recommended_b2b_net" || /^tier_\d+_net$/.test(fieldname || "");
}

function apply_pricing_strategy_column_colors(datatable) {
	var wrapper = datatable && datatable.wrapper;
	if (!wrapper) {
		return;
	}

	$(wrapper).addClass("pricing-strategy-result-columns");
	var regular_fields = [
		"recommended_regular_net", "recommended_regular_gross_margin_percent",
		"change_from_current_normal_percent"
	];
	var b2b_fields = [
		"recommended_b2b_net", "recommended_b2b_gross_margin_percent",
		"b2b_discount_percent"
	];
	var tier_colors = ["#f3e8ff", "#fff7d6", "#ffeade", "#e1f7f5"];
	var utility_field_colors = {
		"fully_loaded_cost": "#fff7e6",
		"warnings": "#fff0f0",
		"group_recommended_regular_net": "#dff4e2",
		"group_recommended_b2b_net": "#dfeeff",
		"average_actual_markup_percent": "#ffdede",
		"average_gross_margin_percent": "#ffdede",
		"average_discount_percent": "#ffdede"
	};
	var report_columns = (frappe.query_report && frappe.query_report.columns) || [];
	var column_rules = [];

	$(wrapper).find(".dt-row-header .dt-cell").each(function (index) {
		var report_column = report_columns[index - 1] || {};
		var fieldname = report_column.fieldname || "";
		var tooltip = get_pricing_strategy_header_tooltip(fieldname);
		if (tooltip) {
			$(this).attr("title", tooltip);
		}
		var background_color = utility_field_colors[fieldname];
		if (regular_fields.indexOf(fieldname) !== -1) {
			background_color = "#e8f5e9";
		} else if (b2b_fields.indexOf(fieldname) !== -1) {
			background_color = "#eaf4ff";
		} else if (/^group_tier_\d+_net$/.test(fieldname)) {
			background_color = "#e7f0e9";
		} else {
			var tier_match = fieldname.match(/^tier_(\d+)_/);
			if (tier_match) {
				background_color = tier_colors[(Number(tier_match[1]) - 1) % tier_colors.length];
			}
		}
		var column_class = (this.className.match(/dt-cell--col-\d+/) || [])[0];
		if (is_pricing_strategy_key_price_field(fieldname)) {
			$(this).addClass("pricing-strategy-key-price-header");
		}
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
	style.text(column_rules.join("") +
		".pricing-strategy-result-columns .dt-row-header " +
		".pricing-strategy-key-price-header .dt-cell__content{" +
		"font-weight:700 !important;color:#000 !important;}");
}

function apply_pricing_strategy_sticky_columns(datatable) {
	var wrapper = datatable && datatable.wrapper;
	if (!wrapper || !datatable.bodyScrollable) {
		return;
	}
	$(wrapper).addClass("pricing-strategy-sticky-columns");
	var sticky_selector = ".dt-cell--col-0,.dt-cell--col-1";
	var empty_layout_frame = null;
	var get_column_width = function (column_index, fallback_width) {
		var cell = $(wrapper).find(
			".dt-row-header .dt-cell--col-" + column_index
		)[0];
		return cell ? cell.getBoundingClientRect().width : fallback_width;
	};
	var update_sticky_offsets = function () {
		wrapper.style.setProperty("--psa-row-index-width", get_column_width(0, 50) + "px");
	};
	var update_sticky_header = function () {
		var scroll_left = datatable.bodyScrollable.scrollLeft;
		$(wrapper).find(".dt-header " + sticky_selector.replace(/,/g, ",.dt-header "))
			.addClass("pricing-strategy-sticky-header-cell")
			.css("transform", "translateX(" + scroll_left + "px)");
		$(wrapper).find(".dt-footer " + sticky_selector.replace(/,/g, ",.dt-footer "))
			.addClass("pricing-strategy-sticky-footer-cell")
			.css("transform", "translateX(" + scroll_left + "px)");
	};
	var refresh_empty_layout = function () {
		var no_data = $(datatable.bodyScrollable).find(".dt-scrollable__no-data");
		if (!no_data.length) {
			return;
		}
		var header_row = $(datatable.header).find(".dt-row-header")[0];
		if (header_row) {
			var header_width = Math.max(
				header_row.scrollWidth || 0,
				header_row.getBoundingClientRect().width || 0
			);
			if (header_width) {
				no_data.css({"width": header_width + "px", "min-width": header_width + "px"});
			}
		}
		if (datatable.bodyRenderer && datatable.bodyRenderer.visibleRows &&
				datatable.bodyRenderer.visibleRows.length === 0) {
			datatable.bodyRenderer.renderFooter();
		}
		var maximum_scroll = Math.max(
			0, datatable.bodyScrollable.scrollWidth - datatable.bodyScrollable.clientWidth
		);
		datatable.bodyScrollable.scrollLeft = Math.min(
			datatable.pricing_strategy_last_scroll_left || 0, maximum_scroll
		);
		update_sticky_header();
	};
	update_sticky_offsets();
	if (datatable.pricing_strategy_sticky_observer) {
		datatable.pricing_strategy_sticky_observer.disconnect();
	}
	if (window.MutationObserver) {
		datatable.pricing_strategy_sticky_observer = new MutationObserver(function () {
			if (empty_layout_frame !== null) {
				return;
			}
			empty_layout_frame = window.requestAnimationFrame(function () {
				empty_layout_frame = null;
				refresh_empty_layout();
				update_sticky_header();
			});
		});
		datatable.pricing_strategy_sticky_observer.observe(
			datatable.bodyScrollable, {childList: true, subtree: true}
		);
	}
	if (datatable.pricing_strategy_last_scroll_left === undefined) {
		datatable.pricing_strategy_last_scroll_left = datatable.bodyScrollable.scrollLeft;
	}
	$(datatable.bodyScrollable)
		.off("scroll.pricing_strategy_sticky_columns")
		.on("scroll.pricing_strategy_sticky_columns", function () {
			var no_data = $(datatable.bodyScrollable).find(".dt-scrollable__no-data");
			if (!no_data.length ||
					datatable.bodyScrollable.scrollWidth > datatable.bodyScrollable.clientWidth) {
				datatable.pricing_strategy_last_scroll_left = datatable.bodyScrollable.scrollLeft;
			}
			window.requestAnimationFrame(update_sticky_header);
		});
	var resizing_column = false;
	$(datatable.header)
		.off("mousedown.pricing_strategy_sticky_resize")
		.on("mousedown.pricing_strategy_sticky_resize", ".dt-cell__resize-handle", function () {
			resizing_column = true;
		});
	$(document.body)
		.off("mouseup.pricing_strategy_sticky_resize")
		.on("mouseup.pricing_strategy_sticky_resize", function () {
			if (!resizing_column) {
				return;
			}
			resizing_column = false;
			window.requestAnimationFrame(function () {
				update_sticky_offsets();
				refresh_empty_layout();
				update_sticky_header();
			});
		});
	$(datatable.header)
		.off("dblclick.pricing_strategy_sticky_resize")
		.on("dblclick.pricing_strategy_sticky_resize", ".dt-cell__resize-handle", function () {
			setTimeout(function () {
				update_sticky_offsets();
				refresh_empty_layout();
				update_sticky_header();
			}, 0);
		});
	datatable.pricing_strategy_refresh_sticky_columns = function () {
		window.requestAnimationFrame(function () {
			update_sticky_offsets();
			refresh_empty_layout();
			update_sticky_header();
		});
	};
	if (!datatable.pricing_strategy_sticky_events_bound) {
		datatable.pricing_strategy_sticky_events_bound = true;
		["onSortColumn", "onSwitchColumn", "onRemoveColumn"].forEach(function (event_name) {
			datatable.on(event_name, function () {
				if (datatable.pricing_strategy_refresh_sticky_columns) {
					datatable.pricing_strategy_refresh_sticky_columns();
				}
			});
		});
	}
	if (datatable.columnmanager && datatable.columnmanager.sortable) {
		datatable.columnmanager.sortable.option("disabled", true);
	}
	if (!document.getElementById("pricing-strategy-sticky-columns-style")) {
		$("<style id='pricing-strategy-sticky-columns-style'>" +
			".pricing-strategy-sticky-columns .dt-cell--col-0{" +
				"position:sticky;left:0;z-index:3;background:#fff;" +
				"width:var(--psa-row-index-width);min-width:var(--psa-row-index-width);" +
				"max-width:var(--psa-row-index-width);flex:0 0 var(--psa-row-index-width);}" +
			".pricing-strategy-sticky-columns .dt-cell--col-1{" +
				"position:sticky;left:var(--psa-row-index-width);z-index:3;background:#fff;" +
				"box-shadow:2px 0 2px rgba(0,0,0,.08);}" +
			".pricing-strategy-sticky-columns .dt-row-header .dt-cell--col-0," +
			".pricing-strategy-sticky-columns .dt-row-header .dt-cell--col-1," +
			".pricing-strategy-sticky-columns .dt-row-filter .dt-cell--col-0," +
			".pricing-strategy-sticky-columns .dt-row-filter .dt-cell--col-1{" +
				"position:relative;left:auto;z-index:30!important;background:#f7fafc!important;}" +
			".pricing-strategy-sticky-columns .pricing-strategy-sticky-header-cell{" +
				"z-index:30!important;background:#f7fafc!important;isolation:isolate;}" +
			".pricing-strategy-sticky-columns .pricing-strategy-sticky-header-cell .dt-cell__content{" +
				"position:relative;z-index:1;background:#f7fafc;}" +
			".pricing-strategy-sticky-columns .pricing-strategy-sticky-footer-cell{" +
				"position:relative;left:auto;z-index:30!important;background:#f7fafc!important;}" +
			".pricing-strategy-sticky-columns .dt-dropdown__list{z-index:60!important;}" +
			"</style>").appendTo("head");
	}
	update_sticky_header();
	refresh_empty_layout();
}

function apply_pricing_strategy_row_highlight(datatable) {
	var wrapper = datatable && datatable.wrapper;
	if (!wrapper) {
		return;
	}
	$(wrapper).addClass("pricing-strategy-row-highlight");
	if (datatable.pricing_strategy_row_highlight_observer) {
		datatable.pricing_strategy_row_highlight_observer.disconnect();
	}
	var restore_selected_row = function () {
		$(wrapper).find(".pricing-strategy-group-reference-row")
			.removeClass("pricing-strategy-group-reference-row");
		get_pricing_group_reference_row_indexes(
			(frappe.query_report && frappe.query_report.data) || []
		).forEach(function (row_index) {
			$(wrapper).find('.dt-row[data-row-index="' + row_index + '"]')
				.addClass("pricing-strategy-group-reference-row");
		});
		$(wrapper).find(".pricing-strategy-selected-row")
			.removeClass("pricing-strategy-selected-row");
		if (datatable.pricing_strategy_selected_row_index === undefined ||
				datatable.pricing_strategy_selected_row_index === null) {
			return;
		}
		$(wrapper).find(
			'.dt-row[data-row-index="' + datatable.pricing_strategy_selected_row_index + '"]'
		).addClass("pricing-strategy-selected-row");
	};
	if (datatable.bodyScrollable && window.MutationObserver) {
		datatable.pricing_strategy_row_highlight_observer = new MutationObserver(function () {
			window.requestAnimationFrame(restore_selected_row);
		});
		datatable.pricing_strategy_row_highlight_observer.observe(
			datatable.bodyScrollable, {childList: true, subtree: true}
		);
	}
	$(wrapper)
		.off("click.pricing_strategy_row_highlight")
		.on("click.pricing_strategy_row_highlight", ".dt-row .dt-cell", function () {
			var selected_row = $(this).closest(".dt-row");
			if (selected_row.hasClass("dt-row-header") ||
					selected_row.hasClass("dt-row-filter") ||
					selected_row.closest(".dt-footer").length) {
				return;
			}
			var row_index = selected_row.attr("data-row-index");
			if (!/^\d+$/.test(row_index || "")) {
				return;
			}
			datatable.pricing_strategy_selected_row_index = Number(row_index);
			restore_selected_row();
		});
	var style = $("#pricing-strategy-row-highlight-style");
	if (!style.length) {
		style = $("<style id='pricing-strategy-row-highlight-style'></style>").appendTo("head");
	}
	style.text(
		".pricing-strategy-row-highlight .pricing-strategy-group-reference-row .dt-cell{" +
		"background:#fdecec !important;}" +
		".pricing-strategy-row-highlight .pricing-strategy-selected-row .dt-cell{" +
		"background:#fff3cd !important;}"
	);
	restore_selected_row();
}

function get_expense_per_unit_tooltip(data) {
	if (!data || data.expense_per_unit === null || data.expense_per_unit === undefined) {
		return "";
	}
	var source = data.expense_source || __("Unavailable");
	var lines = [];
	var allocated_expense = flt(data.allocated_expense);
	var net_cogs = flt(data.net_cogs);
	var sales_qty = flt(data.sales_qty);
	var expense_per_unit = flt(data.expense_per_unit);
	var company_expense_ratio = flt(data.company_expense_ratio) * 100;

	lines.push(__("Total Net Expense") + ": " + format_currency(flt(data.company_expense_total)));
	lines.push(__("Total Company Net COGS") + ": " + format_currency(flt(data.company_net_cogs)));
	lines.push(__("Company Expense Ratio") + ": " + company_expense_ratio.toFixed(3) + "%");
	lines.push(__("Expense allocation basis") + ": " + __(source));

	if (source === "Actual period COGS" && net_cogs > 0 && sales_qty > 0) {
		lines.push(__("Item Net COGS") + ": " + format_currency(net_cogs));
		lines.push(__("Allocated Expense") + ": " + format_currency(allocated_expense));
		lines.push(__("Sales Quantity") + ": " + sales_qty);
		lines.push(
			__("Expense / Unit") + ": " + format_currency(allocated_expense) +
			" / " + sales_qty + " = " + format_currency(expense_per_unit)
		);
	} else if (source === "Base Cost fallback" && flt(data.selected_base_cost) > 0) {
		var base_cost = flt(data.selected_base_cost);
		lines.push(__("Base Cost") + ": " + format_currency(base_cost));
		lines.push(
			__("Expense / Unit") + ": " + format_currency(base_cost) +
			" x " + company_expense_ratio.toFixed(3) + "% = " + format_currency(expense_per_unit)
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

function show_pricing_rule_update_dialog(report) {
	var prepared_report_name = report.raw_data && report.raw_data.doc && report.raw_data.doc.name;
	if (!prepared_report_name) {
		frappe.msgprint(__(
			"Open a completed Pricing Strategy Analysis Prepared Report before updating Pricing Rules."
		));
		return;
	}
	var selection = get_pricing_update_item_codes(report);
	if (!selection.item_codes.length) {
		frappe.msgprint(__("There are no item rows available for Pricing Rule update."));
		return;
	}
	frappe.call({
		method: "worldshading.worldshading.report.pricing_strategy_analysis." +
			"pricing_strategy_analysis.preview_pricing_rule_update",
		freeze: true,
		freeze_message: __("Preparing Pricing Rule update preview..."),
		args: {
			prepared_report_name: prepared_report_name,
			item_codes: JSON.stringify(selection.item_codes)
		},
		callback: function (response) {
			var preview = response.message;
			if (!preview || !preview.entries || !preview.entries.length) {
				frappe.msgprint(__("There are no Pricing Rule changes to preview."));
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
				title: __("Update Pricing Rule"),
				fields: [
					{fieldtype: "HTML", options: summary},
					{
						fieldname: "pricing_rule_updates", fieldtype: "Table",
						label: __("Pricing Rule Changes"), cannot_add_rows: true,
						cannot_delete_rows: true, in_place_edit: false,
						data: preview.entries,
						get_data: function () { return preview.entries; },
						fields: [
							{fieldname: "item_code", fieldtype: "Data", label: __("Item Code"),
								in_list_view: 1, read_only: 1, columns: 2},
							{fieldname: "item_name", fieldtype: "Data", label: __("Item Name"),
								in_list_view: 1, read_only: 1, columns: 2},
							{fieldname: "minimum_qty", fieldtype: "Float", label: __("Min Qty"),
								in_list_view: 1, read_only: 1, columns: 1},
							{fieldname: "maximum_qty", fieldtype: "Float", label: __("Max Qty"),
								in_list_view: 1, read_only: 1, columns: 1},
							{fieldname: "current_rate", fieldtype: "Currency", label: __("Current Rate"),
								in_list_view: 1, read_only: 1, columns: 2},
							{fieldname: "rate", fieldtype: "Currency", label: __("New Rate"),
								in_list_view: 1, read_only: 1, columns: 2},
							{fieldname: "action", fieldtype: "Data", label: __("Action"),
								in_list_view: 1, read_only: 1, columns: 2}
						]
					}
				],
				primary_action_label: __("Continue"),
				primary_action: function () {
					frappe.confirm(
						__("Apply these Pricing Rule changes from Prepared Report {0}?", [
							prepared_report_name
						]),
						function () {
							dialog.get_primary_btn().prop("disabled", true);
							frappe.call({
								method: "worldshading.worldshading.report.pricing_strategy_analysis." +
									"pricing_strategy_analysis.execute_pricing_rule_update",
								freeze: true,
								freeze_message: __("Updating Pricing Rules..."),
								args: {preview_token: preview.token},
								callback: function (update_response) {
									var result = update_response.message || {};
									dialog.hide();
									frappe.msgprint(__(
										"Pricing Rule update completed. Created: {0}, Updated: {1}, Unchanged: {2}.",
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
				]) + '</p>' + get_skipped_update_notice(preview.skipped);
			var price_update_rows = make_mutable_preview_rows(
				preview.entries, "item-price-preview"
			);
			var dialog = new frappe.ui.Dialog({
				title: __("Update Item Price"),
				fields: [
					{fieldtype: "HTML", options: summary + '<p>' +
						__("To remove price rows, tick their left-side row boxes and click Delete. Only rows remaining in the table will be updated.") + '</p>'},
					{
						fieldname: "price_updates",
						fieldtype: "Table",
						label: __("Item Price Changes"),
						cannot_add_rows: true,
						cannot_delete_rows: false,
						in_place_edit: true,
						data: price_update_rows,
						fields: [
							{fieldname: "item_code", fieldtype: "Data", label: __("Item Code"),
								in_list_view: 1, read_only: 1, columns: 2},
							{fieldname: "pricing_group", fieldtype: "Data", label: __("Pricing Group"),
								in_list_view: 1, read_only: 1, columns: 2},
							{fieldname: "price_list", fieldtype: "Data", label: __("Price List"),
								in_list_view: 1, read_only: 1, columns: 1},
							{fieldname: "current_rate", fieldtype: "Currency", label: __("Current Price"),
								in_list_view: 1, read_only: 1, columns: 1},
							{fieldname: "individual_rate", fieldtype: "Currency", label: __("Item Recommendation"),
								in_list_view: 1, read_only: 1, columns: 2},
							{fieldname: "group_rate", fieldtype: "Currency", label: __("Shared Group Price"),
								in_list_view: 1, read_only: 1, columns: 2},
							{fieldname: "new_rate", fieldtype: "Currency", label: __("New Price"),
								in_list_view: 1, read_only: 1, columns: 1},
							{fieldname: "action", fieldtype: "Data", label: __("Action"),
								in_list_view: 1, read_only: 1, columns: 1}
						]
					}
				],
				primary_action_label: __("Continue"),
				primary_action: function () {
					var remaining_rows = dialog.get_value("price_updates") || [];
					var incomplete_groups = get_incomplete_item_price_groups(
						preview.entries || [], remaining_rows
					);
					if (incomplete_groups.length) {
						frappe.msgprint(__(
							"Keep or remove every Item Price row for these Pricing Groups: {0}",
							[incomplete_groups.join(", ")]
						));
						return;
					}
					var selected_rows = get_remaining_item_price_keys(remaining_rows);
					if (!selected_rows.length) {
						frappe.msgprint(__("Keep at least one Item Price row."));
						return;
					}
					frappe.confirm(
						__("Apply the {0} remaining Item Price rows from Prepared Report {1}?", [
							selected_rows.length, prepared_report_name
						]),
						function () {
							dialog.get_primary_btn().prop("disabled", true);
							frappe.call({
								method: "worldshading.worldshading.report.pricing_strategy_analysis." +
									"pricing_strategy_analysis.execute_item_price_update",
								freeze: true,
								freeze_message: __("Updating Item Prices..."),
								args: {preview_token: preview.token,
									selected_rows: JSON.stringify(selected_rows)},
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
			var price_grid = dialog.fields_dict.price_updates.grid;
			disable_preview_grid_row_forms(price_grid);
			price_grid.wrapper.off("change.item_price_preview")
				.on("change.item_price_preview", function () {
					setTimeout(function () {
						disable_preview_grid_row_forms(price_grid);
					}, 0);
				});
		}
	});
}

function get_remaining_item_price_keys(rows) {
	return (rows || []).map(function (row) {
		if (!row || !row.item_code || !row.price_list) {
			return "";
		}
		return String(row.item_code).trim() + "|" + String(row.price_list).trim();
	}).filter(function (key) { return Boolean(key); });
}

function get_incomplete_item_price_groups(all_rows, remaining_rows) {
	var expected = {};
	var remaining = {};
	(all_rows || []).forEach(function (row) {
		if (row && row.group_key) {
			expected[row.group_key] = (expected[row.group_key] || 0) + 1;
		}
	});
	(remaining_rows || []).forEach(function (row) {
		if (row && row.group_key) {
			remaining[row.group_key] = (remaining[row.group_key] || 0) + 1;
		}
	});
	return Object.keys(remaining).filter(function (group_key) {
		return remaining[group_key] !== expected[group_key];
	}).sort();
}

function make_mutable_preview_rows(rows, prefix) {
	return (rows || []).map(function (source, index) {
		var row = {};
		Object.keys(source || {}).forEach(function (key) {
			row[key] = source[key];
		});
		row.name = prefix + "-" + (index + 1);
		row.idx = index + 1;
		return row;
	});
}

function get_pricing_rule_item_preview_fields(tier_count) {
	var fields = [
		{fieldname: "item_code", fieldtype: "Data", label: __("Item Code"),
			in_list_view: 1, read_only: 1, columns: 2},
		{fieldname: "item_name", fieldtype: "Data", label: __("Item Name"),
			in_list_view: 1, read_only: 1, columns: 2},
		{fieldname: "pricing_group", fieldtype: "Data", label: __("Pricing Group"),
			in_list_view: 1, read_only: 1, columns: 2}
	];
	for (var index = 1; index <= tier_count; index++) {
		fields.push({
			fieldname: "tier_" + index + "_discount_percent", fieldtype: "Percent",
			label: __("Tier {0} %", [index]), in_list_view: 1,
			read_only: 1, columns: 1
		});
	}
	return fields;
}

function get_remaining_pricing_rule_item_codes(rows) {
	return (rows || []).map(function (row) {
		return row && row.item_code ? String(row.item_code).trim() : "";
	}).filter(function (item_code) { return Boolean(item_code); });
}

function get_incomplete_pricing_rule_groups(all_rows, remaining_rows) {
	var expected = {};
	var remaining = {};
	(all_rows || []).forEach(function (row) {
		if (row && row.group_key) {
			expected[row.group_key] = (expected[row.group_key] || 0) + 1;
		}
	});
	(remaining_rows || []).forEach(function (row) {
		if (row && row.group_key) {
			remaining[row.group_key] = (remaining[row.group_key] || 0) + 1;
		}
	});
	return Object.keys(remaining).filter(function (group_key) {
		return remaining[group_key] !== expected[group_key];
	}).sort();
}

function disable_preview_grid_row_forms(grid) {
	(grid && grid.grid_rows || []).forEach(function (grid_row) {
		grid_row.toggle_view = function () {};
	});
}

function get_skipped_update_notice(skipped) {
	if (!skipped || !skipped.length) {
		return "";
	}
	var unique_items = {};
	skipped.forEach(function (row) {
		if (row && row.item_code) {
			unique_items[row.item_code] = true;
		}
	});
	var count = Object.keys(unique_items).length || skipped.length;
	return '<div class="alert alert-warning"><strong>' +
		__("{0} items skipped because no valid recommended price was available.", [count]) +
		"</strong></div>";
}

function get_pricing_rule_mode(value) {
	if (value === "Separate by Item") {
		return "separate";
	}
	if (value === "Group by Same Discount") {
		return "same_discount";
	}
	return "combined";
}

function get_effective_mixed_conditions(rule_mode, value) {
	return rule_mode === "separate" ? 0 : (Number(value) === 1 ? 1 : 0);
}

function show_bulk_pricing_rule_update_dialog(report) {
	var prepared_report_name = report.raw_data && report.raw_data.doc && report.raw_data.doc.name;
	if (!prepared_report_name) {
		frappe.msgprint(__("Open a completed Pricing Strategy Analysis Prepared Report before updating Pricing Rules."));
		return;
	}
	var selection = get_pricing_update_item_codes(report);
	if (!selection.item_codes.length) {
		frappe.msgprint(__("There are no item rows available for Pricing Rule update."));
		return;
	}
	frappe.call({
		method: "worldshading.worldshading.report.pricing_strategy_analysis." +
			"pricing_strategy_analysis.preview_bulk_pricing_rule_update",
		freeze: true,
		freeze_message: __("Preparing item discount preview..."),
		args: {prepared_report_name: prepared_report_name,
			item_codes: JSON.stringify(selection.item_codes)},
		callback: function (response) {
			var preview = response.message || {};
			var item_fields = get_pricing_rule_item_preview_fields(preview.tiers);
			var pricing_rule_item_rows = make_mutable_preview_rows(
				preview.items || [], "pricing-rule-item"
			);
			var notice = selection.total_count > 50
				? '<p class="text-warning"><strong>' +
					__("Only the first 50 Items are included from {0} displayed Items.", [selection.total_count]) +
					'</strong></p>' : "";
			notice += get_skipped_update_notice(preview.skipped);
			var item_dialog = new frappe.ui.Dialog({
				title: __("Select Items for Pricing Rules"),
				fields: [
					{fieldtype: "HTML", options: notice +
						'<p>' + __("To remove Items, tick their left-side row boxes and click Delete. Every Item remaining in the table will be included.") + '</p>'},
					{fieldname: "rule_mode", fieldtype: "Select", label: __("Rule Creation Mode"),
						options: "Combined\nSeparate by Item\nGroup by Same Discount",
						default: "Combined", reqd: 1,
						description: __("Combined uses one editable average per tier. Separate keeps each Item's exact discount. Group by Same Discount combines only Items with equal discounts.")},
					{fieldname: "rule_set_name", fieldtype: "Data", label: __("Rule Set Name"),
						default: preview.default_rule_set_name || "Selected Items", reqd: 1,
						description: __("Naming format: PSA - {Rule Set Name} - Tier 1. Change only this Rule Set Name; PSA and the tier are added automatically. Using the same name and mode updates matching rules.")},
					{fieldname: "mixed_conditions", fieldtype: "Check",
						label: __("Mixed Conditions"), default: 0,
						depends_on: "eval:doc.rule_mode!='Separate by Item'",
						description: __("Quantities from different selected Items are combined to reach the tier quantity. Example: 3 + 2 qualifies for a minimum quantity of 5.")},
					{fieldname: "pricing_rule_items", fieldtype: "Table", label: __("Items and Suggested Discounts"),
						cannot_add_rows: true, cannot_delete_rows: false, in_place_edit: true,
						data: pricing_rule_item_rows,
						fields: item_fields}
				],
				primary_action_label: __("Review Tier Rules"),
				primary_action: function () {
					var values = item_dialog.get_values();
					if (!values) {
						return;
					}
					var rows = item_dialog.get_value("pricing_rule_items") || [];
					var incomplete_groups = get_incomplete_pricing_rule_groups(
						preview.items || [], rows
					);
					if (incomplete_groups.length) {
						frappe.msgprint(__(
							"Keep or remove every Item for these Pricing Groups: {0}",
							[incomplete_groups.join(", ")]
						));
						return;
					}
					var selected_codes = get_remaining_pricing_rule_item_codes(rows);
					if (!selected_codes.length) {
						frappe.msgprint(__("Select at least one Item."));
						return;
					}
					var rule_mode = get_pricing_rule_mode(values.rule_mode);
					frappe.call({
						method: "worldshading.worldshading.report.pricing_strategy_analysis." +
							"pricing_strategy_analysis.preview_bulk_pricing_rule_summary",
						freeze: true,
						freeze_message: __("Calculating tier averages..."),
						args: {preview_token: preview.token, item_codes: JSON.stringify(selected_codes),
							rule_mode: rule_mode, rule_set_name: values.rule_set_name,
							mixed_conditions: get_effective_mixed_conditions(
								rule_mode, values.mixed_conditions)},
						callback: function (summary_response) {
							var summary = summary_response.message || {};
							item_dialog.hide();
							show_bulk_pricing_rule_summary_dialog(summary);
						}
					});
				}
			});
			item_dialog.show();
			item_dialog.$wrapper.find(".modal-dialog").css({width: "1200px", "max-width": "96vw"});
			var item_grid = item_dialog.fields_dict.pricing_rule_items.grid;
			disable_preview_grid_row_forms(item_grid);
			item_grid.wrapper.off("change.pricing_rule_preview")
				.on("change.pricing_rule_preview", function () {
					setTimeout(function () {
						disable_preview_grid_row_forms(item_grid);
					}, 0);
				});
		}
	});
}

function show_bulk_pricing_rule_summary_dialog(summary) {
	var mode_message = summary.rule_mode === "separate"
		? __("A separate Pricing Rule will be saved for every selected Item and tier.")
		: (summary.rule_mode === "same_discount"
			? __("Items with the same discount will share one Pricing Rule for that tier.")
			: __("One combined Pricing Rule will be saved for each tier."));
	var summary_dialog = new frappe.ui.Dialog({
		title: __("Confirm Tier Pricing Rules"),
		fields: [
			{fieldtype: "HTML", options: '<p><strong>' + __("Rule Set") + ":</strong> " +
				frappe.utils.escape_html(summary.rule_set_name || "") + '</p><p>' +
				__("Selected Items: {0}.", [summary.selected_item_count || 0]) + " " +
				mode_message + '</p><p>' +
				__("You may edit the Final Discount % before continuing.") + '</p>'},
			{fieldname: "tier_rules", fieldtype: "Table", label: __("Tier Rules"),
				cannot_add_rows: true, cannot_delete_rows: true, in_place_edit: true,
				data: summary.entries || [], get_data: function () { return summary.entries || []; },
				fields: get_pricing_rule_tier_summary_fields()}
		],
		primary_action_label: __("Continue"),
		primary_action: function () {
			var tiers = (summary_dialog.get_value("tier_rules") || []).filter(function (row) {
				return Number(row.included) === 1;
			});
			if (!tiers.length) {
				frappe.msgprint(__("Include at least one quantity tier."));
				return;
			}
			frappe.confirm(__("Create or update these quantity Pricing Rules?"), function () {
				summary_dialog.get_primary_btn().prop("disabled", true);
				frappe.call({
					method: "worldshading.worldshading.report.pricing_strategy_analysis." +
						"pricing_strategy_analysis.execute_bulk_pricing_rule_update",
					freeze: true, freeze_message: __("Updating Pricing Rules..."),
					args: {preview_token: summary.token, tier_discounts: JSON.stringify(tiers)},
					callback: function (response) {
						var result = response.message || {};
						summary_dialog.hide();
						frappe.msgprint(__(
							"Pricing Rule update completed. Created: {0}, Updated: {1}, Unchanged: {2}.",
							[result.created || 0, result.updated || 0, result.unchanged || 0]
						));
					},
					error: function () { summary_dialog.get_primary_btn().prop("disabled", false); }
				});
			});
		}
	});
	summary_dialog.show();
	summary_dialog.$wrapper.find(".modal-dialog").css({width: "1100px", "max-width": "96vw"});
	summary_dialog.fields_dict.tier_rules.grid.wrapper
		.find(".grid-row-check, .grid-remove-rows").hide();
}

function get_pricing_rule_tier_summary_fields() {
	return [
		{fieldname: "included", fieldtype: "Check", label: __("Include"),
			in_list_view: 1, columns: 1},
		{fieldname: "tier_index", fieldtype: "Int", label: __("Tier"),
			in_list_view: 1, read_only: 1, columns: 1},
		{fieldname: "minimum_qty", fieldtype: "Float", label: __("Min Qty"),
			in_list_view: 1, read_only: 1, columns: 1},
		{fieldname: "maximum_qty", fieldtype: "Float", label: __("Max Qty"),
			in_list_view: 1, read_only: 1, columns: 1},
		{fieldname: "item_count", fieldtype: "Int", label: __("Items"),
			in_list_view: 1, read_only: 1, columns: 1},
		{fieldname: "suggested_average_discount", fieldtype: "Percent",
			label: __("Suggested %"), in_list_view: 1, read_only: 1, columns: 1},
		{fieldname: "current_discount_percentage", fieldtype: "Percent",
			label: __("Current %"), in_list_view: 1, read_only: 1, columns: 1},
		{fieldname: "final_discount_percentage", fieldtype: "Percent",
			label: __("Final Discount %"), in_list_view: 1, columns: 2},
		{fieldname: "action", fieldtype: "Data", label: __("Action"),
			in_list_view: 1, read_only: 1, columns: 1},
		{fieldname: "rule_key", fieldtype: "Data", label: __("Rule Key"), read_only: 1}
	];
}

frappe.query_reports["Pricing Strategy Analysis"] = {
		"onload": function (report) {
		apply_pricing_strategy_filter_labels(report);
		report.pricing_strategy_simple_view = false;
		var view_button = report.page.add_inner_button(__("Simple Price View"), function () {
			report.pricing_strategy_simple_view = !report.pricing_strategy_simple_view;
			apply_pricing_strategy_simple_view(
				report.datatable, report.pricing_strategy_simple_view
			);
			if (view_button && view_button.text) {
				view_button.text(__(report.pricing_strategy_simple_view
					? "Full Analysis View" : "Simple Price View"));
			}
		});
		report.page.add_inner_button(__("Update Item Price"), function () {
			show_item_price_update_dialog(report);
		});
		report.page.add_inner_button(__("Update Pricing Rule"), function () {
			show_bulk_pricing_rule_update_dialog(report);
		});
		return restore_prepared_pricing_strategy_filters(report);
	},
	"after_datatable_render": function (datatable) {
		apply_pricing_strategy_sticky_columns(datatable);
		apply_pricing_strategy_column_colors(datatable);
		apply_pricing_strategy_row_highlight(datatable);
		apply_pricing_strategy_simple_view(
			datatable,
			Boolean(frappe.query_report && frappe.query_report.pricing_strategy_simple_view)
		);
	},
	"formatter": function (value, row, column, data, default_formatter) {
		var summary_label = get_pricing_group_summary_label(column.fieldname, data);
		if (summary_label) {
			var summary_label_tooltip = get_pricing_group_summary_tooltip(
				column.fieldname, data
			);
			return '<strong title="' + frappe.utils.escape_html(summary_label_tooltip) + '">' +
				frappe.utils.escape_html(__(summary_label)) + '</strong>';
		}
		if (should_blank_pricing_group_summary_field(column.fieldname, data)) {
			return "";
		}
		var formatted_value = default_formatter(value, row, column, data);
		var group_summary_tooltip = get_pricing_group_summary_tooltip(
			column.fieldname, data
		);
		if (group_summary_tooltip) {
			return '<strong title="' + frappe.utils.escape_html(group_summary_tooltip) + '">' +
				formatted_value + '</strong>';
		}
		if (column.fieldname === "selected_base_cost") {
			var base_cost_tooltip = get_base_cost_tooltip(data);
			if (base_cost_tooltip) {
				return '<span title="' + frappe.utils.escape_html(base_cost_tooltip) + '">' +
					formatted_value + '</span>';
			}
		}
		if (column.fieldname === "expense_per_unit") {
			var tooltip = get_expense_per_unit_tooltip(data);
			if (tooltip) {
				return '<span title="' + frappe.utils.escape_html(tooltip) + '">' +
					formatted_value + '</span>';
			}
		}
		if (column.fieldname === "pricing_group_status") {
			var group_tooltip = get_pricing_group_status_tooltip(data);
			if (group_tooltip) {
				return '<span title="' + frappe.utils.escape_html(group_tooltip) + '">' +
					formatted_value + '</span>';
			}
		}
		var price_tooltip = get_recommended_price_tooltip(column.fieldname, data);
		if (price_tooltip) {
			return '<span title="' + frappe.utils.escape_html(price_tooltip) + '">' +
				formatted_value + '</span>';
		}
		return formatted_value;
	},
	"filters": [
		{
			"fieldname": "pricing_group", "label": __("Pricing Group"),
			"fieldtype": "Link", "options": "Pricing Group",
			"get_query": function () { return {"filters": {"disabled": 0}}; },
			"on_change": function () {
				load_pricing_group_configuration(frappe.query_report);
			}
		},
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
				if (!frappe.query_report.pricing_group_applying_configuration) {
					load_pricing_strategy_settings(frappe.query_report);
				}
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
		{
			"fieldname": "purchase_receipt", "label": __("Purchase Receipt"),
			"fieldtype": "Link", "options": "Purchase Receipt",
			"get_query": function () {
				return {"filters": {
					"company": frappe.query_report.get_filter_value("company"),
					"docstatus": 1,
					"is_return": 0
				}};
			},
			"on_change": function () {
				validate_purchase_receipt_filter(frappe.query_report);
			}
		},
		{"fieldname": "item_group", "label": __("Item Group"), "fieldtype": "Link", "options": "Item Group"},
		{"fieldname": "item", "label": __("Item"), "fieldtype": "Link", "options": "Item"},
		{"fieldname": "stock_uom", "label": __("Stock UOM"), "fieldtype": "Link", "options": "UOM"},
		{"fieldname": "brand", "label": __("Brand"), "fieldtype": "Link", "options": "Brand"},
		{
			"fieldname": "warehouse", "label": __("Warehouse"), "fieldtype": "Link", "options": "Warehouse",
			"get_query": function () {
				return {"filters": {"company": frappe.query_report.get_filter_value("company"), "disabled": 0}};
			}
		},
		{
			"fieldname": "cost_source", "label": __("Cost Basis"), "fieldtype": "Select", "reqd": 1,
			"options": "Current Valuation Rate\nLatest Valuation Rate",
			"default": "Latest Valuation Rate"
		},
		{
			"fieldname": "regular_price_list", "label": __("Regular Price List"),
			"fieldtype": "Link", "options": "Price List", "reqd": 1, "read_only": 1, "hidden": 1,
			"get_query": function () { return {"filters": {"selling": 1, "enabled": 1}}; }
		},
		{"fieldname": "regular_markup", "label": __("Regular Price Markup %"), "fieldtype": "Percent", "read_only": 1, "hidden": 1},
		{
			"fieldname": "b2b_price_list", "label": __("B2B Price List"),
			"fieldtype": "Link", "options": "Price List", "read_only": 1, "hidden": 1,
			"get_query": function () { return {"filters": {"selling": 1, "enabled": 1}}; }
		},
		{"fieldname": "b2b_markup", "label": __("B2B Price Markup %"), "fieldtype": "Percent", "read_only": 1, "hidden": 1},
		{
			"fieldname": "indirect_expense_account", "label": __("Indirect Expense Account"),
			"fieldtype": "Link", "options": "Account", "read_only": 1, "hidden": 1
		},
		{"fieldname": "vat_percent", "label": __("VAT %"), "fieldtype": "Percent", "read_only": 1, "hidden": 1},
		{
			"fieldname": "exclude_expense_from_pricing",
			"label": __("Exclude Expense"),
			"fieldtype": "Check", "default": 0, "read_only": 1, "hidden": 1
		},
		{
			"fieldname": "show_pricing_rule_strategy", "label": __("Show Pricing Rule Strategy"),
			"fieldtype": "Check", "default": 0, "read_only": 1, "hidden": 1
		},
		{"fieldname": "pricing_tiers_json", "label": __("Pricing Tiers"), "fieldtype": "Data", "hidden": 1},
		{
			"fieldname": "exclude_items_without_sales", "label": __("Exclude Items Without Sales"),
			"fieldtype": "Check", "default": 0
		}
	]
};
