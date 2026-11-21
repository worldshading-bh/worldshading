"""Company loan repayment linkage. Native JVs remain the accounting authority."""
import json
import re
import frappe
from frappe import _
from frappe.utils import nowdate
from worldshading.api.bank_loan_workflow import MAKER
from worldshading.api.bank_loan_revisions import commercial_snapshot
from worldshading.worldshading.doctype.bank_loan.rules import as_date
from worldshading.worldshading.doctype.bank_loan.payment_rules import (
    COMPONENTS, money, allocation_totals, expected_postings, validate_postings, payment_status)

ALLOCATION_FIELDS = ('installment','principal_amount','interest_amount','charges_amount','booked_interest','booked_charges')
PAYMENT_FIELDS = ('before_tracking','payment_bank','reason','snapshot','request_id')
LINK_FIELDS = ('custom_bank_loan',) + PAYMENT_FIELDS


def require_maker():
    if frappe.session.user != 'Administrator' and MAKER not in frappe.get_roles():
        frappe.throw(_('Only the Accounts Maker can prepare or link loan payments.'),frappe.PermissionError)


def lock_loan(name):
    # Serialize first payment creation, submissions and plan approval on one existing parent.
    rows=frappe.db.sql('select * from `tabBank Loan` where name=%s for update',(name,),as_dict=True)
    if not rows:frappe.throw(_('Bank Loan does not exist.'))
    return rows[0]


def payment_documents(name, exclude=None, for_update=False):
    # One indexed join; status/date always come from the native JV.
    rows=frappe.db.sql("""select j.name,j.docstatus,j.posting_date,j.workflow_state,
        p.before_tracking,p.request_id,p.allocations
        from `tabJournal Entry` j inner join `tabBank Loan Payment` p on p.journal_entry=j.name
        where j.custom_bank_loan=%s and p.bank_loan=%s order by j.posting_date,j.creation"""+
        (' for update' if for_update else ''),(name,name),as_dict=True)
    return [dict(row, before_tracking=bool(row.before_tracking), allocations=json.loads(row.allocations))
            for row in rows if row.name!=exclude]


def _payment_record(journal, for_update=False):
    rows=frappe.db.sql('select * from `tabBank Loan Payment` where journal_entry=%s'+
                      (' for update' if for_update else ''),(journal,),as_dict=True)
    return rows[0] if rows else None


def _context(doc, payment):
    """Validate native accounting and loan-side instructions together, without extra JV fields."""
    values=frappe._dict(doc.as_dict())
    values.accounts=[frappe._dict(row) for row in values.get('accounts') or []]
    values._original_modified=doc.get('_original_modified')
    for key in PAYMENT_FIELDS:
        values[key]=payment.get('account_snapshot') if key=='snapshot' else payment.get(key)
    allocations=payment.get('allocations') or []
    if isinstance(allocations,str):allocations=json.loads(allocations)
    values.allocations=[frappe._dict(row) for row in allocations]
    return values


def _store_payment(doc, context):
    payment=frappe.get_doc(dict(doctype='Bank Loan Payment',bank_loan=doc.custom_bank_loan,
        journal_entry=doc.name,request_id=context.request_id,payment_bank=context.payment_bank,
        before_tracking=int(bool(context.before_tracking)),reason=context.reason,
        account_snapshot=context.snapshot,allocations=json.dumps(context.allocations,default=str,sort_keys=True)))
    payment.flags.from_bank_loan_service=True
    # A new native JV has its final name during validate, but is inserted just afterwards.
    payment.flags.ignore_links=True
    payment.insert(ignore_permissions=True)


def validate_journal(doc,method=None):
    old=doc.get_doc_before_save()
    if old and old.get('custom_bank_loan') and old.custom_bank_loan!=doc.get('custom_bank_loan'):
        frappe.throw(_('The Bank Loan link cannot be removed or changed after saving.'))
    if not doc.get('custom_bank_loan'):return
    source=_source(doc.custom_bank_loan)  # Keep parent -> payment -> JV locking order.
    payment=_payment_record(doc.name,for_update=True)
    stored=bool(payment)
    if not payment:payment=doc.flags.get('bank_loan_payment')
    if not payment and doc.get('amended_from'):
        original=frappe.db.get_value('Journal Entry',doc.amended_from,['docstatus','custom_bank_loan'],as_dict=True)
        previous=_payment_record(doc.amended_from)
        if original and int(original.docstatus)==2 and original.custom_bank_loan==doc.custom_bank_loan and previous:
            payment=dict(previous,request_id=frappe.generate_hash(length=32))
    if not payment:
        frappe.throw(_('Prepare or link this payment from the Bank Loan so its installment breakdown is recorded.'))
    if payment.get('bank_loan') and payment['bank_loan']!=doc.custom_bank_loan:
        frappe.throw(_('The payment breakdown belongs to another Bank Loan.'))
    context=_context(doc,payment)
    previous=_context(old,payment) if old else None
    context.get_doc_before_save=lambda:previous
    _validate_payment(context,source=source)
    if not stored:_store_payment(doc,context)


