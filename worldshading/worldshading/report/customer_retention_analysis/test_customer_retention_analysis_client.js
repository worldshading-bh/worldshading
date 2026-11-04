const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function escape_html(value) {
	return String(value)
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#39;");
}

global.__ = function (value, replacements) {
	(replacements || []).forEach(function (replacement, index) {
		value = value.replace("{" + index + "}", replacement);
	});
	return value;
};
global.cint = function (value) { return parseInt(value, 10) || 0; };
global.format_currency = function (value, currency) {
	return (currency || "") + " " + Number(value || 0).toFixed(3);
};
let frappe_calls = [];
let link_option_calls = [];
let last_dialog;
let messages = [];
global.frappe = {
	query_reports: {},
	call: function (options) {
		frappe_calls.push(options);
		if (options.method && options.method.indexOf("bulk_create_campaign_customers") !== -1) {
			const response = {message: {created_count: 2, skipped_count: 1}};
			if (options.callback) { options.callback(response); }
			return Promise.resolve(response);
		}
		return Promise.resolve({message: {analysis_year: 2026}});
	},
	datetime: {get_today: function () { return "2026-10-22"; }},
	session: {user: "manager@example.com"},
	defaults: {
		get_user_default: function () { return "World Shading"; },
		get_default: function () { return "BHD"; }
	},
	db: {
		get_link_options: function (doctype, text) {
			link_option_calls.push([doctype, text]);
			return Promise.resolve([
				{value: "PVC 680 GSM", label: "PVC 680 GSM"},
				{value: "Shade Net", label: "Shade Net"}
			]);
		}
	},
	utils: {escape_html: escape_html},
	model: {can_create: function () { return true; }},
	msgprint: function (value) { messages.push(value); },
	ui: {
		Dialog: function (options) {
			this.options = options;
			this.values = {};
			options.fields.forEach((field) => {
				if (field.fieldname) { this.values[field.fieldname] = field.default; }
			});
			this.show = () => { this.shown = true; };
			this.hide = () => { this.hidden = true; };
			last_dialog = this;
		}
	}
};
let dom_elements = {};
let dom_insertions = [];
let created_html = [];

function make_element(selector, length) {
	return {
		selector: selector,
		length: length || 0,
		appendTo: function () { return this; },
		find: function (child_selector) { return make_element(child_selector, 0); },
		html: function () { return this; },
		text: function () { return this; },
		toggle: function () { return this; },
		insertAfter: function (anchor) {
			this.length = 1;
			dom_elements[this.selector] = this;
			dom_insertions.push({selector: this.selector, anchor: anchor.selector});
			return this;
		}
	};
}

global.$ = function (value) {
	if (dom_elements[value]) { return dom_elements[value]; }
	if (typeof value === "string" && value.charAt(0) === "<") {
		created_html.push(value);
		const class_match = value.match(/class=['\"]([^'\"]+)/);
		const selector = class_match ? "." + class_match[1].split(" ")[0] : value;
		return make_element(selector, 1);
	}
	return make_element(value, 0);
};

const script_path = path.join(__dirname, "customer_retention_analysis.js");
let source = fs.readFileSync(script_path, "utf8");
source = source.replace(
	/\}\(\)\);\s*$/,
	"global.__cra_test = {build_result_summary_html: build_result_summary_html, " +
		"update_result_summary: update_result_summary, get_sort_help: get_sort_help, " +
		"apply_sort_help: apply_sort_help, " +
		"install_styles: install_styles, " +
		"summary_value: summary_value, " +
		"get_comparison_year_options: get_comparison_year_options, " +
		"sync_comparison_year_filter: sync_comparison_year_filter, " +
		"restore_prepared_filters: restore_prepared_filters, " +
		"install_refresh_filter_compatibility: install_refresh_filter_compatibility, " +
		"get_column_index: get_column_index, " +
		"can_move_column: can_move_column, " +
		"enable_guarded_column_reordering: enable_guarded_column_reordering, " +
		"get_extra_sticky_fieldnames: get_extra_sticky_fieldnames, " +
		"get_sticky_column_count: get_sticky_column_count, " +
		"align_extra_sticky_columns: align_extra_sticky_columns, " +
		"toggle_sticky_column: toggle_sticky_column, " +
		"protect_permanent_columns: typeof protect_permanent_columns === 'function' " +
			"? protect_permanent_columns : null, " +
		"bind_sticky_observer_cleanup: typeof bind_sticky_observer_cleanup === 'function' " +
			"? bind_sticky_observer_cleanup : null, " +
		"observe_sticky_header_rebuild: typeof observe_sticky_header_rebuild === 'function' " +
			"? observe_sticky_header_rebuild : null};}());"
);
vm.runInThisContext(source, {filename: script_path});

