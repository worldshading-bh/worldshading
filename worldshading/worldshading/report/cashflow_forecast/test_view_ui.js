/* Single view and source drilldown use loaded prepared data, never a new request. */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
let buttons={},boundClick,summaryHTML='',dialog;
const box={length:1,html:html=>{summaryHTML=html;return box;},off:()=>box,
 on:(event,selector,handler)=>{boundClick=handler;return box;}};
const context={__:s=>s,console,format_currency:(v,c)=>String(c||'BHD')+' '+v,
 $:()=>({attr:name=>name==='data-key'?'2026-11-10':'other_receipts'}),
 frappe:{query_reports:{},defaults:{get_user_default:()=> 'Example'},
 datetime:{get_today:()=> '2026-11-10',add_months:()=> '2027-02-10'},utils:{escape_html:s=>String(s).replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')},
 ui:{Dialog:function(options){dialog=options;this.show=()=>{};}},
 call:()=>{throw new Error('Presentation must not request data or queue a report');}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'cashflow_forecast.js'),'utf8'),context);
const settings=context.frappe.query_reports['Cashflow Forecast'];
const report={report_name:'Cashflow Forecast',filters:[],page:{main:{off:()=>box,find:()=>box},add_inner_button:(label,fn)=>{buttons[label]=fn;}},
 get_chart_options:raw=>raw.chart,refresh:()=>{throw new Error('Must not refresh');},prepare_columns:columns=>columns,
 prepare_report_data:function(raw){this.raw_data=raw;this.data=raw.result;}};
settings.onload(report);
assert(!buttons['Detailed View'] && !buttons['Simple View']);
const rows=[{date:'2026-11-10',opening_cash:100,expected_receipts:0,other_receipts:284.7,
 budget_expenses:5,proposed_purchase:0,total_payments:25,closing_cash:359.7,available_above_reserve:359.7,
 previous_year_sales:100,adjusted_sales:110,actual_sales_today:123,total_receipts:284.7,
 fixed_expenses:20,payroll:0,supplier_payments:0,baseline_closing_cash:359.7,purchase_impact:0,
 sources:[{category:'other_receipts',amount:200,doctype:'GL Payment',name:'GLP-INCOMING',related_documents:[{doctype:'Purchase Invoice',name:'PI-REFERENCE'}],date:'2026-11-10',workflow_state:'Pending Bank Payment - Chkr',description:'<incoming>'},
          {category:'fixed_expenses',amount:20,doctype:'GL Payment',name:'GLP-OUTGOING',description:'Outgoing only'}],
 _cashflow_context:{forecast_date:'2026-11-10',sales_adjustment:10,minimum_reserve:0,message:'Saved coverage',report_summary:[{label:'Ending Balance',value:359.7,datatype:'Currency',currency:'BHD'}]}}];
report.prepare_report_data({columns:[],result:rows});context.frappe.query_report=report;
assert.strictEqual(report.data,rows);
['actual_sales_today','previous_year_sales','total_receipts'].forEach(name=>assert(!report.columns.some(c=>c.fieldname===name)));
['fixed_expenses','supplier_payments','payroll'].forEach(name=>assert(!report.columns.find(c=>c.fieldname===name).hidden));
['proposed_purchase','baseline_closing_cash','purchase_impact','available_above_reserve'].forEach(name=>assert(report.columns.find(c=>c.fieldname===name).hidden));
assert.strictEqual(report.columns.find(c=>c.fieldname==='other_receipts').label,'Other Incoming');
const format=v=>String(v);
let sales=settings.formatter(0,0,{fieldname:'expected_receipts'},rows[0],format);
assert(sales.includes('title='));assert(sales.includes('100'));assert(sales.includes('10%'));assert(sales.includes('original calculation'));
let incoming=settings.formatter(284.7,0,{fieldname:'other_receipts'},rows[0],format);
assert(incoming.includes('data-kind="other_receipts"'));
settings.after_datatable_render();
assert(summaryHTML.includes('cashflow-summary'));assert(!summaryHTML.includes('Saved coverage'));assert(!summaryHTML.includes('Row colors:'));assert(!summaryHTML.includes('cashflow-legend'));assert(summaryHTML.includes('Opening Available Cash'));
buttons['Report Notes']();
assert(dialog.fields[0].options.includes('Saved coverage'));
boundClick.call({}, {preventDefault:()=>{}});
const html=dialog.fields[0].options;
assert(html.includes('GLP-INCOMING'));assert(html.includes('PI-REFERENCE'));assert(html.includes('target="_blank"'));assert(html.includes('Pending Bank Payment - Chkr'));assert(html.includes('&lt;incoming&gt;'));
assert(!html.includes('GLP-OUTGOING'));assert(!html.includes('Closing Without Purchase'));
assert(dialog.title.includes('Other Incoming'));
let ordinary=settings.formatter(10,0,{fieldname:'opening_cash'},{closing_cash:-10},format);
let closing=settings.formatter(-10,0,{fieldname:'closing_cash'},{closing_cash:-10},format);
assert(ordinary.includes('cashflow-negative-cell'));assert(!ordinary.includes('color:#b42318'));assert(closing.includes('color:#b42318'));
const scenario=[Object.assign({},rows[0],{proposed_purchase:25,purchase_impact:-25,available_above_reserve:349.7,
 _cashflow_context:{minimum_reserve:10}})];