def approved_terms(source):
    return json.loads(source.approved_plan) if source.get('approved_plan') else json.loads(commercial_snapshot(source))


def require_active(source):
    if source.workflow_state!='Approved' or source.status!='Active':
        frappe.throw(_('Approve and activate the Bank Loan before creating or linking payments.'))


def _source(name):
    source=frappe.get_doc('Bank Loan',name);source.check_permission('read')
    values=dict(lock_loan(name),doctype='Bank Loan')
    for field in source.meta.get_table_fields():
        # Table names come only from trusted DocType metadata, never client input.
        values[field.fieldname]=frappe.db.sql('select * from `tab'+field.options+'` where parent=%s '+
            'and parenttype=%s and parentfield=%s order by idx for update',
            (name,'Bank Loan',field.fieldname),as_dict=True)
        for row in values[field.fieldname]:row['doctype']=field.options
    return frappe.get_doc(values)


def _mapping(source,terms,bank):
    mapping={key:terms.get(key) for key in ['company','currency','loan_account','interest_account','charges_account','cost_center']}
    mapping['payment_account']=bank or terms.get('payment_account')
    if mapping['currency']!=frappe.db.get_value('Company',mapping['company'],'default_currency'):
        frappe.throw(_('Loan payment linking currently requires company-currency loans and ledgers.'))
    for field,root in [('loan_account','Liability'),('interest_account','Expense'),('charges_account','Expense'),('payment_account','Asset')]:
        account=mapping.get(field)
        if not account and field=='charges_account':continue
        info=frappe.db.get_value('Account',account,['company','account_currency','root_type','account_type','disabled','is_group'],as_dict=True) if account else None
        if (not info or info.company!=mapping['company'] or info.account_currency!=mapping['currency'] or
            info.root_type!=root or info.disabled or info.is_group or (field=='payment_account' and info.account_type!='Bank')):
            frappe.throw(_('Select enabled loan-company/currency accounts and a valid paying bank account.'))
    return mapping


def _allocation_values(doc):
    return [{key:row.get(key) for key in ALLOCATION_FIELDS} for row in doc.get('allocations') or []]


def _allocation_labels(doc):
    return [(as_date(row.get('installment_date')).isoformat() if row.get('installment_date') else None,
             row.get('currency') or None) for row in doc.get('allocations') or []]


def _assert_no_duplicate(allocations,others,request):
    keys={r.get('installment') for r in allocations if r.get('installment')}
    for other in others:
        if request and request==other.get('request_id'):
            frappe.throw(_('This payment reference already exists: {0}').format(other['name']))
        if int(other.get('docstatus') or 0)==0 and not other.get('before_tracking'):
            if keys.intersection(r.get('installment') for r in other['allocations']):
                frappe.throw(_('A payment is already in progress for this installment: {0}').format(other['name']))


