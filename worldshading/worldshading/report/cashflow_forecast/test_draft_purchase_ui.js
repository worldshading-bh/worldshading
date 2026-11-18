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
 call:options=>{requests.push(options);
 if(options.method.endsWith('get_draft_purchase')){
  const payments=[{date:'2026-11-11',amount:'100.000'},{date:'2026-12-15',amount:'200.000'}];
  if(options.args.purchase_order==='THREE')payments.push({date:'2027-01-15',amount:'300.000'});
  return Promise.resolve({message:{draft_po:options.args.purchase_order,supplier:'SUP',payments,customs_required:0,import_vat_required:1,customs_date:null,import_vat_date:'2026-11-25',moved_past_dates:1}});
 }
 if(options.method.endsWith('get_supplier_defaults'))throw Error('Draft schedule must not be reset by supplier defaults');
 return Promise.resolve({message:{result:[{_cashflow_context:{today_policy:'auto-v1',vat_policy:'quarter-v4',calculation_inputs:{}}}],columns:[],purchase_preview:true,prepared_report_name:'SAVED'}});
 }}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'cashflow_forecast.js'),'utf8'),context);
const report={report_name:'Cashflow Forecast',filters:[],page:{add_inner_button:(label,fn)=>{buttons[label]=fn;}},refresh:()=>{},
 get_filter:name=>({set_input:value=>{filters[name]=value;}}),get_filter_value:name=>filters[name],get_filter_values:()=>filters,
 raw_data:{doc:{name:'SAVED'},result:[{_cashflow_context:{today_policy:'auto-v1',vat_policy:'quarter-v4',calculation_inputs:{}}}]},
 prepare_report_data:data=>{report.raw_data=data;},get_chart_options:()=>null,render_datatable:()=>{}};
context.frappe.query_reports['Cashflow Forecast'].onload(report);
(async()=>{
 buttons['Check Purchase']();let d=dialog;
 assert(d.fields_dict.draft_po,'Each purchase section has an optional draft PO selector');
 assert.strictEqual(d.fields_dict.draft_po.df.label,'Draft Purchase Order');
 assert.deepStrictEqual(JSON.parse(JSON.stringify(d.fields_dict.draft_po.df.get_query())),{filters:{company:'Example',docstatus:0}});
 d.fields_dict.draft_po.set_input('DRAFT-1');await d.fields_dict.draft_po.df.onchange();
 assert.deepStrictEqual(Array.from(d.fields_dict.payments.grid.df.data,r=>[r.date,r.amount]),[['2026-11-11','100.000'],['2026-12-15','200.000']]);
 assert.strictEqual(d.fields_dict.supplier.value,'SUP');
 assert.strictEqual(d.fields_dict.include_customs_vat.value,1);
 assert.strictEqual(d.fields_dict.import_charges.grid.df.data[0].date,null);
 assert.strictEqual(d.fields_dict.import_charges.grid.df.data[1].date,'2026-11-25');
 const dateChanged=d.fields_dict.payments.grid.df.fields.find(field=>field.fieldname==='date').onchange;
 const rows=d.fields_dict.payments.grid.df.data;
 rows[0].date='2026-11-16';dateChanged();
 assert.strictEqual(rows[1].date,'2026-12-20','PO payments follow the first date using the original day gap');
 assert.strictEqual(rows[1].amount,'200.000','Following dates must not change amounts');
 assert.strictEqual(d.fields_dict.import_charges.grid.df.data[1].date,'2026-11-25','Tax dates stay independent');
 rows[1].date='2026-12-25';dateChanged();rows[0].date='2026-11-17';dateChanged();
 assert.strictEqual(rows[1].date,'2026-12-25','Manual later-date override stays fixed');
 await d.options.primary_action(d.get_values());
 const saved=JSON.parse(filters.purchase_scenario).purchases[0];
 assert.strictEqual(saved.draft_po,'DRAFT-1');assert.strictEqual(saved.payments[1].date,'2026-12-25');
 const before=requests.length;buttons['Check Purchase']();d=dialog;
 assert.strictEqual(d.fields_dict.draft_po.value,'DRAFT-1');
 assert.strictEqual(d.fields_dict.payments.grid.df.data[1].date,'2026-12-25');
 assert.strictEqual(requests.length,before,'Opening saved draft scenario preserves edits and makes no source requests');
 d.fields_dict.payments.grid.df.data[0].date='2026-11-18';
 d.fields_dict.payments.grid.df.fields.find(field=>field.fieldname==='date').onchange();
 assert.strictEqual(d.fields_dict.payments.grid.df.data[1].date,'2026-12-25','Saved manual override remains fixed after reopening');

 d.fields_dict.draft_po.set_input('THREE');await d.fields_dict.draft_po.df.onchange();
 const three=d.fields_dict.payments.grid.df.data,requestCount=requests.length;
 three[0].date='2026-11-21';d.fields_dict.payments.grid.df.fields.find(field=>field.fieldname==='date').onchange();
 assert.deepStrictEqual(Array.from(three,r=>r.date),['2026-11-21','2026-12-25','2027-01-25'],'All later payments preserve their original gaps');
 assert.strictEqual(requests.length,requestCount,'Changing the first date makes no server requests');
 await d.options.primary_action(d.get_values());buttons['Check Purchase']();d=dialog;
 d.fields_dict.payments.grid.df.data[0].date='2026-11-22';
 d.fields_dict.payments.grid.df.fields.find(field=>field.fieldname==='date').onchange();
 assert.deepStrictEqual(Array.from(d.fields_dict.payments.grid.df.data,r=>r.date),['2026-11-22','2026-12-26','2027-01-26'],'Automatic following survives saving and reopening');
 let resolvers=[];context.frappe.call=()=>new Promise(resolve=>resolvers.push(resolve));
 d.fields_dict.draft_po.set_input('OLD');const old=d.fields_dict.draft_po.df.onchange();
 d.fields_dict.draft_po.set_input('NEW');const latest=d.fields_dict.draft_po.df.onchange();
 const response=name=>({message:{draft_po:name,supplier:'SUP',payments:[{date:'2026-12-25',amount:'300.000'}],customs_required:0,import_vat_required:0}});
 resolvers[1](response('NEW'));await latest;resolvers[0](response('OLD'));await old;
 assert.strictEqual(d.fields_dict.draft_po.value,'NEW');assert.strictEqual(d.fields_dict.payments.grid.df.data.length,1);
 let resolvePending;context.frappe.call=options=>options.method.endsWith('get_draft_purchase')?new Promise(resolve=>{resolvePending=resolve;}):Promise.resolve({message:{terms:[],country_known:false}});
 d.fields_dict.draft_po.set_input('PENDING');const pending=d.fields_dict.draft_po.df.onchange();
 d.fields_dict.supplier.set_input('DIFFERENT');await d.fields_dict.supplier.df.onchange();
 resolvePending(response('PENDING'));await pending;
 assert.strictEqual(d.fields_dict.supplier.value,'DIFFERENT','Changing supplier cancels the pending PO load');
 assert.strictEqual(d.fields_dict.draft_po.value,'');
 console.log('Draft PO selector, copied amounts/dates/taxes, saved overrides and stale request guard passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
