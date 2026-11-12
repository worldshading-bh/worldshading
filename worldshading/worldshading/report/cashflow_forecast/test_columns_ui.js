/* Native-table fixture: columns/values move together; no queries or global changes. */
const assert=require('assert'),fs=require('fs'),vm=require('vm'),path=require('path');
function classes(){const set=new Set();return {add:(...x)=>x.forEach(v=>set.add(v)),remove:(...x)=>x.forEach(v=>set.delete(v)),contains:v=>set.has(v),toggle:(v,on)=>on?set.add(v):set.delete(v)};}
function events(obj){obj.handlers={};obj.addEventListener=(n,fn)=>(obj.handlers[n]||(obj.handlers[n]=new Set())).add(fn);obj.removeEventListener=(n,fn)=>obj.handlers[n].delete(fn);return obj;}
let frames=new Map(),frameId=0,styles={},observers=[],alerts=[];
const window=events({requestAnimationFrame:fn=>{frames.set(++frameId,fn);return frameId;},cancelAnimationFrame:id=>frames.delete(id)});
const document=events({getElementById:id=>styles[id]||null,createElement:()=>({}),head:{appendChild:node=>{styles[node.id]=node;}}});
const box={length:1,off:()=>box,on:()=>box,html:()=>box,remove:()=>box};
const context={window,document,console,__:s=>s,format_currency:String,
 MutationObserver:function(fn){this.fn=fn;this.observe=target=>{this.target=target;};this.disconnect=()=>{this.disconnected=true;};observers.push(this);},
 frappe:{query_reports:{},defaults:{get_user_default:()=>''},datetime:{get_today:()=> '2026-11-12',add_months:()=>''},utils:{escape_html:String},msgprint:msg=>alerts.push(msg),call:()=>{throw Error('Column controls must not query/rebuild');}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'cashflow_forecast.js'),'utf8'),context);
const settings=context.frappe.query_reports['Cashflow Forecast'];
const report={report_name:'Cashflow Forecast',filters:[],page:{main:{find:()=>box,off:()=>box},add_inner_button:()=>{}},
 refresh:()=>{throw Error('No report rebuild');},load_report:()=> 'loaded',prepare_columns:x=>x,
 prepare_report_data:function(raw){this.raw_data=raw;this.data=raw.result;},raw_data:{result:[]}};
