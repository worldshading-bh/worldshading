/* Calendar default, per-day reference tooltips and clear fallback notes. */
const assert=require('assert'),fs=require('fs'),vm=require('vm'),path=require('path');
const code=fs.readFileSync(path.join(__dirname,'cashflow_forecast.js'),'utf8');
function setup(today){
 const buttons={};let options;
 const context={__:x=>x,console,format_currency:value=>String(value),frappe:{query_reports:{},defaults:{get_user_default:()=> 'Example'},datetime:{get_today:()=>today},utils:{escape_html:String},ui:{Dialog:function(value){options=value;this.show=()=>{};}}}};
 vm.createContext(context);vm.runInContext(code,context);
 return {context,buttons,settings:context.frappe.query_reports['Cashflow Forecast'],dialog:()=>options};
}
for(const [today,expected] of [['2026-11-18','2027-11-18'],['2028-02-29','2029-02-28'],['2026-12-31','2027-12-31']]){
 const app=setup(today);assert.strictEqual(app.settings.filters.find(f=>f.fieldname==='end_date').default,expected);
}
const app=setup('2026-11-18');
const periods=[{forecast_from:'2027-01-01',forecast_to:'2027-11-18',reference_from:'2026-01-01',reference_to:'2026-11-18',fallback:false},
 {forecast_from:'2027-11-19',forecast_to:'2027-12-31',reference_from:'2025-11-19',reference_to:'2025-12-31',fallback:true}];
const report={report_name:'Cashflow Forecast',filters:[],page:{add_inner_button:(label,fn)=>{app.buttons[label]=fn;}},refresh:()=>{},raw_data:{result:[{currency:'BHD',_cashflow_context:{forecast_date:'2026-11-18',historical_reference_periods:periods}}]}};
app.context.frappe.query_report=report;app.settings.onload(report);
function tooltip(date,month){return app.settings.formatter(100,0,{fieldname:'expected_receipts'},{date,month,currency:'BHD',previous_year_sales:100,expected_receipts:100},String);}
assert(tooltip('2027-01-02').includes('02-01-2026'));
assert(tooltip('2027-11-19').includes('19-11-2025'));
const monthly=tooltip('2027-11-01','2027-11');
assert(monthly.includes('Reference Sales'));assert(!monthly.includes('Reference Sales (2026)'),'Mixed-reference months must not imply one source year');
app.buttons['Report Notes']();
const html=app.dialog().fields[0].options;
assert(html.includes('19-11-2027'));assert(html.includes('31-12-2027'));assert(html.includes('19-11-2025'));assert(html.includes('31-12-2025'));
assert(html.includes('recorded zero-sales days stay zero'));
console.log('One-year default, leap-day clamp, daily references, mixed-month tooltip and fallback notes passed');
