const fs=require('fs'),vm=require('vm'),assert=require('assert');
process.on('unhandledRejection',()=>{});
const full=fs.readFileSync((process.argv[2] || require('path').join(__dirname, '../deploy/custom_scripts/sales_invoice_whatsapp_verification.js')),'utf8');
const code=full.slice(full.indexOf('// WhatsApp verirification'),(full.indexOf('// WS_RETURN_REASON_DIALOG_V1') === -1 ? full.length : full.indexOf('// WS_RETURN_REASON_DIALOG_V1')));
const legacy=p=>({then:(ok,bad)=>legacy(p.then(ok,bad)),done:ok=>{p.then(ok);return legacy(p)},fail:bad=>{p.catch(bad);return legacy(p)}});
const tick=()=>new Promise(r=>setImmediate(r));
async function test(mode){
 let handler,dialog,state='pending',calls=0,saves=0,late=null,hidden=false,alerts=[],timers=[],contact={phone_nos:[],dynamic_whatsapp:0,is_whatsapp_locked:0};
 if(mode==='dynamic')contact.dynamic_whatsapp=1;
 if(['locked','locked_cancel','locked_failure'].includes(mode)) {contact.is_whatsapp_locked=1;contact.phone_nos=[{is_whatsapp:1,country_code:'+973 Bahrain',phone:'30000000'}];}
 if(mode==='unchanged')contact.phone_nos=[{is_whatsapp:1,country_code:'+973 Bahrain',phone:'30000000'}];
 let frm={selected_workflow_action:'Complete',doc:{doctype:'Sales Invoice',name:'TEST',docstatus:0,contact_person:mode==='no_contact'?null:'MOCK',contact_mobile:'',whatsapp_no:mode==='unchanged'?'97330000000':''},refresh_field:()=>{},is_dirty:()=>false,set_value:(k,v)=>{frm.doc[k]=v;return Promise.resolve()},save:(action,cb,btn,err)=>{saves++; if(['save_timeout','late_success'].includes(mode)){late=()=>cb({docs:[Object.assign({},frm.doc)]});return new Promise(()=>{});}return Promise.resolve().then(()=>{if(['save_failure','locked_failure'].includes(mode)){err();return;}cb({docs:[Object.assign({},frm.doc)]});})}};
 const btn={prop:()=>btn};
 const frappe={validated:true,ui:{form:{on:(dt,h)=>handler=h.before_workflow_action},Dialog:function(opts){dialog=this;Object.assign(this,opts);this.show=()=>{};this.hide=()=>{hidden=true;if(this.onhide)this.onhide()};this.get_primary_btn=()=>btn;}},db:{get_doc:()=>mode==='load_failure'?Promise.reject(Error('load')):Promise.resolve(contact),set_value:()=>{saves++;return mode==='save_failure'?Promise.reject(Error('save')):Promise.resolve({})}},call:()=>{calls++;return legacy(mode==='contact_failure'?Promise.reject(Error('contact')):Promise.resolve({message:{status:'success',whatsapp_no:'97330000000'}}))},msgprint:m=>alerts.push(m),show_alert:()=>{},confirm:(msg,yes,no)=>mode==='locked_cancel'?no():yes()};
 vm.runInNewContext(code,{frappe,Promise,Error,console,setTimeout:(f)=>{timers.push(f);return timers.length},clearTimeout:()=>{},__:s=>s});
 let outer=handler(frm);outer.then(()=>state='resolved',()=>state='rejected');await tick();
 if(dialog){if(mode==='cancel')dialog.hide();else {dialog.primary_action({country_code:'+973 Bahrain',whatsapp_no:'30000000'});if(mode==='double')dialog.primary_action({country_code:'+973 Bahrain',whatsapp_no:'30000000'});}}
 await tick();await tick();
 if(['save_timeout','late_success'].includes(mode)){timers.forEach(f=>f());await tick();}
 if(mode==='late_success'){late();await tick();await tick();}
 const failure=['contact_failure','save_failure','load_failure','cancel','save_timeout','late_success','locked_cancel','locked_failure'].includes(mode);
 assert.strictEqual(state,failure?'rejected':'resolved',mode+' workflow state');
 if(failure)assert.strictEqual(frappe.validated,false,mode+' validated');
 if(mode==='double')assert.strictEqual(calls,1,'duplicate contact call');
 if(['dynamic','no_contact','unchanged'].includes(mode))assert.strictEqual(calls,0,mode+' contact untouched');
 console.log('PASS',mode);
}
(async()=>{let failed=0;for(const m of ['contact_failure','save_failure','load_failure','cancel','save_timeout','success','double','dynamic','no_contact','unchanged','locked','locked_cancel','locked_failure','late_success']){try{await test(m)}catch(e){failed++;console.log('FAIL',e.message)}}process.exitCode=failed?1:0})()
