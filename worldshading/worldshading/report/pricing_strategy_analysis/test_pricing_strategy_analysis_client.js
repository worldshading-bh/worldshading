const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.__ = function (value, args) {
	(args || []).forEach(function (arg, index) {
		value = value.replace("{" + index + "}", arg);
	});
	return value;
};
global.flt = function (value) { return Number(value || 0); };
global.format_currency = function (value) { return String(value); };
global.$ = function () { throw new Error("DOM access is not expected in tooltip text tests"); };
global.frappe = {
	query_reports: {},
	msgprint: function () {},
	defaults: {get_user_default: function () { return null; }},
	datetime: {
		get_today: function () { return "2026-09-26"; },
		add_months: function () { return "2025-09-26"; }
	},
	utils: {escape_html: function (value) { return value; }}
};

const implementationPath = __dirname + "/pricing_strategy_analysis.js";
const implementationSource = fs.readFileSync(implementationPath, "utf8");
vm.runInThisContext(implementationSource, {
	filename: "pricing_strategy_analysis.js"
});

assert.ok(
	implementationSource.indexOf('label: __("Mixed Conditions")') !== -1,
	"the Pricing Rule option must use ERPNext's native Mixed Conditions name"
);
assert.strictEqual(
	implementationSource.indexOf('label: __("Combine quantities across selected Items")'),
	-1,
	"the old custom Mixed Conditions label must not remain"
);

assert.strictEqual(
	get_pricing_strategy_header_tooltip("average_actual_markup_percent"),
	"Simple average of the Actual Markup % for Regular, B2B and all quantity prices."
);
assert.strictEqual(
	get_pricing_strategy_header_tooltip("average_gross_margin_percent"),
	"Simple average of the Gross Margin % for Regular, B2B and all quantity prices."
);
assert.strictEqual(
	get_pricing_strategy_header_tooltip("average_discount_percent"),
	"Simple average of the B2B and quantity-price discounts."
);
assert.strictEqual(
	get_pricing_strategy_header_tooltip("sales_contribution_percent"),
	"This Item's Sales Qty as a percentage of the total Sales Qty of its Pricing Group. Group members total 100%."
);
assert.strictEqual(
	get_pricing_strategy_header_tooltip("tier_2_actual_markup_percent"),
	"Profit added on top of the item cost. Formula: (Net Price - Cost) / Cost."
);
assert.strictEqual(
	get_pricing_strategy_header_tooltip("tier_3_discount_percent"),
	"How much lower this price is than its reference price."
);
assert.strictEqual(
	get_pricing_strategy_header_tooltip("recommended_regular_gross_margin_percent"),
	"The part of the net selling price that remains as profit after covering the item cost. Formula: (Net Price - Cost) / Net Price."
);
assert.strictEqual(
	get_pricing_strategy_header_tooltip("item_code"),
	"",
	"obvious identity columns should not have unnecessary tooltips"
);

