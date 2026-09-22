const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = global;
global.__ = function (value) { return value; };
global.format_currency = function (value) { return String(value); };
global.cint = function (value) { return parseInt(value || 0, 10); };
global.flt = function (value, digits) {
	const number = Number(value || 0);
	if (digits === undefined) {
		return number;
	}
	const scale = Math.pow(10, digits);
	return Math.round((number + Number.EPSILON) * scale) / scale;
};
global.precision = function (fieldname) {
	return fieldname && fieldname.indexOf("base_") === 0 ? 2 : 3;
};

global.frappe = {
	call: function () {},
	defaults: { get_default: function () { return "BHD"; } },
	meta: { get_docfield: function () { return true; } },
	session: { user: "cashier@worldshading.com" },
	sys_defaults: {},
	ui: { form: { on: function () {} } }
};

global.erpnext = {
	taxes_and_totals: function () {}
};
erpnext.taxes_and_totals.prototype.set_rounded_total = function () {
	this.frm.doc.rounded_total = 1.300;
	this.frm.doc.rounding_adjustment = 0.031;
};

const implementationPath = __dirname + "/dynamic_rounding_preview.js";
vm.runInThisContext(fs.readFileSync(implementationPath, "utf8"), {
	filename: "dynamic_rounding_preview.js"
});

const rules = [
	{
		minimum_amount: 0.100,
		maximum_amount: 10.000,
		rounding_method: "Nearest",
		rounding_value: 0.050
	}
];

assert.strictEqual(
	worldshading.dynamic_rounding.calculate(1.269, rules),
	1.250,
	"BHD 1.269 must round to BHD 1.250 before save"
);
assert.strictEqual(
	worldshading.dynamic_rounding.calculate(1.025, rules),
	1.050,
	"exact positive half steps must use the server's half-up behavior"
);
assert.strictEqual(
	worldshading.dynamic_rounding.calculate(-1.025, rules),
	-1.050,
	"exact negative half steps must use the server's half-up behavior"
);

worldshading.dynamic_rounding.settings = {
	enabled: true,
	rules: rules
};

const calculator = Object.create(erpnext.taxes_and_totals.prototype);
calculator.frm = {
	doc: {
		doctype: "Sales Invoice",
		grand_total: 0.114,
		base_grand_total: 0.04,
		conversion_rate: 0.376
	}
};
calculator.set_in_company_currency = function (doc, fields) {
	fields.forEach(function (fieldname) {
		doc["base_" + fieldname] = flt(
			doc[fieldname] * doc.conversion_rate,
			precision("base_" + fieldname)
		);
	});
};
calculator.frm.doc.base_grand_total = flt(
	calculator.frm.doc.grand_total * calculator.frm.doc.conversion_rate,
	precision("base_grand_total")
);

calculator.set_rounded_total();

assert.strictEqual(calculator.frm.doc.rounded_total, 0.100);
assert.strictEqual(calculator.frm.doc.rounding_adjustment, -0.014);
assert.strictEqual(calculator.frm.doc.base_rounded_total, 0.04);
assert.strictEqual(calculator.frm.doc.base_rounding_adjustment, 0.00);

console.log("dynamic rounding client regression: PASS");
