"""Read-only schedule estimates for the loan currently being edited."""
import json
import frappe
from frappe import _
from frappe.model.meta import get_field_precision
from frappe.utils import nowdate
from worldshading.api.bank_loan_workflow import MAKER
from worldshading.worldshading.doctype.bank_loan.generator import generate_schedule


@frappe.whitelist()
def preview_schedule(loan, options):
    try:
        loan = json.loads(loan) if isinstance(loan, str) else loan
        options = json.loads(options) if isinstance(options, str) else options
    except (ValueError, TypeError):
        frappe.throw(_('Invalid schedule inputs.'))
    if not isinstance(loan, dict) or not isinstance(options, dict):
        frappe.throw(_('Supply a loan and schedule settings.'))
    if frappe.session.user != 'Administrator' and MAKER not in frappe.get_roles():
        frappe.throw(_('Only the Accounts Maker can generate a Draft loan schedule.'), frappe.PermissionError)
    if loan.get('workflow_state') not in (None, '', 'Draft') or loan.get('docstatus', 0) != 0:
        frappe.throw(_('Return the Bank Loan to Draft before generating its schedule.'))
    if loan.get('name') and not loan.get('__islocal'):
        saved = frappe.get_doc('Bank Loan', loan['name'])
        saved.check_permission('write')
        if saved.workflow_state != 'Draft' or saved.docstatus != 0:
            frappe.throw(_('The saved Bank Loan is not Draft. Reload the form.'))
    elif not frappe.has_permission('Bank Loan', 'create'):
        frappe.throw(_('Not permitted to create Bank Loans.'), frappe.PermissionError)
    field = frappe.get_meta('Bank Loan').get_field('original_principal')
    precision = get_field_precision(field, frappe._dict(loan))
    try:
        result=generate_schedule(loan, options, precision, nowdate())
        if loan.get('name') and not loan.get('__islocal'):
            from worldshading.api.bank_loan_payments import payment_documents
            protected={a.get('installment') for p in payment_documents(loan['name']) if int(p['docstatus'])!=2
                       for a in p['allocations'] if a.get('installment')}
            removed={r.get('name') for r in (loan.get('schedule') or [])[result['retained_rows']:]}
            if protected.intersection(removed):
                raise ValueError('Linked installments cannot be replaced. Revise their unpaid amounts manually and retain the original rows.')
        return result
    except ValueError as error:
        frappe.throw(_(str(error)))
