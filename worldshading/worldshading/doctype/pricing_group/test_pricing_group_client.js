const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

let handlers = null;
const context = {
	console: console,
	__: function (text, args) {
		(args || []).forEach(function (arg, index) {
			text = text.replace("{" + index + "}", arg);
		});
		return text;
	},
	frappe: {
		ui: {form: {on: function (doctype, received) {
			assert.strictEqual(doctype, "Pricing Group");
			handlers = received;
		}}},
		utils: {escape_html: function (value) {
			return String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
				.replace(/>/g, "&gt;").replace(/\"/g, "&quot;");
		}}
	}
};

vm.createContext(context);
vm.runInContext(fs.readFileSync(__dirname + "/pricing_group.js", "utf8"), context);

assert.deepStrictEqual(
	JSON.parse(JSON.stringify(context.get_pricing_group_strategy_query("World Shading"))),
	{filters: {company: "World Shading", enabled: 1}}
);
assert.strictEqual(context.should_clear_pricing_group_strategy("WS", "Other"), true);
assert.strictEqual(context.should_clear_pricing_group_strategy("WS", "WS"), false);

const html = context.build_pricing_group_items_html([{
	item_code: "ITEM-001", item_name: "Blue <Roll>", item_group: "PVC",
	brand: "Rakaz", stock_uom: "Roll", disabled: 0
}, {
	item_code: "ITEM-002", item_name: "Red Roll", item_group: "PVC",
	brand: "Rakaz", stock_uom: "Roll", disabled: 1
}], false);
assert.ok(html.indexOf("2 Items included") !== -1);
assert.ok(html.indexOf("Blue &lt;Roll&gt;") !== -1);
assert.ok(html.indexOf("Blue <Roll>") === -1);
assert.strictEqual(html.indexOf("<th>Status</th>"), -1);
assert.strictEqual(html.indexOf("<td>Enabled</td>"), -1);
assert.strictEqual(html.indexOf("<td>Disabled</td>"), -1);
assert.ok(context.build_pricing_group_items_html([], true).indexOf("Save this Pricing Group") !== -1);

let queryHandler = null;
handlers.setup({
	doc: {company: "WS"},
	set_query: function (fieldname, callback) {
		assert.strictEqual(fieldname, "pricing_strategy");
		queryHandler = callback;
	}
});
assert.deepStrictEqual(JSON.parse(JSON.stringify(queryHandler())), {
	filters: {company: "WS", enabled: 1}
});

console.log("Pricing Group client tests: OK");
