// Copyright (c) 2016, 	9t9it and contributors
// For license information, please see license.txt
/* eslint-disable */


function update_purchase_plan_filter_summary(report) {
	var start_date = report.get_filter_value("start_date");
	var end_date = report.get_filter_value("end_date");
	var summary = report.page.main.find(".purchase-plan-filter-summary");
	if (!start_date || !end_date) {
		summary.remove();
		return;
	}

	var summary_values = [];
	if (start_date && end_date) {
		summary_values.push(
			"<span><strong>" + __("Purchase Plan Date") + ":</strong> " +
			frappe.utils.escape_html(frappe.datetime.str_to_user(start_date)) + " " +
			__("to") + " " +
			frappe.utils.escape_html(frappe.datetime.str_to_user(end_date)) + "</span>"
		);
		var report_days = frappe.datetime.get_day_diff(end_date, start_date);
		var total_report_months = report_days >= 30
			? parseInt(report_days / 30, 10)
			: 0;
		summary_values.push(
			"<span><strong>" + __("Total Report Months") + ":</strong> " +
			total_report_months + "</span>"
		);
	}

	var summary_labels = {
		"months_to_arrive": __("Months to Arrive"),
		"percentage": __("Growth Percentage"),
		"minimum_months": __("Min Stock Months"),
		"pricing_columns_for": __("Price and Cost"),
		"include_repack_to_parent": __("Include Repack to Parent"),
		"include_out_of_stock_sales": __("Include Out of Stock Sales"),
		"disabled_items_only": __("Disabled Items Only")
	};
	(report.filters || []).forEach(function (filter) {
		var field = filter.df || {};
		if (["start_date", "end_date"].indexOf(field.fieldname) !== -1) {
			return;
		}
		var value = report.get_filter_value(field.fieldname);
		if (field.fieldtype == "Check") {
			if (!cint(value)) {
				return;
			}
			value = __("Yes");
		} else if (Array.isArray(value)) {
			value = value.join(", ");
		}
		if (value === undefined || value === null || value === "") {
			return;
		}
		var label = summary_labels[field.fieldname] || __(field.label || field.fieldname);
		label = String(label).replace(/[?:]+$/, "");
		summary_values.push(
			"<span class='purchase-plan-filter-value'><strong>" +
			frappe.utils.escape_html(label) + ":</strong> " +
			frappe.utils.escape_html(String(value)) + "</span>"
		);
	});
	if (!summary.length) {
		summary = $("<div class='purchase-plan-filter-summary'></div>")
			.insertAfter(report.page.main.find(".page-form"));
	}
	summary.html(summary_values.join(""));
}


function purchase_plan_total_value(value) {
	if (typeof value == "number") {
		return value;
	}
	var text = $("<div>").html(value || "").text().replace(/,/g, "");
	var match = text.match(/-?\d+(?:\.\d+)?/);
	return match ? flt(match[0]) : 0;
}


function purchase_plan_selected_options_first(fieldname, options) {
	var selected_values = frappe.query_report.get_filter_value(fieldname) || [];
	if (!Array.isArray(selected_values)) {
		selected_values = [selected_values];
	}
	var option_by_value = {};
	(options || []).forEach(function (option) {
		var value = typeof option == "string" ? option : option.value;
		option_by_value[value] = option;
	});
	var selected_options = selected_values.map(function (value) {
		return option_by_value[value] || {label: value, value: value, description: ""};
	});
	var remaining_options = (options || []).filter(function (option) {
		var value = typeof option == "string" ? option : option.value;
		return selected_values.indexOf(value) === -1;
	});
	return selected_options.concat(remaining_options);
}


