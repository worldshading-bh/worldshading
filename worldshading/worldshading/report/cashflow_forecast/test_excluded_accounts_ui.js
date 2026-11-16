/* Native v12 multi-select behavior, safe restore, cached options and company boundary. */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
let buttons={},calls=[],changes=0,resets=0,company='Example',prepared=false;
const context={__:x=>x,console,frappe:{query_reports:{},defaults:{get_user_default:()=>company},
 datetime:{get_today:()=> '2026-11-15',add_months:()=> '2027-02-15'},utils:{escape_html:x=>String(x).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')},
 ui:{form:{ControlData:{extend:definition=>definition}}},
 call:options=>{calls.push(options);return Promise.resolve({message:options.method.endsWith('get_prepared_filters')?
   {company:'Example',excluded_accounts:['Deposit <Restricted>']}:
   [{value:'Bank',label:'Bank'},...(options.args.company==='Other'?[]:[{value:'BANK TIME DEPOSIT - WS',label:'BANK TIME DEPOSIT - WS'}]),{value:'Deposit <Restricted>',label:'Deposit <Restricted>'}]});}}};
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
 await settings.onload(report);assert.strictEqual(calls.length,1);
 assert.deepStrictEqual(Array.from(field.get_value()),['BANK TIME DEPOSIT - WS']);
 field.set_value([]);await settings.onload(report);assert.strictEqual(field.get_value().length,0,'Cleared defaults stay cleared');
 changes=0;
 let options=await df.get_data('');assert.strictEqual(calls.length,1);
 assert.strictEqual(options[2].label,'Deposit &lt;Restricted&gt;');
 options=await df.get_data('Bank');assert.strictEqual(options.length,2);assert.strictEqual(calls.length,1,'Search reuses company options');
 field.set_value(['Deposit <Restricted>']);assert.strictEqual(changes,1);
 options=await df.get_data('');assert.strictEqual(options[0].value,'Deposit <Restricted>');
 options=await df.get_data('Bank');assert.deepStrictEqual(Array.from(options,o=>o.value),['Deposit <Restricted>','Bank','BANK TIME DEPOSIT - WS']);
 assert.strictEqual(calls.length,1,'Selected-first order uses the existing option cache');
 company='Other';await settings.filters.find(f=>f.fieldname==='company').on_change(report);
 assert.strictEqual(field.get_value().length,0,'Default absent from company accounts must not be selected');assert.strictEqual(changes,1,'Company reset is silent');assert.strictEqual(resets,1);
 await df.get_data('');assert.strictEqual(calls.length,2);assert.strictEqual(calls[1].args.company,'Other');
 prepared=true;await settings.onload(report);
 assert.strictEqual(company,'Example');assert.deepStrictEqual(Array.from(field.get_value()),['Deposit <Restricted>']);
 assert.strictEqual(changes,1,'Snapshot restore must not trigger generation');assert(field.status.includes('&lt;Restricted&gt;'));
 options=await df.get_data('');const count=calls.length;
 field.set_value([]);options=await df.get_data('Bank');assert.deepStrictEqual(Array.from(options,o=>o.value),['Bank','BANK TIME DEPOSIT - WS']);
 assert.strictEqual(calls.length,count,'Unselecting also reuses cached options');
 assert(calls.every(call=>call.method.endsWith('get_accounts') || call.method.endsWith('get_prepared_filters')));
 // A default lookup that finishes later must not overwrite saved or user choices.
 let resolveAccounts;
 context.frappe.call=options=>options.method.endsWith('get_prepared_filters')?
   Promise.resolve({message:{company:'Example',excluded_accounts:[]}}):new Promise(resolve=>{resolveAccounts=resolve;});
 prepared=false;report._cashflow_default_company=null;report._cashflow_account_options=null;
 field.set_value([]);const pending=settings.onload(report);
 prepared=true;await settings.onload(report);
 resolveAccounts({message:[{value:'BANK TIME DEPOSIT - WS'}]});await pending;
 assert.strictEqual(field.get_value().length,0,'Delayed defaults must preserve saved empty exclusions');
 prepared=false;report._cashflow_default_company=null;report._cashflow_account_options=null;
 const loading=settings.onload(report);field.set_value(['Bank']);df.on_change(report);
 resolveAccounts({message:[{value:'BANK TIME DEPOSIT - WS'},{value:'Bank'}]});await loading;
 assert.deepStrictEqual(Array.from(field.get_value()),['Bank'],'Delayed defaults must preserve user selection');
 // Defaults are intersected with currently eligible company accounts.
 context.frappe.call=()=>Promise.resolve({message:[{value:'BANK TIME DEPOSIT - WS'},
   {value:'Petty Cash - WS'},{value:'***63001 - KFH Benefit pay - WS'},{value:'Cash - WS'}]});
 prepared=false;report._cashflow_default_company=null;report._cashflow_account_options=null;field.set_value([]);
 await settings.onload(report);
 assert.deepStrictEqual(Array.from(field.get_value()),['BANK TIME DEPOSIT - WS','Petty Cash - WS','***63001 - KFH Benefit pay - WS']);
 assert(!field.get_value().includes('Cash - WS'),'Non-default cash account stays included');
 // Removed accounts are ignored on the next fresh selection, with no stale names submitted.
 context.frappe.call=()=>Promise.resolve({message:[{value:'Cash - WS'}]});
 report._cashflow_default_company=null;report._cashflow_account_options=null;field.set_value([]);
 await settings.onload(report);assert.strictEqual(field.get_value().length,0);
 console.log('Native v12 account exclusions: cached scoped options, escaping, company reset and silent saved restore passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
