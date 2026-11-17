frappe.ui.form.on('Cheque Leaf', {
    refresh: function(frm) {
        if (frm.doc.cheque_book) {
            frm.add_custom_button(__('Open Cheque Book'), function() {
                frappe.set_route('Form', 'Cheque Book', frm.doc.cheque_book);
            });
        }
        ['cheque_book', 'cheque_number'].forEach(function(field) {
            frm.set_df_property(field, 'read_only', frm.is_new() ? 0 : 1);
        });
        if (frm.is_new()) return;
        const linked = frm.doc.payment_entry || frm.doc.gl_payment || frm.doc.journal_entry;
        if (frm.doc.status !== 'Available' || linked || !frm.perm[0] || !frm.perm[0].write) return;
        frm.add_custom_button(__('Cancel Unused Leaf'), function() {
            if (frm.is_dirty()) {
                frappe.msgprint(__('Save the cheque leaf before cancelling it.'));
                return;
            }
            const dialog = new frappe.ui.Dialog({
                title: __('Cancel Unused Cheque Leaf'),
                fields: [
                    {fieldname: 'reason', label: __('Reason'), fieldtype: 'Small Text', reqd: 1},
                    {fieldname: 'damaged', label: __('Damaged'), fieldtype: 'Check', default: 0}
                ],
                primary_action_label: __('Cancel Leaf'),
                primary_action: function(values) {
                    frappe.call({
                        method: 'worldshading.api.cheque_register.cancel_unused_leaf',
                        args: {leaf_name: frm.doc.name, reason: values.reason, damaged: values.damaged || 0},
                        freeze: true,
                        callback: function(r) {
                            if (r.exc) return;
                            dialog.hide();
                            frm.reload_doc();
                        }
                    });
                }
            });
            dialog.show();
        });
    }
});
