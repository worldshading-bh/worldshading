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

const formHandlers = {};
const rules = [
	{
		minimum_amount: 0.100,
		maximum_amount: 10.000,
		rounding_method: "Nearest",
		rounding_value: 0.050
	}
];

global.frappe = {
	call: function (options) {
		if (
			options.method
			=== "worldshading.api.dynamic_rounding.get_dynamic_rounding_client_settings"
		) {
			options.callback({
				message: { enabled: true, rules: rules }
			});
		}
	},
	defaults: { get_default: function () { return "BHD"; } },
	meta: { get_docfield: function () { return true; } },
	session: { user: "cashier@worldshading.com" },
	sys_defaults: {},
	ui: {
		form: {
			on: function (doctype, handlers) {
				formHandlers[doctype] = handlers;
			}
		}
	}
};

global.erpnext = {
	taxes_and_totals: function () {}
};
erpnext.taxes_and_totals.prototype.set_rounded_total = function () {
	this.frm.doc.rounded_total = flt(
		Math.round(this.frm.doc.grand_total * 10) / 10,
		precision("rounded_total")
	);
	this.frm.doc.rounding_adjustment = flt(
		this.frm.doc.rounded_total - this.frm.doc.grand_total,
		precision("rounding_adjustment")
	);
};

// ERPNext copies this method to cur_frm.cscript before custom hook JS is loaded.
const copiedCoreSetRoundedTotal = erpnext.taxes_and_totals.prototype.set_rounded_total;

const implementationPath = __dirname + "/dynamic_rounding_preview.js";
vm.runInThisContext(fs.readFileSync(implementationPath, "utf8"), {
	filename: "dynamic_rounding_preview.js"
});

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

let updatePaidAmountArgument = "not-called";
const refreshForm = {
	doc: {
		doctype: "Sales Invoice",
		docstatus: 0,
		is_pos: 1,
		name: "new-sales-invoice-1",
		currency: "BHD",
		party_account_currency: "BHD",
		total_advance: 0,
		grand_total: 0.114,
		base_grand_total: 0.04,
		conversion_rate: 0.376
	},
	cscript: {},
	refresh_fields: function () {},
	add_custom_button: function () {}
};
refreshForm.cscript.frm = refreshForm;
refreshForm.cscript.set_rounded_total = copiedCoreSetRoundedTotal;
refreshForm.cscript.set_in_company_currency = function (doc, fields) {
	fields.forEach(function (fieldname) {
		doc["base_" + fieldname] = flt(
			doc[fieldname] * doc.conversion_rate,
			precision("base_" + fieldname)
		);
	});
};
refreshForm.cscript.calculate_taxes_and_totals = function (updatePaidAmount) {
	updatePaidAmountArgument = updatePaidAmount;
	this.set_rounded_total();
};
refreshForm.cscript.calculate_outstanding_amount = function () {
	const doc = this.frm.doc;
	const payableTotal = doc.rounded_total || doc.grand_total;
	doc.paid_amount = (doc.payments || []).reduce(function (total, payment) {
		return total + flt(payment.amount);
	}, 0);
	doc.change_amount = 0;
	if (
		doc.paid_amount > doc.grand_total
		&& (doc.payments || []).some(function (payment) {
			return payment.type === "Cash";
		})
	) {
		doc.change_amount = flt(
			doc.paid_amount - payableTotal + flt(doc.write_off_amount),
			precision("change_amount")
		);
	}
};
refreshForm.cscript.calculate_write_off_amount = function () {
	const doc = this.frm.doc;
	const payableTotal = doc.rounded_total || doc.grand_total;
	if (doc.paid_amount > doc.grand_total) {
		doc.write_off_amount = flt(
			payableTotal - doc.paid_amount + doc.change_amount,
			precision("write_off_amount")
		);
	}
	this.calculate_outstanding_amount(false);
};
refreshForm.doc.base_grand_total = flt(
	refreshForm.doc.grand_total * refreshForm.doc.conversion_rate,
	precision("base_grand_total")
);

global.cur_frm = refreshForm;
formHandlers["Sales Invoice"].refresh(refreshForm);

assert.strictEqual(refreshForm.doc.rounded_total, 0.100);
assert.strictEqual(refreshForm.doc.rounding_adjustment, -0.014);
assert.strictEqual(refreshForm.doc.base_rounded_total, 0.04);
assert.strictEqual(refreshForm.doc.base_rounding_adjustment, 0.00);
assert.strictEqual(
	updatePaidAmountArgument,
	false,
	"settings refresh must preserve cashier-entered payment amounts"
);

// A later ERPNext recalculation must use the wrapped form method, not its copied core method.
refreshForm.doc.grand_total = 1.848;
refreshForm.doc.base_grand_total = flt(
	refreshForm.doc.grand_total * refreshForm.doc.conversion_rate,
	precision("base_grand_total")
);
refreshForm.cscript.set_rounded_total();
assert.strictEqual(refreshForm.doc.rounded_total, 1.850);
assert.strictEqual(refreshForm.doc.rounding_adjustment, 0.002);

// POS payment events must repair a core-rounded value before calculating change/write-off.
refreshForm.doc.grand_total = 0.847;
refreshForm.doc.base_grand_total = 0.847;
refreshForm.doc.rounded_total = 0.800;
refreshForm.doc.base_rounded_total = 0.800;
refreshForm.doc.write_off_amount = 0.050;
refreshForm.doc.base_write_off_amount = 0.050;
refreshForm.doc.change_amount = 0.050;
refreshForm.doc.payments = [{ type: "Cash", amount: 0.850 }];
refreshForm.cscript.calculate_outstanding_amount(false);
refreshForm.cscript.calculate_write_off_amount();
assert.strictEqual(
	refreshForm.doc.rounded_total,
	0.850,
	"POS payment calculations must use the dynamic rounded total"
);
assert.strictEqual(
	refreshForm.doc.change_amount,
	0,
	"an exact payment against the dynamic total must not create cash change"
);
assert.strictEqual(
	refreshForm.doc.write_off_amount,
	0,
	"an exact payment against the dynamic total must not create a write-off"
);

