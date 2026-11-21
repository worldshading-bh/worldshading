/* Single view and source drilldown use loaded prepared data, never a new request. */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
let buttons={},boundClick,summaryHTML='',dialog;
const box={length:1,html:html=>{summaryHTML=html;return box;},off:()=>box,
 on:(event,selector,handler)=>{boundClick=handler;return box;}};
const context={__:s=>s,console,format_currency:(v,c)=>String(c||'BHD')+' '+v,
 $:()=>({attr:name=>name==='data-key'?'2026-12-19':'bank_loan_repayments'}),
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
const rows=[{date:'2026-12-19',currency:'BHD',opening_cash:1000,closing_cash:888,total_payments:112,bank_loan_repayments:112,
 sources:[{date:'2026-12-19',category:'bank_loan_repayments',doctype:'Bank Loan',name:'BL1',amount:112,principal_amount:100,interest_amount:10,charges_amount:2,description:'Installment <one>'}],
 _cashflow_context:{forecast_date:'2026-11-21',bank_loan_names:['BL1'],report_summary:[]}}];
report.prepare_report_data({columns:[],result:rows});context.frappe.query_report=report;
const col=report.columns.find(c=>c.fieldname==='bank_loan_repayments');
assert(col && col.label==='Bank Loan Repayments');
const formatted=settings.formatter(112,0,col,rows[0],String);
assert(formatted.includes('data-kind="bank_loan_repayments"'));
settings.after_datatable_render();boundClick.call({}, {preventDefault:()=>{}});
assert.strictEqual(dialog.title,'Bank Loan Repayments');
const html=dialog.fields[0].options;
assert(html.includes('BL1'));assert(html.includes('Principal'));assert(html.includes('Interest'));assert(html.includes('Charges'));
assert(html.includes('&lt;one&gt;'));
console.log('Loan column and clickable component breakdown use saved report rows without requests');
