frappe.ui.form.on('Journal Entry', {
    setup: function (frm) {
        frm.set_query('custom_bank_loan', function () {
            return {filters: {company: frm.doc.company, workflow_state: 'Approved', status: 'Active'}};
        });
    },
    refresh: function (frm) {
        if (frm.fields_dict.custom_bank_loan && frm.doc.custom_bank_loan) {
            frm.set_df_property('custom_bank_loan', 'read_only', frm.is_new() ? 0 : 1);
            const maker = frappe.session.user === 'Administrator' || (frappe.user_roles || []).includes('Maker - ACC (Workflow)');
            if (!frm.is_new() && Number(frm.doc.docstatus) === 0 && maker) {
                frm.add_custom_button(__('Adjust Loan Payment'), function () { bank_loan_adjust_draft(frm); });
            }
        }
    }
});


function bank_loan_adjust_draft(frm) {
    if (frm.is_dirty()) { frappe.msgprint(__('Save or reload the JV before adjusting its loan payment.')); return; }
    const snapshot = JSON.stringify(frm.doc);
    frappe.call({method: 'worldshading.api.bank_loan_payments.get_draft_payment', args: {journal: frm.doc.name},
        callback: function (reply) {
            if (!reply.message || snapshot !== JSON.stringify(frm.doc) || frm.is_dirty()) return;
            const data = reply.message;
            const labels = {};
            data.schedule.forEach(function (row, i) { labels[row.name] = (i + 1) + ' — ' + frappe.datetime.str_to_user(row.due_date); });
            const rows = data.allocations.map(function (row, i) {
                return Object.assign({}, row, {name: 'loan-adjust-' + i, idx: i + 1,
                    installment_label: labels[row.installment] || __('Before Tracking')});
            });
            const dialog = new frappe.ui.Dialog({title: __('Adjust Loan Payment'), fields: [
                {fieldname: 'posting_date', label: __('Payment Date'), fieldtype: 'Date', reqd: 1, default: data.posting_date},
                {fieldname: 'bank_account', label: __('Paying Bank Account'), fieldtype: 'Link', options: 'Account', reqd: 1,
                    default: data.bank_account, get_query: function () { return {filters: {company: data.company,
                        account_currency: data.currency, account_type: 'Bank', is_group: 0, disabled: 0}}; }},
                {fieldname: 'allocations', label: __('Payment Breakdown'), fieldtype: 'Table', data: rows,
                    cannot_add_rows: true, cannot_delete_rows: true,
                    fields: [
                        {fieldname: 'installment', fieldtype: 'Data', hidden: 1},
                        {fieldname: 'installment_label', label: __('Installment'), fieldtype: 'Data', read_only: 1, in_list_view: 1, columns: 3},
                        {fieldname: 'principal_amount', label: __('Principal'), fieldtype: 'Currency', in_list_view: 1, columns: 3},
                        {fieldname: 'interest_amount', label: __('Interest'), fieldtype: 'Currency', in_list_view: 1, columns: 2},
                        {fieldname: 'charges_amount', label: __('Charges'), fieldtype: 'Currency', in_list_view: 1, columns: 2},
                        {fieldname: 'booked_interest', label: __('Interest Already Booked in Loan Liability'), fieldtype: 'Currency'},
                        {fieldname: 'booked_charges', label: __('Charges Already Booked in Loan Liability'), fieldtype: 'Currency'}]},
                {fieldname: 'reason', label: __('Reason for Adjustment'), fieldtype: 'Small Text', reqd: 1, default: data.reason}
            ], primary_action_label: __('Save Payment'), primary_action: function (values) {
                if (!values) return;
                if (frm.is_dirty() || snapshot !== JSON.stringify(frm.doc)) {
                    frappe.msgprint(__('The JV changed. Reload it and reopen payment adjustment.')); return;
                }
                frappe.call({method: 'worldshading.api.bank_loan_payments.update_draft_payment', freeze: true,
                    args: {journal: frm.doc.name, modified: data.modified, posting_date: values.posting_date,
                        bank_account: values.bank_account, reason: values.reason, allocations: JSON.stringify(values.allocations || [])},
                    callback: function (result) { if (result.message) { dialog.hide(); frm.reload_doc(); } }});
            }});
            dialog.show();
        }});
}
