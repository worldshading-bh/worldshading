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
['baseline_closing_cash','available_above_reserve'].forEach(name=>assert(report.columns.find(c=>c.fieldname===name).hidden));
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
assert.strictEqual(scenario[0].supplier_payments,25);
report.prepare_report_data({columns:[],result:scenario});
assert.strictEqual(scenario[0].supplier_payments,25);
['proposed_purchase','purchase_impact'].forEach(name=>assert(!report.columns.some(c=>c.fieldname===name)));
['baseline_closing_cash','available_above_reserve'].forEach(name=>assert(!report.columns.find(c=>c.fieldname===name).hidden));
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
boundClick.call({classList:{contains:name=>name==='cashflow-opening-balance'}},{preventDefault:()=>{}});
assert(dialog.fields[0].options.includes('Bank - WS'));
assert(dialog.fields[0].options.includes('BHD 120.000'));
console.log('Opening cash account breakdown, support, escaping and hidden start date passed');

// Included overdue remains reviewable from the generated report, grouped from saved data.
const savedOverdue=[
 {date:'2026-10-01',category:'other_payments',doctype:'GL Payment',name:'GL-TEST',amount:'10.000',description:'Office <cost>',workflow_state:'Pending'},
 {date:'2026-10-01',category:'other_payments',doctype:'GL Payment',name:'GL-TEST',amount:'2.000',description:'Another line'},
 {date:'2026-10-02',category:'supplier_payments',doctype:'Payment Entry',name:'PE-TEST',amount:'20.000',description:'Supplier installment',related_doctype:'Purchase Order',related_name:'PO-TEST'},
 {date:'2026-10-03',category:'payroll',doctype:'Journal Entry',name:'JV-TEST',amount:'5.000',description:'Salary'}];
const originalOverdue=JSON.stringify(savedOverdue);
report.raw_data={result:[{date:'2026-11-10',opening_cash:100,currency:'BHD',_cashflow_context:{
 forecast_date:'2026-11-10',base_filters:{include_overdue:1},calculation_inputs:{overdue:savedOverdue},
 report_summary:[{label:'Opening Available Cash',value:100,datatype:'Currency',currency:'BHD'}]}}]};
settings.after_datatable_render();
assert(summaryHTML.includes('cashflow-overdue-total'));
assert(summaryHTML.includes('BHD 37'));
boundClick.call({classList:{contains:name=>name==='cashflow-overdue-total'}},{preventDefault:()=>{}});
assert.strictEqual(dialog.title,'Review Overdue Commitments');
assert(!dialog.fields[0].options.includes('<details open'),'Overdue categories start collapsed');
assert(dialog.fields[0].options.includes('<details class="cashflow-review-group"'));
const overdueHTML=dialog.fields[0].options;
['GL Payments','Journal Entries (JV)','Supplier payments','GL-TEST','PE-TEST','JV-TEST','PO-TEST','2026-10-01','Office &lt;cost&gt;','Another line'].forEach(text=>assert(overdueHTML.includes(text),text));
assert(overdueHTML.includes('BHD 12'));
assert(overdueHTML.includes('Overdue items: 3'));
assert(!overdueHTML.includes('or include them today'));
assert.strictEqual(JSON.stringify(savedOverdue),originalOverdue,'Do not mutate saved overdue rows');
console.log('Saved overdue popup retains categories, original dates, merged amounts and document links');

// Summary and highlights use rendered sources, never pending filter edits.
const manualSources=[{date:'2026-11-10',category:'other_receipts',amount:100,manual_support:true,description:'Support: <Owner>'},
 {date:'2026-11-10',category:'other_receipts',amount:30,description:'Ordinary receipt'},
 {date:'2026-11-10',category:'extra_expenses',amount:25,description:'Repairs'},
 {date:'2026-11-10',category:'proposed_purchase',amount:1000,scenario:true,scenario_kind:'supplier',purchase_number:1},
 {date:'2026-11-12',category:'customs',amount:50,scenario:true,scenario_kind:'arrival',purchase_number:1},
 {date:'2026-11-12',category:'import_vat',amount:105,scenario:true,scenario_kind:'arrival',purchase_number:1},
 {date:'2026-11-12',category:'vat_accrual',amount:-105,scenario:true,scenario_kind:'arrival',purchase_number:1}];
