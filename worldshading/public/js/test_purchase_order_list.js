const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const scriptPath = path.resolve(__dirname, "purchase_order_list.js");
assert.ok(fs.existsSync(scriptPath), "Purchase Order urgency list script has not been implemented");

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
		listview_settings: {"Purchase Order": settings},
		meta: {
			get_docfield: function (doctype, fieldname) {
				if (doctype === "Purchase Order" && fieldname === "custom_is_urgent") {
					return urgencyField;
				}
			}
		}
	}
};

vm.createContext(context);
vm.runInContext(fs.readFileSync(scriptPath, "utf8"), context);

const result = context.frappe.listview_settings["Purchase Order"];
assert.ok(result.add_fields.indexOf("custom_is_urgent") !== -1);
assert.strictEqual(urgencyField.in_list_view, 0,
	"Hide the separate Urgent checkbox column");
assert.strictEqual(result.formatters.status, statusFormatter,
	"Preserve existing Purchase Order formatters");

function originalSubject(doc) {
	return '<input class="list-row-checkbox"><span class="level-item">' +
		'<i class="octicon octicon-heart like-action liked" data-name="' + doc.name + '">\n</i>' +
		'<span class="likes-count">3</span></span>' +
		'<a class="ellipsis" href="#Form/Purchase Order/' + doc.name + '">' +
		(doc.supplier_name || doc.name) + '</a>';
}
const listview = {get_subject_html: originalSubject};

result.onload(listview);
assert.strictEqual(originalOnloadCalls, 1, "Preserve ERPNext Purchase Order list behavior");

const urgentHtml = listview.get_subject_html({name: "PO-0001", custom_is_urgent: 1});
assert.ok(urgentHtml.indexOf("Urgent Purchase Order") !== -1);
assert.ok(urgentHtml.indexOf("<svg") !== -1);
assert.ok(urgentHtml.indexOf("#e24c4c") !== -1);
assert.ok(urgentHtml.indexOf("like-action") === -1);
assert.ok(urgentHtml.indexOf("likes-count") === -1);
assert.ok(urgentHtml.indexOf("list-row-checkbox") !== -1);
assert.ok(urgentHtml.indexOf("<svg") < urgentHtml.indexOf("<a "),
	"Keep urgency outside the truncated supplier link");
assert.strictEqual(listview.get_subject_html({name: "PO-0002", custom_is_urgent: 0}),
	originalSubject({name: "PO-0002"}));
const longName = "Very long supplier name ".repeat(20);
const longHtml = listview.get_subject_html({name: "PO-0003", supplier_name: longName, custom_is_urgent: 1});
assert.ok(longHtml.indexOf("</svg>") < longHtml.indexOf(longName));

result.onload(listview);
assert.strictEqual(originalOnloadCalls, 2);
assert.strictEqual((listview.get_subject_html({name: "PO-0001", custom_is_urgent: 1})
	.match(/Urgent Purchase Order/g) || []).length, 2,
	"Install the urgency badge only once; aria-label and title each contain its label");

console.log("Purchase Order urgency list indicator: OK");
