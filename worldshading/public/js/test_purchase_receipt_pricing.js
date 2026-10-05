const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

let purchaseReceiptHandlers = null;
const context = {
	console: console,
	__: function (text) { return text; },
	frappe: {
		ui: {
			form: {
				on: function (doctype, handlers) {
					assert.strictEqual(doctype, "Purchase Receipt");
					purchaseReceiptHandlers = handlers;
				}
			}
		}
	}
};

vm.createContext(context);
vm.runInContext(fs.readFileSync(__dirname + "/purchase_receipt.js", "utf8"), context);

assert.strictEqual(context.can_show_purchase_receipt_update_pricing({docstatus: 1, is_return: 0}), true);
assert.strictEqual(context.can_show_purchase_receipt_update_pricing({docstatus: 0, is_return: 0}), false);
assert.strictEqual(context.can_show_purchase_receipt_update_pricing({docstatus: 1, is_return: 1}), false);
assert.deepStrictEqual(
	JSON.parse(JSON.stringify(context.get_purchase_receipt_pricing_route_options({
		name: "PR-0001", company: "World Shading", set_warehouse: "Receiving - WS"
	}, "Standard Pricing Strategy"))),
	{
		company: "World Shading",
		pricing_strategy: "Standard Pricing Strategy",
		purchase_receipt: "PR-0001"
	}
);

let addedButton = null;
purchaseReceiptHandlers.refresh({
	doc: {docstatus: 1, is_return: 0},
	add_custom_button: function (label, handler) {
		addedButton = {label: label, handler: handler};
	}
});
assert.strictEqual(addedButton.label, "Update Pricing");

addedButton = null;
purchaseReceiptHandlers.refresh({
	doc: {docstatus: 0, is_return: 0},
	add_custom_button: function () { addedButton = true; }
});
assert.strictEqual(addedButton, null);

console.log("Purchase Receipt pricing workflow tests: OK");