function apply_purchase_plan_filter_labels(report) {
	var page_form = report.page.main.find(".page-form");
	page_form.addClass("purchase-plan-filter-form");
	(report.filters || []).forEach(function (filter) {
		var field = filter.df || {};
		var wrapper = $(filter.wrapper);
		if (!field.fieldname || !wrapper.length) {
			return;
		}
		wrapper.addClass("purchase-plan-filter-control");
		if (wrapper.children(".purchase-plan-filter-label").length) {
			return;
		}
		var label = $("<label class='purchase-plan-filter-label'></label>");
		if (field.fieldtype == "Check") {
			label.addClass("purchase-plan-filter-label-spacer")
				.attr("aria-hidden", "true")
				.html("&nbsp;");
		} else {
			label.text(__(field.label || field.fieldname));
			field.placeholder = "";
			wrapper.find("input").attr("placeholder", "");
			if (field.fieldtype == "MultiSelectList" && filter.update_status) {
				filter.update_status();
			}
		}
		wrapper.prepend(label);
	});
	if (!document.getElementById("purchase-plan-filter-label-style")) {
		$("<style id='purchase-plan-filter-label-style'>" +
			".purchase-plan-filter-form{padding-top:4px;}" +
			".purchase-plan-filter-form .purchase-plan-filter-control{" +
				"box-sizing:border-box;height:50px;min-height:50px;" +
				"margin-top:0 !important;margin-bottom:0 !important;" +
				"padding-top:0 !important;padding-bottom:0 !important;}" +
			".purchase-plan-filter-form .purchase-plan-filter-control>.form-group{" +
				"margin-top:0 !important;margin-bottom:0 !important;}" +
			".purchase-plan-filter-form .purchase-plan-filter-control .checkbox{" +
				"margin-top:1px;margin-bottom:0;}" +
			".purchase-plan-filter-form .purchase-plan-filter-label{" +
				"display:block;height:12px;margin:0;overflow:hidden;" +
				"color:#9ba6b1;font-size:10px;font-weight:600;line-height:12px;" +
				"text-overflow:ellipsis;white-space:nowrap;}" +
			".purchase-plan-filter-form .purchase-plan-filter-label-spacer{" +
				"visibility:hidden;}" +
			"</style>").appendTo("head");
	}
}


