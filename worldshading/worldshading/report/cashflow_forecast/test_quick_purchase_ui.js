/* Quick purchase checks must never enqueue another prepared report. */
const assert=require('assert'),fs=require('fs'),vm=require('vm'),path=require('path');
let dialog,buttons={},calls=[],rendered=0,filters={company:'Example',end_date:'2026-12-31',include_overdue:1,purchase_scenario:'{}'};
let reject=false,exported=0;
const context={__:x=>x,console,setTimeout:()=>{},URL:{createObjectURL:()=> 'blob:check',revokeObjectURL:()=>{}},Blob:function(){},document:{createElement:()=>({click:()=>{exported++;}})},frappe:{query_reports:{},defaults:{get_user_default:()=> 'Example'},
 datetime:{get_today:()=> '2026-11-10',add_months:()=> '2027-02-10'},utils:{escape_html:x=>String(x)},
 ui:{Dialog:function(options){dialog=options;this.get_value=key=>{const field=options.fields.find(f=>f.fieldname===key);return field && field.default;};this.set_df_property=(key,prop,value)=>{options.fields.find(f=>f.fieldname===key)[prop]=value;};this.show=()=>{};this.hide=()=>{if(options.secondary_action)options.secondary_action();};}},show_alert:()=>{},
 call:options=>{calls.push(options);if(reject)return Promise.reject(new Error('Changed forecast filters'));
   return Promise.resolve({message:{result:[{closing_cash:900,_cashflow_context:{calculation_inputs:{events:[]},vat_policy:'quarter-v4',today_policy:'auto-v1'}}],
       columns:[],chart:{},purchase_preview:true,prepared_report_name:'SAVED'}});}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'cashflow_forecast.js'),'utf8'),context);
const settings=context.frappe.query_reports['Cashflow Forecast'];
const report={export_report:()=>{throw Error('Do not export the original prepared attachment');},report_name:'Cashflow Forecast',filters:[],page:{add_inner_button:(label,cb)=>{buttons[label]=cb;}},
 get_filter:key=>({set_input:value=>{filters[key]=value;}}),get_filter_value:key=>filters[key],get_filter_values:()=>filters,
 raw_data:{doc:{name:'SAVED'},result:[{_cashflow_context:{calculation_inputs:{events:[]},vat_policy:'quarter-v4',today_policy:'auto-v1'}}]},
 prepare_report_data:data=>{report.raw_data=data;},get_chart_options:()=>null,render_datatable:()=>{rendered++;},
 generate_background_report:()=>{throw Error('Quick check must not queue');},refresh:()=>{}};
settings.onload(report);
(async()=>{
 buttons['Check Purchase']();
 assert(dialog.fields.some(f=>f.fieldname==='payments'));
 assert(dialog.fields.some(f=>f.fieldname==='eta_date' && f.hidden));
 assert(!dialog.secondary_action);
 await dialog.primary_action({amount:1000,payments:[{date:'2026-12-01',amount:600},{date:'2026-12-10',amount:400}],international:1,eta_date:'2026-11-15'});
 assert(calls[0].method.endsWith('recalculate_purchase'));
 assert.strictEqual(calls[0].args.prepared_report_name,'SAVED');
 const submitted=JSON.parse(calls[0].args.filters.purchase_scenario);
 assert.strictEqual(submitted.schema,4);assert.strictEqual(submitted.purchases[0].payments.length,2);assert(!('amount' in submitted));
 assert.strictEqual(calls.length,1);assert.strictEqual(rendered,1);
 report.export_report();assert.strictEqual(exported,1,'Standard Export must export the displayed purchase check');
 assert.strictEqual(JSON.parse(filters.purchase_scenario).purchases[0].eta_date,'2026-11-15');
 await dialog.fields.find(f=>f.fieldname==='clear_purchase').click();
 assert.strictEqual(calls.length,2);assert.strictEqual(filters.purchase_scenario,'{}');assert.strictEqual(rendered,2);
 buttons['Check Purchase']();reject=true;
 await assert.rejects(()=>dialog.primary_action({amount:2000,payments:[{date:'2026-12-10',amount:2000}]}));
 assert.strictEqual(filters.purchase_scenario,'{}','Failed validation must preserve the displayed purchase');
 assert.strictEqual(rendered,2);
 assert(!calls.some(c=>c.method.includes('background_enqueue_run')));
 console.log('Quick Apply/Clear reuses snapshot, separate ETA, no enqueue, failed validation preserves inputs');
})().catch(error=>{console.error(error);process.exitCode=1;});
