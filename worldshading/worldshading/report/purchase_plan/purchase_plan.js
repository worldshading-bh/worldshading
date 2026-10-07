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
		"minimum_months": __("Purchase Plan Months"),
		"minimum_stock_months": __("Min Stock Months"),
		"include_repack_to_parent": __("Include Repack to Parent"),
		"include_out_of_stock_sales": __("Include Out of Stock Sales"),
		"disabled_items_only": __("Disabled Items Only"),
		"purchase_required_only": __("Purchase Required Items Only")
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


function restore_prepared_purchase_plan_filters(report) {
	var query_params = report.get_query_params ? report.get_query_params() : {};
	var prepared_report_name = query_params.prepared_report_name;
	if (!prepared_report_name) {
		return Promise.resolve();
	}

	return frappe.call({
		method: "worldshading.worldshading.report.purchase_plan.purchase_plan.get_prepared_purchase_plan_filters",
		args: {
			prepared_report_name: prepared_report_name
		}
	}).then(function (response) {
		var filters = response.message || {};
		(report.filters || []).forEach(function (field) {
			var fieldname = field.df.fieldname;
			if (Object.prototype.hasOwnProperty.call(filters, fieldname)) {
				field.set_input(filters[fieldname]);
			}
		});
	});
}


function bind_current_prepared_report_download(report) {
	var prepared_report = report.raw_data && report.raw_data.doc;
	if (!prepared_report || !prepared_report.name) {
		return;
	}

	var download_button = report.page.inner_toolbar.find(
		'button[data-label="' + encodeURIComponent(__("Download Report")) + '"]'
	);
	if (!download_button.length) {
		return;
	}

	// Frappe v12 keeps the first callback when an inner button with the same
	// label already exists. Rebind it so a rebuilt report downloads its own file.
	download_button.off("click").on("click", function () {
		window.open(
			frappe.urllib.get_full_url(
				"/api/method/frappe.core.doctype.prepared_report.prepared_report.download_attachment?" +
					"dn=" + encodeURIComponent(prepared_report.name)
			)
		);
	});
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


function purchase_plan_header_formula(fieldname) {
	var formulas = {
		expected_total_sales: __(
			"Expected Total Sale = (Direct Sales + Estimated Out-of-Stock Sales + Repack Demand) × (1 + Growth %)"
		),
		min: __(
			"Min = Exact Monthly Sales × Min Stock Months (rounded to a whole quantity)"
		),
		monthy_sales: __(
			"Monthly Sales = Expected Total Sale ÷ Report Months\nThe calculation keeps decimals; the column displays a whole number."
		),
		period_expected_sales: __(
			"Arrival Period Expected Sales = Exact Monthly Sales × Months to Arrive"
		),
		shortage_happened: __(
			"Shortage = Available Total Qty − Arrival Period Expected Sales\nA negative value means a shortage."
		),
		available_total_qty: __(
			"Available Total Qty = Available Qty + Usable Repack Available + On Purchase"
		),
		expected_order_quantity: __(
			"Expected Order Quantity = max(Shortage, 0) − Purchase Plan Coverage − Min\nCombined Row = Sum of individual Expected Order Quantities"
		),
		rfq_order_quantity: __(
			"RFQ Order Qty = |Expected Order Quantity| when negative; otherwise 0"
		),
		priority_month: __(
			"Priority Month = Available Total Qty ÷ Exact Monthly Sales\nDisplayed Value = Complete whole months covered"
		)
	};
	return formulas[fieldname] || "";
}


function apply_purchase_plan_header_formulas(datatable) {
	if (!datatable || !datatable.wrapper || !datatable.datamanager) {
		return;
	}
	(datatable.datamanager.getColumns() || []).forEach(function (column) {
		var formula = purchase_plan_header_formula(
			column.fieldname || column.id
		);
		if (!formula) {
			return;
		}
		$(datatable.wrapper).find(
			".dt-row-header .dt-cell--col-" + column.colIndex
		).attr("title", formula)
			.addClass("purchase-plan-formula-heading")
			.find(".dt-cell__content").attr("title", formula);
	});
}


function purchase_plan_rfq_row_needs_highlight(row) {
	return Boolean(row && flt(row.rfq_order_quantity) > 0);
}


function apply_purchase_plan_sticky_columns(datatable) {
	var wrapper = datatable && datatable.wrapper;
	if (!wrapper) {
		return;
	}

	$(wrapper).addClass("purchase-plan-sticky-columns");
	if (datatable.purchase_plan_row_highlight_observer) {
		datatable.purchase_plan_row_highlight_observer.disconnect();
	}
	var selected_row_index = null;
	var row_highlight_frame = null;
	var empty_layout_frame = null;
	var refresh_empty_filter_layout = null;
	var refresh_rfq_required_serials = function () {
		var report_rows = frappe.query_report && frappe.query_report.data
			? frappe.query_report.data : [];
		$(wrapper).find(".dt-row[data-row-index]").each(function () {
			var row_index = $(this).attr("data-row-index");
			if (!/^\d+$/.test(row_index || "")) {
				return;
			}
			$(this).find(".dt-cell--col-0").toggleClass(
				"purchase-plan-rfq-required-serial",
				purchase_plan_rfq_row_needs_highlight(
					report_rows[cint(row_index)]
				)
			);
		});
	};
	var restore_selected_row = function () {
		row_highlight_frame = null;
		$(wrapper).find(".purchase-plan-selected-row")
			.removeClass("purchase-plan-selected-row");
		refresh_rfq_required_serials();
		if (selected_row_index === null) {
			return;
		}
		$(wrapper).find(
			'.dt-row[data-row-index="' + selected_row_index + '"]'
		).addClass("purchase-plan-selected-row");
	};
	var queue_selected_row_restore = function () {
		if (row_highlight_frame !== null) {
			return;
		}
		row_highlight_frame = window.requestAnimationFrame(restore_selected_row);
	};
	datatable.purchase_plan_row_highlight_observer = new MutationObserver(function () {
		queue_selected_row_restore();
		if (empty_layout_frame === null) {
			empty_layout_frame = window.requestAnimationFrame(function () {
				empty_layout_frame = null;
				if (refresh_empty_filter_layout) {
					refresh_empty_filter_layout();
				}
			});
		}
	});
	datatable.purchase_plan_row_highlight_observer.observe(
		datatable.bodyScrollable,
		{childList: true, subtree: true}
	);
	$(wrapper)
		.off("click.purchase_plan_row_highlight")
		.on("click.purchase_plan_row_highlight", ".dt-row .dt-cell", function () {
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
			selected_row_index = cint(row_index);
			restore_selected_row();
		});
	queue_selected_row_restore();
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
		wrapper.style.setProperty("--purchase-plan-invoice-count-width", get_column_width(6, 100) + "px");
	};
	update_sticky_offsets();
	var update_sticky_header = function () {
		var scroll_left = datatable.bodyScrollable.scrollLeft;
		var sticky_header_cells = $(wrapper).find(
			".dt-header .dt-cell--col-0, .dt-header .dt-cell--col-1, " +
			".dt-header .dt-cell--col-2, .dt-header .dt-cell--col-3, " +
			".dt-header .dt-cell--col-4, .dt-header .dt-cell--col-5, " +
			".dt-header .dt-cell--col-6, .dt-header .dt-cell--col-7"
		);
		sticky_header_cells
			.addClass("purchase-plan-sticky-header-cell")
			.css("transform", "translateX(" + scroll_left + "px)");
		var sticky_footer_cells = $(wrapper).find(
			".dt-footer .dt-cell--col-0, .dt-footer .dt-cell--col-1, " +
			".dt-footer .dt-cell--col-2, .dt-footer .dt-cell--col-3, " +
			".dt-footer .dt-cell--col-4, .dt-footer .dt-cell--col-5, " +
			".dt-footer .dt-cell--col-6, .dt-footer .dt-cell--col-7"
		);
		sticky_footer_cells
			.addClass("purchase-plan-sticky-footer-cell")
			.css("transform", "translateX(" + scroll_left + "px)");
	};
	refresh_empty_filter_layout = function () {
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
				no_data.css({
					"width": header_width + "px",
					"min-width": header_width + "px"
				});
			}
		}

		if (datatable.bodyRenderer &&
				datatable.bodyRenderer.visibleRows &&
				datatable.bodyRenderer.visibleRows.length === 0) {
			datatable.bodyRenderer.renderFooter();
		}

		var maximum_scroll = Math.max(
			0,
			datatable.bodyScrollable.scrollWidth - datatable.bodyScrollable.clientWidth
		);
		datatable.bodyScrollable.scrollLeft = Math.min(
			datatable.purchase_plan_last_scroll_left || 0,
			maximum_scroll
		);
		update_sticky_header();
	};
	if (datatable.purchase_plan_last_scroll_left === undefined) {
		datatable.purchase_plan_last_scroll_left = datatable.bodyScrollable.scrollLeft;
	}
	$(datatable.bodyScrollable)
		.off("scroll.purchase_plan_sticky_columns")
		.on("scroll.purchase_plan_sticky_columns", function () {
			var no_data = $(datatable.bodyScrollable).find(".dt-scrollable__no-data");
			if (!no_data.length ||
					datatable.bodyScrollable.scrollWidth > datatable.bodyScrollable.clientWidth) {
				datatable.purchase_plan_last_scroll_left = datatable.bodyScrollable.scrollLeft;
			}
			window.requestAnimationFrame(update_sticky_header);
		});
	update_sticky_header();
	refresh_empty_filter_layout();

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
				refresh_empty_filter_layout();
				update_sticky_header();
			});
		});
	$(datatable.header)
		.off("dblclick.purchase_plan_sticky_resize")
		.on("dblclick.purchase_plan_sticky_resize", ".dt-cell__resize-handle", function () {
			setTimeout(function () {
				update_sticky_offsets();
				refresh_empty_filter_layout();
				update_sticky_header();
			}, 0);
		});

	datatable.purchase_plan_refresh_sticky_columns = function () {
		window.requestAnimationFrame(function () {
			update_sticky_offsets();
			refresh_empty_filter_layout();
			update_sticky_header();
			refresh_rfq_required_serials();
			apply_purchase_plan_header_formulas(datatable);
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
			".purchase-plan-sticky-columns .dt-cell--col-7{" +
				"position:sticky;left:calc(var(--purchase-plan-row-index-width) + var(--purchase-plan-item-width) + var(--purchase-plan-item-name-width) + var(--purchase-plan-unit-width) + var(--purchase-plan-purchase-date-width) + var(--purchase-plan-sale-date-width) + var(--purchase-plan-invoice-count-width));z-index:3;background:#fff;}" +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-0," +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-1," +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-2," +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-3," +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-4," +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-5," +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-6," +
			".purchase-plan-sticky-columns .dt-row-header .dt-cell--col-7," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-0," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-1," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-2," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-3," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-4," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-5," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-6," +
			".purchase-plan-sticky-columns .dt-row-filter .dt-cell--col-7{" +
				"position:relative;left:auto;z-index:30 !important;background:#f7fafc !important;}" +
			".purchase-plan-sticky-columns .purchase-plan-sticky-header-cell{" +
				"z-index:30 !important;background:#f7fafc !important;isolation:isolate;}" +
			".purchase-plan-sticky-columns .purchase-plan-sticky-header-cell .dt-cell__content{" +
				"position:relative;z-index:1;background:#f7fafc;}" +
			".purchase-plan-sticky-columns .purchase-plan-sticky-footer-cell{" +
				"position:relative;left:auto;z-index:30 !important;background:#f7fafc !important;}" +
			".purchase-plan-sticky-columns .dt-dropdown__list{" +
				"z-index:60 !important;}" +
			".purchase-plan-sticky-columns .dt-cell--col-7{" +
				"box-shadow:2px 0 2px rgba(0,0,0,0.08);}" +
			".purchase-plan-sticky-columns .purchase-plan-selected-row .dt-cell{" +
				"background:#fff3cd !important;}" +
			".purchase-plan-sticky-columns .purchase-plan-rfq-required-serial," +
			".purchase-plan-sticky-columns .purchase-plan-selected-row " +
				".purchase-plan-rfq-required-serial{" +
				"background:#fde2e2 !important;color:#c62828 !important;font-weight:700;}" +
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
		"Expected Order Quantity": "#fde2e2",
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
	apply_purchase_plan_header_formulas(datatable);
	$(wrapper).find(".purchase-plan-formula-heading .dt-cell__content").css({
		cursor: "help",
		"text-decoration": "underline dotted",
		"text-underline-offset": "3px"
	});
}


function show_item_reorder_dialog(report) {
	if (report.purchase_plan_combined_view_active) {
		frappe.msgprint(__(
			"Combined View is for analysis only. Reset it before updating Item Reorder."
		));
		return;
	}
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


function purchase_plan_sum_rows(rows, fieldname) {
	return rows.reduce(function (total, row) {
		return total + flt(row[fieldname]);
	}, 0);
}


function purchase_plan_unique_values(rows, fieldname) {
	var values = [];
	rows.forEach(function (row) {
		String(row[fieldname] || "").split(", ").forEach(function (value) {
			value = value.trim();
			if (value && values.indexOf(value) === -1) {
				values.push(value);
			}
		});
	});
	return values;
}


function purchase_plan_latest_value(rows, fieldname) {
	return rows.reduce(function (latest, row) {
		var value = row[fieldname] || "";
		return value > latest ? value : latest;
	}, "");
}


function purchase_plan_latest_row(rows, fieldname) {
	return rows.reduce(function (latest, row) {
		return !latest || (row[fieldname] || "") > (latest[fieldname] || "")
			? row : latest;
	}, null) || {};
}


function purchase_plan_combined_price_details(rows, fieldname, currency) {
	currency = currency || "BHD";
	var display_values = [];
	var tooltip_values = [];
	(rows || []).forEach(function (row) {
		var value = row[fieldname];
		if (value === null || value === undefined || value === "" ||
				!isFinite(Number(value))) {
			tooltip_values.push(row.item + ": " + __("Not available"));
			return;
		}
		var formatted_value = Number(value).toFixed(3);
		display_values.push(formatted_value);
		tooltip_values.push(
			row.item + ": " + formatted_value + " " + currency
		);
	});
	return {
		display: display_values.join(", "),
		tooltip: tooltip_values.join("\n")
	};
}


function purchase_plan_combined_supplier_tooltip(rows, supplier) {
	var sections = [];
	(rows || []).forEach(function (row) {
		var row_suppliers = String(row.item_suppliers || "").split(", ");
		if (row_suppliers.indexOf(supplier) === -1) {
			return;
		}
		var supplier_details = [];
		try {
			supplier_details = JSON.parse(row.supplier_purchase_details || "[]");
		} catch (unused_error) {
			supplier_details = [];
		}
		var detail = supplier_details.filter(function (value) {
			return value.supplier == supplier;
		})[0] || {};
		var supplier_name = detail.supplier_name || supplier;
		var lines = [
			row.item,
			__("Supplier Name") + ": " + supplier_name
		];
		if (detail.purchase_invoice) {
			lines.push(
				__("Last Cost") + ": " +
					format_currency(flt(detail.cost), detail.currency),
				__("Invoice") + ": " + detail.purchase_invoice,
				__("Date") + ": " +
					frappe.datetime.str_to_user(detail.posting_date),
				__("No. of Purchases") + ": " +
					cint(detail.purchase_invoice_count)
			);
		} else {
			lines.push(
				__("No submitted Purchase Invoice history"),
				__("No. of Purchases") + ": " +
					cint(detail.purchase_invoice_count)
			);
		}
		sections.push(lines.join("\n"));
	});
	return sections.join("\n\n");
}


function purchase_plan_combined_tooltip(data, fieldname) {
	if (!data || !data._purchase_plan_combined ||
			!data._purchase_plan_member_rows || !fieldname) {
		return "";
	}
	var ignored_fields = [
		"total_cost", "total_selling_price", "minimum_purchase_qty",
		"reorder_quantity"
	];
	if (ignored_fields.indexOf(fieldname) !== -1) {
		return __("Not combined because the value differs by Item.");
	}
	var lines = data._purchase_plan_member_rows.map(function (member_row) {
		var member_value = member_row[fieldname];
		if (member_value === null || member_value === undefined || member_value === "") {
			member_value = __("Not available");
		}
		var voucher_no = "";
		if (fieldname == "last_purchase_invoice_date") {
			voucher_no = member_row.last_purchase_voucher_no || "";
		} else if (fieldname == "last_sales_invoice_date") {
			voucher_no = member_row.last_sales_voucher_no || "";
		}
		return member_row.item + ": " + member_value +
			(voucher_no ? " (" + voucher_no + ")" : "");
	});
	if (fieldname == "sales_invoice_count") {
		lines.push(__("Combined total counts each invoice only once."));
	} else if (fieldname == "out_of_stock_days") {
		lines.push(__("Combined total counts a day only when the pooled stock is unavailable."));
	} else if ([
			"expected_order_quantity", "rfq_order_quantity"
		].indexOf(fieldname) !== -1) {
		lines.push(__(
			"Combined recommendation is the sum of the individual Expected Order Quantity values."
		));
	} else if ([
			"expected_total_sales", "monthy_sales", "annual_sales",
			"period_expected_sales", "shortage_happened", "min",
			"available_total_qty", "priority_month"
		].indexOf(fieldname) !== -1) {
		lines.push(__("Combined value is recalculated from the pooled demand and stock."));
	}
	return lines.join("\n");
}


function purchase_plan_filter_signature(report) {
	var normalize = function (value) {
		if (Array.isArray(value)) {
			return value.map(normalize);
		}
		if (value && typeof value == "object") {
			var normalized = {};
			Object.keys(value).sort().forEach(function (key) {
				normalized[key] = normalize(value[key]);
			});
			return normalized;
		}
		return value;
	};
	var values = report.get_filter_values
		? report.get_filter_values() : {};
	return JSON.stringify(normalize(values));
}


function purchase_plan_combined_filters_match(report) {
	return report.purchase_plan_combined_filter_signature ===
		purchase_plan_filter_signature(report);
}


function purchase_plan_merge_combination_groups(current_rows, combined_groups) {
	var group_by_item = {};
	(combined_groups || []).forEach(function (group, group_index) {
		(group.item_codes || []).forEach(function (item_code) {
			group_by_item[item_code] = group_index;
		});
	});
	var inserted_groups = {};
	var merged_rows = [];
	(current_rows || []).forEach(function (row) {
		var group_index = group_by_item[row.item];
		if (group_index === undefined) {
			merged_rows.push(row);
			return;
		}
		if (!inserted_groups[group_index]) {
			merged_rows.push(combined_groups[group_index].row);
			inserted_groups[group_index] = true;
		}
	});
	return merged_rows;
}


function purchase_plan_selected_combination_items(group_controls, excluded_control) {
	var selected_items = {};
	(group_controls || []).forEach(function (entry) {
		if (!entry.control || entry.control === excluded_control) {
			return;
		}
		var values = entry.control.get_value() || [];
		if (!Array.isArray(values)) {
			values = [values];
		}
		values.forEach(function (item_code) {
			selected_items[item_code] = true;
		});
	});
	return selected_items;
}


function make_purchase_plan_combined_row(report, rows, label, combined_details) {
	combined_details = combined_details || {};
	var item_codes = rows.map(function (row) { return row.item; });
	var estimated_out_of_stock_sales_qty = flt(
		combined_details.estimated_out_of_stock_sales_qty
	);
	var adjusted_total_sales = purchase_plan_sum_rows(rows, "total_sales")
		+ estimated_out_of_stock_sales_qty
		+ purchase_plan_sum_rows(rows, "converted_repack_demand");
	var expected_total_sales = adjusted_total_sales * (
		1 + flt(report.get_filter_value("percentage")) / 100
	);
	var report_days = frappe.datetime.get_day_diff(
		report.get_filter_value("end_date"), report.get_filter_value("start_date")
	);
	var report_months = report_days >= 30 ? parseInt(report_days / 30, 10) : 0;
	var monthly_sales = report_months
		? parseInt(expected_total_sales, 10) / report_months
		: 0;
	var available_quantity = purchase_plan_sum_rows(rows, "available_quantity");
	var converted_available = purchase_plan_sum_rows(
		rows, "converted_repack_available"
	);
	var on_purchase = purchase_plan_sum_rows(rows, "on_purchase");
	var planning_available = available_quantity + converted_available;
	var period_expected_sales = monthly_sales * flt(
		report.get_filter_value("months_to_arrive")
	);
	var shortage = planning_available + on_purchase - period_expected_sales;
	var minimum_qty = purchase_plan_rfq_order_quantity(
		monthly_sales * flt(report.get_filter_value("minimum_stock_months")), false
	);
	var expected_order_quantity = purchase_plan_sum_rows(
		rows, "expected_order_quantity"
	);
	var rfq_order_quantity = expected_order_quantity < 0
		? purchase_plan_rfq_order_quantity(Math.abs(expected_order_quantity), false)
		: 0;
	var item_groups = purchase_plan_unique_values(rows, "item_group");
	var latest_purchase_row = purchase_plan_latest_row(
		rows, "last_purchase_invoice_date"
	);
	var latest_sales_row = purchase_plan_latest_row(
		rows, "last_sales_invoice_date"
	);

	return {
		_purchase_plan_combined: 1,
		_purchase_plan_member_items: item_codes,
		_purchase_plan_member_rows: rows,
		item: item_codes.join(" + "),
		item_name: label || __("Combined: {0}", [item_codes.join(" + ")]),
		unit: rows[0].unit,
		last_purchase_invoice_date: latest_purchase_row.last_purchase_invoice_date || "",
		last_sales_invoice_date: latest_sales_row.last_sales_invoice_date || "",
		sales_invoice_count: cint(combined_details.sales_invoice_count),
		total_sales: purchase_plan_sum_rows(rows, "total_sales"),
		item_group: item_groups.length === 1 ? item_groups[0] : "",
		out_of_stock_days: combined_details.out_of_stock_days,
		estimated_out_of_stock_sales_qty: estimated_out_of_stock_sales_qty,
		converted_repack_demand: purchase_plan_sum_rows(
			rows, "converted_repack_demand"
		),
		repack_demand_from: purchase_plan_unique_values(
			rows, "repack_demand_from"
		).join(", "),
		percentage: flt(report.get_filter_value("percentage")),
		expected_total_sales: expected_total_sales,
		min: minimum_qty,
		available_quantity: available_quantity,
		converted_repack_available: converted_available,
		on_purchase: on_purchase,
		on_purchase_po: purchase_plan_unique_values(rows, "on_purchase_po").join(", "),
		monthy_sales: monthly_sales,
		annual_sales: monthly_sales * 12,
		period_expected_sales: period_expected_sales,
		shortage_happened: shortage,
		minimum_purchase_qty: null,
		reorder_quantity: null,
		available_total_qty: planning_available + on_purchase,
		expected_order_quantity: expected_order_quantity,
		rfq_order_quantity: rfq_order_quantity,
		priority_month: monthly_sales > 0
			? (planning_available + on_purchase) / monthly_sales : 0,
		item_suppliers: purchase_plan_unique_values(rows, "item_suppliers").join(", "),
		least_supplier_cost: null,
		total_cost: null,
		selling_price: null,
		total_selling_price: null,
		priced_supplier_count: 0,
		supplier_purchase_details: "[]",
		last_purchase_voucher_type: latest_purchase_row.last_purchase_voucher_type || "",
		last_purchase_voucher_no: latest_purchase_row.last_purchase_voucher_no || "",
		last_sales_voucher_type: latest_sales_row.last_sales_voucher_type || "",
		last_sales_voucher_no: latest_sales_row.last_sales_voucher_no || ""
	};
}


function render_purchase_plan_combined_view(report, rows) {
	report.data = rows.slice();
	if (report.raw_data && report.raw_data.add_total_row) {
		report.data.push(report.purchase_plan_original_total_row || {});
	}
	report.purchase_plan_combined_data = report.data;
	report.purchase_plan_combined_view_active = true;
	report.purchase_plan_combined_filter_signature =
		purchase_plan_filter_signature(report);
	report.render_datatable();
}


function show_purchase_plan_combine_dialog(report) {
	var current_rows = (report.data || []).slice();
	if (report.raw_data && report.raw_data.add_total_row) {
		current_rows = current_rows.slice(0, -1);
	}
	var rows = current_rows.filter(function (row) {
		return row.item && !row._purchase_plan_combined;
	});
	if (rows.length < 2) {
		frappe.msgprint(__("At least two individual Item rows are required."));
		return;
	}
	var rows_by_item = {};
	rows.forEach(function (row) { rows_by_item[row.item] = row; });
	var dialog = new frappe.ui.Dialog({
		title: __("Combine Purchase Plan Items"),
		fields: [{
			fieldname: "combination_groups",
			fieldtype: "HTML",
			options: '<div class="purchase-plan-combination-groups"></div>' +
				'<button type="button" class="btn btn-xs btn-default ' +
				'purchase-plan-add-combination-group">' +
				frappe.utils.escape_html(__("Add Another Group")) + '</button>'
		}],
		primary_action_label: __("Combine"),
		primary_action: function () {
			var used_items = {};
			var groups = [];
			for (var group_index = 0; group_index < group_controls.length; group_index++) {
				var item_codes = group_controls[group_index].control.get_value() || [];
				if (!Array.isArray(item_codes)) {
					item_codes = [item_codes];
				}
				if (item_codes.length < 2) {
					frappe.msgprint(__("Group {0}: select at least two Items.", [group_index + 1]));
					return;
				}
				var selected_rows = [];
				for (var item_index = 0; item_index < item_codes.length; item_index++) {
					var item_code = item_codes[item_index];
					if (used_items[item_code]) {
						frappe.msgprint(__("Item {0} is selected in more than one group.", [item_code]));
						return;
					}
					used_items[item_code] = true;
					if (rows_by_item[item_code]) {
						selected_rows.push(rows_by_item[item_code]);
					}
				}
				var units = selected_rows.map(function (row) { return row.unit; })
					.filter(function (unit, index, values_list) {
						return values_list.indexOf(unit) === index;
					});
				if (selected_rows.length !== item_codes.length || units.length !== 1) {
					frappe.msgprint(__(
						"Group {0}: only displayed Items with the same Stock UOM can be combined.",
						[group_index + 1]
					));
					return;
				}
				groups.push({item_codes: item_codes, rows: selected_rows});
			}
			frappe.dom.freeze(__("Calculating combined Item values..."));
			var requests = groups.map(function (group) {
				return frappe.call({
					method: "worldshading.worldshading.report.purchase_plan.purchase_plan.get_combined_purchase_plan_details",
					args: {
						item_codes: JSON.stringify(group.item_codes),
						start_date: report.get_filter_value("start_date"),
						end_date: report.get_filter_value("end_date"),
						include_out_of_stock_sales: report.get_filter_value(
							"include_out_of_stock_sales"
						)
					}
				});
			});
			Promise.all(requests).then(function (responses) {
				frappe.dom.unfreeze();
				if (!report.purchase_plan_combined_view_active) {
					report.purchase_plan_original_data = (report.data || []).slice();
					report.purchase_plan_original_total_row = report.raw_data &&
						report.raw_data.add_total_row
						? report.purchase_plan_original_data.slice(-1)[0] : null;
				}
				var combined_groups = groups.map(function (group, index) {
					return {
						item_codes: group.item_codes,
						row: make_purchase_plan_combined_row(
							report, group.rows, null, responses[index].message || {}
						)
					};
				});
				var remaining_rows = purchase_plan_merge_combination_groups(
					current_rows, combined_groups
				);
				dialog.hide();
				render_purchase_plan_combined_view(report, remaining_rows);
				frappe.show_alert({
					message: __("Combined {0} groups for this view.", [groups.length]),
					indicator: "blue"
				});
			}, function () {
				frappe.dom.unfreeze();
			});
		}
	});
	dialog.show();
	dialog.$wrapper.find(".modal-dialog").css({
		width: "780px",
		"max-width": "95vw"
	});
	dialog.$wrapper.find(".modal-body").css({
		"overflow": "visible"
	});
	var groups_wrapper = dialog.fields_dict.combination_groups.$wrapper.find(
		".purchase-plan-combination-groups"
	);
	var group_controls = [];
	var group_sequence = 0;
	var refresh_group_numbers = function () {
		group_controls.forEach(function (entry, index) {
			entry.wrapper.find(".purchase-plan-combination-group-title")
				.text(__("Group {0}", [index + 1]));
		});
	};
	var add_group = function () {
		group_sequence += 1;
		var group_wrapper = $('<div class="purchase-plan-combination-group"></div>')
			.css({
				border: "1px solid #d1d8dd",
				"border-radius": "4px",
				padding: "10px 12px",
				"margin-bottom": "10px"
			}).appendTo(groups_wrapper);
		var heading = $('<div class="clearfix" style="margin-bottom:8px"></div>')
			.appendTo(group_wrapper);
		$('<strong class="purchase-plan-combination-group-title"></strong>')
			.appendTo(heading);
		var remove_button = $('<button type="button" class="btn btn-xs btn-link pull-right"></button>')
			.text(__("Remove"))
			.appendTo(heading);
		var control_parent = $("<div></div>").appendTo(group_wrapper);
		var control = null;
		control = frappe.ui.form.make_control({
			df: {
				fieldname: "items_to_combine_" + group_sequence,
				fieldtype: "MultiSelectList",
				get_data: function (txt) {
					txt = String(txt || "").toLowerCase();
					var selected_elsewhere =
						purchase_plan_selected_combination_items(
							group_controls, control
						);
					return rows.filter(function (row) {
						var matches_search = !txt ||
							row.item.toLowerCase().indexOf(txt) !== -1 ||
							String(row.item_name || "").toLowerCase().indexOf(txt) !== -1;
						return matches_search && !selected_elsewhere[row.item];
					}).map(function (row) {
						return {value: row.item, description: row.item_name || ""};
					});
				}
			},
			parent: control_parent,
			only_input: true
		});
		control.make_input();
		var entry = {wrapper: group_wrapper, control: control};
		group_controls.push(entry);
		remove_button.on("click", function () {
			if (group_controls.length === 1) {
				frappe.show_alert({message: __("At least one group is required.")});
				return;
			}
			group_controls.splice(group_controls.indexOf(entry), 1);
			group_wrapper.remove();
			refresh_group_numbers();
		});
		refresh_group_numbers();
	};
	dialog.fields_dict.combination_groups.$wrapper.find(
		".purchase-plan-add-combination-group"
	).on("click", add_group);
	add_group();
}


function reset_purchase_plan_combined_view(report) {
	if (!report.purchase_plan_combined_view_active ||
			!report.purchase_plan_original_data) {
		frappe.show_alert({message: __("There is no Combined View to reset.")});
		return;
	}
	report.purchase_plan_combined_view_active = false;
	report.data = report.purchase_plan_original_data.slice();
	report.purchase_plan_combined_data = null;
	report.purchase_plan_original_data = null;
	report.purchase_plan_original_total_row = null;
	report.purchase_plan_combined_filter_signature = null;
	report.render_datatable();
}


function purchase_plan_combined_rfq_table_html() {
	return '<p class="text-muted">' +
		frappe.utils.escape_html(__(
			"Choose the actual Item to order for each temporary combined row. The prepared report will remain unchanged."
		)) + '</p>' +
		'<div class="purchase-plan-combined-rfq-table" style="border:1px solid #d1d8dd;border-radius:4px">' +
			'<div style="display:grid;grid-template-columns:minmax(240px,1.5fr) minmax(220px,1fr) minmax(130px,.6fr);gap:12px;padding:9px 12px;background:#f7fafc;border-bottom:1px solid #d1d8dd;font-weight:600">' +
				'<div>' + frappe.utils.escape_html(__("Combined Items")) + '</div>' +
				'<div>' + frappe.utils.escape_html(__("Item to Order")) + '</div>' +
				'<div>' + frappe.utils.escape_html(__("RFQ Order Qty")) + '</div>' +
			'</div>' +
			'<div class="purchase-plan-combined-rfq-table-body"></div>' +
		'</div>';
}


function choose_purchase_plan_combined_rfq_items(report, report_rows) {
	var combined_rows = report_rows.filter(function (row) {
		return row._purchase_plan_combined &&
			purchase_plan_rfq_order_quantity(row.rfq_order_quantity, false) > 0;
	});
	if (!combined_rows.length) {
		var individual_rfq_items = [];
		report_rows.forEach(function (row) {
			var quantity = purchase_plan_rfq_order_quantity(
				row.rfq_order_quantity, false
			);
			if (row.item && !row._purchase_plan_combined && quantity > 0) {
				individual_rfq_items.push({item_code: row.item, qty: quantity});
			}
		});
		create_request_for_quotation(report, individual_rfq_items, []);
		return;
	}

	var row_controls = [];
	var dialog = new frappe.ui.Dialog({
		title: __("Choose Items for Combined Rows"),
		fields: [{
			fieldname: "combined_items_table",
			fieldtype: "HTML",
			options: purchase_plan_combined_rfq_table_html()
		}],
		primary_action_label: __("Continue"),
		primary_action: function () {
			var selections = [];
			for (var index = 0; index < combined_rows.length; index++) {
				var combined_row = combined_rows[index];
				var member_items = combined_row._purchase_plan_member_items || [];
				var selected_item = row_controls[index].item.get_value();
				var quantity = purchase_plan_rfq_order_quantity(
					row_controls[index].quantity.get_value(), true
				);
				if (quantity <= 0) {
					continue;
				}
				if (member_items.indexOf(selected_item) === -1) {
					frappe.msgprint(__("Please choose an Item belonging to each combined row."));
					return;
				}
				selections.push({
					row: combined_row,
					member_items: member_items,
					selected_item: selected_item,
					qty: quantity
				});
			}

			var rfq_items = [];
			report_rows.forEach(function (row) {
				var quantity = purchase_plan_rfq_order_quantity(
					row.rfq_order_quantity, false
				);
				if (!row.item || quantity <= 0) {
					return;
				}
				if (!row._purchase_plan_combined) {
					rfq_items.push({item_code: row.item, qty: quantity});
					return;
				}
				var selection = selections.filter(function (value) {
					return value.row === row;
				})[0];
				if (selection) {
					rfq_items.push({
						item_code: selection.selected_item,
						qty: selection.qty
					});
				}
			});
			dialog.hide();
			create_request_for_quotation(report, rfq_items, selections.map(function (value) {
				return {
					member_items: value.member_items,
					selected_item: value.selected_item,
					qty: value.qty
				};
			}));
		}
	});
	dialog.show();
	dialog.$wrapper.find(".modal-dialog").css({
		width: "1000px",
		"max-width": "95vw"
	});
	var table_body = dialog.fields_dict.combined_items_table.$wrapper.find(
		".purchase-plan-combined-rfq-table-body"
	);
	if (combined_rows.length > 4) {
		table_body.css({
			"max-height": "55vh",
			"overflow-y": "auto",
			"overflow-x": "hidden"
		});
	}
	combined_rows.forEach(function (row, index) {
		var member_items = row._purchase_plan_member_items || [];
		var table_row = $('<div class="purchase-plan-combined-rfq-row"></div>')
			.css({
				display: "grid",
				"grid-template-columns": "minmax(240px,1.5fr) minmax(220px,1fr) minmax(130px,.6fr)",
				gap: "12px",
				padding: "8px 12px",
				"align-items": "center",
				"border-bottom": index === combined_rows.length - 1
					? "none" : "1px solid #e8e8e8"
			})
			.appendTo(table_body);
		$('<div class="text-muted"></div>')
			.text(row.item_name || member_items.join(" + "))
			.attr("title", member_items.join(" + "))
			.appendTo(table_row);
		var item_cell = $("<div></div>").appendTo(table_row);
		var quantity_cell = $("<div></div>").appendTo(table_row);
		var item_control = frappe.ui.form.make_control({
			df: {
				fieldname: "combined_item_" + index,
				fieldtype: "Link",
				options: "Item",
				get_query: (function (allowed_items) {
					return function () {
						return {filters: {name: ["in", allowed_items], disabled: 0}};
					};
				})(member_items)
			},
			parent: item_cell,
			only_input: true
		});
		item_control.make_input();
		if (combined_rows.length > 4) {
			item_control.$input.on("focus.purchase_plan_combined_rfq", function () {
				table_body.css("padding-bottom", "215px");
				window.requestAnimationFrame(function () {
					table_body.scrollTop(
						table_body.scrollTop() + table_row.position().top
					);
				});
			}).on("blur.purchase_plan_combined_rfq", function () {
				setTimeout(function () {
					table_body.css("padding-bottom", "0");
				}, 200);
			});
		}
		var quantity_control = frappe.ui.form.make_control({
			df: {
				fieldname: "combined_qty_" + index,
				fieldtype: "Float"
			},
			parent: quantity_cell,
			only_input: true
		});
		quantity_control.make_input();
		quantity_control.set_value(
			purchase_plan_rfq_order_quantity(row.rfq_order_quantity, false)
		);
		row_controls.push({
			item: item_control,
			quantity: quantity_control
		});
	});
}


function create_request_for_quotation(report, resolved_rfq_items, combination_notes) {
	var rfq_items = resolved_rfq_items || [];
	var report_rows = report.data || [];
	if (report.raw_data && report.raw_data.add_total_row && report_rows.length) {
		report_rows = report_rows.slice(0, -1);
	}
	if (!resolved_rfq_items) {
		if (report.purchase_plan_combined_view_active) {
			choose_purchase_plan_combined_rfq_items(report, report_rows);
			return;
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
	}

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
	var prepared_purchase_plan = report.raw_data && report.raw_data.doc
		? report.raw_data.doc.name
		: null;
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
					combined_item_values: JSON.stringify(combination_notes || []),
					supplier: supplier,
					supplier_group: supplier_group,
					supplier_country: supplier_country,
					item_purchase_country: item_purchase_country,
					item_origin_country: item_origin_country,
					report_filters: JSON.stringify(report_filters),
					prepared_purchase_plan: prepared_purchase_plan,
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


function purchase_plan_total_cost(quantity, last_purchase_cost) {
	if (last_purchase_cost === null || last_purchase_cost === undefined ||
			last_purchase_cost === "") {
		return null;
	}
	return purchase_plan_rfq_order_quantity(quantity, false) * flt(last_purchase_cost);
}


function purchase_plan_total_selling_price(quantity, selling_price) {
	if (selling_price === null || selling_price === undefined ||
			selling_price === "") {
		return null;
	}
	return purchase_plan_rfq_order_quantity(quantity, false) * flt(selling_price);
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
		setValue: function (value, row_index) {
			var quantity = purchase_plan_rfq_order_quantity(value, false);
			data.rfq_order_quantity = quantity;
			data.total_cost = purchase_plan_total_cost(
				quantity, data.least_supplier_cost
			);
			data.total_selling_price = purchase_plan_total_selling_price(
				quantity, data.selling_price
			);
			input.value = quantity;
			setTimeout(function () {
				var datatable = frappe.query_report && frappe.query_report.datatable;
				if (!datatable || !datatable.datamanager || !datatable.cellmanager) {
					return;
				}
				var total_cost_column = (datatable.datamanager.getColumns() || [])
					.find(function (column) {
						return (column.fieldname || column.id) == "total_cost";
					});
				if (total_cost_column) {
					datatable.cellmanager.updateCell(
						total_cost_column.colIndex, row_index, data.total_cost
					);
				}
				var total_selling_price_column = (datatable.datamanager.getColumns() || [])
					.find(function (column) {
						return (column.fieldname || column.id) == "total_selling_price";
					});
				if (total_selling_price_column) {
					datatable.cellmanager.updateCell(
						total_selling_price_column.colIndex,
						row_index,
						data.total_selling_price
					);
				}
				if (datatable.bodyRenderer) {
					datatable.bodyRenderer.renderFooter();
				}
				if (datatable.purchase_plan_refresh_sticky_columns) {
					datatable.purchase_plan_refresh_sticky_columns();
				}
			}, 0);
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
			"label": __("Start Date"),
			"fieldtype": "Date",
			"reqd": 1,
			"on_change": function() {
				var start_date = frappe.query_report.get_filter_value("start_date");
				if (!/^\d{4}-\d{2}-\d{2}$/.test(start_date || "")) {
					return;
				}
				var suggested_end_date = frappe.datetime.add_days(
					frappe.datetime.add_months(start_date, 12), -1
				);
				var today = frappe.datetime.get_today();
				frappe.query_report.set_filter_value(
					"end_date",
					suggested_end_date > today ? today : suggested_end_date
				);
			}
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
			"fieldname": "child_item_group",
			"label": __("Child Item Groups"),
			"fieldtype": "MultiSelectList",
			"options":"Item Group",
			get_data: function(txt) {
				return frappe.call({
					"method": "worldshading.worldshading.report.purchase_plan.purchase_plan.get_child_item_group_options",
					"args": {
						"txt": txt
					}
				}).then(function(response) {
					return purchase_plan_selected_options_first(
						"child_item_group", response.message || []
					);
				});
			}
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
			"fieldname": "minimum_stock_months",
			"label": __("Min Stock for How Many Months?"),
			"fieldtype": "Data",
			"reqd": 1,
			"description": __("Minimum-stock reserve calculated separately from purchase coverage and applied once in Expected Order Quantity."),
		},
		{
			"fieldname": "minimum_months",
			"label": __("Purchase Plan for How Many Months?"),
			"fieldtype": "Data",
			"reqd": 1,
			"description": __("Months of average sales the new purchase should cover after stock arrives."),
					},
		{
			"fieldname": "brand",
			"label": __("Brand"),
			"fieldtype": "Link",
			"options": "Brand"
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
			"fieldname": "purchase_required_only",
			"label": __("Purchase Required Items Only"),
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
			"least_supplier_cost",
			"total_cost",
			"total_selling_price"
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
		report.page.add_inner_button(__("Combine Items"), function () {
			show_purchase_plan_combine_dialog(report);
		});
		report.page.add_inner_button(__("Reset Combined View"), function () {
			reset_purchase_plan_combined_view(report);
		});
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
		return restore_prepared_purchase_plan_filters(report);
	},
	"after_datatable_render": function (datatable) {
		var report = frappe.query_report;
		if (report.purchase_plan_combined_view_active &&
				report.data !== report.purchase_plan_combined_data) {
			if (purchase_plan_combined_filters_match(report)) {
				if (!report.purchase_plan_combined_restore_pending) {
					report.purchase_plan_combined_restore_pending = true;
					setTimeout(function () {
						report.purchase_plan_combined_restore_pending = false;
						if (report.purchase_plan_combined_view_active &&
								purchase_plan_combined_filters_match(report)) {
							report.data = report.purchase_plan_combined_data;
							report.render_datatable();
						}
					}, 0);
				}
				return;
			}
			report.purchase_plan_combined_view_active = false;
			report.purchase_plan_combined_data = null;
			report.purchase_plan_original_data = null;
			report.purchase_plan_original_total_row = null;
			report.purchase_plan_combined_filter_signature = null;
		}
		enable_purchase_plan_rfq_qty_editing(datatable);
		apply_purchase_plan_sticky_columns(datatable);
		update_purchase_plan_filter_summary(frappe.query_report);
		bind_current_prepared_report_download(frappe.query_report);
	},
	"formatter": function (value, row, column, data, default_formatter) {
		if (data && data._purchase_plan_combined && column.fieldname == "item") {
			return "<span class='text-primary' title='" +
				frappe.utils.escape_html(
					purchase_plan_combined_tooltip(data, "item") ||
					__("Temporary Combined View")
				) + "'>" +
				frappe.utils.escape_html(value || "") + "</span>";
		}
		if (data && data._purchase_plan_combined && [
				"least_supplier_cost", "selling_price"
			].indexOf(column.fieldname) !== -1) {
			var price_details = purchase_plan_combined_price_details(
				data._purchase_plan_member_rows,
				column.fieldname,
				column.options || "BHD"
			);
			if (!price_details.display) {
				return '<span class="text-muted" title="' +
					frappe.utils.escape_html(price_details.tooltip) + '">' +
					__("N/A") + '</span>';
			}
			return '<span title="' +
				frappe.utils.escape_html(price_details.tooltip) + '">' +
				frappe.utils.escape_html(price_details.display) + '</span>';
		}
		var transaction_link_fields = {
			"last_purchase_invoice_date": {
				"voucher_type": "last_purchase_voucher_type",
				"voucher_no": "last_purchase_voucher_no"
			},
			"last_sales_invoice_date": {
				"voucher_type": "last_sales_voucher_type",
				"voucher_no": "last_sales_voucher_no"
			}
		};
		var transaction_link = transaction_link_fields[column.fieldname];
		if (transaction_link && value && data) {
			var voucher_type = data[transaction_link.voucher_type];
			var voucher_no = data[transaction_link.voucher_no];
			var supported_voucher_types = [
				"Purchase Invoice", "Purchase Receipt",
				"Sales Invoice", "Delivery Note"
			];
			var formatted_date = default_formatter(value, row, column, data);
			var transaction_tooltip = purchase_plan_combined_tooltip(
				data, column.fieldname
			) || voucher_no;
			if (voucher_no && supported_voucher_types.indexOf(voucher_type) !== -1) {
				return '<a href="#Form/' + encodeURIComponent(voucher_type) + '/' +
					encodeURIComponent(voucher_no) + '" title="' +
					frappe.utils.escape_html(transaction_tooltip) + '">' + formatted_date + '</a>';
			}
			return transaction_tooltip
				? '<span title="' + frappe.utils.escape_html(transaction_tooltip) + '">' +
					formatted_date + '</span>'
				: formatted_date;
		}
		if (column.fieldname == "on_purchase_po" && value) {
			return value.split(", ").map(function (purchase_order) {
				return '<a href="#Form/Purchase Order/' + encodeURIComponent(purchase_order) + '">' +
					frappe.utils.escape_html(purchase_order) + '</a>';
			}).join(", ");
		}
		if (column.fieldname == "item_suppliers" && value) {
			if (data && data._purchase_plan_combined) {
				return value.split(", ").map(function (supplier) {
					var tooltip = purchase_plan_combined_supplier_tooltip(
						data._purchase_plan_member_rows, supplier
					);
					return '<a href="#Form/Supplier/' + encodeURIComponent(supplier) +
						'" title="' + frappe.utils.escape_html(tooltip) +
						'" style="color:#7a7a7a;font-weight:600">' +
						frappe.utils.escape_html(supplier) + '</a>';
				}).join(", ");
			}
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
				var supplier_name = detail.supplier_name || supplier;
				var color = "#7a7a7a";
				if (index < priced_supplier_count && index === 0) {
					color = "#2e7d32";
				} else if (index < priced_supplier_count && index === 1) {
					color = "#b7791f";
				} else if (index < priced_supplier_count) {
					color = "#c62828";
				}
				var purchase_invoice_count = cint(detail.purchase_invoice_count);
				var tooltip = show_supplier_tooltips
					? __("Supplier Name") + ": " + supplier_name + "\n" +
						__("No submitted Purchase Invoice history") + "\n" +
						__("No. of Purchases") + ": " + purchase_invoice_count
					: "";
				if (detail.purchase_invoice) {
					tooltip = __("Supplier Name") + ": " + supplier_name + "\n" +
						__("Last Cost") + ": " +
						format_currency(flt(detail.cost), detail.currency) + "\n" +
						__("Invoice") + ": " + detail.purchase_invoice + "\n" +
						__("Date") + ": " + frappe.datetime.str_to_user(detail.posting_date) + "\n" +
						__("No. of Purchases") + ": " + purchase_invoice_count;
				}
				var title_attribute = tooltip
					? ' title="' + frappe.utils.escape_html(tooltip) + '"'
					: "";
				return '<a href="#Form/Supplier/' + encodeURIComponent(supplier) +
					'"' + title_attribute +
					'" style="color:' + color + ';font-weight:600">' +
					frappe.utils.escape_html(supplier) + '</a>';
			}).join(", ");
		}
		if (column.fieldname == "estimated_out_of_stock_sales_qty" && data) {
			var completed_report_months = parseInt(flt(data.total_months_in_report), 10);
			var average_monthly_invoices = completed_report_months > 0
				? flt(data.sales_invoice_count) / completed_report_months
				: flt(data.sales_invoice_count);
			if (average_monthly_invoices <= 5) {
				var unavailable_tooltip = purchase_plan_combined_tooltip(
					data, column.fieldname
				);
				return '<span class="text-muted"' + (unavailable_tooltip
					? ' title="' + frappe.utils.escape_html(unavailable_tooltip) + '"'
					: '') + '>' + __("N/A") + '</span>';
			}
		}
		value = default_formatter(value, row, column, data);
		var combined_tooltip = purchase_plan_combined_tooltip(
			data, column.fieldname
		);
		if (combined_tooltip) {
			value = '<span title="' + frappe.utils.escape_html(combined_tooltip) +
				'">' + value + '</span>';
		}
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
