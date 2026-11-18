/* Stateful dialog fixture: switching purchases retains edits without applying them. */
const assert=require('assert'),fs=require('fs'),vm=require('vm'),path=require('path');
let lowestCash=-2075.047;
let dialog,buttons={},requests=[],filters={company:'Example',end_date:'2027-02-10',maximum_shortage:3000,purchase_scenario:'{}'};
function Dialog(options){
 dialog=this;this.options=options;this.fields_dict={};
 this.add_fields=fields=>{fields.filter(f=>f.fieldname).forEach(df=>{
  const control={df,value:df.default,set_input:function(value){this.value=value;},$wrapper:{html:function(value){this.content=value;},find:()=>({}),detach:function(){this.detaches=(this.detaches || 0)+1;return this;},appendTo:function(){this.moves=(this.moves || 0)+1;return this;}},refresh:()=>{}};
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
const context={__:x=>x,console,format_currency:(value,currency)=>currency+' '+Number(value).toFixed(3),frappe:{query_reports:{},defaults:{get_user_default:()=> 'Example'},
 datetime:{get_today:()=> '2026-11-11',add_months:()=> '2027-02-11',add_days:(value,n)=>{const d=new Date(value+'T00:00:00Z');d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10);}},utils:{escape_html:String},ui:{Dialog},show_alert:()=>{},
 call:options=>{requests.push(options);if(options.args.suggest_purchase_dates)return Promise.resolve({message:{suggestions:[{purchase_number:1,first_cost_date:'2026-11-25',supplier_date:'2026-11-30',shift_days:10,lowest_cash:lowestCash,schedule:[{date:'2026-11-25',category:'customs',amount:'50.000'},{date:'2026-11-30',category:'proposed_purchase',kind:'supplier',amount:'600.000'},{date:'2026-12-03',category:'proposed_purchase',kind:'supplier',amount:'400.000'}]},{purchase_number:2,first_cost_date:null}]}});return Promise.resolve({message:{result:[{_cashflow_context:{today_policy:'auto-v1',vat_policy:'quarter-v4',calculation_inputs:{}}}],columns:[],purchase_preview:true,prepared_report_name:'SAVED'}});}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'cashflow_forecast.js'),'utf8'),context);
const report={report_name:'Cashflow Forecast',filters:[],page:{add_inner_button:(label,fn)=>{buttons[label]=fn;}},refresh:()=>{},
 get_filter:name=>({set_input:value=>{filters[name]=value;}}),get_filter_value:name=>filters[name],get_filter_values:()=>filters,
 raw_data:{doc:{name:'SAVED'},result:[{_cashflow_context:{today_policy:'auto-v1',vat_policy:'quarter-v4',calculation_inputs:{}}}]},
 prepare_report_data:data=>{report.raw_data=data;},get_chart_options:()=>null,render_datatable:()=>{}};
context.frappe.query_reports['Cashflow Forecast'].onload(report);
(async()=>{
 const settings=context.frappe.query_reports['Cashflow Forecast'];
 assert.strictEqual(settings.filters.find(f=>f.fieldname==='end_date').default,'2027-11-11');
 assert.strictEqual(settings.filters.find(f=>f.fieldname==='maximum_shortage').default,1000);
 buttons['Check Purchase']();const d=dialog;
 d.fields_dict.payments.grid.df.data=[{date:'2026-11-20',amount:600},{date:'2026-11-23',amount:400}];
 d.fields_dict.include_customs_vat.set_input(1);
 d.fields_dict.import_charges.grid.df.data[0].date='2026-11-15';
 d.fields_dict.add_purchase.df.click();d.fields_dict.payments_1.grid.df.data=[{date:'2026-12-01',amount:500}];
 await d.fields_dict.suggest_date.df.click();
 assert.strictEqual(requests.length,1);assert.strictEqual(requests[0].args.suggest_purchase_dates,1);
 assert.strictEqual(filters.purchase_scenario,'{}','Suggestion must not apply or enqueue');
 assert(d.fields_dict.suggestion.$wrapper.content.includes('30-11-2026'));
 assert(d.fields_dict.suggestion.$wrapper.content.includes('03-12-2026'));
 assert(d.fields_dict.suggestion.$wrapper.content.includes('25-11-2026'));
 assert(d.fields_dict.suggestion.$wrapper.content.includes('Supplier Payment 2'));
 assert(d.fields_dict.suggestion.$wrapper.content.includes('Customs'));
 assert(d.fields_dict.suggestion.$wrapper.content.indexOf('</table>')<d.fields_dict.suggestion.$wrapper.content.indexOf('Lowest closing cash'),'Cash explanation belongs below the payment schedule');
 assert.strictEqual(d.fields_dict.apply_suggestion.df.label,'Use These Dates');
 assert(d.fields_dict.suggestion.$wrapper.content.includes('within your'));
 assert(d.fields_dict.suggestion.$wrapper.content.includes('2075.047'));
 assert(d.fields_dict.suggestion.$wrapper.content.includes('3000.000'));
 assert(d.fields_dict.suggestion.$wrapper.content.includes('is-tolerated'));
 assert(d.fields_dict.suggestion_1.$wrapper.content.includes('No suitable date'));
 assert.strictEqual(d.fields_dict.apply_suggestion.df.hidden,0);
 assert.strictEqual(d.fields_dict.apply_suggestion_1.df.hidden,1);
 lowestCash=1500;
 await d.fields_dict.apply_suggestion.df.click();
 assert(d.fields_dict.suggestion.$wrapper.content.includes('No cash shortage'));
 assert(d.fields_dict.suggestion.$wrapper.content.includes('is-positive'));
 assert(!d.fields_dict.suggestion.$wrapper.content.includes('within your'));
 assert.strictEqual(d.fields_dict.payments.grid.df.data[0].date,'2026-11-30');
 assert.strictEqual(d.fields_dict.payments.grid.df.data[1].date,'2026-12-03');
 assert.strictEqual(d.fields_dict.import_charges.grid.df.data[0].date,'2026-11-25');
 assert.strictEqual(d.fields_dict.import_charges.grid.df.data[1].date,null);
 assert.strictEqual(d.fields_dict.payments_1.grid.df.data[0].date,'2026-12-01');
 assert.strictEqual(requests.length,2,'Applying refreshes other suggestions');
 assert.strictEqual(d.fields_dict.apply_suggestion.$wrapper.detaches,2,'Native button preserved before each result replacement');
 assert.strictEqual(d.fields_dict.apply_suggestion.$wrapper.moves,2,'Use Date remains inside the refreshed panel');
 assert.strictEqual(filters.purchase_scenario,'{}','Dates remain popup drafts until Check Purchases');
 let message='';context.frappe.msgprint=value=>{message=value;};
 d.fields_dict.payments.grid.df.data[0].amount=700;
 await d.fields_dict.apply_suggestion.df.click();assert(message.includes('Payments changed'));
 assert.strictEqual(requests.length,2,'Stale suggestion cannot move edited payments');
 console.log('Purchase suggestions: independent results, opt-in dates, preserved gaps, refreshed results and stale guard passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
