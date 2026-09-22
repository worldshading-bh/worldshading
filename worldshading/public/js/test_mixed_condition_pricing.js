const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const handlers = {};
const item = {
	doctype: "Quotation Item",
	name: "QTN-ITEM-1",
	parenttype: "Quotation",
	item_code: "KSA0001",
	qty: 4
};

const context = {
	console: console,
	window: {},
	locals: {
		"Quotation Item": {
			"QTN-ITEM-1": item
		}
	},
	flt: function (value) { return Number(value) || 0; },
	cint: function (value) { return parseInt(value, 10) || 0; },
	__: function (value) { return value; },
	$: {
		extend: function (target, source) {
			Object.keys(source).forEach(function (key) {
				target[key] = source[key];
			});
			return target;
		}
	},
	frappe: {
		after_ajax: function (callback) {
			return callback();
		},
		ui: {
			form: {
				on: function (doctype, events) {
					handlers[doctype] = events;
				}
			}
		},
		model: {
			get_doc: function () { return item; },
			set_value: function () {}
		},
		utils: {
			escape_html: function (value) { return value; }
		}
	}
};

vm.createContext(context);
vm.runInContext(
	fs.readFileSync(__dirname + "/production_bom.js", "utf8"),
	context,
	{filename: "production_bom.js"}
);

function make_form() {
	const calls = [];
	return {
		doctype: "Quotation",
		doc: {
			docstatus: 0,
			items: [item],
			production_bom_items: []
		},
		fields_dict: {},
		cscript: {
			apply_pricing_rule: function () {
				calls.push(Array.prototype.slice.call(arguments));
			}
		},
		pricing_rule_calls: calls
	};
}

const qty_form = make_form();
handlers["Quotation Item"].qty(qty_form, "Quotation Item", "QTN-ITEM-1");
assert.deepStrictEqual(
	qty_form.pricing_rule_calls,
	[[]],
	"quantity changes must recalculate pricing rules for the complete quotation item table"
);

const item_code_form = make_form();
handlers["Quotation Item"].item_code(item_code_form, "Quotation Item", "QTN-ITEM-1");
assert.deepStrictEqual(
	item_code_form.pricing_rule_calls,
	[],
	"item additions must wait for ERPNext to load quantity and price before pricing runs"
);

const remove_form = make_form();
handlers["Quotation Item"].items_remove(remove_form);
assert.deepStrictEqual(
	remove_form.pricing_rule_calls,
	[[]],
	"item removal must recalculate pricing rules for the remaining quotation items"
);

console.log("mixed-condition pricing recalculation regression: PASS");