const report = frappe.query_reports["Customer Retention Analysis"];

assert.strictEqual(
	typeof global.__cra_test.observe_sticky_header_rebuild,
	"function",
	"sticky headers must observe Frappe header rebuilds"
);
let disconnected_header_observer = false;
let observed_header = null;
let observed_header_options = null;
let rebuild_refresh_count = 0;
let header_observer_callback = null;
global.MutationObserver = function (callback) {
	header_observer_callback = callback;
	this.observe = function (element, options) {
		observed_header = element;
		observed_header_options = options;
	};
};
const rebuilt_header = {};
const header_datatable = {
	header: rebuilt_header,
	cra_header_rebuild_observer: {
		disconnect: function () { disconnected_header_observer = true; }
	}
};
global.__cra_test.observe_sticky_header_rebuild(header_datatable, function () {
	rebuild_refresh_count += 1;
});
assert.strictEqual(disconnected_header_observer, true);
assert.strictEqual(observed_header, rebuilt_header);
assert.deepStrictEqual(observed_header_options, {childList: true, subtree: true});
header_observer_callback();
assert.strictEqual(rebuild_refresh_count, 1);

assert.strictEqual(
	typeof global.__cra_test.bind_sticky_observer_cleanup,
	"function",
	"sticky observers must be disconnected when DataTable is destroyed"
);
let sticky_destroy_callback = null;
let header_cleanup_count = 0;
let row_cleanup_count = 0;
const cleanup_datatable = {
	on: function (event_name, callback) {
		if (event_name === "onDestroy") { sticky_destroy_callback = callback; }
	},
	cra_header_rebuild_observer: {
		disconnect: function () { header_cleanup_count += 1; }
	},
	cra_row_highlight_observer: {
		disconnect: function () { row_cleanup_count += 1; }
	}
};
global.__cra_test.bind_sticky_observer_cleanup(cleanup_datatable);
global.__cra_test.bind_sticky_observer_cleanup(cleanup_datatable);
assert.strictEqual(typeof sticky_destroy_callback, "function");
sticky_destroy_callback();
assert.strictEqual(header_cleanup_count, 1);
assert.strictEqual(row_cleanup_count, 1);
assert.strictEqual(cleanup_datatable.cra_header_rebuild_observer, null);
assert.strictEqual(cleanup_datatable.cra_row_highlight_observer, null);

global.__cra_test.install_styles();
const static_style_html = created_html.filter(function (html) {
	return html.indexOf("id='cra-static-style'") !== -1;
})[0];
assert(static_style_html);
assert(
	static_style_html.indexOf("isolation:isolate;") !== -1,
	"sticky headers must isolate their stacking context after sort redraws"
);

function make_column_element(index, include_dataset) {
	return {
		className: "dt-cell dt-cell--col-" + index + " dt-cell--header",
		dataset: include_dataset ? {colIndex: String(index)} : {}
	};
}

assert.strictEqual(global.__cra_test.get_column_index(make_column_element(7, true)), 7);
assert.strictEqual(global.__cra_test.get_column_index(make_column_element(8, false)), 8);
assert.strictEqual(global.__cra_test.get_column_index(null), null);
[0, 1, 2].forEach(function (anchored_index) {
	assert.strictEqual(global.__cra_test.can_move_column(anchored_index, 5), false);
	assert.strictEqual(global.__cra_test.can_move_column(5, anchored_index), false);
});
assert.strictEqual(global.__cra_test.can_move_column(4, 7), true);
assert.strictEqual(global.__cra_test.can_move_column(7, 3), true);
assert.strictEqual(global.__cra_test.can_move_column(null, 5), false);
assert.doesNotThrow(function () {
	global.__cra_test.enable_guarded_column_reordering({});
});

