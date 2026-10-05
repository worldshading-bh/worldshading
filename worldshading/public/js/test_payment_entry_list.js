const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const scriptPath = path.resolve(__dirname, "payment_entry_list.js");
assert.ok(fs.existsSync(scriptPath), "Payment Entry urgency list script has not been implemented");

let originalOnloadCalls = 0;
const originalOnload = function () { originalOnloadCalls += 1; };
const statusFormatter = function () { return "status"; };
const settings = {
	add_fields: ["status"],
	formatters: {status: statusFormatter},
	onload: originalOnload
};
const urgencyField = {fieldname: "custom_is_urgent", in_list_view: 1};
const context = {
	__: function (value) { return value; },
	frappe: {
		listview_settings: {"Payment Entry": settings},
		meta: {
			get_docfield: function (doctype, fieldname) {
				if (doctype === "Payment Entry" && fieldname === "custom_is_urgent") {
					return urgencyField;
				}
			}
		}
	}
};

vm.createContext(context);
vm.runInContext(fs.readFileSync(scriptPath, "utf8"), context);

const result = context.frappe.listview_settings["Payment Entry"];
assert.ok(result.add_fields.indexOf("custom_is_urgent") !== -1);
assert.strictEqual(urgencyField.in_list_view, 0,
	"Hide the separate Urgent checkbox column");
assert.strictEqual(result.formatters.status, statusFormatter,
	"Preserve existing Payment Entry formatters");

function originalSubject(doc) {
	return '<input class="list-row-checkbox"><span class="level-item">' +
		'<i class="octicon octicon-heart like-action liked" data-name="' + doc.name + '">\n</i>' +
		'<span class="likes-count">3</span></span>' +
		'<a class="ellipsis" href="#Form/Payment Entry/' + doc.name + '">' +
		(doc.supplier_name || doc.name) + '</a>';
}
const listview = {get_subject_html: originalSubject};

result.onload(listview);
assert.strictEqual(originalOnloadCalls, 1, "Preserve ERPNext Payment Entry list behavior");

const urgentHtml = listview.get_subject_html({name: "PE-0001", custom_is_urgent: 1});
assert.ok(urgentHtml.indexOf("Urgent Payment Entry") !== -1);
assert.ok(urgentHtml.indexOf("<svg") !== -1);
assert.ok(urgentHtml.indexOf("#e24c4c") !== -1);
assert.ok(urgentHtml.indexOf("like-action") === -1);
assert.ok(urgentHtml.indexOf("likes-count") === -1);
assert.ok(urgentHtml.indexOf("list-row-checkbox") !== -1);
assert.ok(urgentHtml.indexOf("<svg") < urgentHtml.indexOf("<a "),
	"Keep urgency outside the truncated supplier link");
assert.strictEqual(listview.get_subject_html({name: "PE-0002", custom_is_urgent: 0}),
	originalSubject({name: "PE-0002"}));
const longName = "Very long supplier name ".repeat(20);
const longHtml = listview.get_subject_html({name: "PE-0003", supplier_name: longName, custom_is_urgent: 1});
assert.ok(longHtml.indexOf("</svg>") < longHtml.indexOf(longName));

result.onload(listview);
assert.strictEqual(originalOnloadCalls, 2);
assert.strictEqual((listview.get_subject_html({name: "PE-0001", custom_is_urgent: 1})
	.match(/Urgent Payment Entry/g) || []).length, 2,
	"Install the urgency badge only once; aria-label and title each contain its label");

console.log("Payment Entry urgency list indicator: OK");
