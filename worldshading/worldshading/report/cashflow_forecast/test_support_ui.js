/* Dated support uses one filter update; opening and closing a dialog do nothing. */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
let buttons={},dialog,updates=[],messages=[],filters={support_amount:0,support_payments:'[]',extra_expenses:'[]',end_date:'2026-11-20'};
const context={__:x=>x,console,frappe:{query_reports:{},defaults:{get_user_default:()=> 'Example'},
 datetime:{get_today:()=> '2026-11-15',add_months:()=> '2027-02-15'},utils:{escape_html:x=>String(x)},
 ui:{Dialog:function(options){dialog=options;this.show=()=>{};this.hide=()=>{};}},msgprint:m=>messages.push(m),
 call:()=>{throw Error('Dialog must not enqueue directly');}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'cashflow_forecast.js'),'utf8'),context);
const settings=context.frappe.query_reports['Cashflow Forecast'];
const report={report_name:'Cashflow Forecast',filters:[],page:{add_inner_button:(label,fn)=>{buttons[label]=fn;}},
 get_filter_value:key=>filters[key],set_filter_value:(key,value)=>{updates.push([key,value]);if(typeof key==='object')Object.assign(filters,key);else filters[key]=value;}};
settings.onload(report);
assert(settings.filters.find(f=>f.fieldname==='support_amount').hidden);
assert(settings.filters.find(f=>f.fieldname==='support_payments').hidden);
assert(buttons['Add Support']);buttons['Add Support']();
assert.strictEqual(updates.length,0);assert(!dialog.secondary_action);
let table=dialog.fields.find(f=>f.fieldtype==='Table');
assert.strictEqual(table.data.length,0);assert(!table.fields.find(f=>f.fieldname==='description').reqd);
dialog.primary_action({expenses:[{date:'2026-11-17',amount:100},{date:'2026-11-19',amount:50,description:'Owner funding'}]});
assert.strictEqual(updates.length,1);assert.strictEqual(JSON.parse(filters.support_payments).length,2);
buttons['Add Support']();assert.strictEqual(dialog.fields.find(f=>f.fieldtype==='Table').data.length,2);
dialog.primary_action({expenses:[{date:'2026-11-21',amount:100}]});
assert.strictEqual(updates.length,1);assert.strictEqual(messages.length,1);
dialog.primary_action({expenses:[]});assert.strictEqual(filters.support_payments,'[]');assert.strictEqual(updates.length,2);
filters.support_amount=25;buttons['Add Support']();table=dialog.fields.find(f=>f.fieldtype==='Table');
assert.strictEqual(table.data[0].date,'2026-11-15');assert.strictEqual(table.data[0].amount,25);
dialog.primary_action({expenses:table.data});
assert.strictEqual(filters.support_amount,0);assert.strictEqual(JSON.parse(filters.support_payments)[0].amount,25);
assert.strictEqual(updates.length,3,'Legacy migration updates filters in one batch');
buttons['Add Extra Expenses']();assert(dialog.fields.find(f=>f.fieldtype==='Table').fields.find(f=>f.fieldname==='description').reqd);
console.log('Dated support table, validation, restore, clear and legacy migration passed');