report.prepare_report_data({columns:[],result:scenario});
['proposed_purchase','baseline_closing_cash','purchase_impact','available_above_reserve'].forEach(name=>assert(!report.columns.find(c=>c.fieldname===name).hidden));
report.prepare_report_data({columns:[],result:[Object.assign({},rows[0],{month:'2026-11'})]});
assert.strictEqual(report.columns[0].fieldname,'month');
console.log('Single view, conditional columns, sales tooltip, filtered incoming references, summary and soft highlight checks passed');

const chart=report.get_chart_options({chart:{data:{labels:['2026-11-10'],datasets:[{values:[-10]}]}}});
assert.strictEqual(chart.data.datasets[0].values[0],-10);
assert.strictEqual(chart.height,200);
assert.strictEqual(chart.data.yMarkers[0].value,0);

// Budget details show one daily total, not each account allowance.
report.prepare_report_data({columns:[],result:[Object.assign({},rows[0],{budget_expenses:30,sources:[
 {category:'budget_expenses',amount:10,doctype:'Budget',name:'BUDGET-A',description:'Account one'},
 {category:'budget_expenses',amount:20,doctype:'Budget',name:'BUDGET-A',description:'Account two'}]})]});
settings.after_datatable_render();
context.$=()=>({attr:name=>name==='data-key'?'2026-11-10':'budget_expenses'});
boundClick.call({}, {preventDefault:()=>{}});
assert(dialog.fields[0].options.includes('Daily budget'));
assert(dialog.fields[0].options.includes('BHD 30'));
assert(!dialog.fields[0].options.includes('Account one'));
assert(!dialog.fields[0].options.includes('Scenario Only'));

// Existing snapshots' old HTML notes are restyled rather than shown as a wall of text.
report.raw_data={result:[{date:'2026-11-10',currency:'BHD',_cashflow_context:{forecast_date:'2026-11-10',
 message:'<b>Old notes</b><br>Bank - WS: 100.000; Cash - WS: 20.000<br><div class="alert alert-warning"><ul><li>Check unpaid invoice.</li></ul></div>'}}]};
buttons['Report Notes']();
const notes=dialog.fields[0].options;
assert(notes.includes('Opening Account Balances'));assert(notes.includes('Bank - WS'));assert(notes.includes('Check unpaid invoice.'));
assert(!notes.includes('alert-warning'));assert(notes.includes('<table'));

report.data=[{date:'2026-11-10',currency:'BHD',sources:[{category:'supplier_payments',amount:67.1,name:'PI',doctype:'Purchase Invoice'},
 {category:'vat_accrual',amount:-6.1,name:'PO',doctype:'Purchase Order'}]}];
context.$=()=>({attr:name=>name==='data-key'?'2026-11-10':undefined});
boundClick.call({}, {preventDefault:()=>{}});
assert(dialog.fields[0].options.includes('VAT Adjustment for Quarter-End'));
assert(dialog.fields[0].options.includes('Not a payment today.'));
assert(!dialog.fields[0].options.includes('VAT Accrual'));

// Opening cash opens the saved account breakdown without requests or report rebuilds.
assert.strictEqual(settings.filters.find(f=>f.fieldname==='forecast_date').hidden,1);
report.raw_data={result:[{date:'2026-11-10',opening_cash:105,currency:'BHD',_cashflow_context:{
 forecast_date:'2026-11-10',support_amount:'10.000',opening_accounts:[
 {account:'Bank <Main>',amount:'100.000'},{account:'Cash',amount:'-5.000'}],
 report_summary:[{label:'Opening Available Cash',value:105,datatype:'Currency',currency:'BHD'}]}}]};
settings.after_datatable_render();
assert(summaryHTML.includes('cashflow-opening-balance'));
assert(summaryHTML.includes('View account balances'));
boundClick.call({classList:{contains:name=>name==='cashflow-opening-balance'}},{preventDefault:()=>{}});
assert.strictEqual(dialog.title,'Opening Cash');
let openingDetails=dialog.fields[0].options;
assert(openingDetails.includes('Bank &lt;Main&gt;'));
assert(!openingDetails.includes('Bank <Main>'));
assert(openingDetails.includes('BHD -5.000'));
assert(openingDetails.includes('Support'));
assert(openingDetails.includes('BHD 105.000'));
assert(openingDetails.includes('10-11-2026'));
assert.strictEqual(report.raw_data.result[0].opening_cash,105);
// Older snapshots can use the same account parsing as Report Notes.
report.raw_data={result:[{date:'2026-11-10',opening_cash:120,currency:'BHD',_cashflow_context:{
 message:'Bank - WS: 100.000; Cash - WS: 20.000'}}]};
settings.after_datatable_render();
boundClick.call({classList:{contains:()=>true}},{preventDefault:()=>{}});
assert(dialog.fields[0].options.includes('Bank - WS'));
assert(dialog.fields[0].options.includes('BHD 120.000'));
console.log('Opening cash account breakdown, support, escaping and hidden start date passed');
