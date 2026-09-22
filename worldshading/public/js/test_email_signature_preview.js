const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.document = {};
global.__ = function (value) { return value; };
global.$ = function () {
	return { on: function () {} };
};
global.frappe = {
	boot: { email_accounts: [] },
	provide: function () {
		global.worldshading = global.worldshading || {};
		global.worldshading.email_signature =
			global.worldshading.email_signature || {};
	},
	utils: {
		is_html: function () { return false; },
		escape_html: function (value) { return value; }
	},
	views: {}
};

const source = fs.readFileSync(__dirname + "/email_signature_preview.js", "utf8");
vm.runInThisContext(source, { filename: "email_signature_preview.js" });

frappe.boot.email_accounts = [
	{
		email_account: "IT Support",
		email_id: "it.development@worldshading.com",
		enable_outgoing: 1
	}
];

assert.strictEqual(
	worldshading.email_signature.get_effective_sender({
		dialog: { fields_dict: {} }
	}),
	"it.development@worldshading.com",
	"a composer with one outgoing account must resolve that account as sender"
);

const values = {};
worldshading.email_signature.apply_effective_sender(values, {
	dialog: { fields_dict: {} }
});
assert.strictEqual(
	values.sender,
	"it.development@worldshading.com",
	"the resolved single account must be submitted to the backend"
);

console.log("email signature single-account sender regression: PASS");
