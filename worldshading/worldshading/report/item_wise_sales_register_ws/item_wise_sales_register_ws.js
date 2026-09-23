// Copyright (c) 2026, World Shading
// ERPNext/Frappe v12 compatible report script.

(function () {
	"use strict";

	function apply_filter_labels(report) {
		var page_form = report.page.main.find(".page-form");
		page_form.addClass("iwsr-ws-filter-form");
		(report.filters || []).forEach(function (filter) {
			var field = filter.df || {};
			var wrapper = $(filter.wrapper);
			if (!field.fieldname || !wrapper.length) {
				return;
			}
			wrapper.addClass("iwsr-ws-filter-control");
			if (!wrapper.children(".iwsr-ws-filter-label").length) {
				var label = $("<label class='iwsr-ws-filter-label'></label>");
				if (field.fieldtype === "Check") {
					label.html("&nbsp;").css("visibility", "hidden");
				} else {
					label.text(__(field.label || field.fieldname));
					wrapper.find("input").attr("placeholder", "");
				}
				wrapper.prepend(label);
			}
		});
	}

	function update_filter_summary(report) {
		var summary = report.page.main.find(".iwsr-ws-filter-summary");
		var values = [];
		(report.filters || []).forEach(function (filter) {
			var field = filter.df || {};
			var value = report.get_filter_value(field.fieldname);
			if (field.fieldtype === "Check") {
				if (!cint(value)) { return; }
				value = __("Yes");
			}
			if (value === undefined || value === null || value === "") { return; }
			values.push(
				"<span><strong>" + frappe.utils.escape_html(__(field.label || field.fieldname)) +
				":</strong> " + frappe.utils.escape_html(String(value)) + "</span>"
			);
		});
		if (!summary.length) {
			summary = $("<div class='iwsr-ws-filter-summary'></div>")
				.insertAfter(report.page.main.find(".page-form"));
		}
		summary.html(values.join(""));
	}

	function restore_prepared_filters(report) {
		var params = report.get_query_params ? report.get_query_params() : {};
		if (!params.prepared_report_name) {
			return Promise.resolve();
		}
		return frappe.call({
			method: "worldshading.worldshading.report.item_wise_sales_register_ws.item_wise_sales_register_ws.get_prepared_report_filters",
			args: {prepared_report_name: params.prepared_report_name}
		}).then(function (response) {
			var values = response.message || {};
			(report.filters || []).forEach(function (filter) {
				var fieldname = filter.df.fieldname;
				if (Object.prototype.hasOwnProperty.call(values, fieldname)) {
					filter.set_input(values[fieldname]);
				}
			});
		});
	}

	function bind_prepared_download(report) {
		var prepared = report.raw_data && report.raw_data.doc;
		if (!prepared || !prepared.name) { return; }
		var button = report.page.inner_toolbar.find(
			'button[data-label="' + encodeURIComponent(__("Download Report")) + '"]'
		);
		button.off("click").on("click.iwsr_ws", function () {
			window.open(frappe.urllib.get_full_url(
				"/api/method/frappe.core.doctype.prepared_report.prepared_report.download_attachment?dn=" +
				encodeURIComponent(prepared.name)
			));
		});
	}

	function apply_datatable_style(datatable) {
		if (!datatable || !datatable.wrapper) { return; }
		var wrapper = $(datatable.wrapper);
		wrapper.addClass("iwsr-ws-table");
		var selected_index = datatable.iwsr_ws_selected_index;
		var empty_layout_frame = null;
		var refresh_empty_filter_layout = null;
		wrapper.off("click.iwsr_ws_row").on("click.iwsr_ws_row", ".dt-row .dt-cell", function () {
			var row = $(this).closest(".dt-row");
			if (row.hasClass("dt-row-header") || row.hasClass("dt-row-filter") || row.closest(".dt-footer").length) {
				return;
			}
			selected_index = row.attr("data-row-index");
			datatable.iwsr_ws_selected_index = selected_index;
			wrapper.find(".iwsr-ws-selected-row").removeClass("iwsr-ws-selected-row");
			row.addClass("iwsr-ws-selected-row");
			if (refresh_empty_filter_layout) { refresh_empty_filter_layout(); }
		});

		if (datatable.iwsr_ws_observer) { datatable.iwsr_ws_observer.disconnect(); }
		datatable.iwsr_ws_observer = new MutationObserver(function () {
			if (selected_index !== undefined && selected_index !== null) {
				wrapper.find('.dt-row[data-row-index="' + selected_index + '"]')
					.addClass("iwsr-ws-selected-row");
			}
			if (empty_layout_frame === null) {
				empty_layout_frame = window.requestAnimationFrame(function () {
					empty_layout_frame = null;
					if (refresh_empty_filter_layout) { refresh_empty_filter_layout(); }
				});
			}
		});
		datatable.iwsr_ws_observer.observe(datatable.bodyScrollable, {childList: true, subtree: true});

		var item_column = null;
		var name_column = null;
		var rules = [];
		var important = {
			"Sold Stock Qty": "#eef9f0", "Net Amount": "#eef6ff",
			"Tax": "#fff7e6", "Total": "#f5f0ff", "Current Stock Qty": "#eefafa"
		};
		wrapper.find(".dt-row-header .dt-cell").each(function () {
			var text = $(this).text().trim();
			var column_class = (this.className.match(/dt-cell--col-\d+/) || [])[0];
			if (text === __("Item Code")) { item_column = column_class; }
			if (text === __("Item Name")) { name_column = column_class; }
			if (important[text] && column_class) {
				rules.push(".iwsr-ws-table ." + column_class + "{background:" + important[text] + " !important;}");
			}
		});
		if (item_column && name_column) {
			var update_sticky_offsets = function () {
				var item_width = wrapper.find(".dt-row-header ." + item_column)[0];
				item_width = item_width ? item_width.getBoundingClientRect().width : 130;
				wrapper[0].style.setProperty("--iwsr-ws-item-width", item_width + "px");
			};
			update_sticky_offsets();
			rules.push(".iwsr-ws-table .dt-cell--col-0{position:sticky;left:0;z-index:4;background:#fff;width:50px;min-width:50px;max-width:50px;flex:0 0 50px;}");
			rules.push(".iwsr-ws-table ." + item_column + "{position:sticky;left:50px;z-index:4;background:#fff;}");
			rules.push(".iwsr-ws-table ." + name_column + "{position:sticky;left:calc(50px + var(--iwsr-ws-item-width));z-index:4;background:#fff;box-shadow:2px 0 2px rgba(0,0,0,.08);}");
			rules.push(".iwsr-ws-table .dt-row-header .dt-cell--col-0,.iwsr-ws-table .dt-row-header ." + item_column + ",.iwsr-ws-table .dt-row-header ." + name_column + ",.iwsr-ws-table .dt-row-filter .dt-cell--col-0,.iwsr-ws-table .dt-row-filter ." + item_column + ",.iwsr-ws-table .dt-row-filter ." + name_column + "{position:relative;left:auto;z-index:30!important;background:#f7fafc!important;}");
			rules.push(".iwsr-ws-table .iwsr-ws-sticky-header-cell{z-index:30!important;background:#f7fafc!important;isolation:isolate;}");
			rules.push(".iwsr-ws-table .iwsr-ws-sticky-header-cell .dt-cell__content{position:relative;z-index:1;background:#f7fafc;}");
			rules.push(".iwsr-ws-table .iwsr-ws-sticky-footer-cell{position:relative;left:auto;z-index:30!important;background:#f7fafc!important;}");

			var update_sticky_header = function () {
				var scroll_left = datatable.bodyScrollable.scrollLeft;
				wrapper.find(".dt-header .dt-cell--col-0,.dt-header ." + item_column + ",.dt-header ." + name_column)
					.addClass("iwsr-ws-sticky-header-cell")
					.css("transform", "translateX(" + scroll_left + "px)");
				wrapper.find(".dt-footer .dt-cell--col-0,.dt-footer ." + item_column + ",.dt-footer ." + name_column)
					.addClass("iwsr-ws-sticky-footer-cell")
					.css("transform", "translateX(" + scroll_left + "px)");
			};
			refresh_empty_filter_layout = function () {
				var no_data = $(datatable.bodyScrollable).find(".dt-scrollable__no-data");
				if (!no_data.length) { return; }
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
					datatable.iwsr_ws_last_scroll_left || 0, maximum_scroll
				);
				update_sticky_header();
			};
			if (datatable.iwsr_ws_last_scroll_left === undefined) {
				datatable.iwsr_ws_last_scroll_left = datatable.bodyScrollable.scrollLeft;
			}
			$(datatable.bodyScrollable)
				.off("scroll.iwsr_ws_sticky_columns")
				.on("scroll.iwsr_ws_sticky_columns", function () {
					var no_data = $(datatable.bodyScrollable).find(".dt-scrollable__no-data");
					if (!no_data.length ||
							datatable.bodyScrollable.scrollWidth > datatable.bodyScrollable.clientWidth) {
						datatable.iwsr_ws_last_scroll_left = datatable.bodyScrollable.scrollLeft;
					}
					window.requestAnimationFrame(update_sticky_header);
				});
			update_sticky_header();
			refresh_empty_filter_layout();

			var resizing_column = false;
			$(datatable.header)
				.off("mousedown.iwsr_ws_sticky_resize")
				.on("mousedown.iwsr_ws_sticky_resize", ".dt-cell__resize-handle", function () {
					resizing_column = true;
				});
			$(document.body)
				.off("mouseup.iwsr_ws_sticky_resize")
				.on("mouseup.iwsr_ws_sticky_resize", function () {
					if (!resizing_column) { return; }
					resizing_column = false;
					window.requestAnimationFrame(function () {
						update_sticky_offsets();
						refresh_empty_filter_layout();
						update_sticky_header();
					});
				});
			$(datatable.header)
				.off("dblclick.iwsr_ws_sticky_resize")
				.on("dblclick.iwsr_ws_sticky_resize", ".dt-cell__resize-handle", function () {
					setTimeout(function () {
						update_sticky_offsets();
						refresh_empty_filter_layout();
						update_sticky_header();
					}, 0);
				});
			datatable.iwsr_ws_refresh_sticky_columns = function () {
				window.requestAnimationFrame(function () {
					update_sticky_offsets();
					refresh_empty_filter_layout();
					update_sticky_header();
				});
			};
			if (!datatable.iwsr_ws_sticky_events_bound) {
				datatable.iwsr_ws_sticky_events_bound = true;
				["onSortColumn", "onSwitchColumn", "onRemoveColumn"].forEach(function (event_name) {
					datatable.on(event_name, function () {
						if (datatable.iwsr_ws_refresh_sticky_columns) {
							datatable.iwsr_ws_refresh_sticky_columns();
						}
					});
				});
			}
			if (datatable.columnmanager && datatable.columnmanager.sortable) {
				datatable.columnmanager.sortable.option("disabled", true);
			}
		}
		$("#iwsr-ws-dynamic-style").remove();
		$("<style id='iwsr-ws-dynamic-style'>" + rules.join("") + "</style>").appendTo("head");
	}

	function install_static_style() {
		if ($("#iwsr-ws-static-style").length) { return; }
		$("<style id='iwsr-ws-static-style'>" +
			".iwsr-ws-filter-label{display:block;height:12px;margin:0;color:#9ba6b1;font-size:10px;font-weight:600;line-height:12px;}" +
			".iwsr-ws-filter-summary{display:flex;flex-wrap:wrap;gap:4px 18px;padding:7px 15px;border-bottom:1px solid #d1d8dd;background:#f8f9fa;font-size:12px;}" +
			".iwsr-ws-table .iwsr-ws-selected-row .dt-cell{background:#fff3cd !important;}" +
			"</style>").appendTo("head");
	}

	frappe.query_reports["Item-wise Sales Register WS"] = {
		filters: [
			{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, "default": frappe.defaults.get_user_default("Company")},
			{fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1, "default": frappe.datetime.add_months(frappe.datetime.get_today(), -1)},
			{fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1, "default": frappe.datetime.get_today()},
			{fieldname: "item_code", label: __("Item Code"), fieldtype: "Link", options: "Item"},
			{fieldname: "item_name", label: __("Item Name"), fieldtype: "Data"},
			{fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group"},
			{fieldname: "brand", label: __("Brand"), fieldtype: "Link", options: "Brand"},
			{fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer"},
			{fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse", get_query: function () { return {filters: {company: frappe.query_report.get_filter_value("company"), is_group: 0}}; }},
			{fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project"},
			{fieldname: "sales_basis", label: __("Sales Basis"), fieldtype: "Select", options: "All\nDirect Items\nPacked Items", "default": "All"},
			{fieldname: "include_returns", label: __("Include Returns"), fieldtype: "Check", "default": 1},
			{fieldname: "show_detailed_report", label: __("Show Detailed Report"), fieldtype: "Check", "default": 0}
		],
		onload: function (report) {
			install_static_style();
			apply_filter_labels(report);
			update_filter_summary(report);
			return restore_prepared_filters(report);
		},
		after_datatable_render: function (datatable) {
			apply_datatable_style(datatable);
			update_filter_summary(frappe.query_report);
			bind_prepared_download(frappe.query_report);
		}
	};
}());