function apply_purchase_plan_sticky_columns(datatable) {
	var wrapper = datatable && datatable.wrapper;
	if (!wrapper) {
		return;
	}

	$(wrapper).addClass("purchase-plan-sticky-columns");
	$(wrapper)
		.off("click.purchase_plan_row_highlight")
		.on("click.purchase_plan_row_highlight", ".dt-row .dt-cell", function () {
			var selected_row = $(this).closest(".dt-row");
			if (selected_row.hasClass("dt-row-header") ||
					selected_row.hasClass("dt-row-filter")) {
				return;
			}
			$(wrapper).find(".purchase-plan-selected-row")
				.removeClass("purchase-plan-selected-row");
			selected_row.addClass("purchase-plan-selected-row");
		});
	var row_index_width = 50;
	var get_column_width = function (column_index, fallback_width) {
		var cell = $(wrapper).find(
			".dt-row-header .dt-cell--col-" + column_index
		)[0];
		return cell ? cell.getBoundingClientRect().width : fallback_width;
	};
	var update_sticky_offsets = function () {
		wrapper.style.setProperty("--purchase-plan-row-index-width", row_index_width + "px");
		wrapper.style.setProperty("--purchase-plan-item-width", get_column_width(1, 80) + "px");
		wrapper.style.setProperty("--purchase-plan-item-name-width", get_column_width(2, 200) + "px");
		wrapper.style.setProperty("--purchase-plan-unit-width", get_column_width(3, 100) + "px");
		wrapper.style.setProperty("--purchase-plan-purchase-date-width", get_column_width(4, 120) + "px");
		wrapper.style.setProperty("--purchase-plan-sale-date-width", get_column_width(5, 120) + "px");
	};
	update_sticky_offsets();
	var update_sticky_header = function () {
		var scroll_left = datatable.bodyScrollable.scrollLeft;
		var sticky_header_cells = $(wrapper).find(
			".dt-header .dt-cell--col-0, .dt-header .dt-cell--col-1, " +
			".dt-header .dt-cell--col-2, .dt-header .dt-cell--col-3, " +
			".dt-header .dt-cell--col-4, .dt-header .dt-cell--col-5, " +
			".dt-header .dt-cell--col-6"
		);
		sticky_header_cells
			.addClass("purchase-plan-sticky-header-cell")
			.css("transform", "translateX(" + scroll_left + "px)");
		var sticky_footer_cells = $(wrapper).find(
			".dt-footer .dt-cell--col-0, .dt-footer .dt-cell--col-1, " +
			".dt-footer .dt-cell--col-2, .dt-footer .dt-cell--col-3, " +
			".dt-footer .dt-cell--col-4, .dt-footer .dt-cell--col-5, " +
			".dt-footer .dt-cell--col-6"
		);
		sticky_footer_cells
			.addClass("purchase-plan-sticky-footer-cell")
			.css("transform", "translateX(" + scroll_left + "px)");
	};
	$(datatable.bodyScrollable)
		.off("scroll.purchase_plan_sticky_columns")
		.on("scroll.purchase_plan_sticky_columns", function () {
			window.requestAnimationFrame(update_sticky_header);
		});
	update_sticky_header();

	var resizing_column = false;
	$(datatable.header)
		.off("mousedown.purchase_plan_sticky_resize")
		.on("mousedown.purchase_plan_sticky_resize", ".dt-cell__resize-handle", function () {
			resizing_column = true;
		});
	$(document.body)
		.off("mouseup.purchase_plan_sticky_resize")
		.on("mouseup.purchase_plan_sticky_resize", function () {
			if (!resizing_column) {
				return;
			}
			resizing_column = false;
			window.requestAnimationFrame(function () {
				update_sticky_offsets();
				update_sticky_header();
			});
		});
	$(datatable.header)
		.off("dblclick.purchase_plan_sticky_resize")
		.on("dblclick.purchase_plan_sticky_resize", ".dt-cell__resize-handle", function () {
			setTimeout(function () {
				update_sticky_offsets();
				update_sticky_header();
			}, 0);
		});

	datatable.purchase_plan_refresh_sticky_columns = function () {
		window.requestAnimationFrame(function () {
			update_sticky_offsets();
			update_sticky_header();
		});
	};
	if (!datatable.purchase_plan_sticky_events_bound) {
		datatable.purchase_plan_sticky_events_bound = true;
		["onSortColumn", "onSwitchColumn", "onRemoveColumn"].forEach(function (event_name) {
			datatable.on(event_name, function () {
				if (datatable.purchase_plan_refresh_sticky_columns) {
					datatable.purchase_plan_refresh_sticky_columns();
				}
			});
		});
	}
	if (datatable.columnmanager && datatable.columnmanager.sortable) {
		datatable.columnmanager.sortable.option("disabled", true);
	}

	if (!document.getElementById("purchase-plan-sticky-columns-style")) {
		$("<style id='purchase-plan-sticky-columns-style'>" +
			".purchase-plan-sticky-columns .dt-cell--col-0{" +
				"position:sticky;left:0;z-index:3;background:#fff;" +
				"width:50px;min-width:50px;max-width:50px;flex:0 0 50px;}" +
			".purchase-plan-sticky-columns .dt-cell--col-1{" +
				"position:sticky;left:var(--purchase-plan-row-index-width);z-index:3;background:#fff;}" +
			".purchase-plan-sticky-columns .dt-cell--col-2{" +
				"position:sticky;left:calc(var(--purchase-plan-row-index-width) + var(--purchase-plan-item-width));z-index:3;background:#fff;}" +
			".purchase-plan-sticky-columns .dt-cell--col-3{" +
				"position:sticky;left:calc(var(--purchase-plan-row-index-width) + var(--purchase-plan-item-width) + var(--purchase-plan-item-name-width));z-index:3;background:#fff;}" +
			".purchase-plan-sticky-columns .dt-cell--col-4{" +
				"position:sticky;left:calc(var(--purchase-plan-row-index-width) + var(--purchase-plan-item-width) + var(--purchase-plan-item-name-width) + var(--purchase-plan-unit-width));z-index:3;background:#fff;}" +
			".purchase-plan-sticky-columns .dt-cell--col-5{" +
				"position:sticky;left:calc(var(--purchase-plan-row-index-width) + var(--purchase-plan-item-width) + var(--purchase-plan-item-name-width) + var(--purchase-plan-unit-width) + var(--purchase-plan-purchase-date-width));z-index:3;background:#fff;}" +
			".purchase-plan-sticky-columns .dt-cell--col-6{" +
				"position:sticky;left:calc(var(--purchase-plan-row-index-width) + var(--purchase-plan-item-width) + var(--purchase-plan-item-name-width) + var(--purchase-plan-unit-width) + var(--purchase-plan-purchase-date-width) + var(--purchase-plan-sale-date-width));z-index:3;background:#fff;}" +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-0," +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-1," +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-2," +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-3," +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-4," +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-5," +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-6," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-0," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-1," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-2," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-3," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-4," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-5," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-6{" +
				"position:relative;left:auto;z-index:30 !important;background:#f7fafc !important;}" +
			".purchase-plan-sticky-columns .purchase-plan-sticky-header-cell{" +
				"z-index:30 !important;background:#f7fafc !important;isolation:isolate;}" +
			".purchase-plan-sticky-columns .purchase-plan-sticky-header-cell .dt-cell__content{" +
				"position:relative;z-index:1;background:#f7fafc;}" +
			".purchase-plan-sticky-columns .purchase-plan-sticky-footer-cell{" +
				"position:relative;left:auto;z-index:30 !important;background:#f7fafc !important;}" +
			".purchase-plan-sticky-columns .dt-dropdown__list{" +
				"z-index:60 !important;}" +
			".purchase-plan-sticky-columns .dt-cell--col-6{" +
				"box-shadow:2px 0 2px rgba(0,0,0,0.08);}" +
			".purchase-plan-sticky-columns .purchase-plan-selected-row .dt-cell{" +
				"background:#fff3cd !important;}" +
			".purchase-plan-filter-summary{" +
				"display:flex;flex-wrap:wrap;gap:4px 18px;" +
				"padding:7px 15px;border-bottom:1px solid #d1d8dd;" +
				"background:#f8f9fa;font-size:12px;line-height:18px;}" +
			".purchase-plan-filter-value{white-space:nowrap;}" +
			"</style>").appendTo("head");
	}

	var important_columns = {
		"Direct Sales": "#f0f8ff",
		"Available Quantity": "#eefafa",
		"Available Total Qty": "#eef6ff",
		"On Purchase": "#fff7e6",
		"Min": "#fffbe6",
		"Monthy Sales": "#eef9f0",
		"Annual Sales": "#f5f0ff",
		"Shortage Happend": "#fff0f0",
		"Expected Order Quantity": "#edf9f0",
		"RFQ Order Qty": "#fde2e2",
		"Priority Month": "#f5f0ff"
	};
	var important_column_rules = [];
	$(wrapper).find(".dt-row-header .dt-cell").each(function () {
		var header = $(this).text().trim();
		var background_color = important_columns[header];
		var column_class = (this.className.match(/dt-cell--col-\d+/) || [])[0];
		if (background_color && column_class) {
			important_column_rules.push(
				".purchase-plan-sticky-columns ." + column_class +
				"{background:" + background_color + " !important;}"
			);
		}
	});
	var important_style = $("#purchase-plan-important-columns-style");
	if (!important_style.length) {
		important_style = $("<style id='purchase-plan-important-columns-style'></style>").appendTo("head");
	}
	important_style.text(important_column_rules.join(""));
}