const sortable_options = {};
const sortable = {
	option: function (name, value) {
		sortable_options[name] = value;
	}
};
global.__cra_test.enable_guarded_column_reordering({
	columnmanager: {sortable: sortable}
});
assert.strictEqual(sortable_options.disabled, false);
assert.strictEqual(
	sortable_options.filter,
	".dt-cell__resize-handle, .dt-dropdown, .cra-sticky-header"
);
assert.strictEqual(sortable_options.preventOnFilter, false);
assert.strictEqual(typeof sortable_options.onMove, "function");
assert.strictEqual(sortable_options.onMove({
	dragged: make_column_element(2, true),
	related: make_column_element(5, true)
}), false);
assert.strictEqual(sortable_options.onMove({
	dragged: make_column_element(5, true),
	related: make_column_element(1, true)
}), false);
assert.strictEqual(sortable_options.onMove({
	dragged: make_column_element(5, true),
	related: make_column_element(8, true)
}), true);

function make_sticky_datatable(fieldnames) {
	const columns = fieldnames.map(function (fieldname, index) {
		return {fieldname: fieldname, id: fieldname, colIndex: index};
	});
	const switches = [];
	const datatable = {
		datamanager: {
			getColumns: function () { return columns; }
		},
		columnmanager: {
			switchColumn: function (old_index, new_index) {
				switches.push([old_index, new_index]);
				const old_column = columns[old_index];
				columns[old_index] = columns[new_index];
				columns[new_index] = old_column;
				columns[old_index].colIndex = old_index;
				columns[new_index].colIndex = new_index;
			}
		}
	};
	datatable.columns = columns;
	datatable.switches = switches;
	return datatable;
}

const sticky_datatable = make_sticky_datatable([
	"_rowIndex", "customer", "customer_name", "customer_group",
	"territory", "current_sales", "previous_sales"
]);
assert.deepStrictEqual(
	global.__cra_test.get_extra_sticky_fieldnames(sticky_datatable), []
);
assert.strictEqual(global.__cra_test.get_sticky_column_count(sticky_datatable), 3);
global.__cra_test.toggle_sticky_column(sticky_datatable, sticky_datatable.columns[5]);
assert.deepStrictEqual(sticky_datatable.cra_extra_sticky_fieldnames, ["current_sales"]);
assert.deepStrictEqual(sticky_datatable.switches, [[5, 3]]);
sticky_datatable.cra_sticky_alignment_pending = false;
assert.strictEqual(global.__cra_test.align_extra_sticky_columns(sticky_datatable), true);
global.__cra_test.toggle_sticky_column(sticky_datatable, sticky_datatable.columns[4]);
assert.deepStrictEqual(
	sticky_datatable.cra_extra_sticky_fieldnames,
	["current_sales", "territory"]
);
assert.strictEqual(global.__cra_test.get_sticky_column_count(sticky_datatable), 5);
assert.strictEqual(sticky_datatable.columns[3].fieldname, "current_sales");
assert.strictEqual(sticky_datatable.columns[4].fieldname, "territory");
global.__cra_test.toggle_sticky_column(sticky_datatable, sticky_datatable.columns[3]);
assert.deepStrictEqual(sticky_datatable.cra_extra_sticky_fieldnames, ["territory"]);
assert.deepStrictEqual(sticky_datatable.switches, [[5, 3], [4, 3]]);
sticky_datatable.cra_sticky_alignment_pending = false;
assert.strictEqual(global.__cra_test.align_extra_sticky_columns(sticky_datatable), true);
assert.strictEqual(sticky_datatable.columns[3].fieldname, "territory");

const identity_datatable = make_sticky_datatable([
	"_rowIndex", "customer", "customer_name", "territory"
]);
global.__cra_test.toggle_sticky_column(identity_datatable, identity_datatable.columns[1]);
assert.deepStrictEqual(identity_datatable.cra_extra_sticky_fieldnames, []);
assert.deepStrictEqual(identity_datatable.switches, []);

