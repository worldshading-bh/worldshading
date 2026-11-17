/* Cheque inventory only; payment approvals remain on the payment documents. */
frappe.ui.form.on('Cheque Book', {
    setup: function(frm) {
        frm.set_query('account', function() {
            return {filters: {account_type: 'Bank', is_group: 0}};
        });
    },
    refresh: function(frm) {
        if (frm._cheque_inventory_section) {
            frm._cheque_inventory_section.remove();
            frm._cheque_inventory_section = null;
        }
        if (frm.is_new()) {
            ['account', 'first_leaf_no', 'last_leaf_no', 'book_name'].forEach(function(field) {
                frm.set_df_property(field, 'read_only', 0);
            });
            return;
        }
        const book_name = frm.doc.name;
        frm.add_custom_button(__('View Cheque Leaves'), function() {
            frappe.set_route('List', 'Cheque Leaf', {cheque_book: book_name});
        });
        if (frm.doc.status === 'Active' && frm.perm[0] && frm.perm[0].write) {
            frm.add_custom_button(__('Generate Missing Leaves'), function() {
                if (frm.is_dirty()) {
                    frappe.msgprint(__('Save the cheque book before generating leaves.'));
                    return;
                }
                frappe.call({
                    method: 'worldshading.api.cheque_register.generate_leaves',
                    args: {book_name: book_name},
                    freeze: true,
                    freeze_message: __('Generating cheque leaves...'),
                    callback: function(r) {
                        if (r.exc || !r.message) return;
                        frappe.msgprint(__('Created {0} cheque leaves. {1} already existed.',
                            [r.message.created, r.message.existing]));
                        frm.reload_doc();
                    }
                });
            });
        }
        frappe.call({
            method: 'worldshading.api.cheque_register.get_book_summary',
            args: {book_name: book_name},
            callback: function(r) {
                if (r.exc || !r.message || frm.doc.name !== book_name) return;
                if (frm._cheque_inventory_section) frm._cheque_inventory_section.remove();
                const summary = r.message;
                const cards = [
                    {label: __('Visible Leaves'), count: summary.total},
                    {label: __('Book Capacity'), count: summary.expected, capacity: true}
                ];
                ['Available', 'Reserved', 'Issued', 'Cleared', 'Cancelled', 'Bounced'].forEach(function(status) {
                    cards.push({label: __(status), count: summary.counts[status] || 0, status: status});
                });
                const html = '<div class="row">' + cards.map(function(card, index) {
                    return '<div class="col-xs-6 col-sm-3" style="margin-bottom:12px">' +
                        '<button class="btn btn-default btn-block" data-cheque-card="' + index + '">' +
                        '<strong>' + cint(card.count) + '</strong><br>' +
                        frappe.utils.escape_html(card.label) + '</button></div>';
                }).join('') + '</div>';
                frm.dashboard.show();
                frm._cheque_inventory_section = frm.dashboard.add_section(html);
                frm._cheque_inventory_section.find('[data-cheque-card]').on('click', function() {
                    const card = cards[Number($(this).attr('data-cheque-card'))];
                    if (card.capacity) {
                        frappe.msgprint(__('Book capacity is {0} leaves. Use Generate Missing Leaves to complete its inventory.',
                            [summary.expected]));
                        return;
                    }
                    const filters = {cheque_book: book_name};
                    if (card.status) filters.status = card.status;
                    frappe.set_route('List', 'Cheque Leaf', filters);
                });
                ['account', 'first_leaf_no', 'last_leaf_no', 'book_name'].forEach(function(field) {
                    frm.set_df_property(field, 'read_only', summary.total > 0 ? 1 : 0);
                });
            }
        });
    }
});
