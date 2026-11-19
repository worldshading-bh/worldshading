frappe.ui.form.on('Journal Entry', {
    setup: function (frm) {
        frm.set_query('custom_bank_loan', function () {
            return {filters: {company: frm.doc.company, workflow_state: 'Approved', status: 'Active'}};
        });
    },
    refresh: function (frm) {
        if (frm.fields_dict.custom_bank_loan && frm.doc.custom_bank_loan) {
            frm.set_df_property('custom_bank_loan', 'read_only', frm.is_new() ? 0 : 1);
        }
    }
});