function show_item_reorder_dialog(report) {
	var report_items = {};
	(report.data || []).forEach(function (row) {
		var minimum_qty = flt(row.min);
		if (row.item && minimum_qty > 0) {
			report_items[row.item] = minimum_qty;
		}
	});
	var item_values = Object.keys(report_items).map(function (item_code) {
		return {
			item: item_code,
			minimum_qty: report_items[item_code]
		};
	});

	if (!item_values.length) {
		frappe.msgprint(__("There are no report items with Min greater than zero."));
		return;
	}

	var reorder_configuration = [{
		warehouse_group: "All Warehouses - WS",
		warehouse: "Ras Zuwayed - Warehouse - WS",
		warehouse_reorder_level: __("Report Min"),
		warehouse_reorder_qty: 1,
		material_request_type: "Purchase"
	}];
	var count_request_timer = null;
	var update_selection_count = function () {
		clearTimeout(count_request_timer);
		count_request_timer = setTimeout(function () {
			var selected_item_group = dialog.get_value("item_group");
			var count_field = dialog.fields_dict.selection_count;
			if (!selected_item_group) {
				count_field.$wrapper.html(
					'<p class="text-muted">' +
					__("Select an Item Group to see the matching item count.") +
					'</p>'
				);
				return;
			}
			count_field.$wrapper.html(
				'<p class="text-muted">' + __("Checking matching items...") + '</p>'
			);
			frappe.call({
				method: "worldshading.worldshading.report.purchase_plan.purchase_plan.get_item_reorder_selection_count",
				args: {
					item_values: JSON.stringify(item_values),
					item_groups: JSON.stringify([selected_item_group])
				},
				callback: function (response) {
					count_field.$wrapper.html(
						'<p class="text-success"><strong>' +
						__("{0} matching report Items will be updated.", [response.message || 0]) +
						'</strong></p>'
					);
				}
			});
		}, 300);
	};
	var dialog = new frappe.ui.Dialog({
		title: __("Update Item Reorder"),
		fields: [
			{
				fieldtype: "HTML",
				options: '<p class="text-muted">' +
					__("Select the Item Group to update. A parent group includes all its child groups. There are {0} eligible report items before applying this selection.", [item_values.length]) +
					'</p>'
			},
			{
				fieldname: "item_group",
				fieldtype: "Link",
				options: "Item Group",
				label: __("Item Group to Update"),
				reqd: 1,
				onchange: function () {
					update_selection_count();
				}
			},
			{
				fieldname: "selection_count",
				fieldtype: "HTML",
				options: '<p class="text-muted">' +
					__("Select an Item Group to see the matching item count.") +
					'</p>'
			},
			{
				fieldname: "reorder_configuration",
				fieldtype: "Table",
				label: __("Reorder Configuration"),
				cannot_add_rows: true,
				cannot_delete_rows: true,
				in_place_edit: true,
				data: reorder_configuration,
				get_data: function () {
					return reorder_configuration;
				},
				fields: [
					{
						fieldname: "warehouse_group",
						fieldtype: "Link",
						options: "Warehouse",
						label: __("Check in (group)"),
						in_list_view: 1,
						reqd: 1,
						columns: 3,
						get_query: function () {
							return {filters: {is_group: 1, disabled: 0}};
						}
					},
					{
						fieldname: "warehouse",
						fieldtype: "Link",
						options: "Warehouse",
						label: __("Request for"),
						in_list_view: 1,
						reqd: 1,
						columns: 3,
						get_query: function () {
							return {filters: {is_group: 0, disabled: 0}};
						}
					},
					{
						fieldname: "warehouse_reorder_level",
						fieldtype: "Data",
						label: __("Re-order Level"),
						in_list_view: 1,
						columns: 2,
						read_only: 1
					},
					{
						fieldname: "warehouse_reorder_qty",
						fieldtype: "Float",
						label: __("Re-order Qty"),
						in_list_view: 1,
						columns: 2,
						reqd: 1
					},
					{
						fieldname: "material_request_type",
						fieldtype: "Data",
						label: __("Material Request Type"),
						in_list_view: 1,
						columns: 2,
						read_only: 1
					}
				]
			}
		],
		primary_action_label: __("Update Items"),
		primary_action: function () {
			var values = dialog.get_values();
			var selected_item_group = values && values.item_group ? values.item_group : null;
			if (!selected_item_group) {
				frappe.msgprint(__("Please select an Item Group."));
				return;
			}
			var configuration = values && values.reorder_configuration
				? values.reorder_configuration[0] : null;
			if (!configuration || !configuration.warehouse_group || !configuration.warehouse) {
				frappe.msgprint(__("Please select Check in (group) and Request for Warehouse."));
				return;
			}
			if (flt(configuration.warehouse_reorder_qty) <= 0) {
				frappe.msgprint(__("Re-order Qty must be greater than zero."));
				return;
			}
			frappe.call({
				method: "worldshading.worldshading.report.purchase_plan.purchase_plan.get_item_reorder_selection_count",
				args: {
					item_values: JSON.stringify(item_values),
					item_groups: JSON.stringify([selected_item_group])
				},
				callback: function (count_response) {
					var selected_item_count = count_response.message || 0;
					frappe.confirm(
						__("Update reorder levels for {0} Items in the selected Item Group with Re-order Qty {1} and request for {2}?", [
							selected_item_count, configuration.warehouse_reorder_qty, configuration.warehouse
						]),
						function () {
							frappe.call({
								method: "worldshading.worldshading.report.purchase_plan.purchase_plan.queue_item_reorder_update",
								freeze: true,
								freeze_message: __("Queueing Item reorder update..."),
								args: {
									item_values: JSON.stringify(item_values),
									warehouse_group: configuration.warehouse_group,
									warehouse: configuration.warehouse,
									item_groups: JSON.stringify([selected_item_group]),
									reorder_qty: configuration.warehouse_reorder_qty
								},
								callback: function (response) {
									if (response.message) {
										dialog.hide();
										frappe.show_alert({
											message: __("Reorder update queued for {0} Items.", [response.message.queued_items]),
											indicator: "green"
										}, 10);
									}
								}
							});
							}
					);
				}
			});
		}
	});
	dialog.show();
	dialog.$wrapper.find(".modal-dialog").css({
		width: "1100px",
		"max-width": "95vw"
	});
	setTimeout(function () {
		dialog.fields_dict.reorder_configuration.grid.wrapper.find(".grid-add-row").hide();
	}, 0);
}


