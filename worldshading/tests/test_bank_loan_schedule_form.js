const assert=require('assert'), fs=require('fs'), vm=require('vm');
const events={}, dialogs=[], buttons=[], requests=[];
let current, confirm=true, deferred=false, messages=[];
// Exercise installed v12 Select option caching, including defaults set while hidden.
const nativeSelect={set_options:function(){
    const options=this.df.options.split('\n');
    if(JSON.stringify(options)===this.last_options)return;
    this.last_options=JSON.stringify(options);
    if(this.$input)this.$input.empty().add_options(options);
}};
function selectField(f){
    const field={df:f,options:[]};
    function makeInput(){field.$input={find:()=>({val:()=>null}),empty:()=>({add_options:options=>{field.options=options;}})};}
    field.toggle=show=>{f.hidden=show?0:1;if(show&&!field.$input){makeInput();nativeSelect.set_options.call(field);}};
    if(!f.hidden)makeInput();
    nativeSelect.set_options.call(field); // FieldGroup applies defaults even to hidden fields.
    return field;
}
class Dialog {
    constructor(config) {this.config=config;this.values={};this.fields_dict={};
        (config.fields||[]).forEach(f=>{if(f.default!==undefined)this.values[f.fieldname]=f.default;
            this.fields_dict[f.fieldname]=f.fieldtype==='Select'?selectField(f):{df:f,toggle:show=>{f.hidden=show?0:1;}};
            this.fields_dict[f.fieldname].$wrapper={html: text=>{this.html=text;}};});dialogs.push(this);}
    show(){this.visible=true;}
    hide(){
        if(this.hiding)throw Error('Recursive dialog hide');
        this.hiding=true;this.visible=false;
        // Characterize installed v12: hide triggers secondary_action, then onhide.
        if(this.config.secondary_action)this.config.secondary_action();
        if(this.config.onhide)this.config.onhide();
        this.hiding=false;
    }
    get_values(){return this.values;} get_value(name){return this.values[name];}
    set_value(name,value){this.values[name]=value;return Promise.resolve();}
}
const frappe={session:{user:'maker@example.com'},user_roles:['Maker - ACC (Workflow)'],
    ui:{form:{on(name,handlers){events[name]=handlers;}},Dialog},
    datetime:{get_today:()=> '2026-11-19',add_months:()=> '2026-12-19'},
    utils:{escape_html: s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')},
    msgprint:m=>messages.push(m),confirm:(m,yes,no)=>confirm?yes():no(),
    call: config=>{requests.push(config);if(!deferred)config.callback({message:response});},
    model:{clear_doc:(dt,name)=>{current.doc.schedule=current.doc.schedule.filter(r=>r.name!==name);}}};
const context={frappe,__:s=>s,console};
vm.runInNewContext(fs.readFileSync('worldshading/worldshading/doctype/bank_loan/bank_loan.js','utf8'),context);
const first={name:'old1',doctype:'Bank Loan Installment',due_date:'2026-12-19',principal_amount:100,interest_amount:1,charges_amount:0};
const second={name:'old2',doctype:'Bank Loan Installment',due_date:'2027-01-19',principal_amount:100,interest_amount:1,charges_amount:0};
let response={rows:[{due_date:'2026-12-19',principal_amount:100,interest_amount:2,charges_amount:0,total_amount:102,projected_principal_balance:100},
    {due_date:'2027-01-19',principal_amount:100,interest_amount:1,charges_amount:0,total_amount:101,projected_principal_balance:0}],
    retained_rows:0,precision:3,scheduled_principal:200,scheduled_interest:3,scheduled_charges:0,scheduled_total:203,unscheduled_principal:0};
function form(){current={doc:{name:'BLN-1',workflow_state:'Draft',docstatus:0,currency:'BHD',interest_calculation_basis:'Diminishing',
    interest_rate_type:'Fixed',annual_interest_rate:6,repayment_frequency:'Monthly',disbursement_date:'2026-11-19',schedule:[Object.assign({},first),Object.assign({},second)]},
    meta:{fields:[]},set_df_property(){},set_query(){},add_custom_button(label,fn){buttons.push({label,fn});},
    add_child(field,row){this.doc[field].push(Object.assign({name:'new'+this.doc[field].length},row));},
    refresh_field(){},dirty(){this.changed=true;},set_value(values){Object.assign(this.doc,values);return Promise.resolve();},
    save(){throw Error('Generation must not save');}};return current;}
function open(frm){context.show_bank_loan_schedule_dialog(frm);const settings=dialogs[dialogs.length-1];
    settings.config.primary_action(settings.values);return {settings,preview:dialogs[dialogs.length-1]};}
(async()=>{
    let frm=form();events['Bank Loan'].refresh(frm);assert(buttons.some(b=>b.label==='Generate Schedule'));
    buttons.length=0;frm.doc.workflow_state='Approved';events['Bank Loan'].refresh(frm);assert.equal(buttons.length,0);
    frm=form();const original=JSON.stringify(frm.doc.schedule);let pair=open(frm);
    assert.equal(JSON.stringify(frm.doc.schedule),original);assert(pair.preview.html.includes('203.000'));
    assert.equal(pair.settings.values.method,'Equal Installments');
    assert.equal(pair.settings.fields_dict.method.df.options.split('\n')[0],'Equal Installments');
    assert(!pair.settings.fields_dict.variable_rate_ack);
    assert(!pair.settings.fields_dict.estimate_notice);
    assert(!pair.settings.fields_dict.rate_change);
    assert(!pair.settings.fields_dict.effective_date);
    assert(!pair.settings.fields_dict.new_rate);
    confirm=false;await pair.preview.config.primary_action();assert.equal(JSON.stringify(frm.doc.schedule),original);assert(!frm.changed);
    confirm=true;await pair.preview.config.primary_action();assert.equal(frm.doc.schedule[0].interest_amount,2);assert(frm.changed);assert.equal(frm.doc.scheduled_total,203);
    assert.equal(pair.preview.visible,false);assert.equal(pair.settings.visible,false);
    frm=form();pair=open(frm);frm.doc.annual_interest_rate=9;await pair.preview.config.primary_action();
    assert.equal(frm.doc.schedule[0].interest_amount,1);assert(!frm.changed);assert(messages.length);
    frm=form();response=Object.assign({},response,{retained_rows:1});pair=open(frm);const retained=frm.doc.schedule[0];
    await pair.preview.config.primary_action();assert.strictEqual(frm.doc.schedule[0],retained);assert.equal(frm.doc.schedule[1].interest_amount,1);
    frm=form();pair=open(frm);pair.preview.hide();
    assert.equal(pair.preview.visible,false);assert.equal(pair.settings.visible,true);
    frm=form();frm.doc.interest_rate_type='Variable';context.show_bank_loan_schedule_dialog(frm);
    const variable=dialogs[dialogs.length-1];
    assert(!variable.fields_dict.variable_rate_ack);
    assert.equal(variable.fields_dict.new_rate.df.hidden,1);
    variable.values.rate_change=1;variable.fields_dict.rate_change.df.onchange();
    assert.equal(variable.fields_dict.new_rate.df.hidden,0);
    assert.equal(variable.fields_dict.effective_date.df.reqd,1);
    assert.equal(variable.fields_dict.first_due_date.df.hidden,1);
    assert.equal(variable.fields_dict.first_due_date.df.reqd,0);
    variable.values.rate_change=0;variable.fields_dict.rate_change.df.onchange();
    assert.equal(variable.fields_dict.new_rate.df.hidden,1);
    assert.equal(variable.fields_dict.new_rate.df.reqd,0);
    assert.equal(variable.fields_dict.first_due_date.df.hidden,0);
    frm=form();context.show_bank_loan_schedule_dialog(frm);const amountSettings=dialogs[dialogs.length-1];
    assert.equal(amountSettings.values.calculation_mode,'Interest Rate');
    assert.equal(amountSettings.fields_dict.installment_amount.df.hidden,1);
    amountSettings.values.calculation_mode='Installment Amount';amountSettings.values.method='Equal Principal';
    amountSettings.fields_dict.calculation_mode.df.onchange();
    assert.equal(amountSettings.values.method,'Equal Installments');
    assert.equal(amountSettings.fields_dict.method.df.hidden,1);
    assert.equal(amountSettings.fields_dict.installment_amount.df.hidden,0);
    assert.equal(amountSettings.fields_dict.installment_amount.df.reqd,1);
    assert.deepEqual(amountSettings.fields_dict.rate_source.options,['Use Recorded Rate','Estimate Rate']);
    amountSettings.values.installment_amount=102;
    response=Object.assign({},response,{calculation_mode:'Installment Amount',estimated_annual_rate:8.25,
        installment_amount:102,final_payment_adjustment:0.001,final_interest_adjustment:-0.001,retained_rows:0});
    amountSettings.config.primary_action(amountSettings.values);
    const amountPreview=dialogs[dialogs.length-1];
    assert(amountPreview.html.includes('8.250000'));assert(amountPreview.html.includes('Recorded loan rate unchanged'));
    assert(amountPreview.html.includes('Final payment adjustment'));assert(amountPreview.html.includes('Final interest rounding'));
    assert.equal(frm.doc.annual_interest_rate,6);await amountPreview.config.primary_action();assert.equal(frm.doc.annual_interest_rate,6);
    amountSettings.values.calculation_mode='Interest Rate';amountSettings.fields_dict.calculation_mode.df.onchange();
    assert.equal(amountSettings.fields_dict.method.df.hidden,0);assert.equal(amountSettings.fields_dict.installment_amount.df.reqd,0);
    assert(!variable.fields_dict.calculation_mode);assert(!variable.fields_dict.installment_amount);
    frm=form();frm.doc.annual_interest_rate=0;context.show_bank_loan_schedule_dialog(frm);
    const recordedSettings=dialogs[dialogs.length-1];
    assert.equal(recordedSettings.values.rate_source,'Use Recorded Rate');
    recordedSettings.values.calculation_mode='Installment Amount';recordedSettings.fields_dict.calculation_mode.df.onchange();
    assert.equal(recordedSettings.fields_dict.rate_source.df.hidden,0);
    assert.equal(recordedSettings.fields_dict.remaining_balance.df.hidden,0);
    assert.deepEqual(recordedSettings.fields_dict.remaining_balance.options,['Add Final Settlement','Add to Last Installment']);
    assert.equal(recordedSettings.values.remaining_balance,'Add Final Settlement');
    response=Object.assign({},response,{rate_source:'Use Recorded Rate',recorded_annual_rate:0,
        final_payment_amount:80,final_payment_adjustment:0,settlement_added:true,
        maturity_date:'2027-02-19',previous_maturity_date:'2027-01-19'});
    response.rows[response.rows.length-1].settlement_row=true;
    recordedSettings.config.primary_action(recordedSettings.values);
    const recordedPreview=dialogs[dialogs.length-1];
    assert(recordedPreview.html.includes('Recorded Annual Rate'));assert(!recordedPreview.html.includes('Estimated Annual Rate'));
    assert(!recordedPreview.html.includes('NaN'));assert(recordedPreview.html.includes('Final Settlement'));
    assert(recordedPreview.html.includes('Maturity extended'));assert(!frm.doc.maturity_date);
    await recordedPreview.config.primary_action();assert.equal(frm.doc.maturity_date,'2027-02-19');
    assert.equal(frm.doc.annual_interest_rate,0);
    recordedSettings.values.rate_source='Estimate Rate';recordedSettings.fields_dict.rate_source.df.onchange();
    assert.equal(recordedSettings.fields_dict.remaining_balance.df.hidden,1);
    assert(!variable.fields_dict.rate_source);
    frm=form();deferred=true;context.show_bank_loan_schedule_dialog(frm);let settings=dialogs[dialogs.length-1];
    settings.config.primary_action(settings.values);const request=requests[requests.length-1];settings.values.periods=36;
    const count=dialogs.length;request.callback({message:response});assert.equal(dialogs.length,count);assert(!frm.changed);
    console.log('Bank Loan generation preview/apply checks: PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
