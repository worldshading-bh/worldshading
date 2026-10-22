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

global.__ = function (value) { return value; };
global.cint = function (value) { return parseInt(value, 10) || 0; };
global.format_currency = function (value, currency) {
	return (currency || "") + " " + Number(value || 0).toFixed(3);
};
global.frappe = {
	query_reports: {},
	datetime: {get_today: function () { return "2026-10-22"; }},
	defaults: {
		get_user_default: function () { return "World Shading"; },
		get_default: function () { return "BHD"; }
	},
	utils: {escape_html: escape_html}
};
global.$ = function () { return {length: 0}; };

const script_path = path.join(__dirname, "customer_retention_analysis.js");
let source = fs.readFileSync(script_path, "utf8");
source = source.replace(
	/\}\(\)\);\s*$/,
	"global.__cra_test = {build_result_summary_html: build_result_summary_html};}());"
);
vm.runInThisContext(source, {filename: script_path});

const report = frappe.query_reports["Customer Retention Analysis"];
const default_formatter = function (value) {
	return "<a>" + escape_html(value) + "</a>";
};

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

console.log("Customer Retention Analysis client tests passed");
