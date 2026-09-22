const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const email_field = {fieldname: "email_id", fieldtype: "Data"};
const handlers = {};

function ControlData() {}
ControlData.prototype.bind_change_event = function () {
	this.$input.on("change", function () {});
	this.$input.on("input", function () {});
};

const context = {
	console: console,
	frappe: {
		meta: {
			get_docfield: function (doctype, fieldname) {
				if (doctype === "Email Account" && fieldname === "email_id") {
					return email_field;
				}
				return null;
			}
		},
		ui: {
			form: {
				ControlData: ControlData,
				on: function (doctype, events) {
					Object.keys(events).forEach(function (event) {
						handlers[doctype + ":" + event] = events[event];
					});
				},
				make_control: function () {}
			}
		},
		email: {
			get_contact_list: function () {}
		}
	},
	$: function () {
		return {};
	}
};

vm.createContext(context);
vm.runInContext(
	fs.readFileSync(__dirname + "/email_validation.js", "utf8"),
	context
);

const bound_events = [];
const control = Object.create(ControlData.prototype);
control.df = email_field;
control.doctype = "Email Account";
control.$input = {
	on: function (event) {
		bound_events.push(event);
	}
};
control.bind_change_event();

// Frappe builds controls before evaluating the DocType-specific script.
vm.runInContext(
	fs.readFileSync(__dirname + "/email_account.js", "utf8"),
	context
);

assert.deepStrictEqual(
	bound_events,
	["change"],
	"Email Account address must update only after editing is complete"
);
assert.strictEqual(
	email_field.options,
	"Email",
	"Email Account address must retain client-side email validation"
);

console.log("Email Account domain timing tests passed");