assert.strictEqual(
	get_base_cost_tooltip({
		cost_source_detail: "Latest Valuation Rate", selected_base_cost: 75.475
	}),
	"Cost basis: Latest Valuation Rate. Base cost: 75.475"
);
assert.strictEqual(
	get_expense_per_unit_tooltip({
		expense_source: "Actual period COGS",
		company_expense_total: 200,
		company_net_cogs: 1000,
		company_expense_ratio: 0.2,
		net_cogs: 300,
		allocated_expense: 60,
		sales_qty: 10,
		expense_per_unit: 6
	}),
	"Total Net Expense: 200\n" +
	"Total Company Net COGS: 1000\n" +
	"Company Expense Ratio: 20.000%\n" +
	"Expense allocation basis: Actual period COGS\n" +
	"Item Net COGS: 300\n" +
	"Allocated Expense: 60\n" +
	"Sales Quantity: 10\n" +
	"Expense / Unit: 60 / 10 = 6"
);
assert.strictEqual(
	get_recommended_price_tooltip("recommended_regular_net", {
		recommended_regular_gross: 119
	}),
	"Price including VAT: 119"
);
assert.strictEqual(
	get_recommended_price_tooltip("tier_2_net", {tier_2_gross: 108}),
	"Price including VAT: 108"
);
assert.strictEqual(
	get_recommended_price_tooltip("current_normal_price", {current_normal_gross: 65}),
	"Price including VAT: 65\nCurrent Item Price in the Regular Price List."
);
assert.strictEqual(
	get_recommended_price_tooltip("current_b2b_price", {current_b2b_gross: 60}),
	"Price including VAT: 60\nCurrent Item Price in the B2B Price List."
);
assert.strictEqual(
	get_pricing_group_summary_tooltip("recommended_b2b_net", {
		is_pricing_group_summary: 1,
		group_reference_item_code: "KSA0002",
		group_selection_reason: "Highest Sales Qty",
		group_reference_sales_qty: 80,
		group_reference_sales_contribution_percent: 80,
		recommended_b2b_gross: 60.5
	}),
	"Price including VAT: 60.5\nShared group price follows KSA0002 because it has the highest Sales Qty among Items with valid pricing. Sales Qty: 80; group contribution: 80%."
);
assert.strictEqual(get_pricing_group_summary_tooltip("recommended_regular_net", {
	item_code: "KSA0001"
}), "");
assert.deepStrictEqual(
	get_pricing_group_reference_row_indexes([
		{item_code: "A"},
		{item_code: "B", pricing_group: "Colours", is_pricing_group_reference: 1},
		{item_code: "", is_pricing_group_summary: 1}
	]),
	[1],
	"only the selected Pricing Group source Item row must be highlighted"
);
assert.strictEqual(
	should_blank_pricing_group_summary_field("sales_contribution_percent", {
		is_pricing_group_summary: 1
	}),
	true,
	"blank summary percentages must not be formatted as 0%"
);
assert.strictEqual(
	should_blank_pricing_group_summary_field("recommended_regular_net", {
		is_pricing_group_summary: 1
	}),
	false,
	"recommended Net prices must remain visible on the summary row"
);
assert.deepStrictEqual(
	get_pricing_strategy_sticky_column_config(),
	[
		{index: 0, offset_variable: null, fallback_width: 50},
		{index: 1, offset_variable: "--psa-row-index-width", fallback_width: 130}
	],
	"only row number and Item Code must be sticky"
);
assert.strictEqual(
	get_pricing_group_summary_label("item_code", {
		is_pricing_group_summary: 1, group_summary_label: "Group Strategy Price"
	}),
	"Group Strategy Price"
);

assert.strictEqual(
	get_pricing_group_status_tooltip({pricing_group_status: "Ready"}),
	"All active group Items are present and have valid recommendations."
);
assert.strictEqual(
	get_pricing_group_status_tooltip({pricing_group_status: "Different Current Prices"}),
	"Group Items currently have different prices and can be aligned to one shared price."
);
assert.strictEqual(
	get_pricing_group_status_tooltip({pricing_group_status: "Incomplete Group"}),
	"One or more active group Items are missing from this Prepared Report."
);
assert.strictEqual(
	get_pricing_group_status_tooltip({pricing_group_status: "Missing Cost"}),
	"One or more group Items cannot produce every required recommended price."
);
assert.strictEqual(
	get_pricing_group_status_tooltip({pricing_group_status: "Disabled Group"}),
	"This Pricing Group is disabled and cannot be updated."
);

assert.deepStrictEqual(
	get_pricing_strategy_simple_view_fields([
		{fieldname: "item_code"},
		{fieldname: "pricing_group"},
		{fieldname: "stock_uom"},
		{fieldname: "selected_base_cost"},
		{fieldname: "expense_per_unit"},
		{fieldname: "fully_loaded_cost"},
		{fieldname: "sales_contribution_percent"},
		{fieldname: "current_normal_price"},
		{fieldname: "recommended_regular_net"},
		{fieldname: "recommended_regular_gross"},
		{fieldname: "current_b2b_price"},
		{fieldname: "recommended_b2b_net"},
		{fieldname: "tier_1_net"},
		{fieldname: "tier_1_gross_margin_percent"},
		{fieldname: "warnings"}
	]),
	[
		"item_code", "pricing_group", "stock_uom", "selected_base_cost",
		"expense_per_unit", "fully_loaded_cost", "sales_contribution_percent",
		"current_normal_price", "recommended_regular_net", "current_b2b_price",
		"recommended_b2b_net", "tier_1_net"
	],
	"simple view must retain identity, cost context and strategy net prices"
);

