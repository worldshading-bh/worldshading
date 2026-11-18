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
        if (frm._payment_attachment_section) frm._payment_attachment_section.remove();
        const request = {};
        frm._payment_attachment_request = request;
        const owner = frm.doc.payment_entry || frm.doc.gl_payment || frm.doc.journal_entry;
        if (owner) {
            const section = frm.dashboard.add_section('<h6>' + __('Payment Attachments') + '</h6><p class="text-muted">' + __('Loading...') + '</p>');
            frm._payment_attachment_section = section;
            frm.dashboard.show();
            frappe.call({
                method: 'worldshading.api.cheque_payments.get_leaf_attachments',
                args: {leaf_name: frm.doc.name},
                callback: function(r) {
                    if (frm._payment_attachment_request !== request) return;
                    const data = r.message || {};
                    const escape = frappe.utils.escape_html;
                    const files = (data.files || []).filter(function(file) {
                        return /^(\/files\/|\/private\/files\/|https?:\/\/)/.test(file.file_url || '');
                    });
                    let html = '<h6>' + __('Payment Attachments') + '</h6>';
                    if (data.payment_name) html += '<p class="text-muted">' + escape(data.payment_type + ': ' + data.payment_name) + '</p>';
                    if (data.restricted) html += '<p class="text-muted">' + __('You do not have permission to view this payment’s attachments.') + '</p>';
                    else if (!files.length) html += '<p class="text-muted">' + __('No payment attachments yet.') + '</p>';
                    else html += '<ul>' + files.map(function(file) {
                        return '<li><a target="_blank" rel="noopener noreferrer" href="' + escape(file.file_url).replace(/"/g, '&quot;').replace(/'/g, '&#39;') + '">' +
                            escape(file.file_name || file.file_url) + '</a></li>';
                    }).join('') + '</ul>';
                    section.html(html);
                },
                error: function() {
                    if (frm._payment_attachment_request === request) section.html('<p class="text-muted">' + __('Unable to load payment attachments.') + '</p>');
                }
            });
        }
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
