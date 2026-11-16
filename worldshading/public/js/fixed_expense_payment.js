(function () {
    "use strict";

    function update_fields(frm) {
        const linked = Boolean(frm.doc.custom_fixed_expense);
        let snapshot = {};
        try { snapshot = JSON.parse(frm.doc.custom_expense_snapshot || "{}"); } catch (e) { /* Server verifies the snapshot. */ }
        const variable = (frm._expense_amount_type || snapshot.amount_type) === "Variable";
        const draft = linked && frm.doc.docstatus === 0 && frm.doc.workflow_state === "Draft";
        frm.toggle_reqd("reference_date", !draft);
        frm.toggle_reqd("custom_expense_due_date", linked);
        frm.set_df_property("custom_expense_due_date", "read_only", !frm.is_new());
        if (linked && !frm.is_new()) frm.set_df_property("custom_fixed_expense", "read_only", 1);
        const amount = flt(frm.doc.custom_expense_amount);
        const total = flt(frm.doc.total_amount);
        const digits = precision("total_amount", frm.doc);
        const different = linked && flt(total - amount, digits) !== 0;
        frm.toggle_reqd("custom_adjustment_reason", !variable && (different || Boolean(frm.doc.custom_close_remaining_balance)));
        frm.toggle_display("custom_close_remaining_balance", linked && !variable && total > 0 && total < amount);
        frm.toggle_display("custom_adjustment_reason", linked && !variable);
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
                frm.set_value("custom_expense_amount", r.message.expense_amount);
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
        refresh: update_fields,
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
})();