const manual=Object.assign({},rows[0],{sources:manualSources,other_receipts:130,extra_expenses:25});
report.prepare_report_data({columns:[],result:[manual]});settings.after_datatable_render();
assert(summaryHTML.includes('cashflow-manual-inputs'));
assert(summaryHTML.includes('data-input-kind="support"'));assert(summaryHTML.includes('BHD 100'));
assert(summaryHTML.includes('data-input-kind="expenses"'));assert(summaryHTML.includes('BHD 25'));
assert(summaryHTML.includes('data-input-kind="purchases"'));assert(summaryHTML.includes('BHD 1155'));
assert(settings.formatter(130,0,{fieldname:'other_receipts'},manual,format).includes('cashflow-manual-cell'));
assert(settings.formatter(25,0,{fieldname:'extra_expenses'},manual,format).includes('cashflow-manual-cell'));
assert(!settings.formatter(100,0,{fieldname:'opening_cash'},manual,format).includes('cashflow-manual-cell'));
assert(!settings.formatter(30,0,{fieldname:'other_receipts'},{sources:[manualSources[1]],closing_cash:100},format).includes('cashflow-manual-cell'));
const originalDollar=context.$;context.$=()=>({attr:name=>name==='data-input-kind'?'support':null});
boundClick.call({classList:{contains:name=>name==='cashflow-manual-input'}},{preventDefault:()=>{}});
assert(dialog.title==='Support');assert(dialog.fields[0].options.includes('10-11-2026'));assert(dialog.fields[0].options.includes('&lt;Owner&gt;'));
assert(!dialog.fields[0].options.includes('Ordinary receipt'));
context.$=()=>({attr:name=>name==='data-input-kind'?'purchases':null});
boundClick.call({classList:{contains:name=>name==='cashflow-manual-input'}},{preventDefault:()=>{}});
assert(dialog.fields[0].options.includes('12-11-2026'));assert(dialog.fields[0].options.includes('Import VAT'));assert(!dialog.fields[0].options.includes('-105'));
context.$=originalDollar;
report.prepare_report_data({columns:[],result:[Object.assign({},manual,{month:'2026-11'})]});settings.after_datatable_render();
assert(summaryHTML.includes('BHD 1155'));assert(summaryHTML.includes('data-input-kind="support"'));
assert(settings.formatter(130,0,{fieldname:'other_receipts'},report.data[0],format).includes('cashflow-manual-cell'));
report.prepare_report_data({columns:[],result:[Object.assign({},rows[0],{sources:[]})]});settings.after_datatable_render();
assert(!summaryHTML.includes('class="cashflow-manual-inputs"'));
console.log('Compact manual-input summary, saved-date breakdown and exact-cell highlights passed');

report.prepare_report_data({columns:[],result:[{date:'2026-11-10',opening_cash:100,currency:'BHD',
 _cashflow_context:{forecast_date:'2026-11-10',opening_accounts:[{account:'Bank',amount:100}],
 excluded_opening_accounts:[{account:'Deposit <Restricted>',amount:200}]}}]});
settings.after_datatable_render();
boundClick.call({classList:{contains:name=>name==='cashflow-opening-balance'}},{preventDefault:()=>{}});
assert(dialog.fields[0].options.includes('Excluded Accounts'));assert(dialog.fields[0].options.includes('Deposit &lt;Restricted&gt;'));
assert(dialog.fields[0].options.includes('BHD 100.000'));assert(!dialog.fields[0].options.includes('BHD 300.000'));
console.log('Opening breakdown separates included and excluded balances without adding exclusions to total');

