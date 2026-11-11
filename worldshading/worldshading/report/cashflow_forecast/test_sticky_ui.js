/* DOM fixture for Purchase Plan-style offsets, scrolling, selection and cleanup. */
const assert=require('assert'),fs=require('fs'),vm=require('vm'),path=require('path');
function classes(){const set=new Set();return {add:(...v)=>v.forEach(x=>set.add(x)),remove:(...v)=>v.forEach(x=>set.delete(x)),contains:x=>set.has(x),toggle:(x,on)=>on?set.add(x):set.delete(x)};}
function events(obj){obj.handlers={};obj.addEventListener=(name,fn)=>{(obj.handlers[name]||(obj.handlers[name]=new Set())).add(fn);};obj.removeEventListener=(name,fn)=>obj.handlers[name].delete(fn);return obj;}
const headers=[50,110,145].map(width=>({style:{},getBoundingClientRect:()=>({width})}));
let row=()=>({classList:classes(),getAttribute:()=> '0',closest:()=>null});let currentRow=row();
const body=events({scrollLeft:0,scrollWidth:1200,clientWidth:600,querySelector:()=>null});
const wrapper=events({classList:classes(),style:{setProperty:(k,v)=>{wrapper[k]=v;}},
 querySelector:selector=>selector.includes('dt-row-header .dt-cell')?headers[Number(selector.slice(-1))]:null,
 querySelectorAll:selector=>selector.includes('data-row-index')?[currentRow]:[headers[Number(selector.match(/col-(\d+)/)[1])]]});
let frames=new Map(),frameId=0,observers=[],style;
const window=events({requestAnimationFrame:fn=>{frames.set(++frameId,fn);return frameId;},cancelAnimationFrame:id=>frames.delete(id)});
const document=events({getElementById:()=>style || null,createElement:()=>({}),head:{appendChild:node=>{style=node;}}});
const box={length:1,off:()=>box,on:()=>box,html:()=>box};
const context={window,document,MutationObserver:function(fn){this.fn=fn;this.observe=()=>{};this.disconnect=()=>{this.disconnected=true;};observers.push(this);},
 __:s=>s,format_currency:String,frappe:{query_reports:{},defaults:{get_user_default:()=>''},datetime:{get_today:()=> '2026-11-10',add_months:()=>''},utils:{escape_html:String}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'cashflow_forecast.js'),'utf8'),context);
const settings=context.frappe.query_reports['Cashflow Forecast'];
const dt={wrapper,bodyScrollable:body,options:{serialNoColumn:true},on:(name,fn)=>{dt[name]=fn;},columnmanager:{sortable:{option:()=>{}}}};
const report={report_name:'Cashflow Forecast',filters:[],refresh:()=>{},load_report:()=> 'loaded',page:{add_inner_button:()=>{},main:{off:()=>box,find:()=>box}},raw_data:{result:[{date:'2026-11-10',opening_cash:100,closing_cash:100}]},data:[]};
context.frappe.query_report=report;settings.onload(report);
function flush(){const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn());}
settings.after_datatable_render(dt);
assert.strictEqual(wrapper['--cashflow-left-1'],'50px');assert.strictEqual(wrapper['--cashflow-left-2'],'160px');
assert(style.textContent.includes('::after'),'Pinned divider must not depend on a scrolling cell border');assert(style.textContent.includes('pointer-events:none'));
assert(style.textContent.includes('position:sticky'));assert(style.textContent.includes('z-index:30'));
body.scrollLeft=120;[...body.handlers.scroll].forEach(fn=>fn());flush();assert.strictEqual(headers[2].style.transform,'translateX(120px)');
let cell={closest:selector=>selector==='.dt-cell'?cell:currentRow};
[...wrapper.handlers.click].forEach(fn=>fn({target:cell}));flush();assert(currentRow.classList.contains('cashflow-selected-row'));
currentRow=row();observers[0].fn();flush();assert(currentRow.classList.contains('cashflow-selected-row'),'Restore selected virtual row');
headers[1].getBoundingClientRect=()=>({width:180});
[...wrapper.handlers.mousedown].forEach(fn=>fn({target:{closest:()=>({})}}));[...document.handlers.mouseup].forEach(fn=>fn());flush();
assert.strictEqual(wrapper['--cashflow-left-2'],'230px','Resize changes sticky offsets');
dt.onSortColumn();flush();assert(!currentRow.classList.contains('cashflow-selected-row'));
settings.after_datatable_render(dt);assert(observers[0].disconnected);assert.strictEqual(body.handlers.scroll.size,1);assert.strictEqual(wrapper.handlers.click.size,1);
console.log('Pinned offsets, synchronized scrolling, resize, virtual selection and listener cleanup passed');

const next={wrapper,bodyScrollable:body,options:{serialNoColumn:true},on:()=>{}};
settings.after_datatable_render(next);
assert.strictEqual(dt._cashflow_pin_refresh,null,'Replacing table cleans the abandoned table');
assert.strictEqual(body.handlers.scroll.size,1);
assert.strictEqual(report.load_report(),'loaded');
assert.strictEqual(body.handlers.scroll.size,0);
assert.strictEqual(document.handlers.mouseup.size,0);
assert(!wrapper.classList.contains('cashflow-sticky-columns'));
console.log('Table replacement and report navigation release sticky listeners and observers');
