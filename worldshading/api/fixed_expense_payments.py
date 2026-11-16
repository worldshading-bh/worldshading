# -*- coding: utf-8 -*-
"""Fixed Expense payments: one due occurrence, potentially several partial GLs."""
from __future__ import unicode_literals

import calendar
import copy
import json
import math
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

MONTHS = {'Monthly': 1, 'Quarterly': 3, 'Half-yearly': 6, 'Yearly': 12,
          'Every 2 Years': 24, 'Every 3 Years': 36, 'Every 4 Years': 48, 'Every 5 Years': 60}
GROUP_FIELDS = ('name', 'creation', 'modified', 'docstatus', 'company', 'posting_date', 'total_amount',
                'custom_fixed_expense', 'custom_expense_due_date', 'custom_expense_amount',
                'custom_expense_snapshot', 'custom_close_remaining_balance',
                'custom_next_balance_due_date')
MANAGED_FIELDS = ('custom_fixed_expense', 'custom_expense_due_date', 'custom_expense_snapshot')


def ensure_payment_index():
    """Targeted setup; also retained as a hook for future authorized deployments."""
    if frappe.db.has_column('GL Payment', 'custom_expense_due_date'):
        frappe.db.add_index('GL Payment', ['custom_fixed_expense', 'custom_expense_due_date'],
                            'fixed_expense_due_index')


