// Copyright (c) 2016, 	9t9it and contributors
// For license information, please see license.txt
/* eslint-disable */


function apply_purchase_plan_sticky_columns(datatable) {
	var wrapper = datatable && datatable.wrapper;
	if (!wrapper) {
		return;
	}

	$(wrapper).addClass("purchase-plan-sticky-columns");
	var row_index_cell = $(wrapper).find(".dt-row-header .dt-cell--col-0")[0];
	var row_index_width = row_index_cell ? row_index_cell.getBoundingClientRect().width : 40;
	wrapper.style.setProperty("--purchase-plan-row-index-width", row_index_width + "px");
	var update_sticky_header = function () {
		var scroll_left = datatable.bodyScrollable.scrollLeft;
		$(wrapper).find(
			".dt-header .dt-cell--col-0, .dt-header .dt-cell--col-1"
		).css("transform", "translateX(" + scroll_left + "px)");
	};
	$(datatable.bodyScrollable)
		.off("scroll.purchase_plan_sticky_columns")
		.on("scroll.purchase_plan_sticky_columns", function () {
			window.requestAnimationFrame(update_sticky_header);
		});
	update_sticky_header();

	if (!document.getElementById("purchase-plan-sticky-columns-style")) {
		$("<style id='purchase-plan-sticky-columns-style'>" +
			".purchase-plan-sticky-columns .dt-cell--col-0{" +
				"position:sticky;left:0;z-index:3;background:#fff;}" +
			".purchase-plan-sticky-columns .dt-cell--col-1{" +
				"position:sticky;left:var(--purchase-plan-row-index-width);z-index:2;background:#fff;}" +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-0," +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-1," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-0," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-1{" +
				"position:relative;left:auto;z-index:5;background:#f7fafc;}" +
			".purchase-plan-sticky-columns .dt-cell--col-1{" +
				"box-shadow:2px 0 2px rgba(0,0,0,0.08);}" +
			"</style>").appendTo("head");
	}
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
	var dialog = new frappe.ui.Dialog({
		title: __("Update Item Reorder"),
		fields: [
			{
				fieldtype: "HTML",
				options: '<p class="text-muted">' +
					__("{0} report items with Min greater than zero will be updated.", [item_values.length]) +
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
			frappe.confirm(
				__("Update reorder levels for {0} Items with Re-order Qty {1} and request for {2}?", [
					item_values.length, configuration.warehouse_reorder_qty, configuration.warehouse
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
	dialog.show();
	dialog.$wrapper.find(".modal-dialog").css({
		width: "1100px",
		"max-width": "95vw"
	});
	setTimeout(function () {
		dialog.fields_dict.reorder_configuration.grid.wrapper.find(".grid-add-row").hide();
	}, 0);
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
			"fieldname": "supplier",
			"label": __("Supplier"),
			"fieldtype": "Link",
			"options": "Supplier"
		},
							{
			"fieldname": "months_to_arrive",
			"label": __("Months to Arrive"),
			"fieldtype": "Data",
			"reqd": 1,
					},
							{
			"fieldname": "percentage",
			"label": __("Percentage"),
			"fieldtype": "Data",
			"reqd": 1,
					},
			{
			"fieldname": "minimum_months",
			"label": __("Minimum Months"),
			"fieldtype": "Data",
			"reqd": 1,
					},
		{
			"fieldname": "uom_conversion",
			"label": "UOM Conversion",
			"fieldtype": "Float"
		},
		{
			"fieldname": "long_meter",
			"label": "Long Meter",
			"fieldtype": "Int"
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
		value = default_formatter(value, row, column, data);
		if (column.fieldname == "expected_order_quantity" && data && data.expected_order_quantity < 0) {
			value = "<span style='color:red'>" + value + "</span>";
		}
		if (column.fieldname == "long_meter_to_roll" && data && data.long_meter_to_roll < 0) {
			value = "<span style='color:red'>" + value + "</span>";
		}


		return value;
	},
};
