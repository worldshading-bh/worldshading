// Database-free form checks.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
let events;
const frappe = {ui: {form: {on(dt, handlers) { if (dt === 'Fixed Expense') events = handlers; }}},
    model: {can_create: () => true}};
vm.runInNewContext(fs.readFileSync(__dirname + '/../worldshading/doctype/fixed_expense/fixed_expense.js', 'utf8'),
    {frappe, __: text => text});
function form(state, status) {
    const fields = [{fieldname: 'status', fieldtype: 'Select', read_only: 0},
        {fieldname: 'accounts', fieldtype: 'Table', read_only: 0},
        {fieldname: 'estimated_base_total', fieldtype: 'Currency', read_only: 1}];
    return {doc: {workflow_state: state, status}, meta: {fields}, fields_dict: {},
        is_new: () => false, toggle_reqd: () => {}, buttons: [],
        add_custom_button(label) { this.buttons.push(label); },
        set_df_property(name, property, value) { fields.find(f => f.fieldname === name)[property] = value; }};
}
for (const state of ['Draft', 'Pending Expense - Chkr', 'Pending Expense - App', 'Approved']) {
    const frm = form(state, 'Active');
    events.refresh(frm);
    assert.strictEqual(frm.buttons.length, state === 'Approved' ? 1 : 0);
    assert.strictEqual(frm.meta.fields[1].read_only, state === 'Draft' ? 0 : 1);
    assert.strictEqual(frm.meta.fields[2].read_only, 1);
    frm.doc.workflow_state = 'Draft';
    events.refresh(frm);
    assert.strictEqual(frm.meta.fields[1].read_only, 0, 'returning to Draft unlocks details');
}
const closed = form('Approved', 'Closed');
events.refresh(closed);
assert.strictEqual(closed.buttons.length, 0);
console.log('Fixed Expense workflow form checks: PASS');