function create_request_for_quotation(report) {
	var rfq_items = [];
	var report_rows = report.data || [];
	if (report.raw_data && report.raw_data.add_total_row && report_rows.length) {
		report_rows = report_rows.slice(0, -1);
	}
	report_rows.forEach(function (row) {
		var rfq_order_quantity = purchase_plan_rfq_order_quantity(
			row.rfq_order_quantity, false
		);
		if (row.item && rfq_order_quantity > 0) {
			rfq_items.push({
				item_code: row.item,
				qty: rfq_order_quantity
			});
		}
	});

	if (!rfq_items.length) {
		frappe.msgprint(__("There are no report Items with a purchase requirement."));
		return;
	}
	if (rfq_items.length > 1000) {
		frappe.msgprint(
			__("A maximum of 1000 Items can be added to one RFQ. Apply report filters to reduce the current {0} purchasing Items.", [rfq_items.length])
		);
		return;
	}

	var supplier = report.get_filter_value("supplier") || null;
	var supplier_group = report.get_filter_value("supplier_group") || null;
	var supplier_country = report.get_filter_value("supplier_country") || null;
	var item_purchase_country = report.get_filter_value("purchased_from") || null;
	var item_origin_country = report.get_filter_value("country_of_origin") || null;
	var report_filters = report.get_filter_values ? report.get_filter_values() : {};
	var dialog = new frappe.ui.Dialog({
		title: __("Create Request for Quotation"),
		fields: [
			{
				fieldtype: "HTML",
				options: '<p class="text-muted">' +
					__("{0} report Items with a purchase requirement will be added.", [rfq_items.length]) +
					'</p>'
			},
			{
				fieldname: "warehouse",
				fieldtype: "Link",
				options: "Warehouse",
				label: __("Warehouse"),
				reqd: 1,
				get_query: function () {
					return {filters: {is_group: 0, disabled: 0}};
				}
			},
			{
				fieldname: "supplier_display",
				fieldtype: "Data",
				label: __("Supplier from Report"),
				default: supplier || __("Not selected"),
				read_only: 1
			}
		],
		primary_action_label: __("Create RFQ"),
		primary_action: function () {
			var values = dialog.get_values();
			if (!values || !values.warehouse) {
				return;
			}
			dialog.hide();
			frappe.model.open_mapped_doc({
				method: "worldshading.worldshading.report.purchase_plan.purchase_plan.make_request_for_quotation",
				source_name: "Purchase Plan",
				args: {
					item_values: JSON.stringify(rfq_items),
					supplier: supplier,
					supplier_group: supplier_group,
					supplier_country: supplier_country,
					item_purchase_country: item_purchase_country,
					item_origin_country: item_origin_country,
					report_filters: JSON.stringify(report_filters),
					warehouse: values.warehouse
				},
				freeze_message: __("Preparing Request for Quotation..."),
				run_link_triggers: true
			});
		}
	});
	dialog.show();
	frappe.call({
		method: "worldshading.worldshading.report.purchase_plan.purchase_plan.get_rfq_default_warehouse",
		args: {
			supplier: supplier,
			supplier_country: supplier_country,
			item_purchase_country: item_purchase_country,
			item_origin_country: item_origin_country
		},
		callback: function (response) {
			if (response.message && !dialog.get_value("warehouse")) {
				dialog.set_value("warehouse", response.message);
			}
		}
	});
}