const reportFilterOrder = frappe.query_reports["Pricing Strategy Analysis"].filters.map(function (field) {
	return field.fieldname;
});
assert.deepStrictEqual(
	reportFilterOrder.filter(function (fieldname) {
		return [
			"pricing_group", "company", "pricing_strategy", "from_date", "to_date",
			"purchase_receipt", "item_group", "item", "stock_uom", "brand", "warehouse",
			"cost_source"
		].indexOf(fieldname) !== -1;
	}),
	[
		"pricing_group", "company", "pricing_strategy", "from_date", "to_date",
		"purchase_receipt", "item_group", "item", "stock_uom", "brand", "warehouse",
		"cost_source"
	],
	"visible report filters must follow the approved three-row layout"
);
assert.ok(reportFilterOrder.indexOf("pricing_group") < reportFilterOrder.indexOf("item_group"));
assert.ok(reportFilterOrder.indexOf("pricing_group") < reportFilterOrder.indexOf("item"));
assert.strictEqual(is_pricing_strategy_highlighted_filter("pricing_group"), true);
assert.strictEqual(is_pricing_strategy_highlighted_filter("item_group"), false);
assert.strictEqual(is_pricing_strategy_key_price_field("recommended_regular_net"), true);
assert.strictEqual(is_pricing_strategy_key_price_field("recommended_b2b_net"), true);
assert.strictEqual(is_pricing_strategy_key_price_field("tier_1_net"), true);
assert.strictEqual(is_pricing_strategy_key_price_field("tier_4_net"), true);
assert.strictEqual(is_pricing_strategy_key_price_field("current_normal_price"), false);
assert.strictEqual(is_pricing_strategy_key_price_field("tier_1_gross_margin_percent"), false);
assert.ok(
	implementationSource.indexOf("color:#000 !important;") !== -1,
	"key strategy-price headers must use black text"
);
const pricingGroupFilter = frappe.query_reports["Pricing Strategy Analysis"].filters.filter(function (field) {
	return field.fieldname === "pricing_group";
})[0];
assert.strictEqual(pricingGroupFilter.options, "Pricing Group");

const pricingRulePreviewFields = get_pricing_rule_item_preview_fields(4);
assert.deepStrictEqual(
	pricingRulePreviewFields.map(function (field) { return field.fieldname; }),
	[
		"item_code", "item_name", "pricing_group", "tier_1_discount_percent",
		"tier_2_discount_percent", "tier_3_discount_percent", "tier_4_discount_percent"
	],
	"the item preview must include every configured tier"
);
assert.deepStrictEqual(
	get_remaining_pricing_rule_item_codes([
		{item_code: "GP0001"}, {item_code: ""}, {item_code: "GP0003"}
	]),
	["GP0001", "GP0003"],
	"all rows remaining after native grid deletion must be included"
);
assert.deepStrictEqual(
	get_incomplete_pricing_rule_groups([
		{item_code: "A", group_key: "Colours"},
		{item_code: "B", group_key: "Colours"}
	], [{item_code: "A", group_key: "Colours"}]),
	["Colours"],
	"Pricing Rule preview must reject partial Pricing Groups"
);
assert.deepStrictEqual(
	get_remaining_item_price_keys([
		{item_code: "GP0001", price_list: "Regular Price"},
		{item_code: "GP0001", price_list: "B2B Price"}
	]),
	["GP0001|Regular Price", "GP0001|B2B Price"],
	"Item Price execution must receive only rows remaining in the preview"
);
assert.deepStrictEqual(
	get_incomplete_item_price_groups([
		{item_code: "A", price_list: "Regular", group_key: "Colours"},
		{item_code: "B", price_list: "Regular", group_key: "Colours"}
	], [
		{item_code: "A", price_list: "Regular", group_key: "Colours"}
	]),
	["Colours"],
	"partial Item Price group selections must be detected before confirmation"
);
const originalPreviewRows = [{item_code: "A"}, {item_code: "B"}, {item_code: "C"}];
const mutablePreviewRows = make_mutable_preview_rows(originalPreviewRows, "pricing-rule-item");
assert.deepStrictEqual(
	mutablePreviewRows.map(function (row) { return [row.name, row.idx, row.item_code]; }),
	[
		["pricing-rule-item-1", 1, "A"],
		["pricing-rule-item-2", 2, "B"],
		["pricing-rule-item-3", 3, "C"]
	],
	"deletable popup rows must have stable unique identities"
);
mutablePreviewRows.splice(1, 1);
assert.deepStrictEqual(
	originalPreviewRows,
	[{item_code: "A"}, {item_code: "B"}, {item_code: "C"}],
	"deleting popup rows must not mutate the server preview array"
);
assert.ok(
	pricingRulePreviewFields.reduce(function (total, field) {
		return total + Number(field.columns || 0);
	}, 0) <= 10,
	"preview columns must fit within the ERPNext v12 grid width"
);