// Exact non-cash payment must also remain free of change and write-off.
refreshForm.doc.rounded_total = 0.800;
refreshForm.doc.base_rounded_total = 0.800;
refreshForm.doc.write_off_amount = 0;
refreshForm.doc.change_amount = 0;
refreshForm.doc.payments = [{ type: "Bank", amount: 0.850 }];
refreshForm.cscript.calculate_outstanding_amount(false);
refreshForm.cscript.calculate_write_off_amount();
assert.strictEqual(refreshForm.doc.change_amount, 0);
assert.strictEqual(refreshForm.doc.write_off_amount, 0);

// A zero Cash row must not turn a Benefit Pay overpayment into cash change.
refreshForm.doc.grand_total = 16.170;
refreshForm.doc.base_grand_total = 16.170;
refreshForm.doc.rounded_total = 16.200;
refreshForm.doc.base_rounded_total = 16.200;
refreshForm.doc.write_off_amount = 0;
refreshForm.doc.change_amount = 0;
refreshForm.doc.payments = [
	{ type: "Bank", amount: 16.200 },
	{ type: "Cash", amount: 0 }
];
refreshForm.__ws_dynamic_rounding_settings = {
	enabled: true,
	rules: [{
		minimum_amount: 10,
		maximum_amount: 100,
		rounding_method: "Lowest",
		rounding_value: 0.100
	}]
};
refreshForm.cscript.calculate_outstanding_amount(false);
assert.strictEqual(refreshForm.doc.rounded_total, 16.100);
assert.strictEqual(
	refreshForm.doc.change_amount,
	0,
	"a zero Cash row must not create change for a non-cash overpayment"
);

// Genuine cash overpayment must retain ERPNext's normal positive-change behavior.
refreshForm.doc.grand_total = 0.847;
refreshForm.doc.base_grand_total = 0.847;
refreshForm.doc.rounded_total = 0.800;
refreshForm.doc.base_rounded_total = 0.800;
refreshForm.doc.write_off_amount = 0;
refreshForm.doc.change_amount = 0;
refreshForm.doc.payments = [{ type: "Cash", amount: 1.000 }];
refreshForm.__ws_dynamic_rounding_settings = { enabled: true, rules: rules };
refreshForm.cscript.calculate_outstanding_amount(false);
refreshForm.cscript.calculate_write_off_amount();
assert.strictEqual(refreshForm.doc.change_amount, 0.150);
assert.strictEqual(refreshForm.doc.write_off_amount, 0);

const installedMethods = {
	set_rounded_total: refreshForm.cscript.set_rounded_total,
	calculate_outstanding_amount: refreshForm.cscript.calculate_outstanding_amount,
	calculate_change_amount: refreshForm.cscript.calculate_change_amount,
	calculate_write_off_amount: refreshForm.cscript.calculate_write_off_amount
};
formHandlers["Sales Invoice"].refresh(refreshForm);
Object.keys(installedMethods).forEach(function (methodName) {
	assert.strictEqual(
		refreshForm.cscript[methodName],
		installedMethods[methodName],
		"refresh must not wrap " + methodName + " more than once"
	);
});

// Return rounding mirrors the positive amount only for negative Sales Invoice returns.
["Lowest", "Highest", "Nearest"].forEach(function (method) {
	const returnRules = [{
		minimum_amount: 10, maximum_amount: 100,
		rounding_method: method, rounding_value: 0.100
	}];
	[27.779, 27.700, 10.270, 10.250].forEach(function (amount) {
		const positive = worldshading.dynamic_rounding.calculate(amount, returnRules);
		assert.strictEqual(
			worldshading.dynamic_rounding.calculate(-amount, returnRules, "Sales Invoice", 1),
			-positive
		);
	});
});

const lowestRules = [{
	minimum_amount: 10, maximum_amount: 100,
	rounding_method: "Lowest", rounding_value: 0.100
}];
[
	["Sales Invoice", 1, -27.779, -27.700],
	["Sales Invoice", 0, -27.779, -27.800],
	["Sales Invoice", "0", -27.779, -27.800],
	["Sales Order", 1, -27.779, -27.800],
	["Quotation", 1, -27.779, -27.800],
	["Sales Invoice", 1, 27.779, 27.700],
	["Sales Invoice", 0, 27.779, 27.700]
].forEach(function (scenario) {
	refreshForm.doc.doctype = scenario[0];
	refreshForm.doc.is_return = scenario[1];
	refreshForm.doc.grand_total = scenario[2];
	refreshForm.doc.conversion_rate = 1;
	refreshForm.doc.base_grand_total = flt(scenario[2], 2);
	refreshForm.__ws_dynamic_rounding_settings = { enabled: true, rules: lowestRules };
	refreshForm.cscript.set_rounded_total();
	assert.strictEqual(refreshForm.doc.rounded_total, scenario[3]);
	assert.strictEqual(refreshForm.doc.rounding_adjustment, flt(scenario[3] - scenario[2], 3));
	assert.strictEqual(
		refreshForm.doc.base_rounding_adjustment,
		flt(refreshForm.doc.base_rounded_total - refreshForm.doc.base_grand_total, 2)
	);
});

console.log("dynamic rounding client regression: PASS");
