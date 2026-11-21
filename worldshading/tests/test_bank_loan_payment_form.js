const assert=require('assert'),fs=require('fs'),vm=require('vm');
const events={};let output='',calls=0;const buttons=[],actions={};
const status={precision:3,currency:'BHD',principal_paid:100,interest_paid:10,charges_paid:2,total_paid:112,
 outstanding_principal:900,all_linked_cash_paid:224,plan_approved:true,needs_reschedule:false,
 installments:[{name:'ROW-1',due_date:'2026-12-19',remaining:50,paid:{principal_amount:100,interest_amount:10,charges_amount:2}}],
 history:[{name:'JV-1',posting_date:'2026-12-19',docstatus:1,principal:100,interest:10,charges:2,cash:112,before_tracking:false,installments:['ROW-1']}]};
const context={frappe:{session:{user:'maker@example.com'},user_roles:['Maker - ACC (Workflow)'],
 ui:{form:{on(name,handlers){events[name]=handlers;}}},utils:{escape_html:s=>String(s).replace(/</g,'&lt;')},
 call:options=>{calls++;options.callback({message:status});}},__:s=>s};
vm.runInNewContext(fs.readFileSync('worldshading/public/js/bank_loan_payments.js','utf8'),context);
const frm={doc:{name:'LOAN-1',workflow_state:'Approved',status:'Active'},is_new:()=>false,
 fields_dict:{payment_history:{$wrapper:{html:s=>output=s}}},add_custom_button:(label,fn)=>{buttons.push(label);actions[label]=fn;}};
events['Bank Loan'].refresh(frm);assert(buttons.includes('Create / Link Payment JV'));
assert.equal(calls,0);assert(!buttons.includes('Load Payment Tracking'));assert.equal(typeof events['Bank Loan'].load_payment_tracking,'function');
events['Bank Loan'].load_payment_tracking(frm);assert.equal(calls,1);assert(output.includes('900.000'));
assert.equal((output.match(/<table /g)||[]).length,1);assert(!output.includes('Linked JV History'));assert(output.includes('JV-1'));assert(output.includes('Posted'));assert(output.includes('Remaining Commitment'));
buttons.length=0;frm.doc.workflow_state='Draft';events['Bank Loan'].refresh(frm);assert(!buttons.includes('Create / Link Payment JV'));assert(!buttons.includes('Load Payment Tracking'));assert.equal(typeof events['Bank Loan'].load_payment_tracking,'function');
assert.equal(calls,1);assert(!output.includes('JV-1'));
status.outstanding_principal=800;events['Bank Loan'].load_payment_tracking(frm);assert.equal(calls,2);assert(output.includes('800.000'));
status.currency='<script>';assert(!context.bank_loan_payment_html(status).includes('<script>'));
const meta=JSON.parse(fs.readFileSync('worldshading/worldshading/doctype/bank_loan/bank_loan.json','utf8'));
assert(meta.fields.some(f=>f.fieldname==='load_payment_tracking' && f.fieldtype==='Button'));
assert.equal(meta.field_order.indexOf('load_payment_tracking')+1,meta.field_order.indexOf('payment_history'));
console.log('Bank Loan payment summary and action checks: PASS');
// Exercise identities with native v12 deletion's name lookup and idx filtering.
const grid={df:{data:[{installment:'ROW-1'},{installment:'ROW-2'}]},refresh:function(){return this.df.data;}};
context.bank_loan_payment_grid_setup(grid);
assert(grid.df.data.every(r=>r.name));
grid.refresh();
assert(grid.df.data.every(r=>r.name));assert.notEqual(grid.df.data[0].name,grid.df.data[1].name);
const retained=grid.df.data[1];
const selected=grid.df.data[0];
grid.df.data=grid.df.data.filter(r=>r.idx!==selected.idx);
const index=grid.df.data.findIndex(r=>r.name===selected.name);if(index!==-1)grid.df.data.splice(index,1);
grid.refresh();assert.equal(grid.df.data.length,1);assert.strictEqual(grid.df.data[0],retained);
grid.df.data.push({idx:2,__islocal:true});grid.refresh();assert(grid.df.data[1].name);assert.notEqual(grid.df.data[1].name,retained.name);
const label=context.bank_loan_installment_formatter([{value:'ROW-1',label:'1 — 19-12-2026'}]);
assert.equal(label('ROW-1'),'1 — 19-12-2026');assert.equal(label(''),'');