function purchase_plan_rfq_order_quantity(value, show_message) {
	if (value === null || value === undefined || value === "") {
		return 0;
	}
	var quantity = Number(value);
	if (!isFinite(quantity) || quantity < 0) {
		if (show_message) {
			frappe.msgprint(__("RFQ Order Qty must be zero or a positive number."));
		}
		return 0;
	}
	return Math.floor(quantity + 0.5);
}


function purchase_plan_rfq_qty_editor(parent, data) {
	var input = document.createElement("input");
	input.type = "number";
	input.min = "0";
	input.step = "1";
	input.className = "dt-input";
	parent.appendChild(input);

	return {
		initValue: function (value) {
			input.value = purchase_plan_rfq_order_quantity(value, false);
			input.focus();
			input.select();
		},
		getValue: function () {
			return purchase_plan_rfq_order_quantity(input.value, true);
		},
		setValue: function (value) {
			var quantity = purchase_plan_rfq_order_quantity(value, false);
			data.rfq_order_quantity = quantity;
			input.value = quantity;
		}
	};
}


function enable_purchase_plan_rfq_qty_editing(datatable) {
	if (!datatable || !datatable.datamanager) {
		return;
	}
	(datatable.datamanager.getColumns() || []).forEach(function (column) {
		var fieldname = column.fieldname || column.id;
		if (fieldname == "rfq_order_quantity") {
			column.editable = true;
			column.focusable = true;
		}
	});
}


