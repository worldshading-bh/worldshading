// Database-free tests: node worldshading/tests/test_fixed_expense_dialog.js
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
let handlers, dialog;
const frappe = {validated: true, msgprint: () => {}, ui: {form: {on: (dt, events) => { if (dt === "GL Payment") handlers = events; }},
    Dialog: function (options) { Object.assign(this, options); dialog = this;
        this.show = () => {}; this.hide = () => this.onhide(); }
}};
vm.runInNewContext(fs.readFileSync(__dirname + '/../public/js/fixed_expense_payment.js', 'utf8'), {
    frappe, __: s => s, precision: () => 3,
    flt: (n, p) => p === undefined ? Number(n || 0) : Number(Number(n || 0).toFixed(p))
});
function form(total, variable) {
    return {doc: {custom_fixed_expense: 'FEX', custom_expense_due_date: '2026-12-15',
        custom_expense_amount: 100, total_amount: total, docstatus: 0, workflow_state: 'Draft',
        custom_expense_snapshot: JSON.stringify({amount_type: variable ? 'Variable' : 'Fixed'})},
        is_new: () => true, toggle_reqd: () => {}, toggle_display: () => {}, set_df_property: () => {},
        set_value(values) { Object.assign(this.doc, values); return Promise.resolve(); },
        save() { this.saved = true; return Promise.resolve(); }};
}
async function run() {
    let frm = form(60);
    let pending = handlers.before_save(frm);
    assert.strictEqual(frappe.validated, false);
    assert.strictEqual(dialog.fields.find(f => f.fieldname === 'close_balance').hidden, false);
    dialog.primary_action({reason: ' ', close_balance: 1});
    assert.strictEqual(frm.doc.custom_adjustment_reason, undefined);
    dialog.primary_action({reason: 'Agreed reduction', close_balance: 1});
    await pending;
    assert.strictEqual(frm.doc.custom_adjustment_reason, 'Agreed reduction');
    assert.strictEqual(frm.doc.custom_close_remaining_balance, 1);
    assert.strictEqual(frappe.validated, true);
    const previous = dialog;
    await handlers.before_save(frm);
    assert.strictEqual(dialog, previous, 'same adjustment must not prompt twice');
    frm.doc.total_amount = 70;
    pending = handlers.before_save(frm);
    assert.notStrictEqual(dialog, previous, 'changed payment should ask again with prefilled reason');
    dialog.hide();
    await pending.then(() => { throw new Error('cancel must abort'); }, () => {});
    assert.strictEqual(frappe.validated, false);
    assert.strictEqual(frm.doc.custom_adjustment_reason, 'Agreed reduction');
    frappe.validated = true;
    frm = form(125);
    pending = handlers.before_save(frm);
    assert.strictEqual(dialog.fields.find(f => f.fieldname === 'close_balance').hidden, true);
    dialog.primary_action({reason: 'Additional charge', close_balance: 1});
    await pending;
    assert.strictEqual(frm.doc.custom_close_remaining_balance, 0);
    const overDialog = dialog;
    await handlers.before_save(form(60, true));
    await handlers.before_save(form(100));
    assert.strictEqual(dialog, overDialog, 'variable and exact payments do not prompt');
    frm = form(60);
    pending = handlers.before_workflow_action(frm);
    dialog.primary_action({reason: 'Partial payment', close_balance: 0});
    await pending;
    assert.strictEqual(frm.saved, true, 'workflow waits for values to be saved');
    frm = form(60);
    pending = handlers.before_workflow_action(frm);
    dialog.hide();
    await pending.then(() => { throw new Error('cancel must abort workflow'); }, () => {});
    assert.strictEqual(frm.saved, undefined);
    frappe.validated = true;
    const beforeTolerance = dialog;
    frm = form(99);
    frm.doc.custom_expense_snapshot = JSON.stringify({amount_type: 'Fixed', currency: 'USD',
        company_currency: 'BHD', currency_exchange_tolerance: 1, precision: 3});
    await handlers.before_save(frm);
    assert.strictEqual(dialog, beforeTolerance, 'small foreign difference must not prompt');
    frm.doc.total_amount = 98.999;
    pending = handlers.before_save(frm);
    assert.notStrictEqual(dialog, beforeTolerance, 'difference outside tolerance must prompt');
    dialog.primary_action({reason: 'Larger difference', close_balance: 0});
    await pending;
    console.log('Fixed Expense dialog checks: PASS');
}
run().catch(e => { console.error(e); process.exitCode = 1; });
