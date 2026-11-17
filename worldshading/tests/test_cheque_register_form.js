// Database-free checks: node worldshading/tests/test_cheque_register_form.js
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const events = {};
const calls = [];
const frappe = {
    ui: {form: {on: (dt, handlers) => { events[dt] = handlers; }}},
    call: options => calls.push(options),
    msgprint: () => {},
    set_route: () => {}
};
['cheque_book', 'cheque_leaf'].forEach(name => {
    vm.runInNewContext(fs.readFileSync(__dirname + '/../public/js/' + name + '.js', 'utf8'),
        {frappe, __: text => text});
});
function form(is_new) {
    return {doc: {name: 'BOOK', status: 'Active'}, perm: [{write: 1}], fields: {}, buttons: {},
        is_new: () => is_new, is_dirty: () => false,
        set_df_property(name, prop, value) { this.fields[name] = value; },
        add_custom_button(label, callback) { this.buttons[label] = callback; }};
}
let frm = form(true);
frm.fields = {account: 1, first_leaf_no: 1, last_leaf_no: 1, book_name: 1};
events['Cheque Book'].refresh(frm);
assert.strictEqual(frm.fields.account, 0, 'A new book must not inherit readonly fields from a saved book');
assert.strictEqual(frm.fields.first_leaf_no, 0);
assert.strictEqual(calls.length, 0);
frm = form(true);
frm.fields = {cheque_book: 1, cheque_number: 1};
events['Cheque Leaf'].refresh(frm);
assert.strictEqual(frm.fields.cheque_number, 0, 'A new leaf must allow entry after viewing a saved leaf');
assert.strictEqual(frm.fields.cheque_book, 0);
frm = form(false);
events['Cheque Book'].refresh(frm);
frm.buttons['Generate Missing Leaves']();
assert.strictEqual(calls[calls.length - 1].method, 'worldshading.api.cheque_register.generate_leaves');
assert.strictEqual(calls[calls.length - 1].args.book_name, 'BOOK');
frm.is_dirty = () => true;
const before = calls.length;
frm.buttons['Generate Missing Leaves']();
assert.strictEqual(calls.length, before, 'Unsaved book changes must not generate leaves from stale values');
frm = form(false);
frm.doc.status = 'Available';
frm.doc.journal_entry = 'JV';
events['Cheque Leaf'].refresh(frm);
assert.strictEqual(frm.buttons['Cancel Unused Leaf'], undefined, 'A linked Journal Entry leaf cannot be cancelled as unused');
console.log('Cheque register form checks: PASS');
