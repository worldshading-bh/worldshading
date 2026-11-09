frappe.ui.form.on("Fixed Expense", {
	refresh: function (frm) {
		frm._expense_currency = frm.doc.currency;
		if (!frm.is_new() && frm.doc.status === "Active" && frappe.model.can_create("GL Payment")) {
			frm.add_custom_button(__("Create GL Payment"), function () {
				if (frm.is_dirty()) {
					frappe.msgprint(__("Save the Fixed Expense before creating a GL Payment."));
					return;
				}
				frappe.call({
					method: "worldshading.worldshading.doctype.fixed_expense.fixed_expense.make_gl_payment",
					args: { source_name: frm.doc.name },
					freeze: true,
					callback: function (response) {
						if (!response.message) return;
						frappe.model.with_doctype("GL Payment", function () {
							const payment = frappe.model.sync(response.message)[0];
							frappe.set_route("Form", "GL Payment", payment.name);
						});
					}
				});
			});
		}
		if (frm.fields_dict.estimated_base_total && frm.doc.company_currency) {
			frm.set_df_property("estimated_base_total", "label",
				__("Estimated Total ({0})", [frm.doc.company_currency]));
		}
	},
	currency: function (frm) {
		const previous = frm._expense_currency;
		frm._expense_currency = frm.doc.currency;
		if (previous && previous !== frm.doc.currency && (frm.doc.accounts || []).some(function (row) {
			return flt(row.net_amount) !== 0;
		})) {
			frappe.msgprint(__("Currency changed. Review the Accounts amounts in the selected currency; they have not been converted."));
		}
		calculate_expense_totals(frm);
	},

	setup: function (frm) {
		if (frm.fields_dict.accounts) {
			frm.set_query("account", "accounts", function () {
				return { filters: { company: frm.doc.company, root_type: "Expense",
					account_currency: frm.doc.company_currency, is_group: 0, disabled: 0 } };
			});
			frm.set_query("tax_template", "accounts", function () {
				return { filters: { company: frm.doc.company, disabled: 0 } };
			});
		}
		frm.set_query("cost_center", function () {
			return { filters: { company: frm.doc.company, is_group: 0 } };
		});
		frm.set_query("payment_account", function () {
			return { filters: { company: frm.doc.company,
				account_type: ["in", ["Bank", "Cash"]],
				account_currency: frm.doc.company_currency, is_group: 0, disabled: 0 } };
		});
	},

	company: function (frm) {
		["expense_account", "cost_center", "payment_account", "tax_template"].forEach(function (field) {
			if (frm.fields_dict[field]) frm.set_value(field, "");
		});
		(frm.doc.accounts || []).forEach(function (row) {
			frappe.model.set_value(row.doctype, row.name, { account: "", tax_template: "",
				rate: 0, account_head: "", tax_amount: 0 });
		});
		calculate_expense_totals(frm);
	}
});

frappe.ui.form.on("Recurring Expense Account", {
	accounts_add: calculate_expense_totals,
	accounts_remove: calculate_expense_totals,
	net_amount: calculate_expense_totals,
	tax_template: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const template = row.tax_template;
		const company = frm.doc.company;
		row.rate = 0;
		row.account_head = "";
		calculate_expense_totals(frm);
		if (!template || !company) return;
		return frappe.call({
			method: "worldshading.worldshading.doctype.fixed_expense.fixed_expense.get_expense_tax",
			args: { company: company, tax_template: template },
			callback: function (response) {
				if (!response.message || frm.doc.company !== company
					|| row.tax_template !== template || !(frm.doc.accounts || []).includes(row)) return;
				row.rate = response.message.rate;
				row.account_head = response.message.account_head;
				calculate_expense_totals(frm);
			}
		});
	}
});

function calculate_expense_totals(frm) {
	if (!frm.fields_dict.accounts) return;
	let net = 0;
	let tax = 0;
	(frm.doc.accounts || []).forEach(function (row) {
		row.currency = frm.doc.currency;
		const row_net = flt(row.net_amount, precision("net_amount", row));
		row.tax_amount = flt(row_net * flt(row.rate) / 100, precision("tax_amount", row));
		row.total_amount = flt(row_net + row.tax_amount,
			precision("total_amount", row));
		net += row_net;
		tax += row.tax_amount;
	});
	frm.set_value({
		expected_amount: flt(net, precision("expected_amount", frm.doc)),
		expected_tax_amount: flt(tax, precision("expected_tax_amount", frm.doc)),
		expected_total_amount: flt(net + tax, precision("expected_total_amount", frm.doc))
	});
	frm.refresh_field("accounts");
}
