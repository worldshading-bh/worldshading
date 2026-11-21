const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const events = {};
const queries = {};
const properties = {};
const frm = {doc: {company:'WS', currency:'BHD', workflow_state:'Draft'},
    meta: JSON.parse(fs.readFileSync('worldshading/worldshading/doctype/bank_loan/bank_loan.json')),
    set_query(name, fn) { queries[name] = fn(); },
    set_df_property(name, prop, value) { properties[name] = value; const field=this.meta.fields.find(f => f.fieldname===name); if (field) field[prop]=value; },
    set_value(values) { Object.assign(this.doc, values); return Promise.resolve(); },
    get_field() { return {grid: {cannot_add_rows:false, cannot_delete_rows:false}}; }};
const context = {frappe:{ui:{form:{on(name, handlers) {events[name] = handlers;}}},
    listview_settings:{}}, __: x => x};
vm.runInNewContext(fs.readFileSync('worldshading/worldshading/doctype/bank_loan/bank_loan.js','utf8'), context);
events['Bank Loan'].setup(frm);
assert.equal(queries.loan_account.filters.root_type, 'Liability');
assert.equal(queries.loan_account.filters.account_currency, 'BHD');
assert.equal(queries.loan_account.filters.company, 'WS');
assert.equal(queries.interest_account.filters.root_type, 'Expense');
assert.equal(queries.payment_account.filters.account_type, 'Bank');
events['Bank Loan'].refresh(frm);
assert.equal(properties.original_principal, 0);
frm.doc.workflow_state = 'Approved';
events['Bank Loan'].refresh(frm);
assert.equal(properties.original_principal, 1);
assert.equal(properties.schedule, 1);
frm.doc.workflow_state = 'Draft';
events['Bank Loan'].refresh(frm);
assert.equal(properties.original_principal, 0);
assert.equal(properties.schedule, 0);
vm.runInNewContext(fs.readFileSync('worldshading/worldshading/doctype/bank_loan/bank_loan_list.js','utf8'), context);
const list = context.frappe.listview_settings['Bank Loan'];
assert.equal(list.get_indicator({status:'Active'})[1], 'green');
assert.equal(list.get_indicator({status:'Inactive'})[1], 'orange');
frm.doc.loan_position = 'New Loan';
frm.doc.original_principal = 12000;
frm.doc.disbursement_date = '2026-11-19';
events['Bank Loan'].loan_position(frm);
assert.equal(frm.doc.opening_principal, 12000);
assert.equal(frm.doc.tracking_start_date, '2026-11-19');
frm.doc.original_principal = 15000;
events['Bank Loan'].original_principal(frm);
assert.equal(frm.doc.opening_principal, 15000);
frm.doc.loan_position = 'Existing Loan';
frm.doc.opening_principal = 6000;
frm.doc.tracking_start_date = '2026-12-01';
events['Bank Loan'].original_principal(frm);
assert.equal(frm.doc.opening_principal, 6000);
assert.equal(frm.doc.tracking_start_date, '2026-12-01');
frm.doc.loan_position = 'New Loan';
frm.doc.workflow_state = 'Approved';
events['Bank Loan'].disbursement_date(frm);
assert.equal(frm.doc.opening_principal, 6000);

const dialogs=[];
context.frappe.datetime={get_today:()=> '2026-11-19'};
context.frappe.ui.Dialog=class {
    constructor(config){this.config=config;dialogs.push(this);}
    show(){this.visible=true;}
    hide(){this.visible=false;if(this.config.onhide)this.config.onhide();}
};
(async()=>{
    const baseline={original_principal:'1000.000',annual_interest_rate:'6',maturity_date:'2027-01-01',
        schedule:[{name:'ROW-1',due_date:'2026-12-01',principal_amount:'1000.000',interest_amount:'10.000',charges_amount:'0.000'}]};
    frm.doc=Object.assign({},JSON.parse(JSON.stringify(baseline)),{workflow_state:'Draft',approved_plan:JSON.stringify(baseline)});
    frm.doc.original_principal=1000;frm.doc.annual_interest_rate=6;
    assert.equal(await events['Bank Loan'].validate(frm),true);assert.equal(dialogs.length,0);
    frm.doc.schedule[0].due_date='2027-02-01';
    const saving=events['Bank Loan'].validate(frm);
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(frm.doc.maturity_date,'2027-02-01');
    let dialog=dialogs[dialogs.length-1];assert(dialog.visible);
    assert(dialog.config.fields.some(f=>f.fieldname==='revision_date' && f.read_only && f.default==='2026-11-19'));
    await dialog.config.primary_action({reason:'Bank agreed extension'});
    assert.equal(await saving,true);assert(!dialog.visible);
    assert.equal(frm.doc.revision_reason,'Bank agreed extension');assert.equal(frm.doc.revision_effective_date,'2026-11-19');
    await events['Bank Loan'].validate(frm);assert.equal(dialogs.length,1);
    frm.doc.revision_reason='';context.frappe.validated=true;
    const cancelled=events['Bank Loan'].validate(frm);
    await new Promise(resolve=>setImmediate(resolve));
    dialogs[dialogs.length-1].hide();assert.equal(await cancelled,false);assert.equal(context.frappe.validated,false);
    const workflow=events['Bank Loan'].before_workflow_action(frm);
    await new Promise(resolve=>setImmediate(resolve));
    dialogs[dialogs.length-1].hide();await assert.rejects(workflow);
    frm.doc.workflow_state='Approved';assert.equal(await events['Bank Loan'].validate(frm),true);
    console.log('Bank Loan form, revision popup and list checks: PASS');
})().catch(err=>{console.error(err);process.exitCode=1;});
