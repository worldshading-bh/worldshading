const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const desk = fs.readFileSync(path.resolve(__dirname,
	"../../../../frappe/frappe/public/js/frappe/desk.js"), "utf8");
const start = desk.indexOf("frappe.Application = Class.extend({");
const end = desk.indexOf("\n});", start) + 4;
const extension = path.join(__dirname, "pricing_update_notifications.js");

function session(notes) {
	const displayed = [], calls = [], widths = [], dialog = {};
	dialog.$wrapper = {toggleClass: function (name, enabled) {
		assert.strictEqual(name, "ws-pricing-note");
		dialog.wide = enabled;
	}};
	const styles = [];
	const context = {
		document: {createElement: function () { return {}; }, head: {appendChild: function (style) { styles.push(style.textContent); }}},
		frappe: {boot: {notes: notes}, msgprint: function (options) {
			displayed.push(options.title);
			widths.push(options.wide);
			return dialog;
		}, call: function (options) { calls.push(options); }},
		Class: {extend: function (methods) {
			function Application() {}
			Application.prototype = methods;
			return Application;
		}}
	};
	vm.createContext(context);
	vm.runInContext(desk.slice(start, end), context);
	if (fs.existsSync(extension)) {
		vm.runInContext(fs.readFileSync(extension, "utf8"), context);
	}
	return {app: new context.frappe.Application(), context, displayed, calls, dialog, styles, widths};
}

function pricingNote(title) {
	return {title: title || "Prices Updated - 2026-10-04 15:30:00 - abcdef123456",
		content: "Prices", notify_on_every_login: 1};
}

const notes = [pricingNote(), pricingNote("Pricing Rules Updated - 2026-10-04 15:31:00 - abcdef123457")];
const first = session(notes);
first.app.show_notes();
assert.strictEqual(first.displayed.length, 2);
assert.deepStrictEqual(first.displayed, ["Prices Updated", "Pricing Rules Updated"]);
assert.strictEqual(first.dialog.wide, true, "Combined pricing popup should be wider");
assert.deepStrictEqual(first.widths, [true, true], "Use native wide mode to remove Frappe's narrow-message cap");
assert(first.styles.join("").includes("760px"));
assert.strictEqual(notes[0].title, "Prices Updated - 2026-10-04 15:30:00 - abcdef123456");
first.dialog.custom_onhide();
assert.strictEqual(first.displayed.length, 2, "Dismissing must not redisplay either pricing announcement");
first.app.show_notes();
assert.strictEqual(first.displayed.length, 2, "Route callbacks must not repeat announcements within the same load");
assert.strictEqual(first.calls.length, 0, "Do not persist Seen By; next login must still display the Notes");
assert.strictEqual(first.context.frappe.boot.notes, notes, "Restore the original boot notes list");
first.context.frappe.msgprint({title: "Unrelated message"});
assert.strictEqual(first.dialog.wide, false, "Do not widen later unrelated messages");
assert.strictEqual(first.widths[first.widths.length - 1], undefined);

const next = session([pricingNote()]);
next.app.show_notes();
assert.strictEqual(next.displayed.length, 1, "A fresh Desk load displays the announcement again");

const ordinary = session([{title: "Existing production item", content: "Item", notify_on_every_login: 1}]);
ordinary.app.show_notes();
ordinary.dialog.custom_onhide();
assert.strictEqual(ordinary.displayed.length, 2, "Do not alter unrelated native Note behavior");

const once = session([{name: "Once", title: "Existing once-only note", content: "Item", notify_on_every_login: 0}]);
once.app.show_notes();
once.dialog.custom_onhide();
assert.strictEqual(once.displayed.length, 1);
assert.strictEqual(once.calls.length, 1, "Preserve native Seen By tracking for unrelated Notes");
console.log("Pricing announcements against native Desk popup: OK");
