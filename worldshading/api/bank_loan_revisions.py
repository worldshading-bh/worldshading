"""Append-only approved plan snapshots; native workflow authorizes approval."""
import json
import frappe
from frappe import _
from frappe.utils import now, nowdate
from worldshading.worldshading.doctype.bank_loan.rules import as_date, number
from worldshading.worldshading.doctype.bank_loan.payment_rules import money, validate_schedule_edit

IDENTITY = ('company','bank','agreement_number','currency','original_principal','opening_principal','tracking_start_date',
            'loan_account','interest_account')
FIELDS = ('company','bank','agreement_number','loan_position','currency','original_principal','opening_principal','disbursement_date',
          'tracking_start_date','maturity_date','repayment_frequency','interest_rate_type',
          'interest_calculation_basis','annual_interest_rate','rate_reference','loan_account',
          'interest_account','charges_account','payment_account','cost_center')


def commercial_snapshot(doc):
    result = {}
    precision = doc.precision('original_principal')
    for field in FIELDS:
        value = doc.get(field)
        if field=='agreement_number':
            value=' '.join((value or '').split()).upper() or None
        elif field.endswith('_date'):
            value = as_date(value).isoformat() if value else None
        elif field in ('original_principal','opening_principal'):
            value = str(money(value, precision))
        elif field == 'annual_interest_rate':
            value = str(number(value,'Annual rate').normalize())
        result[field] = value or None
    result['schedule'] = [dict(name=row.get('name'),due_date=as_date(row.get('due_date')).isoformat(),
        **{key:str(money(row.get(key),precision)) for key in ('principal_amount','interest_amount','charges_amount')})
        for row in doc.get('schedule') or []]
    return json.dumps(result,sort_keys=True)


def validate_revision(doc, old, payments):
    prior_revisions = [row.as_dict() if callable(getattr(row,'as_dict',None)) else dict(row) for row in (old.get('revisions') or [])] if old else []
    baseline = old.get('approved_plan') if old else None
    # Preserve server-owned audit fields; a client cannot alter the approval record.
    doc.set('revisions', prior_revisions)
    doc.approved_plan = baseline
    if old and old.get('workflow_state') == 'Approved' and not baseline:
        baseline = commercial_snapshot(old)
        doc.approved_plan = baseline
        doc.append('revisions',dict(revision_number=len(prior_revisions)+1,effective_date=nowdate(),
            reason='Existing approved state captured; see original workflow approval history',approved_by=None,approved_on=now(),snapshot=baseline))
    if payments and old:
        before = json.loads(commercial_snapshot(old))
        after = json.loads(commercial_snapshot(doc))
        if any(before.get(key) != after.get(key) for key in IDENTITY):
            frappe.throw(_('This loan has payment history. Its lender, agreement, company, currency, principal opening position and loan/interest ledgers cannot be changed.'))
        try:
            validate_schedule_edit(before['schedule'],after['schedule'],payments,doc.precision('original_principal'),
                require_reconciled=doc.get('workflow_state')=='Approved' and old.get('workflow_state')!='Approved')
        except ValueError as error:
            frappe.throw(_(str(error)))
    current = commercial_snapshot(doc)
    changed = baseline and json.loads(current) != json.loads(baseline)
    if changed:
        reason = (doc.get('revision_reason') or '').strip()
        if not reason:
            frappe.throw(_('Enter a Revision Reason for the revised loan plan.'))
        # The revision date is recorded when its reason is entered, not selected manually.
        continuing = old and old.get('workflow_state') != 'Approved' and old.get('revision_effective_date') and (old.get('revision_reason') or '').strip() == reason
        doc.revision_effective_date = old.revision_effective_date if continuing else nowdate()
    if doc.get('workflow_state') == 'Approved' and (not baseline or changed):
        doc.approved_plan = current
        doc.append('revisions',dict(revision_number=len(doc.get('revisions') or [])+1,
            effective_date=doc.get('revision_effective_date') or nowdate(),
            reason=(doc.get('revision_reason') or '').strip() or 'Initial approved plan',
            approved_by=frappe.session.user,approved_on=now(),snapshot=current))
    if old and old.get('workflow_state') == 'Approved' and doc.get('workflow_state') == 'Draft' and not changed:
        doc.revision_reason = None
        doc.revision_effective_date = None