assert.strictEqual(
	typeof global.__cra_test.protect_permanent_columns,
	"function",
	"permanent identity columns must have a removal guard"
);
const protected_datatable = make_sticky_datatable([
	"_rowIndex", "customer", "customer_name", "territory"
]);
const removed_column_indexes = [];
protected_datatable.removeColumn = function (index) {
	removed_column_indexes.push(index);
	return "removed";
};
global.__cra_test.protect_permanent_columns(protected_datatable);
const message_count_before_protected_removal = messages.length;
assert.strictEqual(protected_datatable.removeColumn(0), undefined);
assert.strictEqual(protected_datatable.removeColumn(1), undefined);
assert.strictEqual(protected_datatable.removeColumn(2), undefined);
assert.deepStrictEqual(removed_column_indexes, []);
assert.strictEqual(messages.length, message_count_before_protected_removal + 2);
assert.strictEqual(protected_datatable.removeColumn(3), "removed");
assert.deepStrictEqual(removed_column_indexes, [3]);
global.__cra_test.protect_permanent_columns(protected_datatable);
assert.strictEqual(protected_datatable.removeColumn(3), "removed");
assert.deepStrictEqual(removed_column_indexes, [3, 3]);

const rebuilt_datatable = make_sticky_datatable([
	"_rowIndex", "customer", "customer_name", "territory",
	"sales_2025", "current_sales"
]);
rebuilt_datatable.cra_extra_sticky_fieldnames = ["current_sales", "missing_field"];
assert.strictEqual(global.__cra_test.align_extra_sticky_columns(rebuilt_datatable), false);
assert.deepStrictEqual(rebuilt_datatable.cra_extra_sticky_fieldnames, ["current_sales"]);
assert.deepStrictEqual(rebuilt_datatable.switches, [[5, 3]]);
rebuilt_datatable.cra_sticky_alignment_pending = false;
assert.strictEqual(global.__cra_test.align_extra_sticky_columns(rebuilt_datatable), true);
assert.strictEqual(rebuilt_datatable.columns[3].fieldname, "current_sales");

assert.strictEqual(global.__cra_test.can_move_column(4, 7, 5), false);
assert.strictEqual(global.__cra_test.can_move_column(7, 4, 5), false);
assert.strictEqual(global.__cra_test.can_move_column(5, 7, 5), true);

assert.strictEqual(typeof report.get_datatable_options, "function");
const native_header_dropdown = [
	{
		label: "Sort Ascending",
		action: function (column) { this.sortColumn(column.colIndex, "asc"); }
	},
	{
		label: "Sort Descending",
		action: function (column) { this.sortColumn(column.colIndex, "desc"); }
	},
	{
		label: "Reset sorting",
		action: function (column) { this.sortColumn(column.colIndex, "none"); }
	},
	{
		label: "Remove column",
		action: function (column) { this.removeColumn(column.colIndex); }
	}
];
const menu_options = report.get_datatable_options({});
const final_header_dropdown = native_header_dropdown.concat(menu_options.headerDropdown || []);
assert.deepStrictEqual(final_header_dropdown.map(function (item) {
	return item.label;
}), [
	"Sort Ascending", "Sort Descending", "Reset sorting", "Remove column",
	"Pin / Unpin Column"
]);
const menu_calls = [];
const menu_datatable = make_sticky_datatable([
	"_rowIndex", "customer", "customer_name", "territory"
]);
menu_datatable.sortColumn = function (index, direction) {
	menu_calls.push(["sort", index, direction]);
};
menu_datatable.removeColumn = function (index) {
	menu_calls.push(["remove", index]);
};
final_header_dropdown.slice(0, 4).forEach(function (item) {
	item.action.call(menu_datatable, menu_datatable.columns[3]);
});
assert.deepStrictEqual(menu_calls, [
	["sort", 3, "asc"], ["sort", 3, "desc"], ["sort", 3, "none"], ["remove", 3]
]);
final_header_dropdown[4].action.call(menu_datatable, menu_datatable.columns[3]);
assert.deepStrictEqual(menu_datatable.cra_extra_sticky_fieldnames, ["territory"]);

