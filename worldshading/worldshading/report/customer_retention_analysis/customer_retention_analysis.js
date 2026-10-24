// Copyright (c) 2026, World Shading
// ERPNext/Frappe v12 compatible prepared report client.

(function () {
	"use strict";

	var REPORT_NAME = "Customer Retention Analysis";
	var METHOD = "worldshading.worldshading.report.customer_retention_analysis.customer_retention_analysis.get_prepared_report_filters";
	var BULK_CAMPAIGN_METHOD = "worldshading.worldshading.doctype.campaign_customer." +
		"campaign_customer.bulk_create_campaign_customers";
	var STATUS_COLORS = {
		"Lost": "red",
		"Decreased": "orange",
		"Stable": "gray",
		"Increased": "green",
		"New": "blue",
		"Reactivated": "purple"
	};

	function get_current_year() {
		return parseInt(frappe.datetime.get_today().slice(0, 4), 10);
	}

	function get_displayed_customers(report) {
		var customers = [];
		var seen = {};
		(report.data || []).some(function (row) {
			var customer = row.customer;
			if (!customer || seen[customer]) {
				return false;
			}
			seen[customer] = true;
			customers.push(customer);
			return customers.length >= 250;
		});
		return customers;
	}

	function open_campaign_customer_dialog(report) {
		var customers = get_displayed_customers(report);
		if (!customers.length) {
			frappe.msgprint(__("There are no displayed customers to add."));
			return;
		}

		var dialog = new frappe.ui.Dialog({
			title: __("Create Campaign Customers"),
			fields: [
				{
					fieldname: "source_count", fieldtype: "Int",
					label: __("Displayed Customers"), default: customers.length,
					read_only: 1
				},
				{
					fieldname: "campaign", fieldtype: "Link", label: __("Campaign"),
					options: "Campaign", reqd: 1
				},
				{
					fieldname: "caller", fieldtype: "Link", label: __("Caller"),
					options: "User", default: frappe.session.user, reqd: 1
				},
				{
					fieldname: "planned_contact_date", fieldtype: "Date",
					label: __("Planned Contact Date"),
					default: frappe.datetime.get_today(), reqd: 1
				},
				{
					fieldname: "priority", fieldtype: "Select", label: __("Priority"),
					options: "Standard\nTop 20", default: "Standard", reqd: 1
				},
				{
					fieldname: "batch_size", fieldtype: "Int", label: __("Customers to Add"),
					default: Math.min(10, customers.length), reqd: 1,
					description: __("Existing customers are skipped, so the next customers in report order are added.")
				}
			],
			primary_action_label: __("Create"),
			primary_action: function (values) {
				var batch_size = cint(values.batch_size);
				if (batch_size < 1 || batch_size > 250) {
					frappe.msgprint(__("Customers to Add must be between 1 and 250."));
					return;
				}
				frappe.call({
					method: BULK_CAMPAIGN_METHOD,
					args: {
						campaign: values.campaign,
						customers: customers,
						caller: values.caller,
						planned_contact_date: values.planned_contact_date,
						priority: values.priority,
						batch_size: batch_size
					},
					freeze: true,
					freeze_message: __("Creating Campaign Customers..."),
					callback: function (r) {
						if (r.exc) {
							return;
						}
						var result = r.message || {};
						dialog.hide();
						frappe.msgprint({
							title: __("Campaign Customers"),
							message: __("Created: {0}", [result.created_count || 0]) +
								"<br>" + __("Already in Campaign: {0}", [result.skipped_count || 0]),
							indicator: "green"
						});
						report.refresh();
					}
				});
			}
		});
		dialog.show();
	}

	function add_campaign_customer_button(report) {
		if (report.__campaign_customer_button_added) {
			return;
		}
		report.__campaign_customer_button_added = true;
		report.page.add_inner_button(__("Create Campaign Customers"), function () {
			open_campaign_customer_dialog(report);
		});
	}

	function install_styles() {
		if ($("#cra-static-style").length) { return; }
		$("<style id='cra-static-style'>" +
			".cra-filter-summary{display:flex;flex-wrap:wrap;gap:4px 18px;padding:7px 15px;border-bottom:1px solid #d1d8dd;background:#f8f9fa;font-size:12px;}" +
			".cra-result-summary{display:flex;flex-wrap:wrap;gap:7px;padding:9px 15px;border-bottom:1px solid #d1d8dd;background:#fff;font-size:12px;}" +
			".cra-summary-chip{display:inline-flex;align-items:center;min-height:26px;padding:3px 9px;border:1px solid #dfe3e6;border-radius:13px;background:#f8f9fa;white-space:nowrap;}" +
			".cra-summary-chip.indicator{padding-left:21px;}" +
			".cra-summary-risk{border-color:#f4cccc;background:#fff5f5;color:#9b2c2c;}" +
			".cra-table .cra-sticky-header{z-index:30!important;background:#f7fafc!important;}" +
			".cra-table .cra-sticky-header .dt-cell__content{position:relative;z-index:1;background:#f7fafc;}" +
			".cra-table .cra-sticky-footer{position:relative;left:auto;z-index:30!important;background:#f7fafc!important;}" +
			".cra-table .cra-sticky-edge{box-shadow:2px 0 2px rgba(0,0,0,.08);}" +
			".cra-table .dt-row[data-row-index] .dt-cell{cursor:pointer;}" +
			".cra-table .dt-row[data-row-index]:hover .dt-cell{background:#eef6ff!important;}" +
			".cra-table .cra-selected-row .dt-cell{background:#fff3cd!important;}" +
			".cra-table .dt-dropdown__list{z-index:60!important;}" +
			".cra-table .cra-item-group-tooltip{cursor:help;text-decoration:underline dotted;text-underline-offset:3px;}" +
			".cra-table .cra-item-group-heading .dt-cell__content{cursor:help;text-decoration:underline dotted;text-underline-offset:3px;}" +
			"</style>").appendTo("head");
	}

	function summary_value(report, fieldname) {
		var value = report.get_filter_value(fieldname);
		return value === undefined || value === null || value === "" ? __("All") : String(value);
	}

	function update_filter_summary(report) {
		if (!report || !report.page) { return; }
		var labels = [
			["company", __("Company")],
			["analysis_year", __("Analysis Year")],
			["previous_years", __("Previous Years")],
			["retention_status", __("Status")],
			["sort_by", __("Sort By")],
			["top_results", __("Top Results")]
		];
		var parts = labels.map(function (entry) {
			return "<span><strong>" + frappe.utils.escape_html(entry[1]) + ":</strong> " +
				frappe.utils.escape_html(summary_value(report, entry[0])) + "</span>";
		});
		var summary = report.page.main.find(".cra-filter-summary");
		if (!summary.length) {
			summary = $("<div class='cra-filter-summary'></div>")
				.insertAfter(report.page.main.find(".page-form"));
		}
		summary.html(parts.join(""));
	}

	function build_decline_chart(columns, rows) {
		var declines = (rows || []).filter(function (row) {
			return parseFloat(row.decrease_amount || 0) > 0;
		}).slice();
		declines.sort(function (left, right) {
			var difference = parseFloat(right.decrease_amount || 0) -
				parseFloat(left.decrease_amount || 0);
			if (difference) { return difference; }
			return String(left.customer || "").localeCompare(String(right.customer || ""));
		});
		declines = declines.slice(0, 10);
		if (!declines.length) { return; }
		return {
			data: {
				labels: declines.map(function (row) { return row.customer_name || row.customer; }),
				datasets: [{
					name: __("Sales Decrease"),
					values: declines.map(function (row) { return parseFloat(row.decrease_amount || 0); })
				}]
			},
			type: "bar",
			title: __("Largest Sales Decreases"),
			colors: ["#e74c3c"]
		};
	}

	function build_result_summary_html(rows) {
		rows = rows || [];
		var statuses = ["Lost", "Decreased", "Stable", "Increased", "New", "Reactivated"];
		var counts = {};
		statuses.forEach(function (status) { counts[status] = 0; });
		var at_risk = 0;
		rows.forEach(function (row) {
			var status = row.retention_status;
			if (Object.prototype.hasOwnProperty.call(counts, status)) { counts[status] += 1; }
			if (status === "Lost" || status === "Decreased") {
				at_risk += parseFloat(row.previous_sales || 0);
			}
		});
		var parts = statuses.map(function (status) {
			return "<span class='cra-summary-chip indicator " + STATUS_COLORS[status] + "'>" +
				frappe.utils.escape_html(__(status)) + ": " + counts[status] + "</span>";
		});
		var currency = rows.length ? rows[0].report_currency : null;
		var formatted_risk = format_currency(at_risk, currency);
		parts.push("<span class='cra-summary-chip cra-summary-risk'><strong>" +
			frappe.utils.escape_html(__("At-risk Previous Sales")) +
			":</strong> " + frappe.utils.escape_html(String(formatted_risk)) + "</span>");
		return parts.join("");
	}

	function update_result_summary(report) {
		if (!report || !report.page) { return; }
		var rows = report.data || [];
		var summary = report.page.main.find(".cra-result-summary");
		if (!summary.length) {
			summary = $("<div class='cra-result-summary'></div>")
				.insertAfter(report.page.main.find(".cra-filter-summary"));
		}
		summary.html(build_result_summary_html(rows));
	}

	function restore_prepared_filters(report) {
		var params = report.get_query_params ? report.get_query_params() : {};
		if (!params.prepared_report_name) { return Promise.resolve(); }
		return frappe.call({
			method: METHOD,
			args: {prepared_report_name: params.prepared_report_name}
		}).then(function (response) {
			var values = response.message || {};
			(report.filters || []).forEach(function (filter) {
				var fieldname = filter.df.fieldname;
				if (Object.prototype.hasOwnProperty.call(values, fieldname)) {
					filter.set_input(values[fieldname]);
				}
			});
			update_filter_summary(report);
		});
	}

	function apply_sticky_columns(datatable) {
		if (!datatable || !datatable.wrapper || !datatable.bodyScrollable ||
				!datatable.datamanager) { return; }
		var wrapper_element = datatable.wrapper;
		var wrapper = $(wrapper_element);
		wrapper.addClass("cra-table");

		function get_column(fieldname) {
			var matched = null;
			(datatable.datamanager.getColumns() || []).forEach(function (column) {
				if ((column.fieldname || column.id) === fieldname) { matched = column; }
			});
			return matched;
		}

		var rank_column = get_column("rank");
		var customer_column = get_column("customer");
		var customer_name_column = get_column("customer_name");
		if (!rank_column || !customer_column || !customer_name_column) {
			wrapper.find(".dt-row-header .dt-cell").each(function () {
				var text = $(this).text().trim();
				var class_name = (this.className.match(/dt-cell--col-(\d+)/) || [])[1];
				if (class_name === undefined) { return; }
				if (!rank_column && text === __("Rank")) {
					rank_column = {colIndex: cint(class_name)};
				}
				if (!customer_column && text === __("Customer")) {
					customer_column = {colIndex: cint(class_name)};
				}
				if (!customer_name_column && text === __("Customer Name")) {
					customer_name_column = {colIndex: cint(class_name)};
				}
			});
		}
		if (!rank_column || !customer_column || !customer_name_column) { return; }
		var sticky_indices = [
			0, rank_column.colIndex, customer_column.colIndex, customer_name_column.colIndex
		];
		var sticky_header_selector = sticky_indices.map(function (index) {
			return ".dt-header .dt-cell--col-" + index;
		}).join(", ");
		var sticky_footer_selector = sticky_indices.map(function (index) {
			return ".dt-footer .dt-cell--col-" + index;
		}).join(", ");

		if (datatable.cra_row_highlight_observer) {
			datatable.cra_row_highlight_observer.disconnect();
		}
		var selected_row_index = datatable.cra_selected_row_index;
		var row_highlight_frame = null;
		var empty_layout_frame = null;
		var refresh_empty_filter_layout = null;
		var restore_selected_row = function () {
			row_highlight_frame = null;
			wrapper.find(".cra-selected-row").removeClass("cra-selected-row");
			if (selected_row_index === undefined || selected_row_index === null) { return; }
			wrapper.find('.dt-row[data-row-index="' + selected_row_index + '"]')
				.addClass("cra-selected-row");
		};
		var queue_selected_row_restore = function () {
			if (row_highlight_frame !== null) { return; }
			row_highlight_frame = window.requestAnimationFrame(restore_selected_row);
		};
		datatable.cra_row_highlight_observer = new MutationObserver(function () {
			queue_selected_row_restore();
			if (empty_layout_frame === null) {
				empty_layout_frame = window.requestAnimationFrame(function () {
					empty_layout_frame = null;
					if (refresh_empty_filter_layout) { refresh_empty_filter_layout(); }
				});
			}
		});
		datatable.cra_row_highlight_observer.observe(
			datatable.bodyScrollable, {childList: true, subtree: true}
		);
		wrapper.off("click.cra_row_highlight")
			.on("click.cra_row_highlight", ".dt-row .dt-cell", function () {
				var selected_row = $(this).closest(".dt-row");
				if (selected_row.hasClass("dt-row-header") ||
						selected_row.hasClass("dt-row-filter") ||
						selected_row.closest(".dt-footer").length) { return; }
				var row_index = selected_row.attr("data-row-index");
				if (!/^\d+$/.test(row_index || "")) { return; }
				selected_row_index = cint(row_index);
				datatable.cra_selected_row_index = selected_row_index;
				restore_selected_row();
			});
		queue_selected_row_restore();

		function get_column_width(column_index, fallback_width) {
			var cell = wrapper.find(
				".dt-row-header .dt-cell--col-" + column_index
			)[0];
			return cell ? cell.getBoundingClientRect().width : fallback_width;
		}
		function update_sticky_offsets() {
			wrapper_element.style.setProperty("--cra-row-index-width", "50px");
			wrapper_element.style.setProperty(
				"--cra-rank-width", get_column_width(rank_column.colIndex, 65) + "px"
			);
			wrapper_element.style.setProperty(
				"--cra-customer-width", get_column_width(customer_column.colIndex, 140) + "px"
			);
		}
		function update_sticky_rules() {
			var rank_class = ".dt-cell--col-" + rank_column.colIndex;
			var customer_class = ".dt-cell--col-" + customer_column.colIndex;
			var name_class = ".dt-cell--col-" + customer_name_column.colIndex;
			var header_filter = sticky_indices.map(function (index) {
				return ".cra-table .dt-row-header .dt-cell--col-" + index +
					",.cra-table .dt-row-filter .dt-cell--col-" + index;
			}).join(",");
			var rules = [
				".cra-table .dt-cell--col-0{position:sticky;left:0;z-index:4;background:#fff;width:50px;min-width:50px;max-width:50px;flex:0 0 50px;}",
				".cra-table " + rank_class + "{position:sticky;left:var(--cra-row-index-width);z-index:4;background:#fff;}",
				".cra-table " + customer_class + "{position:sticky;left:calc(var(--cra-row-index-width) + var(--cra-rank-width));z-index:4;background:#fff;}",
				".cra-table " + name_class + "{position:sticky;left:calc(var(--cra-row-index-width) + var(--cra-rank-width) + var(--cra-customer-width));z-index:4;background:#fff;box-shadow:2px 0 2px rgba(0,0,0,.08);}",
				header_filter + "{position:relative;left:auto;z-index:30!important;background:#f7fafc!important;}"
			];
			$("#cra-dynamic-style").remove();
			$("<style id='cra-dynamic-style'>" + rules.join("") + "</style>").appendTo("head");
		}
		function update_sticky_header() {
			var scroll_left = datatable.bodyScrollable.scrollLeft;
			wrapper.find(sticky_header_selector)
				.addClass("cra-sticky-header")
				.css("transform", "translateX(" + scroll_left + "px)");
			wrapper.find(sticky_footer_selector)
				.addClass("cra-sticky-footer")
				.css("transform", "translateX(" + scroll_left + "px)");
		}

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
				datatable.cra_last_scroll_left || 0, maximum_scroll
			);
			update_sticky_header();
		};

		update_sticky_offsets();
		update_sticky_rules();
		if (datatable.cra_last_scroll_left === undefined) {
			datatable.cra_last_scroll_left = datatable.bodyScrollable.scrollLeft;
		}
		$(datatable.bodyScrollable).off("scroll.cra_sticky_columns")
			.on("scroll.cra_sticky_columns", function () {
				var no_data = $(datatable.bodyScrollable).find(".dt-scrollable__no-data");
				if (!no_data.length ||
						datatable.bodyScrollable.scrollWidth > datatable.bodyScrollable.clientWidth) {
					datatable.cra_last_scroll_left = datatable.bodyScrollable.scrollLeft;
				}
				window.requestAnimationFrame(update_sticky_header);
			});
		update_sticky_header();
		refresh_empty_filter_layout();

		var resizing_column = false;
		$(datatable.header).off("mousedown.cra_sticky_resize")
			.on("mousedown.cra_sticky_resize", ".dt-cell__resize-handle", function () {
				resizing_column = true;
			});
		$(document.body).off("mouseup.cra_sticky_resize")
			.on("mouseup.cra_sticky_resize", function () {
				if (!resizing_column) { return; }
				resizing_column = false;
				window.requestAnimationFrame(function () {
					update_sticky_offsets();
					update_sticky_rules();
					refresh_empty_filter_layout();
					update_sticky_header();
				});
			});
		$(datatable.header).off("dblclick.cra_sticky_resize")
			.on("dblclick.cra_sticky_resize", ".dt-cell__resize-handle", function () {
				setTimeout(function () {
					update_sticky_offsets();
					update_sticky_rules();
					refresh_empty_filter_layout();
					update_sticky_header();
				}, 0);
			});

		datatable.cra_refresh_sticky_columns = function () {
			window.requestAnimationFrame(function () {
				update_sticky_offsets();
				update_sticky_rules();
				refresh_empty_filter_layout();
				update_sticky_header();
				queue_selected_row_restore();
			});
		};
		if (!datatable.cra_sticky_events_bound) {
			datatable.cra_sticky_events_bound = true;
			["onSortColumn", "onSwitchColumn", "onRemoveColumn"].forEach(function (event_name) {
				datatable.on(event_name, function () {
					if (datatable.cra_refresh_sticky_columns) {
						datatable.cra_refresh_sticky_columns();
					}
				});
			});
		}
		if (datatable.columnmanager && datatable.columnmanager.sortable) {
			datatable.columnmanager.sortable.option("disabled", true);
		}

		var important_columns = {
			"retention_status": "#f7f5ff",
			"current_sales": "#eef6ff",
			"previous_sales": "#f5f0ff",
			"change_amount": "#fff7e6",
			"change_percent": "#fff7e6",
			"inactive_days": "#fffbe6",
			"top_item_group_1": "#f3fbf7",
			"top_item_group_2": "#f3fbf7",
			"top_item_group_3": "#f3fbf7"
		};
		var important_rules = [];
		(datatable.datamanager.getColumns() || []).forEach(function (column) {
			var fieldname = column.fieldname || column.id;
			if (important_columns[fieldname]) {
				important_rules.push(
					".cra-table .dt-cell--col-" + column.colIndex +
					"{background:" + important_columns[fieldname] + "!important;}"
				);
			}
		});
		var important_style = $("#cra-important-columns-style");
		if (!important_style.length) {
			important_style = $("<style id='cra-important-columns-style'></style>")
				.appendTo("head");
		}
		important_style.text(important_rules.join(""));

		var report_rows = frappe.query_report && frappe.query_report.data || [];
		var item_group_period = report_rows.length && report_rows[0].item_group_sales_period;
		var item_group_heading = __("Ranked by net sales across the selected comparison period");
		if (item_group_period) { item_group_heading += " (" + item_group_period + ")"; }
		["top_item_group_1", "top_item_group_2", "top_item_group_3"].forEach(function (fieldname) {
			var column = get_column(fieldname);
			if (!column) { return; }
			wrapper.find(".dt-row-header .dt-cell--col-" + column.colIndex)
				.addClass("cra-item-group-heading")
				.attr("title", item_group_heading);
		});
	}

	frappe.query_reports["Customer Retention Analysis"] = {
		filters: [
			{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, "default": frappe.defaults.get_user_default("Company")},
			{fieldname: "analysis_year", label: __("Analysis Year"), fieldtype: "Int", reqd: 1, "default": get_current_year()},
			{fieldname: "previous_years", label: __("Previous Years"), fieldtype: "Select", options: "1\n2\n3\n4\n5", "default": 1},
			{fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer"},
			{fieldname: "customer_group", label: __("Customer Group"), fieldtype: "Link", options: "Customer Group"},
			{fieldname: "territory", label: __("Territory"), fieldtype: "Link", options: "Territory"},
			{fieldname: "retention_status", label: __("Retention Status"), fieldtype: "Select", options: "\nLost\nDecreased\nStable\nIncreased\nNew\nReactivated"},
			{fieldname: "minimum_historical_sales", label: __("Minimum Historical Sales"), fieldtype: "Currency", "default": 0},
			{fieldname: "top_results", label: __("Top Results"), fieldtype: "Select", options: "20\n50\n100\n250\nAll", "default": "100"},
			{fieldname: "sort_by", label: __("Sort By"), fieldtype: "Select", options: "Importance\nDecrease Amount\nCurrent Sales\nPrevious Sales\nInactive Days\nCurrent Invoice Count", "default": "Importance"},
			{fieldname: "sort_direction", label: __("Sort Direction"), fieldtype: "Select", options: "Descending\nAscending", "default": "Descending"}
		],
		formatter: function (value, row, column, data, default_formatter) {
			var formatted = default_formatter(value, row, column, data);
			var fieldname = column && column.fieldname;
			if (/^top_item_group_[123]$/.test(fieldname || "") && data) {
				var amount = data[fieldname + "_sales"];
				if (amount !== undefined && amount !== null && value) {
					var period = data.item_group_sales_period || __("Selected Period");
					var tooltip = String(value) + "\n" + __("Net Sales") + " (" + period + "): " +
						format_currency(amount, data.report_currency);
					return "<span class='cra-item-group-tooltip' title=\"" +
						frappe.utils.escape_html(tooltip) + "\">" + formatted + "</span>";
				}
			}
			if (fieldname === "retention_status" && STATUS_COLORS[value]) {
				return "<span class='indicator " + STATUS_COLORS[value] + "'>" +
					frappe.utils.escape_html(String(value)) + "</span>";
			}
			if (fieldname === "change_amount" || fieldname === "change_percent") {
				var numeric_value = parseFloat(value || 0);
				if (numeric_value < 0) { return "<span class='text-danger'>" + formatted + "</span>"; }
				if (numeric_value > 0) { return "<span class='text-success'>" + formatted + "</span>"; }
			}
			return formatted;
		},
		get_chart_data: function (columns, result) {
			return build_decline_chart(columns, result);
		},
		onload: function (report) {
			install_styles();
			update_filter_summary(report);
			update_result_summary(report);
			add_campaign_customer_button(report);
			return restore_prepared_filters(report);
		},
			after_datatable_render: function (datatable) {
			apply_sticky_columns(datatable);
			update_filter_summary(frappe.query_report);
			update_result_summary(frappe.query_report);
		}
	};
}());
