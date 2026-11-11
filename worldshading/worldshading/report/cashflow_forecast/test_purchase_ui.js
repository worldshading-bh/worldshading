/* Isolated scenario UI fixture; no browser or network. */
const assert=require('assert'),fs=require('fs'),vm=require('vm'),path=require('path');
let calls=[],dialog,buttons={},filters={company:'Example',end_date:'2026-12-31',include_overdue:1,purchase_scenario:'{}'};
const context={__:x=>x,console,frappe:{query_reports:{},defaults:{get_user_default:()=> 'Example'},
 datetime:{get_today:()=> '2026-11-10',add_months:()=> '2027-02-10'},utils:{escape_html:x=>String(x)},
 ui:{Dialog:function(options){dialog=options;this.get_value=key=>{const field=options.fields.find(f=>f.fieldname===key);return field && field.default;};this.set_df_property=(key,prop,value)=>{options.fields.find(f=>f.fieldname===key)[prop]=value;};this.show=()=>{};this.hide=()=>{if(options.secondary_action) options.secondary_action();};}},show_alert:()=>{},
 call:options=>{calls.push(options);return Promise.resolve({message:options.method.endsWith('preview_purchase') ? {events:[]} : {name:'PREPARED-SCENARIO'}});}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'cashflow_forecast.js'),'utf8'),context);
const settings=context.frappe.query_reports['Cashflow Forecast'];
const report={report_name:'Cashflow Forecast',filters:[],page:{add_inner_button:(label,callback)=>{buttons[label]=callback;}},
 refresh:()=>{},get_filter_value:key=>filters[key],get_filter_values:()=>filters,
 set_filter_value:(key,value)=>{filters[key]=value;return Promise.resolve();},generate_background_report:()=>{},
 toggle_primary_button_disabled:()=>{},toggle_nothing_to_show:()=>{}};
settings.onload(report);assert(buttons['Check Purchase']);buttons['Check Purchase']();
assert(dialog.fields.some(f=>f.fieldname==='international'));
assert(!dialog.fields.some(f=>f.fieldname==='amount'),'Purchase totals come from the payment table');
assert(!dialog.fields.some(f=>['date','split_payments'].includes(f.fieldname)),'Payment dates belong only in the table');
assert(dialog.fields.some(f=>f.fieldname==='payments'));
const eta=dialog.fields.find(f=>f.fieldname==='eta_date'),international=dialog.fields.find(f=>f.fieldname==='international');
assert(eta.hidden,'ETA must be hidden on opening a local purchase');
international.default=1;international.onchange();assert.strictEqual(eta.hidden,0);assert.strictEqual(eta.reqd,1);assert.strictEqual(dialog.fields.find(f=>f.fieldname==='import_note').hidden,0);
international.default=0;international.onchange();assert.strictEqual(eta.hidden,1);assert.strictEqual(eta.reqd,0);
assert(!dialog.fields.some(f=>['charges','tax_template','description','order_date'].includes(f.fieldname)));
assert(!dialog.secondary_action,'Closing or applying must never run Clear Purchase');
const purchase={amount:1000,payments:[{date:'2026-11-15',amount:1000}],international:1,eta_date:'2026-11-12'};
dialog.primary_action(purchase);
setImmediate(()=>{
 try {
  assert.strictEqual(calls[0].type,'POST');assert(calls[0].method==='frappe.desk.query_report.background_enqueue_run');
  assert.strictEqual(JSON.parse(filters.purchase_scenario).purchases[0].payments[0].amount,1000);
  assert.strictEqual(JSON.parse(filters.purchase_scenario).schema,4);
  assert.strictEqual(calls.filter(c=>c.method==='frappe.desk.query_report.background_enqueue_run').length,1,'Apply/hide queues exactly once');
  assert(calls.some(c=>c.method==='frappe.desk.query_report.background_enqueue_run'));
  assert.strictEqual(report.prepared_report_doc_name,'PREPARED-SCENARIO');
  const format=v=>String(v);
  assert(settings.formatter(1,0,{fieldname:'date'},{closing_cash:1,scenario_supplier:true},format).includes('cashflow-scenario-supplier'));
  assert(settings.formatter(1,0,{fieldname:'date'},{closing_cash:1,scenario_arrival:true,scenario_supplier:true},format).includes('cashflow-scenario-arrival'));
  const negative=settings.formatter(1,0,{fieldname:'date'},{closing_cash:-1,scenario_arrival:true},format);
  assert(negative.includes('cashflow-negative-cell'));assert(negative.includes('cashflow-purchase-cell'),'Purchase stays highlighted on negative days');
  const clear=dialog.fields.find(f=>f.fieldname==='clear_purchase').click;
  Promise.resolve(clear()).then(()=>{
   assert.strictEqual(filters.purchase_scenario,'{}');
   assert.strictEqual(calls.filter(c=>c.method==='frappe.desk.query_report.background_enqueue_run').length,2,'Clear/hide queues once without recursive calls');
   const count=calls.length;filters.purchase_scenario=JSON.stringify({schema:3,amount:500,date:'2026-11-30',split_payments:0,payments:[{date:'2026-12-01',amount:300}],international:1,eta_date:'2026-11-20'});buttons['Check Purchase']();
   const restored=dialog.fields.find(f=>f.fieldname==='payments').data;
   assert.strictEqual(restored.length,1);assert.strictEqual(restored[0].date,'2026-11-30');assert.strictEqual(restored[0].amount,500);
   assert.strictEqual(dialog.fields.find(f=>f.fieldname==='eta_date').hidden,0,'Saved international purchase shows ETA on opening');
   assert(!dialog.secondary_action);
   assert.strictEqual(calls.length,count,'Opening/cancelling cannot clear or queue anything');
   console.log('Simple purchase fields, one-shot Apply/Clear, safe modal hide, POST and highlight checks passed');
  }).catch(error=>{console.error(error);process.exitCode=1;});
 } catch(error){console.error(error);process.exitCode=1;}
});
