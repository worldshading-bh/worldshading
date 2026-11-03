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
		"summary_value: summary_value, " +
		"get_comparison_year_options: get_comparison_year_options, " +
		"sync_comparison_year_filter: sync_comparison_year_filter, " +
		"restore_prepared_filters: restore_prepared_filters, " +
		"install_refresh_filter_compatibility: install_refresh_filter_compatibility};}());"
);
vm.runInThisContext(source, {filename: script_path});

const report = frappe.query_reports["Customer Retention Analysis"];
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