def _validate_payment(doc,source=None):
    old=doc.get_doc_before_save()
    if old and old.get('custom_bank_loan'):
        if old.custom_bank_loan!=doc.get('custom_bank_loan'):
            frappe.throw(_('The Bank Loan link cannot be removed or changed after saving.'))
        if int(old.docstatus)==1:
            if any(str(old.get(k) or '')!=str(doc.get(k) or '') for k in LINK_FIELDS) or _allocation_values(old)!=_allocation_values(doc) or _allocation_labels(old)!=_allocation_labels(doc):
                frappe.throw(_('Submitted loan payment links and allocations are immutable. Cancel/amend the JV through its workflow.'))
            return
    if not doc.get('custom_bank_loan'):
        if doc.get('allocations'):
            frappe.throw(_('Select the Bank Loan for these allocations.'))
        return
    first_link=not old or not old.get('custom_bank_loan')
    if first_link:require_maker()
    source=source or _source(doc.custom_bank_loan)
    if first_link:require_active(source)
    if old and doc.get('_original_modified'):
        current=frappe.db.sql('select modified from `tabJournal Entry` where name=%s for update',(doc.name,),as_dict=True)
        if current and str(current[0].modified)!=str(doc.get('_original_modified')):
            frappe.throw(_('This JV changed. Reload it before saving.'),frappe.TimestampMismatchError)
    terms=approved_terms(source)
    precision=source.precision('original_principal')
    mapping=_mapping(source,terms,doc.get('payment_bank'))
    if old and old.get('snapshot'):
        mapping=json.loads(old.snapshot)
        # Paying bank may be corrected on a Draft, after normal company/currency checks.
        mapping['payment_account']=_mapping(source,terms,doc.get('payment_bank'))['payment_account']
    existing_posted=first_link and old and int(old.docstatus)==1
    if doc.company!=mapping['company'] or (not existing_posted and doc.transaction_type not in ('Other Expenses','Bank Transfer')):
        frappe.throw(_('Loan payment JVs must use the loan company and Other Expenses or Bank Transfer workflow.'))
    allocations=_allocation_values(doc)
    try:totals=allocation_totals(allocations,precision)
    except ValueError as error:frappe.throw(_(str(error)))
    before=bool(doc.get('before_tracking'))
    posting=as_date(doc.posting_date)
    start=as_date(terms['tracking_start_date'])
    if int(doc.docstatus)==1 and posting>as_date(nowdate()):
        frappe.throw(_('Keep future-dated loan payments in Draft until their payment date, or enter the actual bank payment date.'))
    if before:
        historical_link=first_link and old and int(old.docstatus)==1
        historical_continuation=old and old.get('custom_bank_loan')==source.name and old.get('before_tracking') and int(old.docstatus)==0
        historical_amendment=False
        if doc.get('amended_from'):
            original=frappe.db.get_value('Journal Entry',doc.amended_from,
                ['docstatus','custom_bank_loan'],as_dict=True)
            previous=_payment_record(doc.amended_from)
            historical_amendment=bool(original and int(original.docstatus)==2 and original.custom_bank_loan==source.name and previous and previous.get('before_tracking'))
        if not (historical_link or historical_continuation or historical_amendment) or posting>=start:
            frappe.throw(_('Before Tracking is for an earlier submitted JV or its native cancelled-payment amendment.'))
        if len(allocations)!=1 or allocations[0].get('installment'):
            frappe.throw(_('Historical before-tracking payments use one breakdown without an installment.'))
    elif posting<start:
        frappe.throw(_('For earlier submitted JVs, select Before Tracking Start.'))
    others=payment_documents(source.name,doc.name,for_update=True)
    _assert_no_duplicate(allocations,others,doc.get('request_id'))
    state=payment_status(terms['schedule'],others,terms['opening_principal'],precision)
    balances={r['name']:r for r in state['installments']}
    due={r['name']:r['due_date'] for r in terms['schedule']}
    variance=False
    for row,values in zip(doc.allocations,allocations):
        if not before:
            if values['installment'] not in balances:frappe.throw(_('Select an installment from the approved loan schedule.'))
            row.installment_date=due[values['installment']]
            remaining=balances[values['installment']]['balances']
            variance=variance or any(money(values.get(k),precision)!=remaining[k] for k in COMPONENTS)
        if before:row.installment_date=None
        row.currency=mapping['currency']
        for field in COMPONENTS+('booked_interest','booked_charges'):row[field]=float(money(values.get(field),precision))
    if not before and totals['principal_amount']>state['outstanding_principal']:
        frappe.throw(_('Principal paid cannot exceed the remaining tracked principal. Review the allocation or approved opening position.'))
    if (variance or before or (first_link and old and int(old.docstatus)==1)) and not (doc.get('reason') or '').strip():
        frappe.throw(_('Enter a reason for the payment difference or existing-JV link.'))
    try:validate_postings(mapping,totals,[dict(r) for r in doc.accounts],precision)
    except ValueError as error:frappe.throw(_(str(error)))
    doc.payment_bank=mapping['payment_account']
    doc.snapshot=json.dumps(mapping,sort_keys=True)
    if old and old.get('request_id'):
        if doc.request_id!=old.request_id:frappe.throw(_('The payment reference cannot be changed.'))
    else:
        value=doc.get('request_id') or frappe.generate_hash(length=32)
        if not re.match(r'^[A-Za-z0-9-]{16,64}$',value):frappe.throw(_('Invalid payment reference.'))
        doc.request_id=value


def protect_history(doc,method=None):
    validate_journal(doc,method)


def before_cancel(doc,method=None):
    validate_journal(doc,method)
    if doc.get('custom_bank_loan'):
        _source(doc.custom_bank_loan)


def protect_journal_delete(doc,method=None):
    if not doc.get('custom_bank_loan'):return
    _source(doc.custom_bank_loan)
    if int(doc.docstatus)!=0:
        frappe.throw(_('Keep posted/cancelled loan JVs for payment audit history; use cancellation and amendment instead of deletion.'))
    payment=_payment_record(doc.name,for_update=True)
    if payment:
        frappe.delete_doc('Bank Loan Payment',payment.name,ignore_permissions=True,
            flags={'from_bank_loan_service':True})


