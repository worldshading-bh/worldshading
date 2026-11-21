"""Scoped JE fields for company bank loan repayment linkage."""
import frappe

FIELDS = [dict(fieldname='custom_bank_loan',label='Bank Loan',fieldtype='Link',options='Bank Loan',insert_after='user_remark')]
LEGACY_FIELDS = ('custom_bank_loan_section','custom_loan_before_tracking','custom_loan_bank_account',
                 'custom_loan_allocations','custom_loan_variance_reason','custom_loan_snapshot','custom_loan_request')


def migrate_payment_details():
    """Preserve existing links before removing the former JV fields; safe to run again."""
    if not frappe.db.exists('Custom Field','Journal Entry-custom_loan_allocations'):return
    from worldshading.api.bank_loan_payments import _store_payment
    for row in frappe.get_all('Journal Entry',filters={'custom_bank_loan':['is','set']},fields=['name']):
        doc=frappe.get_doc('Journal Entry',row.name)
        if frappe.db.exists('Bank Loan Payment',{'journal_entry':doc.name}):continue
        context=frappe._dict(request_id=doc.get('custom_loan_request') or frappe.generate_hash(length=32),
            payment_bank=doc.get('custom_loan_bank_account'),before_tracking=doc.get('custom_loan_before_tracking'),
            reason=doc.get('custom_loan_variance_reason'),snapshot=doc.get('custom_loan_snapshot'),
            allocations=[r.as_dict() for r in doc.get('custom_loan_allocations') or []])
        if not context.allocations or not context.snapshot or not context.payment_bank:
            frappe.throw('Review incomplete legacy loan payment before removing JV fields: '+doc.name)
        _store_payment(doc,context)


def setup_payment_fields():
    if not frappe.db.exists('DocType','Bank Loan Payment'):return
    migrate_payment_details()
    item=FIELDS[0];name='Journal Entry-custom_bank_loan'
    if frappe.db.exists('Custom Field',name):
        field=frappe.get_doc('Custom Field',name)
        if field.fieldtype!='Link' or field.options!='Bank Loan':
            frappe.throw('Review the existing Journal Entry Bank Loan field before setup.')
        field.insert_after='user_remark';field.allow_on_submit=1;field.save()
    else:
        frappe.get_doc(dict(item,doctype='Custom Field',dt='Journal Entry',allow_on_submit=1)).insert()
    for fieldname in LEGACY_FIELDS:
        name='Journal Entry-'+fieldname
        if frappe.db.exists('Custom Field',name):frappe.delete_doc('Custom Field',name)
    frappe.clear_cache(doctype='Journal Entry')
    frappe.db.add_index('Journal Entry',['custom_bank_loan'],'bank_loan_payment_index')
    frappe.db.add_index('Bank Loan Payment',['bank_loan'],'bank_loan_payment_loan_index')
    upgrade_revision_action()


def upgrade_revision_action():
    """Rename only the existing loan edit action; keep states, roles and other routes."""
    if not frappe.db.exists('Workflow','Bank Loan Approval'):
        return
    workflow=frappe.get_doc('Workflow','Bank Loan Approval')
    changed=False
    for row in workflow.transitions:
        if row.state=='Approved' and row.next_state=='Draft' and row.action=='Request Editing':
            if not frappe.db.exists('Workflow Action Master','Revise Future Schedule'):
                frappe.get_doc(dict(doctype='Workflow Action Master',workflow_action_name='Revise Future Schedule')).insert()
            row.action='Revise Future Schedule';changed=True
    if changed:workflow.save()