assert.deepStrictEqual(
	global.__cra_test.get_comparison_year_options(2026),
	[2025, 2024, 2023, 2022, 2021]
);
const filter_definitions = {};
report.filters.forEach(function (filter) { filter_definitions[filter.fieldname] = filter; });
assert.strictEqual(filter_definitions.item_group.fieldtype, "MultiSelectList");
assert.strictEqual(filter_definitions.item_group.options, "Item Group");
assert.strictEqual(typeof filter_definitions.item_group.get_data, "function");
const item_group_options_promise = filter_definitions.item_group.get_data("PVC").then(function (options) {
	assert.deepStrictEqual(link_option_calls, [["Item Group", "PVC"]]);
	assert.strictEqual(options[0].value, "PVC 680 GSM");
});
assert(filter_definitions.customer_type);
assert.strictEqual(filter_definitions.customer_type.fieldtype, "Select");
assert.strictEqual(filter_definitions.customer_type.options, "All\nCompany\nIndividual");
assert.strictEqual(filter_definitions.customer_type.default, "All");
assert.strictEqual(filter_definitions.comparison_year.fieldtype, "Select");
assert.strictEqual(filter_definitions.comparison_year.reqd, 1);
assert(filter_definitions.sort_by.options.indexOf("Comparison Sales") !== -1);
assert(filter_definitions.sort_by.options.indexOf("Previous Sales") === -1);
assert.strictEqual(global.__cra_test.summary_value({
	get_filter_value: function () { return ["PVC 680 GSM", "Shade Net"]; }
}, "item_group"), "PVC 680 GSM, Shade Net");

function make_comparison_report(analysis_year, comparison_year) {
	let current_analysis_year = analysis_year;
	let current_comparison_year = comparison_year;
	const comparison_filter = {
		df: {fieldname: "comparison_year", options: ""},
		get_value: function () { return current_comparison_year; },
		set_input: function (value) { current_comparison_year = value; },
		refresh: function () { this.refresh_count = (this.refresh_count || 0) + 1; }
	};
	return {
		comparison_filter: comparison_filter,
		get_filter_value: function (fieldname) {
			return fieldname === "analysis_year" ? current_analysis_year : current_comparison_year;
		},
		get_filter: function (fieldname) {
			return fieldname === "comparison_year" ? comparison_filter : null;
		},
		set_analysis_year: function (value) { current_analysis_year = value; }
	};
}

const dynamic_report = make_comparison_report(2026, 2024);
dynamic_report.refresh = function () { this.refresh_count = (this.refresh_count || 0) + 1; };
global.__cra_test.sync_comparison_year_filter(dynamic_report);
assert.strictEqual(
	dynamic_report.comparison_filter.df.options,
	"2025\n2024\n2023\n2022\n2021"
);
assert.strictEqual(dynamic_report.get_filter_value("comparison_year"), 2024);
dynamic_report.set_analysis_year(2024);
filter_definitions.analysis_year.on_change(dynamic_report);
assert.strictEqual(
	dynamic_report.comparison_filter.df.options,
	"2023\n2022\n2021\n2020\n2019"
);
assert.strictEqual(dynamic_report.get_filter_value("comparison_year"), 2023);
assert.strictEqual(dynamic_report.refresh_count, 1);

const default_formatter = function (value) {
	return "<a>" + escape_html(value) + "</a>";
};

[
	{fieldname: "current_sales", year: 2026},
	{fieldname: "previous_sales", year: 2021},
	{fieldname: "sales_2024", year: 2024}
].forEach(function (example) {
	const data = {
		selected_item_group: "PVC 680 GSM",
		analysis_year: 2026,
		comparison_year: 2021,
		report_currency: "BHD"
	};
	data["overall_sales_" + example.year] = 100;
	const sales_tooltip = report.formatter(
		25,
		null,
		{fieldname: example.fieldname},
		data,
		default_formatter
	);
	assert(sales_tooltip.indexOf("cra-sales-scope-tooltip") !== -1);
	assert(sales_tooltip.indexOf("PVC 680 GSM Sales (" + example.year + "): BHD 25.000") !== -1);
	assert(sales_tooltip.indexOf("Total Customer Sales (" + example.year + "): BHD 100.000") !== -1);
	assert(sales_tooltip.indexOf("Share of Total: 25.0%") !== -1);
});

