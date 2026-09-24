frappe.ui.form.on("Pricing Strategy Template", {
	setup: function (frm) {
		frm.set_query("regular_price_list", function () {
			return {filters: {enabled: 1, selling: 1}};
		});
		frm.set_query("b2b_price_list", function () {
			return {filters: {enabled: 1, selling: 1}};
		});
		frm.set_query("indirect_expense_account", function () {
			return {
				filters: {
					company: frm.doc.company,
					root_type: "Expense",
					disabled: 0
				}
			};
		});
	},

	company: function (frm) {
		frm.set_value("indirect_expense_account", "");
	}
});
