const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function session(busy) {
	const ready = [], timers = [], hidden = [], calls = [], popups = [];
	let visible = false;
	const modal = {_isShown: Boolean(busy), _isTransitioning: Boolean(busy)};
	const classes = new Set();
	const dialog = {
		custom_onhide: function () {},
		$wrapper: {
			data: function () { return modal; },
			is: function () { return visible; },
			one: function (event, callback) { hidden.push(callback); },
			addClass: function (name) { classes.add(name); },
			removeClass: function (name) { classes.delete(name); }
		}
	};
	const context = {
		document: {},
		__: function (value) { return value; },
		setTimeout: function (callback) { timers.push(callback); },
		format_currency: function (value, currency) { return currency + " " + value; },
		$: function () { return {on: function (event, callback) { ready.push(callback); }}; },
		frappe: {
			msg_dialog: dialog,
			utils: {
				escape_html: function (value) {
					return value.replace(/&/g, "&amp;").replace(/</g, "&lt;")
						.replace(/>/g, "&gt;").replace(/"/g, "&quot;");
				},
				get_form_link: function (doctype, name) { return "#Form/" + doctype + "/" + name; }
			},
			call: function (options) { calls.push(options); },
			msgprint: function (options) {
				assert.strictEqual(modal._isShown, false, "Do not overwrite pricing while opening");
				assert.strictEqual(modal._isTransitioning, false, "Wait for closing animations");
				modal._isShown = true;
				visible = true;
				popups.push(options);
				return dialog;
			}
		}
	};
	function flush() { while (timers.length) { timers.shift()(); } }
	vm.createContext(context);
	["purchase_order_urgent_popup.js", "payment_entry_urgent_popup.js", "gl_payment_urgent_popup.js"].forEach(function (file) {
		vm.runInContext(fs.readFileSync(path.join(__dirname, file), "utf8"), context);
	});
	ready.forEach(function (callback) { callback(); callback(); });
	flush();
	assert.strictEqual(calls.length, 3, "Only one request per document type per page load");
	return {
		calls, popups, dialog, classes,
		close: function () {
			visible = false;
			modal._isShown = false;
			modal._isTransitioning = false;
			hidden.splice(0).forEach(function (callback) { callback(); });
			flush();
		}
	};
}
const po = {name: "PO-1", supplier_name: "Supplier <One>", currency: "BHD", grand_total: 12,
	workflow_state: "Pending", custom_urgent_reason: '<script>alert("x")</script>'};
const pe = {name: "PE-1", party_name: "Party Two", paid_from_account_currency: "USD", paid_amount: 24};
const gl = {name: "GLP-1", party_name: "Party Three", currency: "SAR", total_amount: 36};

// Responses arrive out of order while the pricing backdrop is opening.
const all = session(true);
all.calls[2].callback({message: [gl]});
all.calls[0].callback({message: [po]});
assert.strictEqual(all.popups.length, 0, "Wait for every type before showing");
all.calls[1].callback({message: [pe]});
assert.strictEqual(all.popups.length, 0, "Wait for pricing to close");
all.close();
assert.strictEqual(all.popups.length, 1);
assert.strictEqual(all.popups[0].title, "Urgent Documents (3)");
const html = all.popups[0].message;
["Purchase Orders (1)", "Payment Entries (1)", "GL Payments (1)",
	"#Form/Purchase Order/PO-1", "#Form/Payment Entry/PE-1", "#Form/GL Payment/GLP-1",
	"BHD 12", "USD 24", "SAR 36", "&lt;script&gt;"].forEach(function (text) {
	assert.ok(html.includes(text), text);
});
assert.ok(!html.includes('<script>'));
assert.ok(html.indexOf("Purchase Orders (1)") < html.indexOf("Payment Entries (1)"));
assert.strictEqual(all.dialog.keep_open, true);
assert.strictEqual(all.dialog.custom_onhide, null);
assert.strictEqual(all.popups[0].clear, true);
all.close();
assert.strictEqual(all.popups.length, 1, "No second urgency popup after Close");
assert.strictEqual(all.classes.size, 0, "Remove width styling from the shared dialog");

const sparse = session(false);
sparse.calls[0].callback({message: [po]});
sparse.calls[1].callback({message: []});
sparse.calls[2].callback({message: [gl]});
assert.strictEqual(sparse.popups[0].title, "Urgent Documents (2)");
assert.ok(!sparse.popups[0].message.includes("<h5>Payment Entries"));

const empty = session(false);
empty.calls.forEach(function (call) { call.callback({message: []}); });
assert.strictEqual(empty.popups.length, 0);

const failed = session(false);
failed.calls[0].callback({message: [po]});
failed.calls[1].error();
failed.calls[1].callback({exc: "Failure"}); // Some request paths invoke both callbacks.
failed.calls[2].callback({message: [gl]});
assert.strictEqual(failed.popups.length, 1);
assert.strictEqual(failed.popups[0].title, "Urgent Documents (2)");
assert.ok(failed.popups[0].message.includes("Could not load urgent documents"));
console.log("Combined urgency: all types, empty sections, escaping, failures and pricing compatibility OK");
