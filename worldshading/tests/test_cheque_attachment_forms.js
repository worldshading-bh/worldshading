// Database-free v12 form checks; no financial documents/uploads are created.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const events = {}, calls = [];
let dialog, uploader, hasAttachment = false, failSave = false, silentSave = false, hold = false, delaySave = false, finishSave;
let leafReply = {payment_type: 'GL Payment', payment_name: 'GL-1', files: [
    {file_name: '<img src=x>', file_url: '/private/files/a.pdf'},
    {file_name: 'unsafe', file_url: 'javascript:alert(1)'},
    {file_name: 'quoted', file_url: '/files/a.pdf" onclick="alert(1)'}]};
const frappe = {
    session: {user: 'maker'}, validated: true,
    utils: {escape_html: x => String(x).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')},
    msgprint: () => {}, set_route: () => {},
    ui: {form: {on: (dt, handlers) => {events[dt] = handlers;}},
        Dialog: function(options) { Object.assign(this, options); dialog=this;
            this.fields_dict={uploader: {$wrapper:{}}}; this.show=()=>{}; this.hide=()=>{if(this.onhide)this.onhide();}; },
        FileUploader: function(options) {uploader=options;}},
    call: options => { calls.push(options); if(hold)return;
        options.callback({message: options.method.endsWith('get_leaf_attachments') ? leafReply : {has_attachment:hasAttachment}}); }
};
for (const file of ['cheque_payment','cheque_leaf']) vm.runInNewContext(fs.readFileSync(__dirname+'/../public/js/'+file+'.js','utf8'),{frappe,__:x=>x});
function payment() {
    return {doctype:'GL Payment',doc:{doctype:'GL Payment',name:'GL-1',payment_type:'Outgoing',mode_of_payment:'Cheque',docstatus:0,
        workflow_state:'Pending Reconciliation',cheque_leaf:'CL-1'},selected_workflow_action:'Reconciled',saves:0,
        is_dirty:()=>false,save(action,callback,btn,error) {this.saves++;
            if(delaySave)return new Promise(resolve=>{finishSave=()=>{callback({docs:[Object.assign({},this.doc)]});resolve();};});
            if(silentSave)return Promise.resolve();
            if(failSave){error();callback({exc:'failed'});} else callback({docs:[Object.assign({},this.doc)]});return Promise.resolve();}};
}
function leaf() {
    const sections=[];
    return {doc:{name:'CL-1',status:'Reserved',gl_payment:'GL-1'},perm:[{write:1}],is_new:()=>false,
        set_df_property:()=>{},add_custom_button:()=>{},sections,
        dashboard:{add_section(html){const section={html,htmlSet(v){this.html=v;},html(v){this.content=v;},remove(){this.removed=true;}};
            section.content=html;sections.push(section);return section;},show:()=>{}}};
}
async function run() {
    let frm=payment(); let pending=events['GL Payment'].before_workflow_action(frm); await Promise.resolve();
    assert.ok(pending && pending.then,'Cheque reconciliation must wait for attachment confirmation');
    assert.strictEqual(frappe.validated,false);
    assert.ok(uploader && uploader.docname==='GL-1');
    await dialog.primary_action(); assert.strictEqual(frm.saves,0,'Cannot continue without a qualifying server attachment');
    hasAttachment=true;
    await dialog.primary_action(); await pending;
    assert.strictEqual(frm.saves,1);assert.strictEqual(frappe.validated,true);
    const previousDialog=dialog; frm=payment(); await events['GL Payment'].before_workflow_action(frm);
    assert.strictEqual(dialog,previousDialog,'A qualifying existing attachment must not prompt another upload');
    hasAttachment=false; frm=payment(); pending=events['GL Payment'].before_workflow_action(frm); await Promise.resolve();
    const cancelled=pending.then(()=>{throw Error('Cancellation resolved');},()=>{});dialog.hide();await cancelled;assert.strictEqual(frm.saves,0);
    for(const mode of ['failure','silent']) {
        hasAttachment=false;frm=payment();pending=events['GL Payment'].before_workflow_action(frm); await Promise.resolve();
        const failed=pending.then(()=>{throw Error('Failed save continued');},()=>{});
        hasAttachment=true;failSave=mode==='failure';silentSave=mode==='silent';
        await dialog.primary_action();await failed;assert.strictEqual(frappe.validated,false);
    }
    failSave=false;silentSave=false;
    hasAttachment=false;frm=payment();pending=events['GL Payment'].before_workflow_action(frm);await Promise.resolve();
    hold=true;const inFlight=dialog.primary_action();const verification=calls[calls.length-1];
    const aborted=pending.then(()=>{throw Error('In-flight cancellation resolved');},()=>{});
    dialog.hide();await aborted;verification.callback({message:{has_attachment:true}});await inFlight;
    assert.strictEqual(frm.saves,0,'Closing while the server checks attachments must not save or resume');
    assert.strictEqual(frappe.validated,false);hold=false;
    hasAttachment=false;frm=payment();pending=events['GL Payment'].before_workflow_action(frm);await Promise.resolve();
    hasAttachment=true;delaySave=true;const saving=dialog.primary_action();await Promise.resolve();
    assert.strictEqual(typeof finishSave,'function');
    const stopped=pending.then(()=>{throw Error('Cancelled save resumed workflow');},()=>{});
    dialog.hide();await stopped;finishSave();await saving;assert.strictEqual(frappe.validated,false);delaySave=false;
    frm=payment();frm.doc.mode_of_payment='Cash';const before=calls.length;
    assert.strictEqual(events['GL Payment'].before_workflow_action(frm),undefined);assert.strictEqual(calls.length,before);
    frm=payment();frm.is_dirty=()=>true;
    await events['GL Payment'].before_workflow_action(frm).then(()=>{throw Error('Dirty payment accepted');},()=>{});
    const l=leaf();events['Cheque Leaf'].refresh(l);
    assert.ok(l.sections.length,'Linked payment attachments must appear on leaf');
    let html=l.sections[l.sections.length-1].content;
    assert.ok(html.includes('a.pdf') && html.includes('&lt;img'));assert.ok(!html.includes('javascript:'));assert.ok(!html.includes('" onclick="'),'Attribute quotes must be escaped even with native v12 text-only escape_html');
    leafReply={files:[],restricted:true};events['Cheque Leaf'].refresh(l);
    assert.ok(l.sections[l.sections.length-1].content.includes('permission'));
    leafReply={files:[]};events['Cheque Leaf'].refresh(l);
    assert.ok(l.sections[l.sections.length-1].content.includes('No payment attachments'));
    hold=true;events['Cheque Leaf'].refresh(l);const stale=calls[calls.length-1];
    events['Cheque Leaf'].refresh(l);const current=calls[calls.length-1];
    current.callback({message:{files:[]}});stale.callback({message:{files:[{file_name:'STALE',file_url:'/files/stale.pdf'}]}});
    assert.ok(!l.sections[l.sections.length-1].content.includes('STALE'),'Late responses must not replace current section');
    console.log('Cheque attachment form checks: PASS');
}
run().catch(e=>{console.error(e);process.exit(1);});
