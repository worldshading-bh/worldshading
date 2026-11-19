frappe.ui.form.on('Bank Loan', {
    load_payment_tracking: function (frm) {
        if (!frm.is_new()) bank_loan_load_payments(frm);
    },
    refresh: function (frm) {
        if (frm.is_new() || !frm.fields_dict.payment_history) return;
        frm._loan_tracking_request=(frm._loan_tracking_request||0)+1;
        frm._loan_tracking_loading=false;
        frm.fields_dict.payment_history.$wrapper.html('<p class="text-muted">'+frappe.utils.escape_html(__('Tracking not loaded.'))+'</p>');
        const maker = frappe.session.user === 'Administrator' || (frappe.user_roles || []).includes('Maker - ACC (Workflow)');
        if (maker && frm.doc.workflow_state === 'Approved' && frm.doc.status === 'Active') {
            frm.add_custom_button(__('Create / Link Payment JV'), function () {
                if (frm.is_dirty()) { frappe.msgprint(__('Save the loan before preparing payments.')); return; }
                frappe.call({method:'worldshading.api.bank_loan_payments.get_status',args:{loan:frm.doc.name},
                    callback:function(r){if(r.message)bank_loan_payment_dialog(frm,r.message);}});
            });
        }
    }
});

function bank_loan_load_payments(frm) {
    if(frm._loan_tracking_loading)return;
    const name=frm.doc.name;
    const request=(frm._loan_tracking_request||0)+1;
    frm._loan_tracking_request=request;
    frm._loan_tracking_loading=true;
    frm.fields_dict.payment_history.$wrapper.html('<p class="text-muted">'+frappe.utils.escape_html(__('Loading…'))+'</p>');
    frappe.call({method:'worldshading.api.bank_loan_payments.get_status',args:{loan:name},callback:function(r){
        if(frm.doc.name!==name || frm._loan_tracking_request!==request)return;
        frm._loan_tracking_loading=false;
        if(r.message)frm.fields_dict.payment_history.$wrapper.html(bank_loan_payment_html(r.message));
    },error:function(){
        if(frm.doc.name!==name || frm._loan_tracking_request!==request)return;
        frm._loan_tracking_loading=false;
        frm.fields_dict.payment_history.$wrapper.html('<p class="text-muted">'+frappe.utils.escape_html(__('Unable to load tracking. Try again.'))+'</p>');
    }});
}

function bank_loan_payment_html(status) {
    const esc=frappe.utils.escape_html;
    const amount=function(value){return Number(value||0).toFixed(status.precision===undefined?3:status.precision);};
    let html='<p><strong>'+esc(__('Since Tracking Start'))+'</strong></p><div class="row">';
    [['principal_paid','Principal Paid'],['interest_paid','Interest Paid'],['charges_paid','Charges Paid'],
        ['total_paid','Total Cash Paid'],['outstanding_principal','Outstanding Principal']].forEach(function(item){
        html+='<div class="col-sm-2"><div class="text-muted">'+esc(__(item[1]))+'</div><strong>'+amount(status[item[0]])+'</strong></div>';
    });
    html+='</div>';
    if(!status.plan_approved)html+='<p class="text-muted">'+esc(__('Draft schedule — approve the loan before creating or linking payments.'))+'</p>';
    if(status.needs_reschedule)html+='<p class="text-warning">'+esc(__('Payment amounts differ from the plan. Review the unpaid schedule.'))+'</p>';
    const journals={};
    const unallocated=[];
    (status.history||[]).forEach(function(row){
        if(row.before_tracking || !(row.installments||[]).length){unallocated.push(row);return;}
        row.installments.forEach(function(name){(journals[name]||(journals[name]=[])).push(row);});
    });
    const journal=function(row){
        const link=row.name?'<a href="#Form/Journal%20Entry/'+encodeURIComponent(row.name)+'">'+esc(row.name)+'</a>':esc(__('Restricted JV'));
        const state=row.docstatus===2?'Cancelled':row.docstatus===1?'Posted':'Pending';
        return link+' — '+esc(String(row.posting_date||''))+' — '+esc(__(state));
    };
    html+='<p class="text-muted">'+esc(__('All linked cash paid: '))+amount(status.all_linked_cash_paid)+' '+esc(status.currency||'')+'</p>';
    html+='<div class="table-responsive"><table class="table table-bordered"><thead><tr>';
    ['Due Date','Principal Paid','Interest Paid','Charges Paid','Total Paid','Remaining Commitment','Linked JVs'].forEach(function(t){html+='<th>'+esc(__(t))+'</th>';});
    html+='</tr></thead><tbody>';
    (status.installments||[]).forEach(function(row){
        const paid=row.paid;
        const total=Number(paid.principal_amount||0)+Number(paid.interest_amount||0)+Number(paid.charges_amount||0);
        html+='<tr><td>'+esc(String(row.due_date||''))+'</td><td>'+amount(paid.principal_amount)+'</td><td>'+amount(paid.interest_amount)+'</td><td>'+amount(paid.charges_amount)+'</td><td>'+amount(total)+'</td><td>'+amount(row.remaining)+'</td><td>'+(journals[row.name]||[]).map(journal).join('<br>')+'</td></tr>';
    });
    unallocated.forEach(function(row){
        const posted=row.docstatus===1;
        html+='<tr><td>'+esc(__(row.before_tracking?'Before Tracking':'Unallocated'))+'</td><td>'+amount(posted?row.principal:0)+'</td><td>'+amount(posted?row.interest:0)+'</td><td>'+amount(posted?row.charges:0)+'</td><td>'+amount(posted?row.cash:0)+'</td><td>—</td><td>'+journal(row)+'</td></tr>';
    });
    return html+'</tbody></table></div>';
}

