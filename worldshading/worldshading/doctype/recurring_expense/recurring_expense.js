frappe.ui.form.on("Recurring Expense", {
	setup: function (frm) {
		frm.set_query("expense_account", function () {
			return {
				filters: {
					company: frm.doc.company,
					root_type: "Expense",
					is_group: 0,
					disabled: 0
				}
			};
		});
	},

	company: function (frm) {
		frm.set_value("expense_account", "");
	},

	billing_currency: function (frm) {
		if (!frm.doc.billing_currency) {
			frm.set_value("provider_amount", 0);
		}
	}
});
