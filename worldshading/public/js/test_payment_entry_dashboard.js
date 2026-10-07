const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const scriptPath = path.resolve(__dirname, "payment_entry_dashboard.js");
assert.ok(fs.existsSync(scriptPath), "Payment Entry dashboard script has not been implemented");

let handlers;
const context = {
	__: function (value) { return value; },
	frappe: {
		ui: {
			form: {
				on: function (doctype, value) {
					assert.strictEqual(doctype, "Payment Entry");
					handlers = value;
				}
			}
		}
	}
};

vm.createContext(context);
vm.runInContext(fs.readFileSync(scriptPath, "utf8"), context);

const links = {};
function makeLink(doctype) {
	const link = {
		visible: true,
		attributes: {},
		count: "",
		disabled: false,
		toggle: function (visible) { this.visible = visible; return this; },
		attr: function (name, value) {
			if (value === undefined) { return this.attributes[name]; }
			this.attributes[name] = value;
			return this;
		},
		find: function (selector) {
			const self = this;
			if (selector === ".count") {
				return {
					text: function (value) { self.count = String(value); return this; },
					toggleClass: function () { return this; }
				};
			}
			if (selector === ".badge-link") {
				return {
					attr: function (name, value) {
						if (name === "disabled") { self.disabled = value; }
						return this;
					}
				};
			}
		}
	};
	links[doctype] = link;
	return link;
}

["Sales Invoice", "Purchase Invoice", "Sales Order"].forEach(makeLink);

const frm = {
	doc: {
		_ws_sales_invoice_references: [{reference_name: "OLD-SINV"}],
		_ws_purchase_invoice_references: [],
		references: [
			{reference_doctype: "Sales Invoice", reference_name: "SINV-001"},
			{reference_doctype: "Purchase Invoice", reference_name: "PINV-001"},
			{reference_doctype: "Sales Invoice", reference_name: "SINV-002"},
			{reference_doctype: "Sales Invoice", reference_name: "SINV-001"}
		]
	},
	dashboard: {
		transactions_area: {
			find: function (selector) {
				const match = selector.match(/data-doctype="([^"]+)"/);
				return links[match[1]] || makeLink(match[1]);
			}
		}
	}
};

handlers.refresh(frm);
assert.deepStrictEqual(
	Object.keys(frm.doc).filter(function (key) {
		return key.indexOf("_ws_") === 0;
	}),
	[],
	"Dashboard state must never be stored as unknown fields on frm.doc"
);
assert.strictEqual(links["Sales Invoice"].visible, true);
assert.strictEqual(links["Sales Invoice"].attributes["data-names"], "SINV-001,SINV-002");
assert.strictEqual(links["Sales Invoice"].count, "2");
assert.strictEqual(links["Sales Invoice"].disabled, false);
assert.strictEqual(links["Purchase Invoice"].attributes["data-names"], "PINV-001",
	"Purchase Invoice links must not include Sales Invoice names");
assert.strictEqual(links["Sales Order"].visible, false,
	"Reference doctypes absent from this Payment Entry must stay hidden");

links["Sales Invoice"].attributes["data-names"] = "SINV-001,PINV-001,SINV-002";
links["Sales Invoice"].count = "3";
handlers.dashboard_update(frm);
assert.strictEqual(links["Sales Invoice"].attributes["data-names"], "SINV-001,SINV-002",
	"Dashboard update must correct Frappe's unfiltered Dynamic Link names");
assert.strictEqual(links["Sales Invoice"].count, "2");

console.log("Payment Entry reference dashboard behavior: OK");