// Supplier display names travel with the saved event and are escaped in drilldown.
context.$=()=>({attr:name=>name==='data-key'?'2026-11-10':'supplier_payments'});
report.data=[Object.assign({},rows[0],{sources:[{category:'supplier_payments',amount:25,doctype:'Payment Entry',name:'PE-SUPPLIER',party_type:'Supplier',party:'SUP-001',supplier_name:'Example <Trading>'}]})];
settings.after_datatable_render();boundClick.call({}, {preventDefault:()=>{}});
assert(dialog.fields[0].options.includes('Example &lt;Trading&gt;'));
assert(dialog.fields[0].options.includes('PE-SUPPLIER'));
console.log('Supplier payment drilldown shows escaped supplier name alongside its document');

// Saved daily reports also use the full period for the baseline comparison.
const comparisonRows=[Object.assign({},rows[0],{baseline_closing_cash:100,closing_cash:100,
 _cashflow_context:{report_summary:[{label:'Lowest Balance',value:50,datatype:'Currency',currency:'BHD'},
 {label:'Lowest Balance Date',value:'2026-11-12'},
 {label:'Lowest Cash Without Purchase',value:200,datatype:'Currency',currency:'BHD'},
 {label:'Lowest Cash With Purchase',value:50,datatype:'Currency',currency:'BHD'}]}}),
 Object.assign({},rows[0],{date:'2026-11-12',baseline_closing_cash:200,closing_cash:50})];
report.prepare_report_data({columns:[],result:comparisonRows});settings.after_datatable_render();
assert(!summaryHTML.includes('Lowest Cash With Purchase'));
assert(summaryHTML.includes('Lowest Cash Without Purchase'));
assert(summaryHTML.includes('Across the whole forecast, excluding added purchases. Support and extra expenses stay included.'));
assert(summaryHTML.includes('Across the whole forecast, including added purchases.'));
assert(summaryHTML.includes('On 10-11-2026'));
assert(summaryHTML.includes('BHD 100'));
console.log('Whole-period comparison, baseline date, explanatory tooltips and duplicate removal passed');

report.prepare_report_data({columns:[],result:[Object.assign({},rows[0],{_cashflow_context:{
 excluded_opening_accounts:[{account:'Deposit',amount:'100.100'},{account:'Adjustment',amount:'-20.050'}],
 sales_comparison:{current_start:'2026-01-01',current_end:'2026-11-10',previous_start:'2025-01-01',previous_end:'2025-11-10',current:'120.000',previous:'100.000',difference:'20.000',percentage:'20.00'}}})]});
settings.after_datatable_render();
assert(summaryHTML.includes('Sales this year'));
assert(summaryHTML.includes('+20.00%'));
buttons['Report Notes']();assert(dialog.fields[0].options.includes('80.05'));
console.log('Signed excluded-account total and year-to-date sales comparison summary passed');

boundClick.call({classList:{contains:name=>name==='cashflow-sales-comparison'}},{preventDefault:()=>{}});
assert.strictEqual(dialog.title,'Sales Comparison');
assert(!dialog.fields[0].options.includes('Submitted sales invoices, including VAT and returns.'));
console.log('Sales comparison popup omits the removed explanatory sentence');

const referenceRow=Object.assign({},rows[0],{date:'2027-11-18',previous_year_sales:110,expected_receipts:110,
 _cashflow_context:{historical_reference_year:2025,sales_adjustment:0}});
report.prepare_report_data({columns:[],result:[referenceRow]});
let referenceTip=settings.formatter(110,0,{fieldname:'expected_receipts'},referenceRow,v=>String(v));
assert(referenceTip.includes('Reference Sales (2025)'));assert(referenceTip.includes('18-11-2025'));
referenceRow.date='2028-02-29';referenceRow.previous_year_sales=0;
referenceTip=settings.formatter(0,0,{fieldname:'expected_receipts'},referenceRow,v=>String(v));
assert(referenceTip.includes('28-02-2025'));assert(referenceTip.includes('Recorded net sales for this reference date are zero.'));
console.log('Fixed reference-year tooltip identifies the exact source date and recorded zero sales');
