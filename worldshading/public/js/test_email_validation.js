const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const controlPrototype = {
	bind_change_event: function () {
		this.original_bind_called = true;
	}
};

global.frappe = {
	ui: {
		form: {
			ControlData: function () {}
		}
	}
};
frappe.ui.form.ControlData.prototype = controlPrototype;

const implementationPath = __dirname + "/email_validation.js";
const source = fs.existsSync(implementationPath) ?
	fs.readFileSync(implementationPath, "utf8") : "";
vm.runInThisContext(source, { filename: "email_validation.js" });

function makeControl(options) {
	const events = [];
	const control = Object.create(frappe.ui.form.ControlData.prototype);
	control.df = { options: options };
	control.$input = {
		on: function (eventName) {
			events.push(eventName);
		}
	};
	control.get_input_value = function () { return "hil"; };
	control.parse_validate_and_set_in_model = function () {};
	control.events = events;
	return control;
}

const emailControl = makeControl("Email");
emailControl.bind_change_event();
assert.deepStrictEqual(
	emailControl.events,
	["change"],
	"Email controls must validate on change, not on every input event"
);
assert.strictEqual(emailControl.original_bind_called, undefined);

const normalControl = makeControl(undefined);
normalControl.bind_change_event();
assert.strictEqual(
	normalControl.original_bind_called,
	true,
	"non-Email Data controls must retain the core event binding"
);

console.log("email validation timing regression: PASS");