@frappe.whitelist()
def get_status(loan):
    source=frappe.get_doc('Bank Loan',loan);source.check_permission('read')
    rows=payment_documents(loan)
    terms=approved_terms(source)
    status=payment_status(terms['schedule'],rows,terms['opening_principal'],source.precision('original_principal'))
    status['currency']=source.currency
    status['precision']=source.precision('original_principal')
    status['plan_approved']=bool(source.get('approved_plan')) or source.workflow_state=='Approved'
    status['revision_count']=len(source.get('revisions') or [])
    history=[]
    for row in rows:
        total=allocation_totals(row['allocations'],source.precision('original_principal'))
        visible=frappe.has_permission('Journal Entry','read',doc=row['name'])
        history.append(dict(name=row['name'] if visible else None,posting_date=row['posting_date'],
            docstatus=row['docstatus'],workflow_state=row.get('workflow_state'),before_tracking=row['before_tracking'],
            installments=sorted({a.get('installment') for a in row['allocations'] if a.get('installment')}),
            principal=total['principal_amount'],interest=total['interest_amount'],charges=total['charges_amount'],cash=total['cash']))
    status['history']=history
    status['schedule']=[dict(name=r['name'],due_date=r['due_date']) for r in terms['schedule']]
    status['protected_installments']=sorted({a.get('installment') for r in rows if int(r['docstatus'])!=2 for a in r['allocations'] if a.get('installment')})
    return status


@frappe.whitelist(methods=['POST'])
def make_payment(loan,allocations,posting_date=None,bank_account=None,reason=None,request_id=None):
    require_maker()
    if not frappe.has_permission('Journal Entry','create'):frappe.throw(_('Not permitted to create Journal Entries.'),frappe.PermissionError)
    source=_source(loan);require_active(source)
    if request_id:
        matches=frappe.db.sql('select bank_loan,journal_entry from `tabBank Loan Payment` where request_id=%s for update',
                              (request_id,),as_dict=True)
        existing=matches[0] if matches else None
        if existing:
            if existing.bank_loan!=loan:frappe.throw(_('This payment reference belongs to another loan.'))
            journal=frappe.get_doc('Journal Entry',existing.journal_entry);journal.check_permission('read')
            return journal.as_dict()
    terms=approved_terms(source)
    allocations=json.loads(allocations) if isinstance(allocations,str) else allocations
    if not isinstance(allocations,list):frappe.throw(_('Supply the payment breakdown.'))
    mapping=_mapping(source,terms,bank_account)
    try:totals=allocation_totals(allocations,source.precision('original_principal'))
    except ValueError as error:frappe.throw(_(str(error)))
    journal=frappe.new_doc('Journal Entry')
    journal.update(dict(company=source.company,voucher_type='Journal Entry',transaction_type='Other Expenses',
        posting_date=posting_date or nowdate(),custom_bank_loan=source.name,
        user_remark='Bank Loan {0}: repayment'.format(source.name)))
    from frappe.model.workflow import get_workflow_name,get_workflow
    if get_workflow_name('Journal Entry'):
        workflow=get_workflow('Journal Entry');journal.set(workflow.workflow_state_field,workflow.states[0].state)
    journal.flags.bank_loan_payment=dict(allocations=allocations,payment_bank=mapping['payment_account'],
        reason=reason,request_id=request_id or frappe.generate_hash(length=32))
    journal.set('accounts',[])
    try:postings=expected_postings(mapping,totals)
    except ValueError as error:frappe.throw(_(str(error)))
    for account,amount in postings.items():
        journal.append('accounts',dict(account=account,account_currency=source.currency,exchange_rate=1,
            debit=float(max(amount,0)),credit=float(max(-amount,0)),
            debit_in_account_currency=float(max(amount,0)),credit_in_account_currency=float(max(-amount,0)),cost_center=mapping['cost_center']))
    journal.total_debit=float(sum(max(value,0) for value in postings.values()))
    journal.total_credit=journal.total_debit
    journal.difference=0
    journal.insert()  # Native create permissions, validation and workflow; never submit.
    return journal.as_dict()


@frappe.whitelist(methods=['POST'])
def link_existing(loan,journal,allocations,before_tracking=0,bank_account=None,reason=None):
    require_maker()
    source=_source(loan);require_active(source)
    doc=frappe.get_doc('Journal Entry',journal);doc.check_permission('read');doc.check_permission('write')
    if doc.get('custom_bank_loan'):
        frappe.throw(_('This JV already has a loan link. Review it directly.'))
    if int(doc.docstatus)!=1:frappe.throw(_('Link an existing submitted JV. Use Create Payment for a new Draft.'))
    rows=json.loads(allocations) if isinstance(allocations,str) else allocations
    if not isinstance(rows,list):frappe.throw(_('Supply the payment breakdown.'))
    doc.custom_bank_loan=loan
    doc.flags.bank_loan_payment=dict(allocations=rows,before_tracking=int(before_tracking or 0),
        payment_bank=bank_account or source.payment_account,reason=reason)
    doc.save()  # Native submitted-document rules and all existing hooks still apply.
    return doc.name
