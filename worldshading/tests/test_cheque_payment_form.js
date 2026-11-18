// Database-free form behaviour: node worldshading/tests/test_cheque_payment_form.js
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const events = {};
const calls = [];
let dialog, failSave = false, silentSave = false;
const details = {leaf: 'CL-1', cheque_number: '000101', account: 'Bank', company: 'Company',
    party_type: 'Supplier', party: 'SUP', payee: '<img src=x onerror=alert(1)>', amount: 100,
    currency: 'BHD', cheque_date: '2026-11-20'};
const frappe = {
    validated: true,
    session: {user: 'approver'},
    ui: {form: {on: (dt, handlers) => { events[dt] = handlers; }},
        Dialog: function(options) {
            Object.assign(this, options); dialog = this;
            this.show = () => {};
            this.hide = () => { if (this.onhide) this.onhide(); };
        }},
    utils: {escape_html: value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')},
    msgprint: () => {},
    call: options => {
        calls.push(options);
        options.callback({message: details});
    }
};
vm.runInNewContext(fs.readFileSync(__dirname + '/../public/js/cheque_payment.js', 'utf8'),
    {frappe, __: value => value});
function form(dt, state, action) {
    return {doctype: dt, doc: {doctype: dt, name: dt === 'Payment Entry' ? 'PE-1' : 'GL-1',
        payment_type: dt === 'Payment Entry' ? 'Pay' : 'Outgoing', mode_of_payment: 'Cheque',
        workflow_state: state, cheque_leaf: 'CL-1'}, selected_workflow_action: action,
        is_dirty: () => false, saves: 0,
        set_value(field, value) { this.doc[field] = value; return Promise.resolve(); },
        save(action, callback, btn, on_error) {
            this.saves++;
            // v12 catches save errors; its returned promise can still resolve.
            if (silentSave) return Promise.resolve();
            if (failSave) {
                if (on_error) on_error();
                if (callback) callback({exc: 'Save failed'});
            } else if (callback) {
                assert.strictEqual(action, 'Save');
                assert.strictEqual(this.doc.custom_cheque_signing_confirmation, 'confirm');
                this.doc.custom_cheque_signing_confirmation = JSON.stringify({user: 'approver', details: details});
                callback({docs: [Object.assign({}, this.doc)]});
            }
            return Promise.resolve();
        }};
}
async function run() {
    for (const dt of ['Payment Entry', 'GL Payment']) {
        let frm = form(dt, 'Pending Cheque Payment - App', dt === 'Payment Entry' ? 'Approve' : 'Paid');
        const before = calls.length;
        let pending = events[dt].before_workflow_action(frm);
        assert.strictEqual(frappe.validated, false);
        assert.strictEqual(calls.length, before + 1);
        assert.strictEqual(frm.saves, 0);
        assert.ok(dialog.fields.some(f => f.fieldname === 'confirm_signed' && f.reqd));
        const markup = dialog.fields.find(f => f.fieldtype === 'HTML').options;
        assert.ok(markup.includes('&lt;img'));
        assert.ok(!markup.includes('<img'));
        dialog.primary_action({confirm_signed: 0});
        assert.strictEqual(frm.saves, 0, 'Unchecked signing cannot continue');
        await dialog.primary_action({confirm_signed: 1});
        await pending;
        assert.strictEqual(frm.saves, 1);
        assert.ok(frm.doc.custom_cheque_signing_confirmation);
        assert.strictEqual(frappe.validated, true);

        frm = form(dt, 'Pending Cheque Payment - App', dt === 'Payment Entry' ? 'Approve' : 'Paid');
        pending = events[dt].before_workflow_action(frm);
        const cancelled = pending.then(() => { throw new Error('Cancelled dialog resolved'); }, () => {});
        dialog.hide(); await cancelled;
        assert.strictEqual(frm.saves, 0);
        assert.strictEqual(frm.doc.custom_cheque_signing_confirmation, undefined);
    }
    let frm = form('Payment Entry', 'Pending Bank Payment - App', 'Approve');
    assert.strictEqual(events['Payment Entry'].before_workflow_action(frm), undefined);
    frm = form('Payment Entry', 'Pending Cheque Payment - App', 'Approve');
    frm.doc.payment_type = 'Receive';
    assert.strictEqual(events['Payment Entry'].before_workflow_action(frm), undefined);
    frm = form('GL Payment', 'Pending Cheque Payment - App', 'Paid');
    failSave = true;
    const pending = events['GL Payment'].before_workflow_action(frm);
    const rejected = pending.then(() => { throw new Error('Failed save resolved workflow'); }, () => {});
    await dialog.primary_action({confirm_signed: 1});
    await rejected;
    assert.ok(!frm.doc.custom_cheque_signing_confirmation);
    assert.strictEqual(frappe.validated, false);
    failSave = false; silentSave = true;
    frm = form('Payment Entry', 'Pending Cheque Payment - App', 'Approve');
    const silent = events['Payment Entry'].before_workflow_action(frm);
    const silentRejected = silent.then(() => { throw new Error('Unconfirmed save continued workflow'); }, () => {});
    await dialog.primary_action({confirm_signed: 1});
    await silentRejected;
    console.log('Cheque signing form checks: PASS');
}
run().catch(error => { console.error(error); process.exit(1); });