frappe.query_reports["Purchase Plan"] = {
	"filters": [
		{
			"fieldname": "start_date",
			"label": __("Plan Start Date"),
			"fieldtype": "Date",
			"reqd": 1,
					},
		{
			"fieldname": "end_date",
			"label": __("Plan End Date"),
			"fieldtype": "Date",
			"reqd": 1,
			"on_change": function() {
				var end_date = frappe.query_report.get_filter_value("end_date");
				var today = frappe.datetime.get_today();
				if (end_date && end_date > today) {
					frappe.msgprint(__("Plan End Date cannot be later than today."));
					frappe.query_report.set_filter_value("end_date", today);
				}
			},
					},
		{
			"fieldname": "supplier",
			"label": __("Supplier"),
			"fieldtype": "Link",
			"options": "Supplier"
		},
		{
			"fieldname": "supplier_group",
			"label": __("Supplier Group"),
			"fieldtype": "Link",
			"options": "Supplier Group"
		},
		{
			"fieldname": "supplier_country",
			"label": __("Supplier Country"),
			"fieldtype": "Link",
			"options": "Country"
		},
							{
			"fieldname": "item",
			"label": __("Item"),
			"fieldtype": "Link",
			"options":"Item",
					},
		{
			"fieldname": "parent_item_group",
			"label": __("Parent Item Groups"),
			"fieldtype": "MultiSelectList",
			"options":"Item Group",
			get_data: function(txt) {
				return frappe.db.get_link_options("Item Group", txt, {
					"is_group": 1
				}).then(function(options) {
					return purchase_plan_selected_options_first("parent_item_group", options);
				});
			},
			on_change: function() {
				frappe.query_report.set_filter_value("child_item_group", []);
			}
		},
		{
			"fieldname": "child_item_group",
			"label": __("Child Item Groups"),
			"fieldtype": "MultiSelectList",
			"options":"Item Group",
			get_data: function(txt) {
				return frappe.call({
					"method": "worldshading.worldshading.report.purchase_plan.purchase_plan.get_child_item_group_options",
					"args": {
						"txt": txt,
						"parent_groups": JSON.stringify(
							frappe.query_report.get_filter_value("parent_item_group") || []
						)
					}
				}).then(function(response) {
					return purchase_plan_selected_options_first(
						"child_item_group", response.message || []
					);
				});
			}
		},
		{
			"fieldname": "purchased_from",
			"label": __("Item Purchase Country"),
			"fieldtype": "Link",
			"options": "Country"
		},
		{
			"fieldname": "country_of_origin",
			"label": __("Item Country of Origin"),
			"fieldtype": "Link",
			"options": "Country"
		},
							{
			"fieldname": "months_to_arrive",
			"label": __("How Many Months to Arrive?"),
			"fieldtype": "Data",
			"reqd": 1,
			"description": __("Estimated months from placing the purchase order until the stock becomes available."),
					},
							{
			"fieldname": "percentage",
			"label": __("Percentage"),
			"fieldtype": "Data",
			"reqd": 1,
					},
			{
			"fieldname": "minimum_months",
			"label": __("Min Stock for How Many Months?"),
			"fieldtype": "Data",
			"reqd": 1,
			"description": __("Months of average sales used for one minimum-stock reserve. The order calculation applies this reserve twice."),
					},
		{
			"fieldname": "pricing_columns_for",
			"label": __("Show Price and Cost For"),
			"fieldtype": "Select",
			"options": ["All Items", "Items Requiring Purchase"],
			"default": "All Items"
		},
		{
			"fieldname": "include_repack_to_parent",
			"label": __("Include Repack to Parent"),
			"fieldtype": "Check",
			"default": 0
		},
		{
			"fieldname": "include_out_of_stock_sales",
			"label": __("Include Out of Stock Sales"),
			"fieldtype": "Check",
			"default": 0
		},
		{
			"fieldname": "disabled_items_only",
			"label": __("Disabled Items Only"),
			"fieldtype": "Check",
			"default": 0
		}



	],
	"get_datatable_options": function (options) {
		(options.columns || []).forEach(function (column) {
			var fieldname = column.fieldname || column.id;
			if (fieldname == "rfq_order_quantity") {
				column.editable = true;
				column.focusable = true;
			}
		});
		options.getEditor = function (col_index, row_index, value, parent, column, row, data) {
			var fieldname = column ? (column.fieldname || column.id) : null;
			if (fieldname != "rfq_order_quantity" || !data || !data.item) {
				return false;
			}
			return purchase_plan_rfq_qty_editor(parent, data);
		};
		var total_fields = [
			"sales_invoice_count",
			"total_sales",
			"estimated_out_of_stock_sales_qty",
			"converted_repack_demand",
			"expected_total_sales",
			"min",
			"available_quantity",
			"converted_repack_available",
			"on_purchase",
			"available_total_qty",
			"monthy_sales",
			"annual_sales",
			"period_expected_sales",
			"shortage_happened",
			"minimum_purchase_qty",
			"reorder_quantity",
			"expected_order_quantity",
			"rfq_order_quantity",
			"selling_price",
			"least_supplier_cost"
		];
		options.hooks = options.hooks || {};
		options.hooks.columnTotal = function (values, cell) {
			var fieldname = cell.column.fieldname;
			if (fieldname == "item") {
				return __("Total");
			}
			if (total_fields.indexOf(fieldname) === -1) {
				return "";
			}
			if (fieldname == "expected_order_quantity") {
				return values.reduce(function (total, value) {
					var quantity = purchase_plan_total_value(value);
					return total + (quantity < 0 ? quantity : 0);
				}, 0);
			}
			return values.reduce(function (total, value) {
				return total + purchase_plan_total_value(value);
			}, 0);
		};
		return options;
	},
	"onload": function (report) {
		apply_purchase_plan_filter_labels(report);
		report.page.add_inner_button(__("Create RFQ"), function () {
			create_request_for_quotation(report);
		});
		report.page.add_inner_button(__("Update Item Reorder"), function () {
			show_item_reorder_dialog(report);
		});
		var end_date_filter = report.get_filter("end_date");
		if (end_date_filter && end_date_filter.datepicker) {
			end_date_filter.datepicker.update({
				maxDate: frappe.datetime.str_to_obj(frappe.datetime.get_today())
			});
		}
		update_purchase_plan_filter_summary(report);
	},
	"after_datatable_render": function (datatable) {
		enable_purchase_plan_rfq_qty_editing(datatable);
		apply_purchase_plan_sticky_columns(datatable);
		update_purchase_plan_filter_summary(frappe.query_report);
	},
	"formatter": function (value, row, column, data, default_formatter) {
		if (column.fieldname == "on_purchase_po" && value) {
			return value.split(", ").map(function (purchase_order) {
				return '<a href="#Form/Purchase Order/' + encodeURIComponent(purchase_order) + '">' +
					frappe.utils.escape_html(purchase_order) + '</a>';
			}).join(", ");
		}
		if (column.fieldname == "item_suppliers" && value) {
			var priced_supplier_count = data ? cint(data.priced_supplier_count) : 0;
			var supplier_details = [];
			try {
				supplier_details = JSON.parse(data.supplier_purchase_details || "[]");
			} catch (unused_error) {
				supplier_details = [];
			}
			var show_supplier_tooltips = supplier_details.length > 0;
			if (!show_supplier_tooltips) {
				supplier_details = value.split(", ").map(function (supplier) {
					return {supplier: supplier};
				});
			}
			return supplier_details.map(function (detail, index) {
				var supplier = detail.supplier;
				var color = "#7a7a7a";
				if (index < priced_supplier_count && index === 0) {
					color = "#2e7d32";
				} else if (index < priced_supplier_count && index === 1) {
					color = "#b7791f";
				} else if (index < priced_supplier_count) {
					color = "#c62828";
				}
				var tooltip = show_supplier_tooltips
					? __("No submitted Purchase Invoice history")
					: "";
				if (detail.purchase_invoice) {
					tooltip = __("Last Cost") + ": " +
						format_currency(flt(detail.cost), detail.currency) + "\n" +
						__("Invoice") + ": " + detail.purchase_invoice + "\n" +
						__("Date") + ": " + frappe.datetime.str_to_user(detail.posting_date);
				}
				var title_attribute = tooltip
					? ' title="' + frappe.utils.escape_html(tooltip) + '"'
					: "";
				return '<a href="#Form/Supplier/' + encodeURIComponent(supplier) +
					'"' + title_attribute +
					' style="color:' + color + ';font-weight:600">' +
					frappe.utils.escape_html(supplier) + '</a>';
			}).join(", ");
		}
		if (column.fieldname == "estimated_out_of_stock_sales_qty" && data) {
			var completed_report_months = parseInt(flt(data.total_months_in_report), 10);
			var average_monthly_invoices = completed_report_months > 0
				? flt(data.sales_invoice_count) / completed_report_months
				: flt(data.sales_invoice_count);
			if (average_monthly_invoices <= 5) {
				return '<span class="text-muted">' + __("N/A") + '</span>';
			}
		}
		value = default_formatter(value, row, column, data);
		if (column.fieldname == "expected_order_quantity" && data && data.expected_order_quantity < 0) {
			value = "<span style='color:red'>" + value + "</span>";
		}
		if (column.fieldname == "rfq_order_quantity" && data && flt(data.rfq_order_quantity) > 0) {
			value = "<span style='color:#c62828'>" + value + "</span>";
		}
		if (column.fieldname == "shortage_happened" && data && flt(data.shortage_happened) < 0) {
			value = "<span style='color:red'>" + value + "</span>";
		}
		if (column.fieldname == "priority_month" && data && parseInt(flt(data.priority_month), 10) === 0) {
			value = "<span style='color:red'>" + value + "</span>";
		}


		return value;
	},
};
