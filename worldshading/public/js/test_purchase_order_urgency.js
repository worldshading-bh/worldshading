const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const scriptPath = path.resolve(__dirname, "purchase_order_urgency.js");
assert.ok(fs.existsSync(scriptPath), "Purchase Order urgency form script has not been implemented");

let handlers;
let dialogOptions;
let callOptions;
let confirmation;

const context = {
	__: function (value) { return value; },
	frappe: {
		workflow: {
			is_read_only: function () { return false; }
		},
		ui: {
			form: {
				on: function (doctype, value) {
					assert.strictEqual(doctype, "Purchase Order");
					handlers = value;
				}
			},
			Dialog: function (options) {
				dialogOptions = options;
				this.show = function () {};
				this.hide = function () {};
			}
		},
		call: function (options) { callOptions = options; },
		confirm: function (message, action) {
			confirmation = message;
			action();
		},
		show_alert: function () {}
	}
};

vm.createContext(context);
vm.runInContext(fs.readFileSync(scriptPath, "utf8"), context);

function makeForm(urgent) {
	const buttons = {};
	return {
		doc: {
			name: "PO-0001",
			docstatus: 1,
			custom_is_urgent: urgent ? 1 : 0,
			custom_urgent_reason: urgent ? "Pay today" : ""
		},
		perm: [{write: 1}],
		is_new: function () { return false; },
		add_custom_button: function (label, action) { buttons[label] = action; },
		remove_custom_button: function () {},
		reload_doc: function () {},
		buttons: buttons
	};
}

let frm = makeForm(false);
handlers.refresh(frm);
assert.ok(frm.buttons["Mark as Urgent"], "Normal PO must offer Mark as Urgent");
frm.buttons["Mark as Urgent"]();
assert.strictEqual(dialogOptions.title, "Mark Purchase Order as Urgent");
dialogOptions.primary_action({reason: "Advance required"});
assert.strictEqual(callOptions.method,
	"worldshading.api.purchase_order_urgency.set_purchase_order_urgency");
assert.deepStrictEqual(JSON.parse(JSON.stringify(callOptions.args)), {
	po_name: "PO-0001", urgent: 1, reason: "Advance required"
});

frm = makeForm(true);
handlers.refresh(frm);
assert.ok(frm.buttons["Mark as Normal"], "Urgent PO must offer Mark as Normal");
frm.buttons["Mark as Normal"]();
assert.strictEqual(confirmation, "Remove the urgent label from this Purchase Order?");
assert.deepStrictEqual(JSON.parse(JSON.stringify(callOptions.args)),
	{po_name: "PO-0001", urgent: 0, reason: ""});

frm = makeForm(false);
frm.perm = [{write: 0}];
handlers.refresh(frm);
assert.deepStrictEqual(Object.keys(frm.buttons), [], "Read-only users must not see urgency actions");

context.frappe.workflow.is_read_only = function () { return true; };
frm = makeForm(false);
handlers.refresh(frm);
assert.deepStrictEqual(Object.keys(frm.buttons), [],
	"Users outside the workflow state's Allow Edit For role must not see urgency actions");

console.log("Purchase Order urgency form behavior: OK");