def due_date(anchor, frequency, index):
    anchor = getdate(anchor)
    months = MONTHS[frequency] * index
    year, month = divmod(anchor.year * 12 + anchor.month - 1 + months, 12)
    month += 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def due_dates(anchor, frequency, start, through, end=None):
    anchor, start, through = getdate(anchor), getdate(start), getdate(through)
    if end:
        through = min(through, getdate(end))
    index = max(0, ((start.year - anchor.year) * 12 + start.month - anchor.month) // MONTHS[frequency])
    result = []
    while True:
        current = due_date(anchor, frequency, index)
        if current > through:
            break
        if current >= start:
            result.append(current)
        index += 1
    return result


def next_balance_date(anchor, posting_date, today):
    after = max(getdate(posting_date), getdate(today))
    anchor = getdate(anchor)
    index = max(0, (after.year - anchor.year) * 12 + after.month - anchor.month)
    while due_date(anchor, 'Monthly', index) <= after:
        index += 1
    return due_date(anchor, 'Monthly', index)


def balance_from_payments(amount, rows, precision, amount_type='Fixed'):
    paid = flt(sum(flt(r.get('total_amount')) for r in rows if cint(r.get('docstatus')) == 1), precision)
    closed = any(cint(r.get('docstatus')) == 1 and cint(r.get('custom_close_remaining_balance')) for r in rows)
    remaining = max(0, flt(amount - paid, precision))
    if amount_type == 'Variable' and any(cint(r.get('docstatus')) == 1 for r in rows):
        return {'scheduled': amount, 'paid': paid, 'remaining': 0, 'closed_remainder': 0,
                'excess': 0, 'closed': True,
                'active': [r.get('name') for r in rows if cint(r.get('docstatus')) == 0]}
    return {'scheduled': amount, 'paid': paid, 'remaining': 0 if closed else remaining,
            'closed_remainder': remaining if closed else 0,
            'excess': max(0, flt(paid - amount, precision)), 'closed': closed,
            'active': [r.get('name') for r in rows if cint(r.get('docstatus')) == 0]}


def allocate_rows(original_rows, amount, precision):
    """Allocate gross balance with exact currency rounding; keep original tax rates."""
    rows = copy.deepcopy(original_rows)
    original_total = sum(flt(r['net_amount']) + flt(r['tax_amount']) for r in rows)
    if original_total <= 0 or amount <= 0:
        raise ValueError('A positive payment amount is required.')
    units = int(round(amount * 10 ** precision))
    shares = [(flt(r['net_amount']) + flt(r['tax_amount'])) / original_total * units for r in rows]
    portions = [int(math.floor(share)) for share in shares]
    order = sorted(range(len(rows)), key=lambda i: (-(shares[i] - portions[i]), i))
    for index in order[:units - sum(portions)]:
        portions[index] += 1
    for index, row in enumerate(rows):
        gross = flt(portions[index] / float(10 ** precision), precision)
        row['net_amount'] = flt(gross / (1 + flt(row['rate']) / 100), precision)
        # Tax takes the rounding remainder, as it does on a gross-inclusive bank amount.
        row['tax_amount'] = flt(gross - row['net_amount'], precision)
        row['total_amount'] = gross
    return rows


def _lock_expense(name):
    # A parent lock serializes first creation too (there may be no GL row yet).
    rows = frappe.db.sql('select * from `tabFixed Expense` where name=%s for update', (name,), as_dict=True)
    if not rows:
        frappe.throw(_('Fixed Expense does not exist.'))
    return rows[0]


def _current_expense(name):
    values = _lock_expense(name)
    values['doctype'] = 'Fixed Expense'
    values['accounts'] = frappe.db.sql(
        'select * from `tabRecurring Expense Account` where parent=%s '
        'and parenttype=%s and parentfield=%s order by idx for update',
        (name, 'Fixed Expense', 'accounts'), as_dict=True)
    for row in values['accounts']:
        row['doctype'] = 'Recurring Expense Account'
    return frappe.get_doc(values)


def _payments(name, scheduled_date):
    # Locking reads see committed state after waiting, even under REPEATABLE READ.
    return frappe.db.sql('select {0} from `tabGL Payment` where custom_fixed_expense=%s '
                         'and custom_expense_due_date=%s order by creation, name for update'.format(
                             ', '.join('`{0}`'.format(f) for f in GROUP_FIELDS)),
                         (name, scheduled_date), as_dict=True)


def _snapshot(rows):
    if not rows:
        return None
    value = rows[0].get('custom_expense_snapshot')
    if not value:
        frappe.throw(_('This expense payment needs its original amount reviewed before another payment can be created.'))
    return json.loads(value)


def _new_snapshot(source):
    from worldshading.worldshading.doctype.fixed_expense.fixed_expense import _build_gl_payment
    payment = frappe.get_doc(_build_gl_payment(source.name, source=source))
    return {'company': source.company, 'amount': payment.total_amount, 'amount_type': source.amount_type,
            'precision': payment.precision('total_amount'),
            'currency': source.currency,
            'source_amount': source.expected_total_amount,
            'remarks': payment.remarks,
            'items': [{key: row.get(key) for key in ('account', 'template_type', 'tax_template',
                       'rate', 'account_head', 'net_amount', 'tax_amount', 'remarks')}
                      for row in payment.items]}


def _check_date(source, scheduled_date, existing=False):
    if not scheduled_date:
        frappe.throw(_('Select the Expense Due Date.'))
    if existing:
        return
    if source.status != 'Active':
        frappe.throw(_('Only Active expenses can create a new scheduled payment.'))
    dt = getdate(scheduled_date)
    if dt not in due_dates(source.first_due_date, source.billing_frequency,
                           source.start_date, dt, source.end_date):
        frappe.throw(_('Expense Due Date must match the expense schedule and Tracking Start Date.'))


def _state(source_name, scheduled_date, exclude=None):
    source = _current_expense(source_name)
    rows = _payments(source_name, scheduled_date)
    _check_date(source, scheduled_date, bool(rows))
    snapshot = _snapshot(rows) if rows else _new_snapshot(source)
    snapshot.setdefault('amount_type', source.amount_type)
    if snapshot['company'] != source.company:
        frappe.throw(_('The expense company differs from its saved payment history.'))
    others = [r for r in rows if r.name != exclude]
    state = balance_from_payments(snapshot['amount'], others, snapshot['precision'], snapshot['amount_type'])
    return source, rows, snapshot, state


def _available(state):
    if state['active']:
        frappe.throw(_('A payment is already in progress: {0}').format(', '.join(state['active'])))
    if state['remaining'] <= 0 or state['closed']:
        frappe.throw(_('This scheduled expense is already paid or closed.'))


@frappe.whitelist()
def payment_context(source_name, scheduled_due_date):
    source = frappe.get_doc('Fixed Expense', source_name)
    source.check_permission('read')
    _lock_expense(source_name)
    source, rows, snapshot, state = _state(source_name, scheduled_due_date)
    _available(state)
    return {'expense_amount': state['remaining'], 'amount_type': snapshot['amount_type']}


@frappe.whitelist()
def get_payment_dates(source_name):
    source = frappe.get_doc('Fixed Expense', source_name)
    source.check_permission('read')
    dates = due_dates(source.first_due_date, source.billing_frequency, source.start_date,
                      due_date(nowdate(), source.billing_frequency, 1), source.end_date) if source.status == 'Active' else []
    # Include prior carried balances, even if the master has since been closed.
    for row in frappe.get_all('GL Payment', filters={'custom_fixed_expense': source_name,
                             'custom_expense_due_date': ['is', 'set']}, fields=['custom_expense_due_date']):
        dates.append(getdate(row.custom_expense_due_date))
    result = []
    for dt in sorted(set(dates)):
        rows = _payments(source_name, dt)
        if rows:
            snap = _snapshot(rows)
            state = balance_from_payments(snap['amount'], rows, snap['precision'], snap.get('amount_type', source.amount_type))
            if state['active'] or state['remaining'] <= 0:
                continue
        result.append(str(dt))
    return result


def make_payment(source_name, scheduled_due_date):
    source = frappe.get_doc('Fixed Expense', source_name)
    source.check_permission('read')
    if not frappe.has_permission('GL Payment', 'create'):
        frappe.throw(_('Not permitted to create GL Payments.'), frappe.PermissionError)
    _lock_expense(source_name)
    source, rows, snapshot, state = _state(source_name, scheduled_due_date)
    _available(state)
    source.validate_payment_defaults()
    payment = frappe.new_doc('GL Payment')
    _set_initial_workflow(payment)
    payment.update({'company': source.company, 'posting_date': nowdate(), 'payment_type': 'Outgoing',
                    'cost_center': source.cost_center or frappe.db.get_value('Company', source.company, 'cost_center'),
                    'mode_of_payment': source.mode_of_payment, 'payment_account': source.payment_account,
                    'party_type': 'Supplier', 'party': source.supplier, 'party_name': None, 'tax_id': None,
                    'reference_no': None, 'reference_date': None,
                    'custom_fixed_expense': source.name, 'custom_expense_due_date': getdate(scheduled_due_date),
                    'custom_expense_amount': state['remaining'],
                    'custom_expense_snapshot': json.dumps(snapshot),
                    'custom_close_remaining_balance': 0, 'custom_adjustment_reason': None,
                    'remarks': snapshot['remarks'] + '\n' + _('Expense due: {0}').format(scheduled_due_date)})
    if source.supplier:
        supplier = frappe.get_doc('Supplier', source.supplier)
        payment.party_name, payment.tax_id = supplier.supplier_name, supplier.tax_id
    payment.set('items', [])
    for row in allocate_rows(snapshot['items'], state['remaining'], snapshot['precision']):
        payment.append('items', row)
    for field in ('net_amount', 'tax_amount', 'total_amount'):
        payment.set(field, flt(sum(flt(r.get(field)) for r in payment.items), payment.precision(field)))
    payment.check_permission('create')
    return payment


def _previous(doc):
    return frappe.db.get_value('GL Payment', doc.name, list(MANAGED_FIELDS) +
                              ['custom_expense_amount', 'custom_next_balance_due_date'], as_dict=True) if not doc.is_new() else None


def _validate_items(doc, source):
    from worldshading.worldshading.doctype.fixed_expense.fixed_expense import get_tax_details
    currency = frappe.db.get_value('Company', source.company, 'default_currency')
    payment_account = frappe.db.get_value('Account', doc.payment_account,
        ['company', 'account_type', 'disabled', 'is_group', 'account_currency'], as_dict=True)
    if (not payment_account or payment_account.company != source.company
            or payment_account.account_type not in ('Bank', 'Cash') or payment_account.disabled
            or payment_account.is_group or payment_account.account_currency != currency):
        frappe.throw(_('Select an enabled Bank or Cash payment account in company currency.'))
    center = frappe.db.get_value('Cost Center', doc.cost_center, ['company', 'is_group'], as_dict=True)
    if not center or center.company != source.company or center.is_group:
        frappe.throw(_('Select a non-group Cost Center belonging to this Company.'))
    if not doc.items:
        frappe.throw(_('Add at least one Account.'))
    for row in doc.items:
        account = frappe.db.get_value('Account', row.account,
                    ['company', 'root_type', 'disabled', 'is_group', 'account_currency'], as_dict=True)
        if (not account or account.company != source.company or account.root_type != 'Expense'
                or account.disabled or account.is_group or account.account_currency != currency):
            frappe.throw(_('Select enabled company-currency expense accounts.'))
        if row.template_type != 'Purchase Taxes and Charges Template' or not row.tax_template:
            frappe.throw(_('Select a Purchase Tax Template on each Account row.'))
        tax = get_tax_details(source.company, currency, row.tax_template)
        row.rate, row.account_head = tax['rate'], tax['account_head']
        for field in ('net_amount', 'tax_amount'):
            if not math.isfinite(flt(row.get(field))) or flt(row.get(field)) < 0:
                frappe.throw(_('Payment amounts must be finite and non-negative.'))
            row.set(field, flt(row.get(field), doc.precision(field, 'items')))
        expected_tax = flt(row.net_amount * row.rate / 100, doc.precision('tax_amount', 'items'))
        # Permit one currency unit of rounding for a gross balance allocation.
        if abs(flt(row.tax_amount - expected_tax, doc.precision('tax_amount', 'items'))) > 10 ** -doc.precision('tax_amount', 'items'):
            frappe.throw(_('Tax Amount does not match the selected template.'))
        row.total_amount = flt(row.net_amount + row.tax_amount, doc.precision('total_amount', 'items'))
    for field in ('net_amount', 'tax_amount', 'total_amount'):
        doc.set(field, flt(sum(flt(r.get(field)) for r in doc.items), doc.precision(field)))


def validate_payment(doc, method=None):
    doc.flags.valid_fixed_expense_payment = False
    old = _previous(doc)
    if old and old.custom_expense_due_date:
        if any(str(old.get(f) or '') != str(doc.get(f) or '') for f in MANAGED_FIELDS[:2]):
            frappe.throw(_('The Fixed Expense and Expense Due Date cannot be changed after saving.'))
    if not doc.get('custom_fixed_expense'):
        if doc.get('custom_expense_due_date') or doc.get('custom_expense_snapshot'):
            frappe.throw(_('Select the Fixed Expense for this payment.'))
        return
    # Historical submitted GLs without a due date are not silently reclassified.
    if old and not old.custom_expense_due_date and cint(doc.docstatus) == 2:
        return
    _lock_expense(doc.custom_fixed_expense)
    source, rows, snapshot, state = _state(doc.custom_fixed_expense, doc.get('custom_expense_due_date'), doc.name)
    saved = next((r for r in rows if r.name == doc.name), None)
    if saved and doc.get('_original_modified') and str(saved.modified) != str(doc._original_modified):
        frappe.throw(_('This GL Payment changed. Reload it before saving.'), frappe.TimestampMismatchError)
    source.check_permission('read')
    _available(state)
    if doc.company != source.company or doc.payment_type != 'Outgoing':
        frappe.throw(_('Fixed Expense payments must be Outgoing and use the expense company.'))
    doc.custom_expense_snapshot = json.dumps(snapshot)
    doc.custom_expense_amount = state['remaining']
    doc.custom_next_balance_due_date = old.custom_next_balance_due_date if old else None
    _validate_items(doc, source)
    if doc.total_amount <= 0:
        frappe.throw(_('Enter a payment amount greater than zero.'))
    difference = flt(doc.total_amount - state['remaining'], snapshot['precision'])
    variable = snapshot.get('amount_type') == 'Variable'
    if variable:
        doc.custom_close_remaining_balance = 0
        doc.custom_next_balance_due_date = None
    if not variable and difference and not (doc.get('custom_adjustment_reason') or '').strip():
        frappe.throw(_('Enter an Adjustment Reason when the payment differs from the Expense Amount.'))
    if cint(doc.get('custom_close_remaining_balance')) and difference >= 0:
        frappe.throw(_('Close Remaining Balance is only needed when paying less than the Expense Amount.'))
    if not variable and cint(doc.docstatus) == 1 and difference < 0 and not cint(doc.get('custom_close_remaining_balance')):
        doc.custom_next_balance_due_date = next_balance_date(doc.custom_expense_due_date, doc.posting_date, nowdate())
    elif cint(doc.docstatus) == 1:
        doc.custom_next_balance_due_date = None
    _set_initial_workflow(doc)
    doc.flags.valid_fixed_expense_payment = True


def _set_initial_workflow(doc):
    if doc.is_new() and not doc.get('workflow_state'):
        from frappe.model.workflow import get_workflow_name, get_workflow
        if get_workflow_name('GL Payment'):
            workflow = get_workflow('GL Payment')
            if workflow.workflow_state_field != 'workflow_state' or not workflow.states:
                frappe.throw(_('Review the GL Payment workflow before creating expense payments.'))
            doc.workflow_state = workflow.states[0].state


def is_fixed_expense_draft(doc):
    return bool(doc.get('custom_fixed_expense') and doc.get('custom_expense_due_date')
                and doc.flags.get('valid_fixed_expense_payment') and cint(doc.docstatus) == 0
                and doc.get('workflow_state') == 'Draft')


def before_cancel(doc, method=None):
    if not doc.get('custom_fixed_expense') or not doc.get('custom_expense_due_date'):
        return
    _lock_expense(doc.custom_fixed_expense)
    rows = _payments(doc.custom_fixed_expense, doc.custom_expense_due_date)
    seen = False
    for row in rows:
        if row.name == doc.name:
            seen = True
        elif seen and cint(row.docstatus) != 2:
            frappe.throw(_('Cancel later payments for this expense due date first: {0}').format(row.name))


def protect_history(doc, method=None):
    old = _previous(doc)
    if (old and old.custom_expense_due_date) or doc.get('custom_expense_due_date'):
        if method == 'on_trash':
            frappe.throw(_('Fixed Expense payment history cannot be deleted.'))
        before = frappe.get_doc('GL Payment', doc.name)
        protected = MANAGED_FIELDS + ('company', 'posting_date', 'payment_type', 'payment_account',
            'cost_center', 'party_type', 'party', 'net_amount', 'tax_amount', 'total_amount',
            'custom_expense_amount', 'custom_close_remaining_balance', 'custom_adjustment_reason',
            'custom_next_balance_due_date')
        if any(str(before.get(f) or '') != str(doc.get(f) or '') for f in protected):
            frappe.throw(_('Fixed Expense payment amounts and identity cannot be edited after submission.'))
        fields = ('account', 'template_type', 'tax_template', 'net_amount', 'tax_amount',
                  'total_amount', 'rate', 'account_head')
        if [[r.get(f) for f in fields] for r in before.items] != [[r.get(f) for f in fields] for r in doc.items]:
            frappe.throw(_('Fixed Expense payment account rows cannot be edited after submission.'))


def validate_master(doc, method=None):
    if doc.is_new():
        return
    old = _lock_expense(doc.name)
    if doc.get('_original_modified') and str(old.modified) != str(doc._original_modified):
        frappe.throw(_('This Fixed Expense changed. Reload it before saving.'), frappe.TimestampMismatchError)
    if any(str(doc.get(f) or '') != str(old.get(f) or '') for f in ('company', 'currency', 'first_due_date', 'billing_frequency')):
        if frappe.db.sql('select name from `tabGL Payment` where custom_fixed_expense=%s '
                         'and custom_expense_due_date is not null limit 1 for update', (doc.name,)):
            frappe.throw(_('This expense has payment history. Create a new Fixed Expense to change its company, currency or renewal schedule.'))


def _due_candidates(today):
    through = getdate(today) + timedelta(days=2)
    candidates = set()
    for source in frappe.get_all('Fixed Expense', filters={'status': 'Active'},
                                fields=['name', 'first_due_date', 'start_date', 'end_date', 'billing_frequency']):
        for dt in due_dates(source.first_due_date, source.billing_frequency, source.start_date, through, source.end_date):
            candidates.add((source.name, str(dt)))
    for row in frappe.get_all('GL Payment', filters={'docstatus': 1,
                         'custom_next_balance_due_date': ['<=', through], 'custom_fixed_expense': ['is', 'set']},
                         fields=['custom_fixed_expense', 'custom_expense_due_date']):
        if row.custom_expense_due_date:
            candidates.add((row.custom_fixed_expense, str(row.custom_expense_due_date)))
    return sorted(candidates)


def _auto_eligible(rows, snapshot, through):
    if not rows:
        return True
    state = balance_from_payments(snapshot['amount'], rows, snapshot['precision'], snapshot.get('amount_type', 'Fixed'))
    if state['active'] or state['remaining'] <= 0:
        return False
    # An explicitly cancelled last attempt requires accounts to create its replacement.
    if cint(rows[-1].docstatus) == 2:
        return False
    completed = [r for r in rows if cint(r.docstatus) == 1]
    return bool(completed and completed[-1].custom_next_balance_due_date
                and getdate(completed[-1].custom_next_balance_due_date) <= through)


def create_due_payments():
    """Daily job. Register only after the existing test masters have been retired."""
    through = getdate(nowdate()) + timedelta(days=2)
    for source_name, scheduled_date in _due_candidates(nowdate()):
        try:
            _lock_expense(source_name)
            source, rows, snapshot, state = _state(source_name, scheduled_date)
            if _auto_eligible(rows, snapshot, through):
                payment = make_payment(source_name, scheduled_date)
                payment.insert()
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(frappe.get_traceback(), 'Fixed Expense payment: {0} / {1}'.format(source_name, scheduled_date))


def preview_due_payments(today=None):
    """Read-only report for activation review; never inserts a payment."""
    result = []
    through = getdate(today or nowdate()) + timedelta(days=2)
    for source_name, scheduled_date in _due_candidates(today or nowdate()):
        try:
            _lock_expense(source_name)
            source, rows, snapshot, state = _state(source_name, scheduled_date)
            if _auto_eligible(rows, snapshot, through):
                payment = make_payment(source_name, scheduled_date)
                result.append({'expense': source_name, 'due_date': scheduled_date,
                               'amount': payment.total_amount,
                               'ready': bool(payment.payment_account and payment.cost_center)})
        except Exception as exc:
            result.append({'expense': source_name, 'due_date': scheduled_date, 'error': str(exc)})
    return result
