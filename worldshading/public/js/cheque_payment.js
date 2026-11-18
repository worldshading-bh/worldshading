/* Signing confirms the physical cheque; existing workflows still post accounts. */
(function() {
    if (frappe.ws_cheque_payment_registered) return;
    frappe.ws_cheque_payment_registered = true;
    const confirmation_field = 'custom_cheque_signing_confirmation';
    function is_outgoing_cheque(frm) {
        return frm.doc.mode_of_payment === 'Cheque' &&
            frm.doc.payment_type === (frm.doctype === 'Payment Entry' ? 'Pay' : 'Outgoing');
    }
    function cheque_action(frm) {
        if (!is_outgoing_cheque(frm)) return null;
        const state = frm.doc.workflow_state;
        if (frm.selected_workflow_action === 'Void Cheque' && frm.doc.docstatus === 0 &&
                (state === 'Pending Reconciliation' || (frm.doctype === 'Payment Entry' &&
                ['Handover Security Cheque', 'Security Cheque Issued'].includes(state)))) return 'void';
        if (frm.doctype === 'GL Payment') {
            return state === 'Pending Cheque Payment - App' && frm.selected_workflow_action === 'Paid' ? 'sign' : null;
        }
        return ['Pending Cheque Payment - App', 'Pending Security Cheque - App'].includes(state) &&
            frm.selected_workflow_action === 'Approve' ? 'sign' : null;
    }
    function save_confirmation(frm, expected) {
        // v12 frm.save catches failures, so a resolved promise alone is not
        // evidence of persistence. Require its successful response callback.
        return new Promise(function(resolve, reject) {
            let responded = false;
            const saved = frm.save('Save', function(response) {
                responded = true;
                const doc = response && !response.exc && response.docs && response.docs.find(function(row) {
                    return row.doctype === frm.doctype && row.name === frm.doc.name;
                });
                let acknowledgement;
                try { acknowledgement = doc && JSON.parse(doc[confirmation_field]); } catch (error) { /* invalid reply */ }
                const keys = ['leaf', 'account', 'company', 'currency', 'party_type', 'party', 'payee', 'amount', 'cheque_date'];
                if (!acknowledgement || acknowledgement.user !== frappe.session.user ||
                        acknowledgement.operation !== expected.operation ||
                        !acknowledgement.details || !keys.every(function(key) {
                            return String(acknowledgement.details[key]) === String(expected[key]);
                        })) {
                    reject(new Error('Cheque confirmation was not saved for the displayed details'));
                    return;
                }
                resolve();
            }, null, function() {
                responded = true;
                reject(new Error('Payment save failed'));
            });
            if (saved && saved.then) saved.then(function() {
                if (!responded) reject(new Error('Payment was not saved'));
            }, reject);
        });
    }
    function confirm_signing(frm) {
        const operation = cheque_action(frm);
        if (!operation) return;
        const voiding = operation === 'void';
        frappe.validated = false;
        if (frm.is_dirty()) {
            frappe.msgprint(__('Save the payment before confirming cheque signing.'));
            return Promise.reject(new Error('Save payment first'));
        }
        return new Promise(function(resolve, reject) {
            frappe.call({
                method: 'worldshading.api.cheque_payments.get_signing_details',
                args: {doctype: frm.doctype, name: frm.doc.name, operation: operation},
                error: reject,
                callback: function(response) {
                    if (response.exc || !response.message) {
                        reject(new Error('Cheque details unavailable'));
                        return;
                    }
                    const details = response.message;
                    if (details.operation !== operation) {
                        reject(new Error('Unexpected cheque action'));
                        return;
                    }
                    // The server verified the cancelled original, ownership and
                    // unchanged physical cheque. Existing approvals still run.
                    if (!voiding && details.already_cleared === true) {
                        frappe.validated = true;
                        resolve();
                        return;
                    }
                    const rows = [
                        [__('Cheque'), details.cheque_number + ' (' + details.leaf + ')'],
                        [__('Bank Account'), details.account],
                        [__('Payee'), details.payee],
                        [__('Amount'), details.currency + ' ' + details.amount],
                        [__('Cheque Date'), details.cheque_date]
                    ];
                    const html = rows.map(function(row) {
                        return '<p><strong>' + frappe.utils.escape_html(row[0]) + ':</strong> ' +
                            frappe.utils.escape_html(String(row[1] || '')) + '</p>';
                    }).join('');
                    const old_confirmation = frm.doc[confirmation_field];
                    let completed = false, saving = false;
                    const fields = [{fieldtype: 'HTML', fieldname: 'cheque_details', options: html}];
                    if (voiding) fields.push({fieldtype: 'Small Text', fieldname: 'void_reason',
                        reqd: 1, label: __('Reason for voiding this cheque')});
                    fields.push({fieldtype: 'Check', fieldname: voiding ? 'confirm_void' : 'confirm_signed', reqd: 1,
                        label: voiding ? __('I confirm the old cheque is unusable or stopped with the bank and will not be used') :
                            __('I confirm that this physical cheque has been signed')});
                    const dialog = new frappe.ui.Dialog({
                        title: voiding ? __('Void Cheque and Prepare Replacement') : __('Confirm Cheque Signed'),
                        fields: fields,
                        primary_action_label: voiding ? __('Void Cheque and Continue') : __('Confirm Signed and Continue'),
                        primary_action: function(values) {
                            if (saving) return;
                            if (!(voiding ? values.confirm_void : values.confirm_signed)) {
                                frappe.msgprint(__('Please confirm the cheque action before continuing.'));
                                return;
                            }
                            const reason = String(values.void_reason || '').trim();
                            if (voiding && (!reason || reason.length > 500)) {
                                frappe.msgprint(__('Enter a void reason of 1 to 500 characters.'));
                                return;
                            }
                            if (frm.is_dirty()) {
                                frappe.msgprint(__('The payment changed. Save it and review the cheque again.'));
                                return;
                            }
                            saving = true;
                            frappe.validated = true;
                            return frm.set_value(confirmation_field, voiding ? 'void:' + reason : 'confirm')
                                .then(function() { return save_confirmation(frm, details); })
                                .then(function() {
                                    if (completed) return;
                                    completed = true;
                                    dialog.hide();
                                    frappe.validated = true;
                                    resolve();
                                }).catch(function(error) {
                                    completed = true;
                                    dialog.hide();
                                    frappe.validated = false;
                                    return frm.set_value(confirmation_field, old_confirmation)
                                        .then(function() { reject(error); });
                                });
                        }
                    });
                    dialog.onhide = function() {
                        if (!completed) {
                            completed = true;
                            frappe.validated = false;
                            reject(new Error('Cheque signing confirmation cancelled'));
                        }
                    };
                    dialog.show();
                }
            });
        });
    }
    ['Payment Entry', 'GL Payment'].forEach(function(doctype) {
        frappe.ui.form.on(doctype, {
            setup: function(frm) {
                frm.set_query('cheque_leaf', function() {
                    return {filters: {
                        account: (frm.doctype === 'Payment Entry' ? frm.doc.paid_from : frm.doc.payment_account) || '',
                        company: frm.doc.company || '', status: 'Available', signed: 0, damaged: 0
                    }};
                });
            },
            cheque_leaf: function(frm) {
                if (!is_outgoing_cheque(frm)) return;
                const leaf = frm.doc.cheque_leaf;
                if (!leaf) return frm.set_value('reference_no', '');
                return frappe.db.get_value('Cheque Leaf', leaf, 'cheque_number').then(function(response) {
                    if (frm.doc.cheque_leaf === leaf && response.message) {
                        return frm.set_value('reference_no', response.message.cheque_number);
                    }
                });
            },
            before_workflow_action: confirm_signing
        });
    });
})();
