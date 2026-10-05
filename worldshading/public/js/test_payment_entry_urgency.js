const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const scriptPath = path.resolve(__dirname, "payment_entry_urgency.js");
assert.ok(fs.existsSync(scriptPath), "Payment Entry urgency form script has not been implemented");

let handlers;
let dialogOptions;
let callOptions;
let confirmation;

const context = {
	__: function (value) { return value; },
	frappe: {
		meta: {get_docfield: function () { return {}; }},
		workflow: {
			is_read_only: function () { return false; }
		},
		ui: {
			form: {
				on: function (doctype, value) {
					assert.strictEqual(doctype, "Payment Entry");
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
			name: "PE-0001",
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
assert.ok(frm.buttons["Mark as Urgent"], "Normal PE must offer Mark as Urgent");
frm.buttons["Mark as Urgent"]();
assert.strictEqual(dialogOptions.title, "Mark Payment Entry as Urgent");
dialogOptions.primary_action({reason: "Advance required"});
assert.strictEqual(callOptions.method,
	"worldshading.api.payment_entry_urgency.set_payment_entry_urgency");
assert.deepStrictEqual(JSON.parse(JSON.stringify(callOptions.args)), {
	pe_name: "PE-0001", urgent: 1, reason: "Advance required"
});

frm = makeForm(true);
handlers.refresh(frm);
assert.ok(frm.buttons["Mark as Normal"], "Urgent PE must offer Mark as Normal");
frm.buttons["Mark as Normal"]();
assert.strictEqual(confirmation, "Remove the urgent label from this Payment Entry?");
assert.deepStrictEqual(JSON.parse(JSON.stringify(callOptions.args)),
	{pe_name: "PE-0001", urgent: 0, reason: ""});

frm = makeForm(false);
frm.perm = [{write: 0}];
handlers.refresh(frm);
assert.deepStrictEqual(Object.keys(frm.buttons), [], "Read-only users must not see urgency actions");

context.frappe.workflow.is_read_only = function () { return true; };
frm = makeForm(false);
handlers.refresh(frm);
assert.deepStrictEqual(Object.keys(frm.buttons), [],
	"Users outside the workflow state's Allow Edit For role must not see urgency actions");

console.log("Payment Entry urgency form behavior: OK");
