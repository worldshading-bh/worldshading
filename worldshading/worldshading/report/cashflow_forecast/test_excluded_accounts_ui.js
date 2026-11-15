/* Native v12 multi-select behavior, safe restore, cached options and company boundary. */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
let buttons={},calls=[],changes=0,resets=0,company='Example',prepared=false;
const context={__:x=>x,console,frappe:{query_reports:{},defaults:{get_user_default:()=>company},
 datetime:{get_today:()=> '2026-11-15',add_months:()=> '2027-02-15'},utils:{escape_html:x=>String(x).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')},
 ui:{form:{ControlData:{extend:definition=>definition}}},
 call:options=>{calls.push(options);return Promise.resolve({message:options.method.endsWith('get_prepared_filters')?
   {company:'Example',excluded_accounts:['Deposit <Restricted>']}:
   [{value:'Bank',label:'Bank'},{value:'Deposit <Restricted>',label:'Deposit <Restricted>'}]});}}};
vm.createContext(context);
const nativePath=process.env.FRAPPE_MULTISELECT_PATH || '/home/hilal/frappe-bench/apps/frappe/frappe/public/js/frappe/form/controls/multiselect_list.js';
vm.runInContext(fs.readFileSync(nativePath,'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'cashflow_forecast.js'),'utf8'),context);
const settings=context.frappe.query_reports['Cashflow Forecast'];
const df=settings.filters.find(f=>f.fieldname==='excluded_accounts');assert(df && df.fieldtype==='MultiSelectList');
const field=Object.assign({},context.frappe.ui.form.ControlMultiSelectList,{df,values:[],_options:[],_selected_values:[],
 set_status:function(text){this.status=text;},parse_validate_and_set_in_model:function(){if(!this.inside_change_event)changes++;}});
const companyField={df:{fieldname:'company'},set_input:value=>{company=value;}};
const report={report_name:'Cashflow Forecast',prepared_report:true,filters:[companyField,field],
 page:{add_inner_button:(label,fn)=>{buttons[label]=fn;}},
 get_filter:name=>name==='excluded_accounts'?field:null,get_filter_value:name=>name==='company'?company:field.get_value(),
 get_query_params:()=>prepared?{prepared_report_name:'SAVED'}:{},reset_report_view:()=>{resets++;},refresh:()=>{throw Error('Prepared filter must not generate');}};
context.frappe.query_report=report;
(async()=>{
 await settings.onload(report);assert.strictEqual(calls.length,0);
 let options=await df.get_data('');assert.strictEqual(calls.length,1);
 assert.strictEqual(options[1].label,'Deposit &lt;Restricted&gt;');
 options=await df.get_data('Bank');assert.strictEqual(options.length,1);assert.strictEqual(calls.length,1,'Search reuses company options');
 field.set_value(['Deposit <Restricted>']);assert.strictEqual(changes,1);
 options=await df.get_data('');assert.strictEqual(options[0].value,'Deposit <Restricted>');
 options=await df.get_data('Bank');assert.deepStrictEqual(Array.from(options,o=>o.value),['Deposit <Restricted>','Bank']);
 assert.strictEqual(calls.length,1,'Selected-first order uses the existing option cache');
 company='Other';settings.filters.find(f=>f.fieldname==='company').on_change(report);
 assert.strictEqual(field.get_value().length,0);assert.strictEqual(changes,1,'Company reset is silent');assert.strictEqual(resets,1);
 await df.get_data('');assert.strictEqual(calls.length,2);assert.strictEqual(calls[1].args.company,'Other');
 prepared=true;await settings.onload(report);
 assert.strictEqual(company,'Example');assert.deepStrictEqual(Array.from(field.get_value()),['Deposit <Restricted>']);
 assert.strictEqual(changes,1,'Snapshot restore must not trigger generation');assert(field.status.includes('&lt;Restricted&gt;'));
 options=await df.get_data('');const count=calls.length;
 field.set_value([]);options=await df.get_data('Bank');assert.deepStrictEqual(Array.from(options,o=>o.value),['Bank']);
 assert.strictEqual(calls.length,count,'Unselecting also reuses cached options');
 assert(calls.every(call=>call.method.endsWith('get_accounts') || call.method.endsWith('get_prepared_filters')));
 console.log('Native v12 account exclusions: cached scoped options, escaping, company reset and silent saved restore passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