const unfiltered_sales = report.formatter(
	25,
	null,
	{fieldname: "current_sales"},
	{analysis_year: 2026, overall_sales_2026: 100, report_currency: "BHD"},
	default_formatter
);
assert.strictEqual(unfiltered_sales, "<a>25</a>");

const combined_sales_tooltip = report.formatter(
	25,
	null,
	{fieldname: "current_sales"},
	{
		selected_item_groups: ["PVC 680 GSM", "Shade Net", "No Sales Group"],
		selected_item_group_sales: {
			"2026": [
				{item_group: "PVC 680 GSM", sales: 20},
				{item_group: "Shade Net", sales: 5},
				{item_group: "No Sales Group", sales: 0}
			]
		},
		analysis_year: 2026,
		overall_sales_2026: 100,
		report_currency: "BHD"
	},
	default_formatter
);
assert(combined_sales_tooltip.indexOf("PVC 680 GSM: BHD 20.000") !== -1);
assert(combined_sales_tooltip.indexOf("Shade Net: BHD 5.000") !== -1);
assert(combined_sales_tooltip.indexOf("No Sales Group: BHD 0.000") !== -1);
assert(combined_sales_tooltip.indexOf("Selected Groups Total (2026): BHD 25.000") !== -1);
assert(combined_sales_tooltip.indexOf("Total Customer Sales (2026): BHD 100.000") !== -1);
assert(combined_sales_tooltip.indexOf("Combined Share of Total: 25.0%") !== -1);

const tooltip = report.formatter(
	"Outdoor & Shade",
	null,
	{fieldname: "top_item_group_1"},
	{
		top_item_group_1_sales: 4250.75,
		item_group_sales_period: "2023\u20132026",
		report_currency: "BHD"
	},
	default_formatter
);
assert(tooltip.indexOf("cra-item-group-tooltip") !== -1);
assert(tooltip.indexOf("Outdoor &amp; Shade") !== -1);
assert(tooltip.indexOf("Net Sales (2023\u20132026): BHD 4250.750") !== -1);

const no_amount = report.formatter(
	"Outdoor",
	null,
	{fieldname: "top_item_group_1"},
	{top_item_group_1_sales: null},
	default_formatter
);
assert.strictEqual(no_amount, "<a>Outdoor</a>");

const summary = global.__cra_test.build_result_summary_html([
	{retention_status: "Decreased", previous_sales: 100, report_currency: "BHD"},
	{retention_status: "Stable", previous_sales: 50, report_currency: "BHD"}
]);
assert(summary.indexOf("cra-summary-chip") !== -1);
assert(summary.indexOf("BHD 100.000") !== -1);
assert(summary.indexOf("&lt;div") === -1);

let selected_sort = "Importance";
let input_native_title = null;
let wrapper_native_title = null;
let wrapper_tooltip = "Sort By";
let sort_change_handler = null;
const sort_filter = {
	get_value: function () { return selected_sort; },
	$input: {
		attr: function (name, value) {
			if (name === "title") { input_native_title = value; }
			return this;
		},
		removeAttr: function (name) {
			if (name === "title") { input_native_title = null; }
			return this;
		},
		off: function () { return this; },
		on: function (name, handler) {
			if (name === "change.cra_sort_help") { sort_change_handler = handler; }
			return this;
		}
	},
	$wrapper: {
		attr: function (name, value) {
			if (name === "title") { wrapper_native_title = value; }
			if (name === "data-original-title") { wrapper_tooltip = value; }
			return this;
		},
		removeAttr: function (name) {
			if (name === "title") { wrapper_native_title = null; }
			return this;
		},
		addClass: function () { return this; }
	}
};
global.__cra_test.apply_sort_help({
	get_filter: function () { return sort_filter; }
});
assert(wrapper_tooltip.indexOf("0–100") !== -1);
assert(wrapper_tooltip.indexOf("45% average historical sales rank") !== -1);
assert(wrapper_tooltip.indexOf("45% decrease amount rank") !== -1);
assert(wrapper_tooltip.indexOf("10% inactive days rank") !== -1);
assert(wrapper_tooltip.indexOf("45% average historical sales rank") !== -1);
assert.strictEqual(input_native_title, null);
assert.strictEqual(wrapper_native_title, null);
assert.strictEqual(typeof sort_change_handler, "function");

