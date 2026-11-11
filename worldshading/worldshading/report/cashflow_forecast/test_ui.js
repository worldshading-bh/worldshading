/* Node-only report boundary checks. No browser, network or business data. */
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const context = {frappe: {query_reports: {}, defaults: {get_user_default: () => 'Example'},
    datetime: {get_today: () => '2026-11-09', add_months: () => '2027-02-09'},
    utils: {escape_html: s => String(s).replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')},
    ui: {}}, __: s => s, format_currency: value => String(value), console};
vm.createContext(context);
const file = path.join(__dirname, 'cashflow_forecast.js');
if (fs.existsSync(file)) vm.runInContext(fs.readFileSync(file, 'utf8'), context);
const settings = context.frappe.query_reports['Cashflow Forecast'];
assert(settings, 'Cashflow report must register');
const fields = settings.filters.map(f => f.fieldname);
['company','end_date','sales_adjustment','support_amount','extra_expenses'].forEach(
    name => assert(fields.includes(name), 'Missing filter: '+name));
assert(settings.filters.find(f => f.fieldname === 'extra_expenses').hidden);
assert(!fields.includes('today_receipts'),'Remaining receipts are automatic');
assert(!fields.includes('holiday_list'), 'Holiday calendars are automatic by date');
assert(!fields.includes('accounts'), 'Available accounts are resolved from the parent groups, not manually selected');
assert(settings.filters.find(f=>f.fieldname==='account_scope').hidden);
const format = value => String(value);
assert(settings.formatter(-10, 0, {fieldname:'closing_cash'}, {closing_cash:-10}, format).includes('#b42318'));
assert(settings.formatter('x', 0, {fieldname:'source_details'}, {date:'2026-11-09', sources:[{}]}, format).includes('cashflow-details'));
assert(!settings.formatter('<img>', 0, {fieldname:'source_details'}, {date:'2026-11-09', sources:[{}]}, format).includes('<img>'));
console.log('Report UI boundary checks passed');
var seenMethod = null;
context.frappe.call = opts => { seenMethod = opts.type; return {}; };
var originalCall = context.frappe.call;
var report = {report_name: 'Cashflow Forecast', page: {add_inner_button: () => {}},
    refresh: function () { return context.frappe.call({method:'frappe.desk.query_report.run', type:'GET', args:{report_name:this.report_name}}); }};
settings.onload(report);
report.refresh();
assert.strictEqual(seenMethod, 'POST', 'Scenario filters must use POST to avoid URL length limits');
assert.strictEqual(context.frappe.call, originalCall, 'Report must restore the shared call function');
console.log('Large-scenario request boundary passed');
var templateEngine = process.env.FRAPPE_MICROTEMPLATE_PATH || path.resolve(__dirname, '../../../../../frappe/frappe/public/js/frappe/microtemplate.js');
if (fs.existsSync(templateEngine)) {
    context.format_currency = value => String(value);
    vm.runInContext(fs.readFileSync(templateEngine, 'utf8'), context);
    var template = fs.readFileSync(path.join(__dirname, 'cashflow_forecast.html'), 'utf8');
    var render = context.frappe.template.compile(template, 'cashflow_print_test');
    assert.strictEqual(typeof render, 'function', 'Print format must compile in Frappe v12');
    var printed = render({filters:{company:'<unsafe>', end_date:'2026-12-31'}, report:{
        raw_data:{message:'<b>Planning assumptions</b>'}, columns:[{fieldname:'closing_cash',label:'Closing',fieldtype:'Currency'}],
        data:[{closing_cash:-2,currency:'BHD'}]}});
    assert(printed.includes('&lt;unsafe&gt;'));
    assert(printed.includes('Planning assumptions'));
    assert(printed.includes('-2'));
    console.log('Frappe v12 print template boundary passed');
}
var stored = {};
var savedValues = {company:'Example', account_scope:'parent-groups-v1', extra_expenses:'[{"date":"2026-11-19","amount":500,"description":"Saved scenario"}]', support_amount:120, forecast_date:'2026-11-09'};
context.frappe.call = opts => Promise.resolve({message:savedValues});
var savedReport = {report_name:'Cashflow Forecast', refresh:function(){}, page:{add_inner_button:()=>{}},
    get_query_params:()=>({prepared_report_name:'SNAPSHOT'}),
    filters:Object.keys(savedValues).map(name=>({df:{fieldname:name},set_input:value=>{stored[name]=value;}}))};
settings.onload(savedReport).then(function () {
    assert.strictEqual(stored.extra_expenses, savedValues.extra_expenses);
    assert.strictEqual(stored.support_amount, 120);
    assert.strictEqual(stored.account_scope, 'parent-groups-v1');
    assert.strictEqual(stored.forecast_date, '2026-11-09');
    var freshDate;
    context.frappe.datetime.get_today = () => '2026-11-10';
    settings.onload({report_name:'Cashflow Forecast',refresh:function(){},page:{add_inner_button:()=>{}},
        filters:[{df:{fieldname:'forecast_date'},set_input:value=>{freshDate=value;}}]});
    assert.strictEqual(freshDate, '2026-11-10', 'Fresh scenarios update date even when report settings were cached');
    console.log('Prepared scenario restoration and next-day date checks passed');
}).catch(function(error){ console.error(error); process.exitCode=1; });
var renderedContext = '';
var fakeBox = {length:1, off:function(){return this;},on:function(){return this;},html:function(html){renderedContext=html;return this;}};
context.frappe.query_report = {page:{main:{off:()=>fakeBox,find:()=>fakeBox}},raw_data:{result:[{
    _cashflow_context:{message:'Saved coverage warning',report_summary:[{label:'Ending',value:123}],chart:{type:'line'}}}]},
    get_chart_options:raw=>raw.chart,render_chart:function(options){this.savedChart=options;}};
settings.after_datatable_render();
assert(!renderedContext.includes('Saved coverage warning'));
assert.strictEqual(context.frappe.query_report.raw_data.message,'Saved coverage warning');
assert(renderedContext.includes('123'));
assert.strictEqual(context.frappe.query_report.savedChart.type,'line');
console.log('Compact summary, notes and restored saved graph passed');
function renderOpeningWithOverdue(opening, overdue, included) {
    var row={opening_cash:opening,closing_cash:123,currency:'BHD',_cashflow_context:{
        report_summary:[{label:'Opening Available Cash',value:opening,datatype:'Currency',currency:'BHD'}],
        base_filters:{include_overdue:included},calculation_inputs:{overdue:overdue}}};
    context.frappe.query_report.raw_data={result:[row]};
    settings.after_datatable_render();
    assert.strictEqual(row.opening_cash,opening);
    assert.strictEqual(row.closing_cash,123,'Summary must not change running cash');
    return renderedContext;
}
var openingHtml=renderOpeningWithOverdue(100,[{amount:'120.000'},{amount:'5.000'}],1);
assert(openingHtml.includes('After overdue'));
assert(openingHtml.includes('-25'));
assert(openingHtml.includes('cashflow-after-overdue is-negative'));
assert.strictEqual((openingHtml.match(/class="cashflow-card"/g)||[]).length,1,'Keep one opening card');
openingHtml=renderOpeningWithOverdue(100,[{amount:20}],1);
assert(openingHtml.includes('After overdue'));
assert(openingHtml.includes('80'));
assert(!openingHtml.includes('cashflow-after-overdue is-negative'));
assert(!renderOpeningWithOverdue(100,[{amount:20}],0).includes('After overdue'));
assert(!renderOpeningWithOverdue(100,[],1).includes('After overdue'));
assert(!renderOpeningWithOverdue(100,null,1).includes('After overdue'));
console.log('Opening summary shows cash after included overdue without changing balances');


assert.strictEqual(settings.filters.find(f=>f.fieldname==='include_overdue').default,0);
var overdueDialogs=[], queuedAlerts=0;
context.frappe.ui.Dialog=function(options){overdueDialogs.push(options);this.show=function(){};this.hide=function(){};};
context.frappe.show_alert=function(){queuedAlerts++;};
var currentFilters={company:'Example',end_date:'2026-12-31',include_overdue:0};
var generationReport={report_name:'Cashflow Forecast',refresh:function(){},generate_background_report:function(){throw new Error('Native generator must be guarded');},
    page:{add_inner_button:()=>{}},filters:[],get_filter_values:()=>currentFilters,
    toggle_primary_button_disabled:function(){},toggle_nothing_to_show:function(){}};
settings.onload(generationReport);
context.format_currency=(value)=>String(value);
context.frappe.call=function(options){
    assert.strictEqual(options.type,'POST');
    if(options.always)options.always();
    return Promise.resolve({message: currentFilters.include_overdue ? {name:'PREPARED-NEW'} : {blocked:true,overdue_review:{currency:'BHD',items:[
        {date:'2026-11-01',category:'supplier_payments',amount:500,doctype:'Payment Entry',name:'PE-OVERDUE',description:'<unsafe>'}]}}});
};
generationReport.generate_background_report().then(function(){
    assert.strictEqual(overdueDialogs.length,1);
    assert.strictEqual(queuedAlerts,0,'Blocked overdue review must not announce a queued report');
    assert(overdueDialogs[0].fields[0].options.includes('PE-OVERDUE'));
    assert(overdueDialogs[0].fields[0].options.includes('&lt;unsafe&gt;'));
    assert.strictEqual(generationReport.prepared_report_doc_name,undefined);
    currentFilters.include_overdue=1;
    return generationReport.generate_background_report();
}).then(function(){
    assert.strictEqual(generationReport.prepared_report_doc_name,'PREPARED-NEW');
    assert.strictEqual(overdueDialogs.length,1,'Explicit inclusion should proceed without another overdue popup');
    assert.strictEqual(queuedAlerts,1);
    console.log('Overdue popup blocks unchecked generation and checked mode proceeds');
}).catch(function(error){console.error(error);process.exitCode=1;});

['date','opening_cash','total_payments','source_details'].forEach(function(field) {
    var output=settings.formatter(10,0,{fieldname:field},{date:'2026-11-10',closing_cash:-1,sources:[{}]},format);
    assert(output.includes('cashflow-negative-cell'),'Every cell in a shortfall row must be highlighted: '+field);
});
assert(!settings.formatter(10,0,{fieldname:'opening_cash'},{closing_cash:1},format).includes('cashflow-negative-cell'));
assert(settings.formatter(10,0,{fieldname:'total_payments'},{closing_cash:1,date:'2026-11-10'},format).includes('data-kind="payments"'));
assert(!settings.filters.some(f=>f.fieldname==='detailed_view'));

// Native v12 toolbar fields have only_input=true and no label element.
let filterLabels=[];
const labelWrapper={find:()=>({length:0}),prepend:html=>{filterLabels.push(html);}};
settings.onload({report_name:'Cashflow Forecast',refresh:()=>{},page:{add_inner_button:()=>{}},
 filters:[{df:{fieldname:'end_date',label:'Forecast Until',fieldtype:'Date'},$wrapper:labelWrapper}]});
assert.strictEqual(filterLabels.length,0,'Keep the compact placeholder-only filter layout');
console.log('Compact filters do not inject extra labels');
