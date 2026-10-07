(function () {
	"use strict";

	var reference_links = [
		["Sales Invoice", "_ws_sales_invoice_references"],
		["Purchase Invoice", "_ws_purchase_invoice_references"],
		["Sales Order", "_ws_sales_order_references"],
		["Purchase Order", "_ws_purchase_order_references"],
		["Journal Entry", "_ws_journal_entry_references"],
		["Expense Claim", "_ws_expense_claim_references"],
		["Employee Advance", "_ws_employee_advance_references"],
		["Fees", "_ws_fees_references"]
	];

	frappe.ui.form.on("Payment Entry", {
		before_load: configure_reference_links,
		refresh: configure_reference_links,
		dashboard_update: configure_reference_links
	});

	function configure_reference_links(frm) {
		var references = frm.doc.references || [];

		reference_links.forEach(function (link) {
			var doctype = link[0];
			var legacy_fieldname = link[1];
			var names = get_reference_names(references, doctype);

			delete frm.doc[legacy_fieldname];
			update_dashboard_link(frm, doctype, names);
		});
	}

	function get_reference_names(references, doctype) {
		var names = [];

		references.forEach(function (row) {
			if (row.reference_doctype === doctype && row.reference_name &&
				names.indexOf(row.reference_name) === -1) {
				names.push(row.reference_name);
			}
		});

		return names;
	}

	function update_dashboard_link(frm, doctype, names) {
		if (!frm.dashboard || !frm.dashboard.transactions_area) {
			return;
		}

		var link = frm.dashboard.transactions_area.find(
			'.document-link[data-doctype="' + doctype + '"]'
		);

		link.toggle(names.length > 0);
		link.attr("data-names", names.join(","));
		link.find(".count")
			.text(names.length)
			.toggleClass("hidden", names.length === 0);
		link.find(".badge-link").attr("disabled", names.length === 0);
	}
})();
