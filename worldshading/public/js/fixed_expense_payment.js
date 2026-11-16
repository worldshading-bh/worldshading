(function () {
    "use strict";

    function is_variable(frm) {
        let snapshot = {};
        try { snapshot = JSON.parse(frm.doc.custom_expense_snapshot || "{}"); } catch (e) { /* Server verifies the snapshot. */ }
        return (frm._expense_amount_type || snapshot.amount_type) === "Variable";
    }

    function adjustment_key(frm) {
        return JSON.stringify([frm.doc.custom_fixed_expense, frm.doc.custom_expense_due_date,
            flt(frm.doc.custom_expense_amount), flt(frm.doc.total_amount)]);
    }

    function within_exchange_tolerance(frm) {
        let snapshot = {};
        try { snapshot = JSON.parse(frm.doc.custom_expense_snapshot || "{}"); } catch (e) { return false; }
        if (snapshot.amount_type !== "Fixed" || !snapshot.currency || !snapshot.company_currency ||
            snapshot.currency === snapshot.company_currency) return false;
        const digits = snapshot.precision === undefined ? precision("total_amount", frm.doc) : snapshot.precision;
        const difference = Math.abs(flt(flt(frm.doc.total_amount) - flt(frm.doc.custom_expense_amount), digits));
        const tolerance = flt(snapshot.currency_exchange_tolerance, digits);
        return flt(frm.doc.total_amount) > 0 && tolerance > 0 && difference > 0 && difference <= tolerance;
    }

    function collect_adjustment(frm, force) {
        const amount = flt(frm.doc.custom_expense_amount);
        const total = flt(frm.doc.total_amount);
        if (!frm.doc.custom_fixed_expense || is_variable(frm) || within_exchange_tolerance(frm) || total <= 0 ||
            flt(total - amount, precision("total_amount", frm.doc)) === 0) return Promise.resolve(false);
        const key = adjustment_key(frm);
        if (!force && (frm.doc.custom_adjustment_reason || "").trim() &&
            (!frm._fixed_adjustment_key || frm._fixed_adjustment_key === key)) return Promise.resolve(false);
        frappe.validated = false;
        return new Promise(function (resolve, reject) {
            let accepted = false;
            const dialog = new frappe.ui.Dialog({
                title: __("Payment Adjustment"),
                fields: [
                    {fieldname: "expense_amount", label: __("Expense Amount"), fieldtype: "Currency", read_only: 1, default: amount},
                    {fieldname: "payment_amount", label: __("Payment Amount"), fieldtype: "Currency", read_only: 1, default: total},
                    {fieldname: "reason", label: __("Adjustment Reason"), fieldtype: "Small Text", reqd: 1,
                        default: frm.doc.custom_adjustment_reason || ""},
                    {fieldname: "close_balance", label: __("Close Remaining Balance"), fieldtype: "Check",
                        hidden: total >= amount, default: total < amount ? frm.doc.custom_close_remaining_balance || 0 : 0}
                ],
                primary_action_label: __("Save"),
                primary_action: function (values) {
                    if (!values || !(values.reason || "").trim()) {
                        frappe.msgprint(__("Enter an Adjustment Reason."));
                        return;
                    }
                    if (adjustment_key(frm) !== key) {
                        frappe.msgprint(__("The payment amount changed. Close this dialog and save again."));
                        return;
                    }
                    Promise.resolve(frm.set_value({
                        custom_adjustment_reason: values.reason.trim(),
                        custom_close_remaining_balance: total < amount && values.close_balance ? 1 : 0
                    })).then(function () {
                        frm._fixed_adjustment_key = key;
                        accepted = true;
                        frappe.validated = true;
                        dialog.hide();
                        resolve(true);
                    }).catch(reject);
                },
                onhide: function () {
                    if (!accepted) {
                        frappe.validated = false;
                        reject(new Error("Payment adjustment cancelled."));
                    }
                }
            });
            dialog.show();
        });
    }

    function update_fields(frm) {
        const linked = Boolean(frm.doc.custom_fixed_expense);
        const variable = is_variable(frm);
        if (frm.fields_dict && frm.fields_dict.items) {
            const grid = frm.fields_dict.items.grid;
            ["account", "template_type", "tax_template"].forEach(function (field) {
                grid.toggle_enable(field, !linked);
            });
            grid.cannot_add_rows = linked;
            grid.refresh();
        }
        const draft = linked && frm.doc.docstatus === 0 && frm.doc.workflow_state === "Draft";
        frm.toggle_reqd("reference_date", !draft);
        frm.toggle_reqd("custom_expense_due_date", linked);
        frm.set_df_property("custom_expense_due_date", "read_only", !frm.is_new());
        if (linked && !frm.is_new()) frm.set_df_property("custom_fixed_expense", "read_only", 1);
        // The dialog collects these values; keep the saved choices visible for review.
        frm.toggle_reqd("custom_adjustment_reason", false);
        frm.set_df_property("custom_adjustment_reason", "read_only", 1);
        frm.set_df_property("custom_close_remaining_balance", "read_only", 1);
        frm.toggle_display("custom_close_remaining_balance", linked && !variable && Boolean(frm.doc.custom_close_remaining_balance));
        frm.toggle_display("custom_adjustment_reason", linked && !variable && Boolean(frm.doc.custom_adjustment_reason));
    }

    function fetch_amount(frm) {
        frm._expense_amount_type = null;
        update_fields(frm);
        if (!frm.is_new() || !frm.doc.custom_fixed_expense || !frm.doc.custom_expense_due_date) return;
        const expense = frm.doc.custom_fixed_expense;
        const due = frm.doc.custom_expense_due_date;
        frappe.call({
            method: "worldshading.api.fixed_expense_payments.payment_context",
            args: { source_name: expense, scheduled_due_date: due },
            callback: function (r) {
                if (!r.message || expense !== frm.doc.custom_fixed_expense || due !== frm.doc.custom_expense_due_date) return;
                frm._expense_amount_type = r.message.amount_type;
                frm.clear_table("items");
                (r.message.items || []).forEach(function (row) {
                    Object.assign(frm.add_child("items"), row);
                });
                frm.refresh_field("items");
                frm.set_value({
                    custom_expense_amount: r.message.expense_amount,
                    custom_expense_snapshot: r.message.expense_snapshot,
                    net_amount: (r.message.items || []).reduce(function (sum, row) { return sum + flt(row.net_amount); }, 0),
                    tax_amount: (r.message.items || []).reduce(function (sum, row) { return sum + flt(row.tax_amount); }, 0),
                    total_amount: r.message.expense_amount
                });
                update_fields(frm);
            }
        });
    }

    frappe.ui.form.on("GL Payment", {
        setup: function (frm) {
            frm.set_query("custom_fixed_expense", function () {
                return { filters: { company: frm.doc.company } };
            });
        },
        refresh: function (frm) {
            if (!frm.doc.__unsaved && (frm.doc.custom_adjustment_reason || "").trim()) {
                frm._fixed_adjustment_key = adjustment_key(frm);
            }
            update_fields(frm);
            if (frm.doc.docstatus === 0 && !is_variable(frm) && !within_exchange_tolerance(frm) && frm.doc.custom_fixed_expense &&
                (frm.doc.custom_adjustment_reason || "").trim() &&
                flt(frm.doc.total_amount - frm.doc.custom_expense_amount, precision("total_amount", frm.doc)) !== 0) {
                frm.add_custom_button(__("Edit Adjustment"), function () {
                    collect_adjustment(frm, true).then(function (changed) {
                        if (changed) return frm.save();
                    }).catch(function () { /* Closing the dialog leaves the document unchanged. */ });
                });
            }
        },
        before_save: function (frm) {
            if (frappe.validated === false) return;
            return collect_adjustment(frm);
        },
        before_workflow_action: function (frm) {
            return collect_adjustment(frm).then(function (changed) {
                if (changed) return frm.save();
            });
        },
        custom_fixed_expense: fetch_amount,
        custom_expense_due_date: fetch_amount,
        custom_expense_amount: update_fields,
        custom_close_remaining_balance: update_fields,
        total_amount: function (frm) {
            if (frm.doc.custom_close_remaining_balance &&
                flt(frm.doc.total_amount) >= flt(frm.doc.custom_expense_amount)) {
                frm.set_value("custom_close_remaining_balance", 0);
            }
            update_fields(frm);
        }
    });

    frappe.ui.form.on("GL Payment Item", {
        before_items_remove: function (frm) {
            if (frm.doc.custom_fixed_expense) {
                frappe.throw(__("Account rows are set by the Fixed Expense. Change only the payment amounts."));
            }
        }
    });
})();