selected_sort = "Decrease Amount";
sort_change_handler();
assert(wrapper_tooltip.indexOf("comparison-year sales minus analysis-year sales") !== -1);
assert.strictEqual(input_native_title, null);
assert.strictEqual(wrapper_native_title, null);

selected_sort = "Comparison Sales";
sort_change_handler();
assert(wrapper_tooltip.indexOf("selected comparison year") !== -1);

function reset_dom() {
	dom_elements = {};
	dom_insertions = [];
}

function make_report(prepared) {
	const result = {
		data: [],
		filters: [{
			df: {fieldname: "analysis_year"},
			set_input: function () {}
		}],
		page: {
			main: {find: global.$},
			buttons: [],
			add_inner_button: function (label, action) {
				this.buttons.push({label: label, action: action});
			}
		},
		get_filter_value: function (fieldname) {
			return fieldname === "analysis_year" ? 2026 : "";
		},
		get_query_params: function () {
			return prepared ? {prepared_report_name: "PREP-1"} : {};
		},
		refresh: function () { this.refresh_count = (this.refresh_count || 0) + 1; }
	};
	return result;
}

const prepared_values = {
	analysis_year: 2024,
	comparison_year: 2021,
	item_group: "PVC 680 GSM",
	sort_by: "Previous Sales"
};
const prepared_order = [];
const prepared_filter_values = {
	analysis_year: 2026, comparison_year: 2025, item_group: "", sort_by: "Importance"
};
const prepared_filters = ["analysis_year", "comparison_year", "item_group", "sort_by"].map(function (fieldname) {
	return {
		df: {fieldname: fieldname, options: ""},
		get_value: function () { return prepared_filter_values[fieldname]; },
		set_input: function (value) {
			prepared_order.push(fieldname + ":" + value);
			prepared_filter_values[fieldname] = value;
		},
		set_value: function (value) {
			prepared_order.push(fieldname + "_value:" + JSON.stringify(value));
			prepared_filter_values[fieldname] = value;
			return Promise.resolve();
		},
		refresh: function () {
			if (fieldname === "comparison_year") {
				prepared_order.push("comparison_options:" + this.df.options.replace(/\n/g, ","));
			}
		}
	};
});
const prepared_restore_report = {
	filters: prepared_filters,
	page: {main: {find: global.$}},
	get_query_params: function () { return {prepared_report_name: "PREP-ORDERED"}; },
	get_filter: function (fieldname) {
		return prepared_filters.filter(function (filter) {
			return filter.df.fieldname === fieldname;
		})[0];
	},
	get_filter_value: function (fieldname) { return prepared_filter_values[fieldname]; }
};

let core_sort_value = "Comparison Sales";
const core_sort_filter = {
	value: "Comparison Sales",
	get_value: function () {
		return this.value === "Previous Sales" ? "" : this.value;
	},
	set_input: function (value) {
		this.value = value;
		core_sort_value = value;
	}
};
const core_restore_report = {
	get_filter: function (fieldname) {
		return fieldname === "sort_by" ? core_sort_filter : null;
	},
	refresh: function () {
		core_sort_filter.set_input("Previous Sales");
		return Promise.resolve("core-result");
	}
};
global.__cra_test.install_refresh_filter_compatibility(core_restore_report);

function assert_clean_layout() {
	assert.strictEqual(dom_elements[".cra-partial-year-notice"], undefined);
	const summary_insertion = dom_insertions.filter(function (entry) {
		return entry.selector === ".cra-result-summary";
	})[0];
	assert(summary_insertion);
	assert.strictEqual(summary_insertion.anchor, ".cra-filter-summary");
}

