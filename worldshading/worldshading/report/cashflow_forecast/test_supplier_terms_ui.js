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
 call:options=>{requests.push(options);if(options.method.endsWith('get_supplier_defaults'))return Promise.resolve({message:{supplier:'SUP',supplier_name:'Example Trading',international:true,payment_terms:'50/50',terms:[{portion:'50',basis:'Day(s) after invoice date',credit_days:0},{portion:'50',basis:'Day(s) after invoice date',credit_days:30}]}});if(options.args.suggest_purchase_dates)return Promise.resolve({message:{suggestions:[{purchase_number:1,first_cost_date:'2026-11-25',supplier_date:'2026-11-30',shift_days:10,lowest_cash:lowestCash},{purchase_number:2,first_cost_date:null}]}});return Promise.resolve({message:{result:[{_cashflow_context:{today_policy:'auto-v1',vat_policy:'quarter-v4',calculation_inputs:{}}}],columns:[],purchase_preview:true,prepared_report_name:'SAVED'}});}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'cashflow_forecast.js'),'utf8'),context);
const report={report_name:'Cashflow Forecast',filters:[],page:{add_inner_button:(label,fn)=>{buttons[label]=fn;}},refresh:()=>{},
 get_filter:name=>({set_input:value=>{filters[name]=value;}}),get_filter_value:name=>filters[name],get_filter_values:()=>filters,
 raw_data:{doc:{name:'SAVED'},result:[{_cashflow_context:{today_policy:'auto-v1',vat_policy:'quarter-v4',calculation_inputs:{}}}]},
 prepare_report_data:data=>{report.raw_data=data;},get_chart_options:()=>null,render_datatable:()=>{}};
context.frappe.query_reports['Cashflow Forecast'].onload(report);
(async()=>{
 buttons['Check Purchase']();const d=dialog;
 assert(d.fields_dict.supplier && !d.fields_dict.supplier.df.reqd);
 assert.strictEqual(d.fields_dict.supplier.df.label,'Supplier');
 d.fields_dict.payments.grid.df.data=[{date:'2026-11-20',amount:10000}];
 d.fields_dict.supplier.set_input('SUP');await d.fields_dict.supplier.df.onchange();
 let rows=d.fields_dict.payments.grid.df.data;
 assert.deepStrictEqual(Array.from(rows,r=>Number(r.amount)),[10000,0]);
 assert.deepStrictEqual(Array.from(rows,r=>r.date),['2026-11-20','2026-12-20']);
 assert.strictEqual(d.fields_dict.include_customs_vat.value,1);
 assert.strictEqual(d.fields_dict.import_charges.df.hidden,0);
 const change=d.fields_dict.payments.grid.df.fields.find(f=>f.fieldname==='date').onchange;
 rows[0].date='2026-11-25';change();assert.strictEqual(rows[1].date,'2026-12-25');
 rows[1].date='2026-12-31';change();rows[0].date='2026-11-26';change();
 assert.strictEqual(rows[1].date,'2026-12-31','Manual date overrides stay unchanged');
 rows[1].amount=7000;rows[0].amount=8000;change();
 assert.strictEqual(rows[1].amount,7000,'Amounts stay entirely manual');
 assert.strictEqual(requests.filter(r=>r.method.endsWith('get_supplier_defaults')).length,1,'Editing dates/amounts never calls the server');
 assert(!d.fields_dict.apply_terms,'No separate template-reset button');
 d.fields_dict.supplier.set_input('');await d.fields_dict.supplier.df.onchange();
 d.fields_dict.supplier.set_input('SUP');await d.fields_dict.supplier.df.onchange();rows=d.fields_dict.payments.grid.df.data;
 assert.deepStrictEqual(Array.from(rows,r=>Number(r.amount)),[8000,7000]);
 await d.options.primary_action(d.get_values());
 assert.strictEqual(JSON.parse(filters.purchase_scenario).purchases[0].supplier,'SUP');
 d.fields_dict.supplier.set_input('');await d.fields_dict.supplier.df.onchange();
 assert.strictEqual(d.fields_dict.payments.grid.df.data.length,2,'Clearing supplier retains manual payments');
 // Saved supplier dates must follow an anchor edited while profile data is loading.
 const profile={supplier:'SUP',supplier_name:'Example',international:true,payment_terms:'50/50',terms:[{portion:'50',basis:'Day(s) after invoice date',credit_days:0},{portion:'50',basis:'Day(s) after invoice date',credit_days:30}]};
 let resolveProfile;context.frappe.call=()=>new Promise(resolve=>{resolveProfile=resolve;});report._cashflow_supplier_defaults={};
 filters.purchase_scenario=JSON.stringify({schema:5,purchases:[{supplier:'SUP',payments:[{date:'2026-11-20',amount:100},{date:'2026-12-20',amount:100}]}]});
 buttons['Check Purchase']();let pendingDialog=dialog;
 pendingDialog.fields_dict.payments.grid.df.data[0].date='2026-11-25';
 pendingDialog.fields_dict.payments.grid.df.fields.find(f=>f.fieldname==='date').onchange();
 resolveProfile({message:profile});await new Promise(resolve=>setImmediate(resolve));
 assert.strictEqual(pendingDialog.fields_dict.payments.grid.df.data[1].date,'2026-12-25','Saved-date tracking must include first-date edits during loading');
 // A country default must not undo a checkbox manually changed while loading.
 report._cashflow_supplier_defaults={};filters.purchase_scenario='{}';buttons['Check Purchase']();pendingDialog=dialog;
 pendingDialog.fields_dict.supplier.set_input('SUP');const loading=pendingDialog.fields_dict.supplier.df.onchange();
 let warning='';context.frappe.msgprint=value=>{warning=value;};
 pendingDialog.fields_dict.payments.grid.df.data[0].amount=100;
 pendingDialog.options.primary_action(pendingDialog.get_values());assert(warning.includes('wait'),'Do not check a half-loaded supplier schedule');
 pendingDialog.fields_dict.include_customs_vat.set_input(1);pendingDialog.fields_dict.include_customs_vat.df.onchange();
 pendingDialog.fields_dict.include_customs_vat.set_input(0);pendingDialog.fields_dict.include_customs_vat.df.onchange();
 resolveProfile({message:profile});await loading;
 assert.strictEqual(pendingDialog.fields_dict.include_customs_vat.value,0,'Late country default must preserve manual tax choices');
 console.log('Optional supplier, cached terms, automatic date following, manual amounts and independent manual overrides passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
