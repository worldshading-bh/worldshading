/* Stateful dialog fixture: switching purchases retains edits without applying them. */
const assert=require('assert'),fs=require('fs'),vm=require('vm'),path=require('path');
let dialog,buttons={},requests=[],filters={company:'Example',end_date:'2027-02-10',purchase_scenario:'{}'};
function Dialog(options){
 dialog=this;this.options=options;this.fields_dict={};
 this.add_fields=fields=>{fields.filter(f=>f.fieldname).forEach(df=>{
  const control={df,value:df.default,set_input:function(value){this.value=value;},refresh:()=>{}};
  if(df.fieldtype==='Table')control.grid={df,refresh:()=>{}};
  if(df.fieldtype==='Section Break'){control.collapse=value=>{control.collapsed=value;};control.wrapper={appendTo:()=>{}};}
  this.fields_dict[df.fieldname]=control;
 });};
 this.add_fields(options.fields);
 this.get_value=name=>this.fields_dict[name].value;
 this.get_values=()=>Object.keys(this.fields_dict).reduce((out,key)=>{const field=this.fields_dict[key];out[key]=field.grid?field.grid.df.data:field.value;return out;},{});
 this.set_df_property=(name,key,value)=>{this.fields_dict[name].df[key]=value;};
 this.show=()=>{};this.hide=()=>{if(options.secondary_action)options.secondary_action();};
}
const context={__:x=>x,console,frappe:{query_reports:{},defaults:{get_user_default:()=> 'Example'},
 datetime:{get_today:()=> '2026-11-11',add_months:()=> '2027-02-11'},utils:{escape_html:String},ui:{Dialog},show_alert:()=>{},
 call:options=>{requests.push(options);return Promise.resolve({message:{result:[{_cashflow_context:{today_policy:'auto-v1',vat_policy:'quarter-v4',calculation_inputs:{}}}],columns:[],purchase_preview:true,prepared_report_name:'SAVED'}});}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'cashflow_forecast.js'),'utf8'),context);
const report={report_name:'Cashflow Forecast',filters:[],page:{add_inner_button:(label,fn)=>{buttons[label]=fn;}},refresh:()=>{},
 get_filter:name=>({set_input:value=>{filters[name]=value;}}),get_filter_value:name=>filters[name],get_filter_values:()=>filters,
 raw_data:{doc:{name:'SAVED'},result:[{_cashflow_context:{today_policy:'auto-v1',vat_policy:'quarter-v4',calculation_inputs:{}}}]},
 prepare_report_data:data=>{report.raw_data=data;},get_chart_options:()=>null,render_datatable:()=>{}};
context.frappe.query_reports['Cashflow Forecast'].onload(report);
(async()=>{
 buttons['Check Purchase']();const d=dialog;
 assert(!d.fields_dict.purchase_choice);assert(!d.fields_dict.amount);
 assert(d.fields_dict.purchase_section_0.df.collapsible);
 const first=d.fields_dict.payments.grid;
 first.df.data=[{date:'2026-11-20',amount:1000}];
 d.fields_dict.add_purchase.df.click();
 assert(d.fields_dict.purchase_section_1.df.collapsible);assert.strictEqual(d.fields_dict.purchase_section_0.collapsed,true);
 assert.strictEqual(d.fields_dict.purchase_section_1.collapsed,false);
 const second=d.fields_dict.payments_1.grid;
 second.df.data=[{date:'2026-12-01',amount:500}];
 d.fields_dict.international_1.set_input(1);d.fields_dict.international_1.df.onchange();d.fields_dict.eta_date_1.set_input('2026-11-25');
 assert.strictEqual(d.fields_dict.eta_date.df.hidden,1);assert.strictEqual(d.fields_dict.eta_date_1.df.hidden,0);
 first.df.data[0].amount=1200;
 await d.options.primary_action(d.get_values());
 let sent=JSON.parse(filters.purchase_scenario);assert.strictEqual(sent.purchases.length,2);
 assert.strictEqual(sent.purchases[0].payments[0].amount,1200);assert.strictEqual(sent.purchases[1].payments[0].amount,500);
 assert.strictEqual(sent.purchases[1].eta_date,'2026-11-25');assert(!('amount' in sent.purchases[0]));
 d.fields_dict.remove_purchase.df.click();assert.strictEqual(requests.length,1);
 await d.options.primary_action(d.get_values());sent=JSON.parse(filters.purchase_scenario);assert.strictEqual(sent.purchases.length,1);
 assert.strictEqual(sent.purchases[0].payments[0].amount,500);
 buttons['Check Purchase']();assert.strictEqual(dialog.fields_dict.payments.grid.df.data[0].amount,500);
 const before=filters.purchase_scenario;dialog.hide();assert.strictEqual(filters.purchase_scenario,before);
 // An untouched newly added section is not a zero-value purchase.
 dialog.fields_dict.add_purchase.df.click();await dialog.options.primary_action(dialog.get_values());
 assert.strictEqual(JSON.parse(filters.purchase_scenario).purchases.length,1);
 await dialog.fields_dict.clear_purchase.df.click();assert.strictEqual(filters.purchase_scenario,'{}');
 assert(requests.every(r=>r.method.endsWith('recalculate_purchase')));
 console.log('Independent collapsible purchases preserve rows; Add, Remove, blank-section handling, restore and Clear pass');
})().catch(error=>{console.error(error);process.exitCode=1;});