reset_dom();
item_group_options_promise.then(function () {
	return core_restore_report.refresh();
}).then(function (result) {
	assert.strictEqual(result, "core-result");
	assert.strictEqual(core_sort_value, "Comparison Sales");
	return report.onload(make_report(false));
}).then(function () {
	assert_clean_layout();
	reset_dom();
	frappe.call = function () { return Promise.resolve({message: prepared_values}); };
	return global.__cra_test.restore_prepared_filters(prepared_restore_report);
}).then(function () {
	assert.deepStrictEqual(prepared_order.slice(0, 3), [
		"analysis_year:2024",
		"comparison_options:2023,2022,2021,2020,2019",
		"comparison_year:2021"
	]);
	assert.deepStrictEqual(prepared_filter_values.item_group, ["PVC 680 GSM"]);
	assert(prepared_order.indexOf('item_group_value:["PVC 680 GSM"]') !== -1);
	assert.strictEqual(prepared_filter_values.sort_by, "Comparison Sales");
	frappe.call = function (options) {
		frappe_calls.push(options);
		if (options.method && options.method.indexOf("bulk_create_campaign_customers") !== -1) {
			const response = {message: {created_count: 2, skipped_count: 1}};
			if (options.callback) { options.callback(response); }
			return Promise.resolve(response);
		}
		return Promise.resolve({message: {analysis_year: 2026}});
	};
	reset_dom();
	return report.onload(make_report(true));
}).then(function () {
	assert_clean_layout();

	const empty_report = make_report(false);
	frappe_calls = [];
	messages = [];
	last_dialog = null;
	return report.onload(empty_report).then(function () {
		assert.strictEqual(empty_report.page.buttons.length, 1);
		assert.strictEqual(empty_report.page.buttons[0].label, "Create Campaign Customers");
		empty_report.page.buttons[0].action();
		assert.strictEqual(last_dialog, null);
		assert.strictEqual(frappe_calls.length, 0);
		assert.strictEqual(messages[messages.length - 1], "There are no displayed customers to add.");

		const populated_report = make_report(false);
		populated_report.data = [
			{customer: "CUST-0001"},
			{customer: "CUST-0002"},
			{customer: "CUST-0001"},
			{customer: ""},
			{customer: "CUST-0003"}
		];
		frappe_calls = [];
		messages = [];
		return report.onload(populated_report).then(function () {
			assert.strictEqual(populated_report.page.buttons.length, 1);
			populated_report.page.buttons[0].action();
			assert.ok(last_dialog.shown);
			assert.deepStrictEqual(
				last_dialog.options.fields.filter((field) => field.fieldname).map((field) => field.fieldname),
				["source_count", "campaign", "caller", "planned_contact_date", "priority", "batch_size"]
			);
			assert.strictEqual(last_dialog.values.source_count, 3);
			assert.strictEqual(last_dialog.values.caller, "manager@example.com");
			assert.strictEqual(last_dialog.values.planned_contact_date, "2026-10-22");

			last_dialog.options.primary_action({
				campaign: "SPRINT-2026",
				caller: "cashier@example.com",
				planned_contact_date: "2026-10-25",
				priority: "Standard",
				batch_size: 2
			});
			assert.strictEqual(frappe_calls.length, 1);
			assert.strictEqual(
				frappe_calls[0].method,
				"worldshading.worldshading.doctype.campaign_customer.campaign_customer." +
					"bulk_create_campaign_customers"
			);
			assert.deepStrictEqual(frappe_calls[0].args, {
				campaign: "SPRINT-2026",
				customers: ["CUST-0001", "CUST-0002", "CUST-0003"],
				caller: "cashier@example.com",
				planned_contact_date: "2026-10-25",
				priority: "Standard",
				batch_size: 2
			});
			assert.ok(last_dialog.hidden);
			assert.strictEqual(populated_report.refresh_count, 1);
			assert(messages[messages.length - 1].message.indexOf("Created: 2") !== -1);
			assert(messages[messages.length - 1].message.indexOf("Already in Campaign: 1") !== -1);

			const unauthorized_report = make_report(false);
			frappe.model.can_create = function () { return false; };
			return report.onload(unauthorized_report).then(function () {
				assert.strictEqual(unauthorized_report.page.buttons.length, 0);
				frappe.model.can_create = function () { return true; };
			});
		});
	});
}).then(function () {
	console.log("Customer Retention Analysis client tests passed");
}).catch(function (error) {
	console.error(error.stack || error);
	process.exitCode = 1;
});