const tierSummaryFields = get_pricing_rule_tier_summary_fields();
assert.strictEqual(tierSummaryFields[0].fieldname, "included");
assert.strictEqual(tierSummaryFields[0].label, "Include");
assert.strictEqual(tierSummaryFields[0].fieldtype, "Check");

assert.strictEqual(
	get_skipped_update_notice([
		{item_code: "A", price_kind: "Regular", reason: "No price"},
		{item_code: "A", price_kind: "B2B", reason: "No price"},
		{item_code: "B", reason: "No discount"}
	]),
	'<div class="alert alert-warning"><strong>2 items skipped because no valid recommended price was available.</strong></div>',
	"skipped warnings must be compact and count unique items"
);
assert.strictEqual(get_effective_mixed_conditions("separate", 1), 0);
assert.strictEqual(get_effective_mixed_conditions("combined", 1), 1);
assert.strictEqual(get_effective_mixed_conditions("same_discount", 1), 1);

const restoredFilterValues = {};
const preparedFilterReport = {
	pricing_strategy_restoring_prepared_filters: false,
	filters: ["pricing_group", "company", "pricing_strategy", "regular_price_list", "purchase_receipt"].map(function (fieldname) {
		return {df: {fieldname: fieldname}, set_input: function (value) {
			restoredFilterValues[fieldname] = value;
		}};
	})
};
apply_prepared_pricing_strategy_filters(preparedFilterReport, {
	pricing_group: "PVC Colours", company: "World Shading", pricing_strategy: "Standard Pricing Strategy",
	regular_price_list: "Regular Price", purchase_receipt: "PR-0001"
});
assert.deepStrictEqual(restoredFilterValues, {
	pricing_group: "PVC Colours", company: "World Shading", pricing_strategy: "Standard Pricing Strategy",
	regular_price_list: "Regular Price", purchase_receipt: "PR-0001"
});
assert.strictEqual(preparedFilterReport.pricing_strategy_restoring_prepared_filters, false);

