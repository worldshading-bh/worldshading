// Copyright (c) 2026, World Shading
// ERPNext/Frappe v12 compatible prepared report client.

(function () {
	"use strict";

	var REPORT_NAME = "Customer Retention Analysis";
	var METHOD = "worldshading.worldshading.report.customer_retention_analysis.customer_retention_analysis.get_prepared_report_filters";
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

	function install_styles() {
		if ($("#cra-static-style").length) { return; }
		$("<style id='cra-static-style'>" +
			".cra-filter-summary{display:flex;flex-wrap:wrap;gap:4px 18px;padding:7px 15px;border-bottom:1px solid #d1d8dd;background:#f8f9fa;font-size:12px;}" +
			".cra-partial-year-notice{margin:8px 15px;padding:8px 12px;border-left:3px solid #f0ad4e;background:#fff8e8;color:#6f5315;font-size:12px;}" +
			".cra-result-summary{display:flex;flex-wrap:wrap;gap:6px 16px;padding:8px 15px;border-bottom:1px solid #d1d8dd;background:#fff;font-size:12px;}" +
			".cra-result-summary .indicator{white-space:nowrap;}" +
			".cra-table .cra-sticky-header{z-index:30!important;background:#f7fafc!important;}" +
			".cra-table .cra-sticky-edge{box-shadow:2px 0 2px rgba(0,0,0,.08);}" +
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

	function update_partial_year_notice(report) {
		if (!report || !report.page) { return; }
		var today = frappe.datetime.get_today();
		var current_year = parseInt(today.slice(0, 4), 10);
		var analysis_year = parseInt(report.get_filter_value("analysis_year"), 10);
		var show = analysis_year === current_year && today < current_year + "-12-31";
		var notice = report.page.main.find(".cra-partial-year-notice");
		if (show && !notice.length) {
			notice = $("<div class='cra-partial-year-notice'></div>")
				.text(__("This is a year-to-date comparison against the complete previous calendar year; sales are not annualized."))
				.insertAfter(report.page.main.find(".cra-filter-summary"));
		}
		if (notice.length) { notice.toggle(show); }
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

	function update_result_summary(report) {
		if (!report || !report.page) { return; }
		var rows = report.data || [];
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
			return "<span class='indicator " + STATUS_COLORS[status] + "'>" +
				frappe.utils.escape_html(__(status)) + ": " + counts[status] + "</span>";
		});
		var formatted_risk = frappe.format(at_risk, {fieldtype: "Currency"});
		parts.push("<span><strong>" + frappe.utils.escape_html(__("At-risk Previous Sales")) +
			":</strong> " + frappe.utils.escape_html(String(formatted_risk)) + "</span>");
		var summary = report.page.main.find(".cra-result-summary");
		if (!summary.length) {
			summary = $("<div class='cra-result-summary'></div>");
			var anchor = report.page.main.find(".cra-partial-year-notice");
			if (!anchor.length) { anchor = report.page.main.find(".cra-filter-summary"); }
			summary.insertAfter(anchor);
		}
		summary.html(parts.join(""));
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
			update_partial_year_notice(report);
		});
	}

	function apply_sticky_columns(datatable) {
		if (!datatable || !datatable.wrapper || !datatable.bodyScrollable) { return; }
		var wrapper = $(datatable.wrapper);
		wrapper.addClass("cra-table");
		var columns = {};
		wrapper.find(".dt-row-header .dt-cell").each(function () {
			var text = $(this).text().trim();
			var column_class = (this.className.match(/dt-cell--col-\d+/) || [])[0];
			if (text === __("Rank")) { columns.rank = column_class; }
			if (text === __("Customer")) { columns.customer = column_class; }
			if (text === __("Customer Name")) { columns.customer_name = column_class; }
		});
		if (!columns.rank || !columns.customer || !columns.customer_name) { return; }

		function width_of(column_class, fallback) {
			var cell = wrapper.find(".dt-row-header ." + column_class)[0];
			return cell ? cell.getBoundingClientRect().width : fallback;
		}

		function refresh_rules() {
			var rank_width = width_of(columns.rank, 65);
			var customer_width = width_of(columns.customer, 140);
			var rules = [
				".cra-table ." + columns.rank + "{position:sticky;left:0;z-index:4;background:#fff;}",
				".cra-table ." + columns.customer + "{position:sticky;left:" + rank_width + "px;z-index:4;background:#fff;}",
				".cra-table ." + columns.customer_name + "{position:sticky;left:" + (rank_width + customer_width) + "px;z-index:4;background:#fff;}"
			];
			$("#cra-dynamic-style").remove();
			$("<style id='cra-dynamic-style'>" + rules.join("") + "</style>").appendTo("head");
		}

		function refresh_header() {
			var scroll_left = datatable.bodyScrollable.scrollLeft;
			wrapper.find(".dt-header ." + columns.rank + ",.dt-header ." + columns.customer + ",.dt-header ." + columns.customer_name)
				.addClass("cra-sticky-header")
				.css("transform", "translateX(" + scroll_left + "px)");
			wrapper.find("." + columns.customer_name).addClass("cra-sticky-edge");
		}

		refresh_rules();
		refresh_header();
		$(datatable.bodyScrollable)
			.off("scroll.cra_sticky_columns")
			.on("scroll.cra_sticky_columns", function () {
				window.requestAnimationFrame(refresh_header);
			});
		$(document.body)
			.off("mouseup.cra_sticky_resize")
			.on("mouseup.cra_sticky_resize", function () {
				window.requestAnimationFrame(function () {
					refresh_rules();
					refresh_header();
				});
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
			update_partial_year_notice(report);
			update_result_summary(report);
			return restore_prepared_filters(report);
		},
		after_datatable_render: function (datatable) {
			apply_sticky_columns(datatable);
			update_filter_summary(frappe.query_report);
			update_partial_year_notice(frappe.query_report);
			update_result_summary(frappe.query_report);
		}
	};
}());
