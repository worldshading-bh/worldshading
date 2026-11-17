/* Native v12 row removal: each popup must retain the unselected rows. */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
let dialog,buttons={};
const folder=process.env.FRAPPE_CONTROL_ROOT || '/home/hilal/frappe-bench/apps/frappe/frappe/public/js/frappe/form/';
const context={__:x=>x,console,frappe:{query_reports:{},ui:{form:{}},defaults:{get_user_default:()=> 'Example'},
 datetime:{get_today:()=> '2026-11-17',add_months:()=> '2027-02-17'},utils:{escape_html:String},
 timeout:()=>Promise.resolve(),run_serially:tasks=>{context.lastSerial=tasks.reduce((promise,task)=>promise.then(task),Promise.resolve());return context.lastSerial;}}};
vm.createContext(context);
let rowCode=fs.readFileSync(folder+'grid_row.js','utf8').replace(/^import .*$/gm,'').replace('export default class GridRow','class GridRow');
vm.runInContext(rowCode+'\nthis.NativeGridRow=GridRow;',context);
let gridCode=fs.readFileSync(folder+'grid.js','utf8').replace(/^import .*$/gm,'').replace('export default class Grid','class Grid');
vm.runInContext(gridCode+'\nthis.NativeGrid=Grid;',context);
const prefix="this.remove_rows_button.on('click', function() {";
const start=gridCode.indexOf(prefix)+prefix.length,end=gridCode.indexOf('\n\t\t});\n\t}\n\tselect_row',start);
assert(start>prefix.length && end>start);
const bulkRemove=vm.runInContext('(function(){var me=this;'+gridCode.slice(start,end)+'\n})',context);
function makeGrid(df){
 const grid={df,is_editable:()=>true,get_data:context.NativeGrid.prototype.get_data,get_selected_children:context.NativeGrid.prototype.get_selected_children,
 refresh_remove_rows_button:()=>{},refresh:function(){
  this.grid_rows=(this.df.data || []).map((doc,i)=>{if(doc.idx===undefined)doc.idx=i+1;return {doc,grid:this,remove:context.NativeGridRow.prototype.remove};});
  this.grid_rows_by_docname={};this.grid_rows.forEach(row=>{this.grid_rows_by_docname[row.doc.name]=row;});
 }};
 grid.refresh();return grid;
}
context.frappe.ui.Dialog=function(options){
 dialog=this;this.options=options;this.fields_dict={};this.show=()=>{};this.hide=()=>{};
 this.add_fields=fields=>fields.forEach(df=>{if(!df.fieldname)return;const control={df,value:df.default,set_input:function(value){this.value=value;},refresh:()=>{}};
  if(df.fieldtype==='Table')control.grid=makeGrid(df);
  if(df.fieldtype==='Section Break')control.collapse=()=>{};
  this.fields_dict[df.fieldname]=control;});
 this.add_fields(options.fields);this.get_value=name=>this.fields_dict[name].value;
 this.set_df_property=(name,key,value)=>{this.fields_dict[name].df[key]=value;};
};
vm.runInContext(fs.readFileSync(path.join(__dirname,'cashflow_forecast.js'),'utf8'),context);
const seed=[{date:'2026-11-20',amount:100,description:'First'},{date:'2026-11-21',amount:200,description:'Second'}];
let filters={company:'Example',end_date:'2027-12-31',support_payments:JSON.stringify(seed),extra_expenses:JSON.stringify(seed),purchase_scenario:JSON.stringify({schema:5,purchases:[{payments:seed,customs_required:1,customs_date:'2026-11-20',import_vat_required:1,import_vat_date:'2026-11-21'}]})};
const report={report_name:'Cashflow Forecast',filters:[],page:{add_inner_button:(label,fn)=>{buttons[label]=fn;}},refresh:()=>{},get_filter_value:key=>filters[key],get_filter_values:()=>filters};
context.frappe.query_reports['Cashflow Forecast'].onload(report);
(async()=>{
 for(const label of ['Add Support','Add Extra Expenses']){
  buttons[label]();const grid=dialog.fields_dict.expenses.grid;
  assert.strictEqual(new Set(grid.df.data.map(row=>row.name)).size,2,'Seed rows need distinct names');
  const first=grid.df.data[0];grid.grid_rows[1].remove();assert.strictEqual(grid.df.data.length,1);assert.strictEqual(grid.df.data[0],first);
  context.NativeGrid.prototype.add_new_row.call(grid);context.NativeGrid.prototype.add_new_row.call(grid);
  assert.strictEqual(new Set(grid.df.data.map(row=>row.name)).size,3,'New rows also need distinct names');
  grid.df.data[0].__checked=1;grid.df.data[2].__checked=1;
  const survivor=grid.df.data[1];bulkRemove.call(grid);await context.lastSerial;
  assert.strictEqual(grid.df.data.length,1);assert.strictEqual(grid.df.data[0],survivor);assert.strictEqual(survivor.idx,1);
 }
 buttons['Check Purchase']();let grid=dialog.fields_dict.payments.grid;
 const first=grid.df.data[0];grid.grid_rows[1].remove();assert.strictEqual(grid.df.data.length,1);assert.strictEqual(grid.df.data[0],first);
 grid=dialog.fields_dict.import_charges.grid;
 assert.strictEqual(grid.df.cannot_delete_rows,true);
 grid.grid_rows[0].remove();assert.strictEqual(grid.df.data.length,2,'Fixed charges cannot be deleted');
 grid.df.data[0].__checked=1;bulkRemove.call(grid);await context.lastSerial;
 assert.strictEqual(grid.df.data.length,2,'Bulk deletion also leaves both charge rows');
 grid.df.data[0].date=null;assert.strictEqual(grid.df.data[0].date,null);
 grid.df.data[0].date='2026-12-01';assert.strictEqual(grid.df.data[0].date,'2026-12-01','A blank date can be filled again');
 dialog.fields_dict.add_purchase.df.click();grid=dialog.fields_dict.payments_1.grid;
 context.NativeGrid.prototype.add_new_row.call(grid);assert(grid.df.data.every(row=>row.name));
 assert.strictEqual(new Set(grid.df.data.map(row=>row.name)).size,2);
 console.log('Native v12 single/bulk deletion, additions and reindexing preserve unselected popup rows');
})().catch(error=>{console.error(error);process.exitCode=1;});
