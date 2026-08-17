// Copyright (c) 2016, 	9t9it and contributors
// For license information, please see license.txt
/* eslint-disable */


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
			".purchase-plan-sticky-columns .dt-cell--col-6{" +
				"box-shadow:2px 0 2px rgba(0,0,0,0.08);}" +
			".purchase-plan-sticky-columns .purchase-plan-selected-row .dt-cell{" +
				"background:#fff3cd !important;}" +
			"</style>").appendTo("head");
	}

	var important_columns = {
		"Direct Sales": "#f0f8ff",
		"Available Total Qty": "#eef6ff",
		"On Purchase": "#fff7e6",
		"Expected Order Quantity": "#edf9f0",
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
	(report.data || []).forEach(function (row) {
		var expected_order_quantity = flt(row.expected_order_quantity);
		if (row.item && expected_order_quantity < 0) {
			rfq_items.push({
				item_code: row.item,
				qty: Math.abs(expected_order_quantity)
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
	var purchase_country = report.get_filter_value("purchased_from") || null;
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
					purchase_country: purchase_country,
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
			purchase_country: purchase_country
		},
		callback: function (response) {
			if (response.message && !dialog.get_value("warehouse")) {
				dialog.set_value("warehouse", response.message);
			}
		}
	});
}


frappe.query_reports["Purchase Plan"] = {
	"filters": [
		{
			"fieldname": "start_date",
			"label": __("Start Date"),
			"fieldtype": "Date",
			"reqd": 1,
					},
		{
			"fieldname": "end_date",
			"label": __("End Date"),
			"fieldtype": "Date",
			"reqd": 1,
			"on_change": function() {
				var end_date = frappe.query_report.get_filter_value("end_date");
				var today = frappe.datetime.get_today();
				if (end_date && end_date > today) {
					frappe.msgprint(__("End Date cannot be later than today."));
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
					return response.message || [];
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
		}



	],
	"onload": function (report) {
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
	},
	"after_datatable_render": function (datatable) {
		apply_purchase_plan_sticky_columns(datatable);
	},
	"formatter": function (value, row, column, data, default_formatter) {
		if (column.fieldname == "on_purchase_po" && value) {
			return value.split(", ").map(function (purchase_order) {
				return '<a href="#Form/Purchase Order/' + encodeURIComponent(purchase_order) + '">' +
					frappe.utils.escape_html(purchase_order) + '</a>';
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
		if (column.fieldname == "priority_month" && data && parseInt(flt(data.priority_month), 10) === 0) {
			value = "<span style='color:red'>" + value + "</span>";
		}


		return value;
	},
};