// Dialog grids need local identities for native selection and deletion.
function bank_loan_payment_grid_setup(grid) {
    const refresh=grid.refresh;
    let sequence=0;
    const identify=function(){
        (grid.df.data||[]).forEach(function(row,index){
            if(!row.name)row.name='loan-payment-row-'+(++sequence);
            row.idx=index+1;
        });
    };
    identify();
    grid.refresh=function(){
        identify();
        return refresh.apply(this,arguments);
    };
}

function bank_loan_installment_formatter(options) {
    const labels={};options.forEach(function(row){labels[row.value]=row.label;});
    return function(value){return frappe.utils.escape_html(labels[value]||value||'');};
}

function bank_loan_payment_dialog(frm,status) {
    const options=(status.schedule||[]).map(function(row,i){return {value:row.name,label:(i+1)+' — '+frappe.datetime.str_to_user(row.due_date)};});
    const balances={};(status.installments||[]).forEach(function(row){balances[row.name]=row.balances;});
    const first=(status.installments||[]).find(function(row){return Number(row.remaining)>0;});
    const initial=first?Object.assign({installment:first.name,booked_interest:0,booked_charges:0},first.balances):{};
    const reference=frappe.utils.get_random(32);
    let dialog;
    const update=function(){
        if(!dialog)return;
        const link=dialog.get_value('mode')==='Link Existing JV';
        const fields={existing_journal:link,before_tracking:link,posting_date:!link};
        Object.keys(fields).forEach(function(name){const field=dialog.fields_dict[name];field.df.reqd=name!=='before_tracking'&&fields[name]?1:0;field.toggle(fields[name]);});
    };
    dialog=new frappe.ui.Dialog({title:__('Loan Payment'),fields:[
        {fieldname:'mode',label:__('Action'),fieldtype:'Select',options:'New Payment\nLink Existing JV',default:'New Payment',reqd:1,onchange:update},
        {fieldname:'existing_journal',label:__('Submitted Journal Entry'),fieldtype:'Link',options:'Journal Entry',hidden:1,
            get_query:function(){return {filters:{company:frm.doc.company,docstatus:1}};}},
        {fieldname:'before_tracking',label:__('Payment Before Tracking Start'),fieldtype:'Check',default:0,hidden:1},
        {fieldname:'posting_date',label:__('Payment Date'),fieldtype:'Date',default:frappe.datetime.get_today(),reqd:1},
        {fieldname:'bank_account',label:__('Paying Bank Account'),fieldtype:'Link',options:'Account',default:frm.doc.payment_account,reqd:1,
            get_query:function(){return {filters:{company:frm.doc.company,account_currency:frm.doc.currency,account_type:'Bank',is_group:0,disabled:0}};}},
        {fieldname:'allocations',label:__('Payment Breakdown'),fieldtype:'Table',data:first?[initial]:[],
            on_setup:bank_loan_payment_grid_setup,
            fields:[{fieldname:'installment',label:__('Installment'),fieldtype:'Select',options:options,formatter:bank_loan_installment_formatter(options),in_list_view:1,columns:3},
                {fieldname:'principal_amount',label:__('Principal'),fieldtype:'Currency',in_list_view:1,columns:3},
                {fieldname:'interest_amount',label:__('Interest'),fieldtype:'Currency',in_list_view:1,columns:2},
                {fieldname:'charges_amount',label:__('Charges'),fieldtype:'Currency',in_list_view:1,columns:2},
                {fieldname:'booked_interest',label:__('Interest Already Booked in Loan Liability'),fieldtype:'Currency',default:0},
                {fieldname:'booked_charges',label:__('Charges Already Booked in Loan Liability'),fieldtype:'Currency',default:0}]},
        {fieldname:'reason',label:__('Payment Difference / Linking Reason'),fieldtype:'Small Text'},
        {fieldtype:'HTML',options:'<p class="text-muted">'+frappe.utils.escape_html(__('Continue saves a Draft JV for approval.'))+'</p>'}
    ],primary_action_label:__('Continue'),primary_action:function(values){
        if(!values)return;
        if(frm.is_dirty()){frappe.msgprint(__('The loan changed. Save it and reopen payment preparation.'));return;}
        const linking=values.mode==='Link Existing JV';
        const allocations=(values.allocations||[]).map(function(row){
            const result={};['installment','principal_amount','interest_amount','charges_amount','booked_interest','booked_charges'].forEach(function(k){result[k]=row[k];});
            if(linking&&values.before_tracking)result.installment=null;
            return result;
        });
        const args={loan:frm.doc.name,allocations:JSON.stringify(allocations),bank_account:values.bank_account,reason:values.reason};
        if(linking){args.journal=values.existing_journal;args.before_tracking=values.before_tracking||0;}
        else{args.posting_date=values.posting_date;args.request_id=reference;}
        const perform=function(){frappe.call({method:'worldshading.api.bank_loan_payments.'+(linking?'link_existing':'make_payment'),args:args,freeze:true,callback:function(r){
            if(!r.message)return;dialog.hide();
            if(linking){bank_loan_load_payments(frm);frappe.set_route('Form','Journal Entry',r.message);}
            else{frappe.set_route('Form','Journal Entry',r.message.name);}
        }});};
        if(linking)frappe.confirm(__('Link this submitted JV using the entered breakdown? Its accounting entries will remain unchanged.'),perform);
        else perform();
    }});
    dialog.show();update();
}
