frappe.ui.form.on('Cheque Leaf', {
    refresh: function(frm) {
        frm.set_df_property('damaged', 'read_only', 1);
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
        if (frm.doc.status !== 'Available' || frm.doc.signed || linked || !frm.perm[0] || !frm.perm[0].write) return;
        frm.add_custom_button(__('Cancel Unused Leaf'), function() {
            if (frm.is_dirty()) {
                frappe.msgprint(__('Save the cheque leaf before cancelling it.'));
                return;
            }
            let damage_file = null, completed = false, saving = false;
            const dialog = new frappe.ui.Dialog({
                title: __('Cancel Unused Cheque Leaf'),
                fields: [
                    {fieldname: 'reason', label: __('Reason'), fieldtype: 'Small Text', reqd: 1},
                    {fieldname: 'damaged', label: __('Damaged'), fieldtype: 'Check', default: 0},
                    {fieldname: 'damage_upload', fieldtype: 'HTML',
                        options: '<p>' + __('A photo or document is required when Damaged is selected. It will be saved privately on this leaf.') + '</p><div class="damage-upload-area"></div>'}
                ],
                primary_action_label: __('Cancel Leaf'),
                primary_action: function(values) {
                    if (completed || saving) return;
                    if (frm.is_dirty()) { frappe.msgprint(__('Save the changed cheque leaf before cancelling.')); return; }
                    const reason = String(values.reason || '').trim();
                    if (!reason) { frappe.msgprint(__('Enter a cancellation reason.')); return; }
                    if (values.damaged && !damage_file) {
                        frappe.msgprint(__('Upload the damaged cheque photo or document before continuing.'));
                        return;
                    }
                    saving = true;
                    frappe.call({
                        method: 'worldshading.api.cheque_register.cancel_unused_leaf',
                        args: {leaf_name: frm.doc.name, reason: reason, damaged: values.damaged || 0, damage_file: values.damaged ? damage_file : null},
                        freeze: true,
                        callback: function(r) {
                            saving = false;
                            if (r.exc || r.message !== frm.doc.name) return;
                            completed = true;
                            dialog.hide();
                            frm.reload_doc();
                        },
                        error: function() { saving = false; }
                    });
                }
            });
            dialog.onhide = function() { completed = true; };
            dialog.show();
            new frappe.ui.FileUploader({
                doctype: 'Cheque Leaf', docname: frm.doc.name,
                wrapper: dialog.fields_dict.damage_upload.$wrapper.find('.damage-upload-area'), disable_file_browser: true,
                method: 'worldshading.api.cheque_register.upload_damaged_leaf_attachment',
                on_success: function(file) { if (!completed && file && file.name) damage_file = file.name; }
            });
        });
    }
});