context.frappe.query_report=report;settings.onload(report);
function makeTable(fields) {
 const columns=fields.map((field,i)=>({fieldname:field,id:field,colIndex:i,width:i?145:50}));
 const values=fields.map((field,i)=>({field,value:'value:'+field}));
 const body=events({scrollLeft:0,scrollWidth:2400,clientWidth:700,querySelector:()=>null});
 let selected={classList:classes(),getAttribute:()=> '0',closest:()=>null};
 const header={},cells=[];function cell(i){return cells[i]||(cells[i]={classList:classes(),style:{},getBoundingClientRect:()=>({width:columns[i]?columns[i].width:50})});}
 const wrapper=events({classList:classes(),style:{setProperty:(k,v)=>{wrapper[k]=v;}},
  querySelector:s=>{let m=s.match(/dt-row-header \.dt-cell--col-(\d+)/);return m?cell(+m[1]):null;},
  querySelectorAll:s=>s.includes('data-row-index')?[selected]:[cell(+(s.match(/col-(\d+)/)||[])[1])]});
 const hooks={};let sorterOptions={disabled:false,filter:'.dt-cell__resize-handle, .dt-dropdown',preventOnFilter:false};
 const table={wrapper,header,bodyScrollable:body,options:{serialNoColumn:true},on:(name,fn)=>{(hooks[name]||(hooks[name]=[])).push(fn);},
  datamanager:{getColumns:()=>columns},emit:(name,...args)=>(hooks[name]||[]).forEach(fn=>fn(...args)),
  columnmanager:{sortable:{option:function(k,v){if(arguments.length===1)return sorterOptions[k];sorterOptions[k]=v;}},
   switchColumn:(a,b)=>{[columns[a],columns[b]]=[columns[b],columns[a]];[values[a],values[b]]=[values[b],values[a]];columns.forEach((c,i)=>c.colIndex=i);
    window.requestAnimationFrame(()=>table.emit('onSwitchColumn',columns[a],columns[b]));}},
  removeColumn:i=>{let removed=columns.splice(i,1)[0];values.splice(i,1);columns.forEach((c,j)=>c.colIndex=j);table.emit('onRemoveColumn',removed);}};
 table.fields=()=>columns.map(c=>c.fieldname);table.values=values;table.sorterOptions=sorterOptions;table.cells=cells;table.selected=selected;
 table.newHeader=()=>{sorterOptions={disabled:false};table.columnmanager.sortable={option:function(k,v){if(arguments.length===1)return sorterOptions[k];sorterOptions[k]=v;}};table.sorterOptions=sorterOptions;
  observers.filter(o=>!o.disconnected&&o.target===header).forEach(o=>o.fn());};
 return table;
}
function flush(){let count=0;while(frames.size){assert(++count<60,'Layout must settle without an observer loop');const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn());}}
const fields=['_rowIndex','date','opening_cash','expected_receipts','payroll','closing_cash','source_details'];
let table=makeTable(fields);report.datatable=table;settings.after_datatable_render(table);flush();
assert.strictEqual(table.sorterOptions.disabled,false,'Analytical columns can be dragged');
assert.strictEqual(typeof table.sorterOptions.onMove,'function');
const moving=(a,b)=>table.sorterOptions.onMove({dragged:{dataset:{colIndex:String(a)}},related:{dataset:{colIndex:String(b)}}});
assert.strictEqual(moving(3,5),true);assert.strictEqual(moving(1,4),false);assert.strictEqual(moving(5,2),false);
const options=settings.get_datatable_options({columns:[]});
const pin=options.headerDropdown.find(item=>item.label==='Pin / Unpin Column');assert(pin,'Native column menu must offer pin/unpin');
pin.action.call(table,table.datamanager.getColumns()[5]);flush();
assert.deepStrictEqual(table.fields().slice(0,4),['_rowIndex','date','opening_cash','closing_cash']);
assert.strictEqual(moving(3,5),false,'Extra pinned columns are protected from dragging');
assert(styles['cashflow-sticky-style'].textContent.includes('.dt-cell--col-3::after'));
pin.action.call(table,table.datamanager.getColumns().find(c=>c.fieldname==='payroll'));flush();
assert.deepStrictEqual(table.fields().slice(0,5),['_rowIndex','date','opening_cash','closing_cash','payroll']);
pin.action.call(table,table.datamanager.getColumns().find(c=>c.fieldname==='closing_cash'));flush();
assert.deepStrictEqual(table.fields().slice(0,5),['_rowIndex','date','opening_cash','payroll','closing_cash']);
for(let i=0;i<table.values.length;i++)assert.strictEqual(table.values[i].field,table.fields()[i],'Values and field identity must move together');
// Reordering non-sticky columns is native and keeps selection/value formatting intact.
let clickedCell={closest:selector=>selector==='.dt-cell'?clickedCell:table.selected};
table.wrapper.handlers.click.forEach(fn=>fn({target:clickedCell}));flush();
assert(table.selected.classList.contains('cashflow-selected-row'));
table.columnmanager.switchColumn(4,5);flush();
assert(table.selected.classList.contains('cashflow-selected-row'),'Column moves preserve row selection');
assert.strictEqual(table.values[4].field,table.fields()[4]);
// More than the original three sticky columns and resized widths remain supported.
table.datamanager.getColumns()[1].width=180;
table.wrapper.handlers.dblclick.forEach(fn=>fn());flush();
assert.strictEqual(table.wrapper['--cashflow-left-2'],'230px');
const before=table.fields().slice();pin.action.call(table,table.datamanager.getColumns()[1]);flush();assert.deepStrictEqual(table.fields(),before);
table.removeColumn(2);flush();assert(table.fields().includes('opening_cash'),'Opening Cash cannot be removed');
table.newHeader();flush();assert.strictEqual(table.sorterOptions.disabled,false);assert.strictEqual(typeof table.sorterOptions.onMove,'function');
table.bodyScrollable.scrollLeft=120;table.bodyScrollable.handlers.scroll.forEach(fn=>fn());flush();assert.strictEqual(table.cells[3].style.transform,'translateX(120px)');
// Refresh and quick-purchase preparation restore layout by field names, not old indexes.
report.prepare_report_data({columns:[],result:[{date:'2026-11-12',opening_cash:100,expected_receipts:20,payroll:10,closing_cash:110,sources:[]}]});
assert.deepStrictEqual(Array.from(report.columns.filter(c=>!c.hidden).slice(0,3),c=>c.fieldname),['date','opening_cash','payroll']);
report.prepare_report_data({columns:[],result:[{date:'2026-11-12',month:'2026-11',opening_cash:100,payroll:10,closing_cash:110,sources:[]}]});
assert.deepStrictEqual(Array.from(report.columns.filter(c=>!c.hidden).slice(0,3),c=>c.fieldname),['month','opening_cash','payroll']);
// Conditional purchase columns may disappear and return without losing field-based pins.
report.prepare_report_data({columns:[],result:[{date:'2026-11-12',opening_cash:100,payroll:10,proposed_purchase:5,baseline_closing_cash:110,closing_cash:105,sources:[{scenario:true}]}]});
let conditional=makeTable(['_rowIndex',...Array.from(report.columns.filter(c=>!c.hidden),c=>c.fieldname)]);
report.datatable=conditional;settings.after_datatable_render(conditional);flush();
pin.action.call(conditional,conditional.datamanager.getColumns().find(c=>c.fieldname==='baseline_closing_cash'));flush();
report.prepare_report_data({columns:[],result:[{date:'2026-11-12',opening_cash:100,payroll:10,proposed_purchase:0,baseline_closing_cash:110,closing_cash:110,sources:[]}]});
assert(report.columns.find(c=>c.fieldname==='baseline_closing_cash').hidden);
report.prepare_report_data({columns:[],result:[{date:'2026-11-12',opening_cash:100,payroll:10,proposed_purchase:5,baseline_closing_cash:110,closing_cash:105,sources:[{scenario:true}]}]});
assert.deepStrictEqual(Array.from(report.columns.filter(c=>!c.hidden).slice(0,4),c=>c.fieldname),['date','opening_cash','payroll','baseline_closing_cash']);
const old=table;report.load_report();flush();assert.strictEqual(old.bodyScrollable.handlers.scroll.size,0);
assert(!old.wrapper.classList.contains('cashflow-sticky-columns'));
assert.strictEqual(conditional.bodyScrollable.handlers.scroll.size,0);
assert(observers.every(o=>o.disconnected),'Every header/body observer must be released');
context.frappe.query_report={report_name:'Other Report'};
assert.strictEqual(old.sorterOptions.onMove,undefined,'Restore native drag settings on navigation');
console.log('Guarded column reorder, pin/unpin, field identity, header recreation, refresh and cleanup passed');