const clearedReceiptScope = {};
clear_purchase_receipt_item_scope_filters({
	pricing_strategy_restoring_prepared_filters: false,
	get_filter_value: function () { return "PR-0001"; },
	set_filter_value: function (values) { Object.assign(clearedReceiptScope, values); }
});
assert.deepStrictEqual(clearedReceiptScope, {
	item: "", item_group: "", pricing_group: "", brand: "", stock_uom: ""
});
let pricingGroupCallCount = 0;
let pricingGroupValues = null;
let pricingStrategyLoadCount = 0;
const originalLoadPricingStrategySettings = load_pricing_strategy_settings;
load_pricing_strategy_settings = function () { pricingStrategyLoadCount += 1; };
frappe.call = function (options) {
	pricingGroupCallCount += 1;
	assert.strictEqual(
		options.method,
		"worldshading.worldshading.doctype.pricing_group.pricing_group.get_pricing_group_configuration"
	);
	assert.deepStrictEqual(options.args, {pricing_group: "PVC Colours"});
	options.callback({message: {
		company: "World Shading", item_group: "PVC 680 GSM",
		pricing_strategy: "PVC Strategy"
	}});
};
load_pricing_group_configuration({
	pricing_strategy_restoring_prepared_filters: false,
	get_filter_value: function () { return "PVC Colours"; },
	set_filter_value: function (values) { pricingGroupValues = values; },
	get_filter: function () { return null; }
});
assert.strictEqual(pricingGroupCallCount, 1);
assert.deepStrictEqual(pricingGroupValues, {
	company: "World Shading", item_group: "PVC 680 GSM", pricing_strategy: "PVC Strategy",
	purchase_receipt: ""
});
assert.strictEqual(pricingStrategyLoadCount, 1);
load_pricing_group_configuration({
	pricing_strategy_restoring_prepared_filters: true,
	get_filter_value: function () { return "PVC Colours"; }
});
load_pricing_group_configuration({
	pricing_strategy_restoring_prepared_filters: false,
	get_filter_value: function () { return ""; }
});
assert.strictEqual(pricingGroupCallCount, 1, "restoration and a cleared group must not fetch configuration");
load_pricing_strategy_settings = originalLoadPricingStrategySettings;
const purchaseReceiptFilter = frappe.query_reports["Pricing Strategy Analysis"].filters.filter(
	function (field) { return field.fieldname === "purchase_receipt"; }
)[0];
assert.ok(purchaseReceiptFilter);
assert.strictEqual(
	purchaseReceiptFilter.on_change.toString().indexOf("validate_purchase_receipt_filter") !== -1,
	true,
	"Purchase Receipt selection must run the friendly eligibility check"
);
assert.deepStrictEqual(pricingGroupFilter.get_query().filters, {disabled: 0});
frappe.query_report = {get_filter_value: function () { return "World Shading"; }};
assert.deepStrictEqual(purchaseReceiptFilter.get_query().filters, {
	company: "World Shading", docstatus: 1, is_return: 0
});

let purchaseReceiptPopup = null;
let clearedPurchaseReceipt = null;
frappe.msgprint = function (options) { purchaseReceiptPopup = options; };
frappe.call = function (options) {
	assert.strictEqual(
		options.method,
		"worldshading.worldshading.report.pricing_strategy_analysis." +
			"pricing_strategy_analysis.get_purchase_receipt_pricing_eligibility"
	);
	options.callback({message: {
		eligible: false,
		message: "Purchase Receipt PR-0001 has no active stock Items for pricing analysis."
	}});
};
validate_purchase_receipt_filter({
	pricing_strategy_restoring_prepared_filters: false,
	get_filter_value: function (fieldname) {
		return fieldname === "purchase_receipt" ? "PR-0001" : "World Shading";
	},
	set_filter_value: function (values) {
		if (Object.prototype.hasOwnProperty.call(values, "purchase_receipt")) {
			clearedPurchaseReceipt = values.purchase_receipt;
		}
	}
});
assert.strictEqual(clearedPurchaseReceipt, "");
assert.strictEqual(purchaseReceiptPopup.indicator, "orange");
assert.ok(purchaseReceiptPopup.message.indexOf("no active stock Items") !== -1);
assert.ok(reportFilterOrder.indexOf("purchase_receipt") > reportFilterOrder.indexOf("to_date"));
assert.ok(reportFilterOrder.indexOf("warehouse") > reportFilterOrder.indexOf("brand"));
assert.strictEqual(
	frappe.query_reports["Pricing Strategy Analysis"].filters.filter(function (field) {
		return field.fieldname === "cost_source";
	})[0].default,
	"Latest Valuation Rate"
);
assert.strictEqual(pricing_strategy_controlled_fields.indexOf("cost_source"), -1);
assert.ok(reportFilterOrder.indexOf("pricing_group") < reportFilterOrder.indexOf("company"));
assert.ok(reportFilterOrder.indexOf("pricing_group") < reportFilterOrder.indexOf("pricing_strategy"));

console.log("Pricing Strategy Analysis header tooltip tests: OK");
