# -*- coding: utf-8 -*-
"""Own-company outgoing PE/GL cheque reservations and signing attestations."""
from __future__ import unicode_literals

import json
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now, strip_html
from frappe.model.workflow import get_transitions, has_approval_access
from worldshading.api import cheque_register as register


CONFIRMATION = 'custom_cheque_signing_confirmation'
SOURCE_FIELDS = {'Payment Entry': 'payment_entry', 'GL Payment': 'gl_payment'}
PREPARATION = ('Draft', 'Scheduled', 'Pending Payment - Maker', 'Prepare Security Cheque')
SIGNING = {
    ('Payment Entry', 'Pending Cheque Payment - App'): ('Approve', 'Pending Reconciliation'),
    ('Payment Entry', 'Pending Security Cheque - App'): ('Approve', 'Handover Security Cheque'),
    ('GL Payment', 'Pending Cheque Payment - App'): ('Paid', 'Pending Reconciliation')
}
VOID = {
    ('Payment Entry', 'Pending Reconciliation'): 'Pending Payment - Maker',
    ('GL Payment', 'Pending Reconciliation'): 'Draft',
    ('Payment Entry', 'Handover Security Cheque'): 'Prepare Security Cheque',
    ('Payment Entry', 'Security Cheque Issued'): 'Prepare Security Cheque'
}


def _outgoing(doc):
    return (doc.doctype in SOURCE_FIELDS and doc.get('mode_of_payment') == 'Cheque' and
            doc.get('payment_type') == ('Pay' if doc.doctype == 'Payment Entry' else 'Outgoing'))


def _plans():
    if not hasattr(frappe.local, 'ws_cheque_payment_plans'):
        frappe.local.ws_cheque_payment_plans = {}
    return frappe.local.ws_cheque_payment_plans


def _company_currency(company):
    return frappe.db.get_value('Company', company, 'default_currency')


def _party_payee(doc):
    if not doc.get('party'):
        return doc.get('cheque_payee') if doc.doctype == 'GL Payment' else ''
    if not doc.get('party_type'):
        frappe.throw(_('Select the payment party type.'))
    title_field = frappe.get_meta(doc.party_type).get_title_field()
    return frappe.db.get_value(doc.party_type, doc.party, title_field) or doc.party


def _current_leaf(name):
    # Current locking read is necessary under v12/MariaDB repeatable-read.
    # The shared non-waiting account mutex avoids document/account lock cycles.
    rows = frappe.db.sql('SELECT * FROM `tabCheque Leaf` WHERE name=%s FOR UPDATE',
                         (name,), as_dict=True)
    if not rows:
        frappe.throw(_('Cheque leaf does not exist.'))
    return frappe.get_doc(dict(rows[0], doctype='Cheque Leaf'))


def _locked_leaves(names):
    leaves = {name: frappe.get_doc('Cheque Leaf', name) for name in set(names) if name}
    for leaf in leaves.values():
        leaf.check_permission('read')
    for account in sorted(set(leaf.account for leaf in leaves.values())):
        register._lock_account(account)
    for name, old in list(leaves.items()):
        current = _current_leaf(name)
        if current.account != old.account:
            frappe.throw(_('Cheque bank account changed. Reload and try again.'))
        current.check_permission('read')
        leaves[name] = current
    return leaves


def _owner(leaf):
    owners = [(dt, leaf.get(field)) for dt, field in SOURCE_FIELDS.items() if leaf.get(field)]
    if leaf.get('journal_entry'):
        owners.append(('Journal Entry', leaf.journal_entry))
    if len(owners) > 1:
        frappe.throw(_('Cheque leaf has conflicting payment links. Contact accounts.'))
    return owners[0] if owners else None


def _values(doc, leaf):
    account = doc.get('paid_from') if doc.doctype == 'Payment Entry' else doc.get('payment_account')
    if account != leaf.account or doc.company != leaf.company:
        frappe.throw(_('Cheque leaf must belong to this payment bank account and company.'))
    if doc.doctype == 'Payment Entry':
        if doc.get('paid_from_account_currency') and doc.paid_from_account_currency != leaf.currency:
            frappe.throw(_('Cheque currency does not match the payment bank currency.'))
        amount = flt(doc.get('paid_amount'), doc.precision('paid_amount'))
    else:
        if leaf.currency != _company_currency(doc.company):
            frappe.throw(_('Cheque GL Payments currently require a bank account in company currency.'))
        amount = flt(doc.get('total_amount'), doc.precision('total_amount'))
    if amount <= 0 or not doc.get('reference_date'):
        frappe.throw(_('A positive cheque amount and Cheque Date are required.'))
    # The printed name is a snapshot once signed, even if a party master is
    # subsequently renamed. Party identifiers remain part of the locked details.
    payee = leaf.payee if cint(leaf.get('signed')) else _party_payee(doc)
    return {'leaf': leaf.name, 'account': leaf.account, 'company': doc.company,
            'currency': leaf.currency, 'party_type': doc.get('party_type') or '',
            'party': doc.get('party') or '', 'payee': str(payee or '').strip(),
            'amount': amount, 'cheque_date': str(getdate(doc.reference_date))}


def _cleared_original(doc):
    """Native Amend is the only route for retaining an already-cleared cheque."""
    if not doc.get('amended_from'):
        return None
    original = frappe.get_doc(doc.doctype, doc.amended_from)
    original.check_permission('read')
    if not original.get('cheque_leaf'):
        return None
    leaf = frappe.get_doc('Cheque Leaf', original.cheque_leaf)
    if leaf.status != 'Cleared':
        return None
    if cint(original.docstatus) != 2 or not _outgoing(original):
        frappe.throw(_('Amend the cancelled outgoing payment to retain its cleared cheque.'))
    return original


def _check_cleared_amendment(doc, leaf, original):
    if not original:
        return False
    if (doc.get('cheque_leaf') != original.cheque_leaf or leaf.status != 'Cleared' or
            not cint(leaf.get('signed')) or not _outgoing(doc) or
            _values(doc, leaf) != _values(original, leaf) or
            (not doc.get('party') and (doc.get('cheque_payee') or '') != (original.get('cheque_payee') or ''))):
        frappe.throw(_('An accounting amendment must retain the same cleared cheque, bank, payee, amount and cheque date.'))
    owner = _owner(leaf)
    if owner not in ((doc.doctype, original.name), (doc.doctype, doc.name)):
        frappe.throw(_('This cleared cheque has already been linked to another amendment.'))
    if owner == (doc.doctype, original.name):
        original.check_permission('amend')
    return True


def _check_leaf(doc, leaf, values, cleared_amendment=False):
    owner = _owner(leaf)
    if owner and owner != (doc.doctype, doc.name) and not cleared_amendment:
        frappe.throw(_('This cheque leaf is already linked to another payment.'))
    if cint(leaf.get('damaged')) or leaf.status not in ('Available', 'Reserved', 'Issued', 'Cleared'):
        frappe.throw(_('This cheque leaf is not usable.'))
    if not owner and (leaf.status != 'Available' or cint(leaf.get('signed'))):
        frappe.throw(_('Select an Available, unsigned cheque leaf.'))
    book = frappe.get_doc('Cheque Book', leaf.cheque_book)
    if not owner and book.status != 'Active':
        frappe.throw(_('Select a leaf from an Active cheque book.'))
    date = getdate(values['cheque_date'])
    if not (owner and cint(leaf.get('signed'))) and (
            (book.get('valid_from') and date < getdate(book.valid_from)) or
            (book.get('valid_to') and date > getdate(book.valid_to))):
        frappe.throw(_('Cheque Date is outside this cheque book validity period.'))


def _action_access(doc, action, target):
    doc.check_permission('write')
    return any(t.action == action and t.next_state == target and
               has_approval_access(frappe.session.user, doc, t) for t in get_transitions(doc.as_dict()))


def _approval_access(doc):
    pair = SIGNING.get((doc.doctype, doc.get('workflow_state')))
    return bool(pair and _action_access(doc, pair[0], pair[1]))


def _void_access(doc):
    target = VOID.get((doc.doctype, doc.get('workflow_state')))
    if not target or cint(doc.docstatus) != 0:
        return False
    if frappe.session.user != 'Administrator' and 'Finance (Workflow)' not in frappe.get_roles():
        return False
    return _action_access(doc, 'Void Cheque', target)


def prepare_payment(doc, method=None):
    """Supply the actual printed reference before native bank validation runs."""
    original = _cleared_original(doc)
    if original:
        if doc.get('cheque_leaf') and doc.cheque_leaf != original.cheque_leaf:
            frappe.throw(_('Retain the original cleared cheque on this amendment.'))
        doc.cheque_leaf = original.cheque_leaf
    if doc.get('cheque_leaf') and _outgoing(doc):
        leaf = frappe.get_doc('Cheque Leaf', doc.cheque_leaf)
        leaf.check_permission('read')
        doc.reference_no = leaf.cheque_number
        if doc.get('party'):
            doc.party_name = _party_payee(doc)


def _confirmation(doc, previous, values, leaf):
    raw, old = doc.get(CONFIRMATION), previous.get(CONFIRMATION) if previous else None
    void_request = isinstance(raw, str) and raw.startswith('void:')
    if raw and raw != old and raw != 'confirm' and not void_request:
        frappe.throw(_('Cheque signing confirmation must come from the approval dialog.'))
    if raw == 'confirm' or void_request:
        operation = 'void' if void_request else 'sign'
        access = _void_access(doc) if void_request else _approval_access(doc)
        if (not previous or doc.workflow_state != previous.workflow_state or
                cint(doc.docstatus) != 0 or not access or not values['payee']):
            frappe.throw(_('Confirm this cheque action only at its permitted workflow stage.'))
        acknowledgement = {'operation': operation, 'user': frappe.session.user,
                           'confirmed_on': now(), 'details': values}
        if void_request:
            reason = strip_html(raw[5:]).strip()
            if (not reason or len(reason) > 500 or not cint(leaf.get('signed')) or
                    leaf.status not in ('Reserved', 'Issued')):
                frappe.throw(_('A signed cheque and a void reason of 1 to 500 characters are required.'))
            acknowledgement['reason'] = reason
        doc.set(CONFIRMATION, json.dumps(acknowledgement, sort_keys=True))
        return acknowledgement
    if raw:
        try:
            acknowledgement = json.loads(raw)
        except (TypeError, ValueError):
            acknowledgement = {}
        if (acknowledgement.get('details') == values and
                acknowledgement.get('user') == frappe.session.user and
                acknowledgement.get('operation') in ('sign', 'void')):
            return acknowledgement
    doc.set(CONFIRMATION, None)
    return None


def _has_payment_attachment(doc, leaf):
    filters = {'attached_to_doctype': doc.doctype, 'attached_to_name': doc.name,
               'is_folder': 0, 'file_url': ['is', 'set']}
    # A replacement must not reuse the previous cheque's payment attachments.
    # Cleared amendments retain their inherited documents and original signature.
    if leaf.status != 'Cleared' and leaf.get('signature_confirmed_on'):
        filters['creation'] = ['>=', leaf.signature_confirmed_on]
    return bool(frappe.get_all('File', filters=filters, fields=['name'], limit_page_length=1))


def validate_payment(doc, method=None):
    if doc.doctype not in SOURCE_FIELDS:
        return
    key = (doc.doctype, doc.name)
    _plans().pop(key, None)
    previous = doc.get_doc_before_save()
    if previous and doc.get('amended_from') != previous.get('amended_from'):
        frappe.throw(_('A saved payment cannot change its amendment reference.'))
    original = _cleared_original(doc)
    if original and not doc.get('cheque_leaf'):
        frappe.throw(_('A cleared cheque amendment cannot remove its cheque.'))
    state = doc.get('workflow_state') or 'Draft'
    old_name = previous.get('cheque_leaf') if previous else None
    new_name = doc.get('cheque_leaf')
    if not old_name and not new_name:
        if doc.get(CONFIRMATION):
            frappe.throw(_('Select a cheque leaf before confirming signing.'))
        if (previous and cint(previous.docstatus) == 1) or not _outgoing(doc):
            return
        if cint(doc.docstatus) != 2 and (cint(doc.docstatus) == 1 or state not in PREPARATION):
            frappe.throw(_('Select a cheque leaf before continuing cheque processing.'))
        return

    leaves = _locked_leaves([old_name, new_name])
    old_leaf = leaves.get(old_name)
    if previous and cint(previous.docstatus) == 1 and new_name != old_name:
        frappe.throw(_('A submitted payment cannot change its cheque leaf.'))
    if old_leaf and cint(old_leaf.get('signed')):
        expected = _values(previous, old_leaf)
        expected['payee'] = old_leaf.payee
        payee_changed = (doc.doctype == 'GL Payment' and not doc.get('party') and
                         (doc.get('cheque_payee') or '') != (previous.get('cheque_payee') or ''))
        if not _outgoing(doc) or new_name != old_name or payee_changed or _values(doc, old_leaf) != expected:
            frappe.throw(_('Signed cheque details cannot change. Cancel and prepare a replacement if necessary.'))
    if new_name and not _outgoing(doc):
        frappe.throw(_('Our cheque leaves can only be used for outgoing Cheque payments.'))

    releases = []
    if old_leaf and old_name != new_name:
        if _owner(old_leaf) not in (None, (doc.doctype, doc.name)) or old_leaf.status not in ('Available', 'Reserved'):
            frappe.throw(_('The previous cheque reservation cannot be released.'))
        releases.append(old_leaf)
    if not new_name:
        doc.set(CONFIRMATION, None)
        if _outgoing(doc) and state not in PREPARATION and cint(doc.docstatus) != 2:
            frappe.throw(_('Select a cheque leaf before continuing cheque processing.'))
        _plans()[key] = {'releases': releases, 'leaf': None}
        return

    leaf = leaves[new_name]
    cleared_amendment = _check_cleared_amendment(doc, leaf, original)
    values = _values(doc, leaf)
    amendment_note = None
    cancelling = cint(doc.docstatus) == 2 or method == 'before_cancel'
    if cancelling:
        if _owner(leaf) not in (None, (doc.doctype, doc.name)):
            frappe.throw(_('This cheque leaf belongs to another payment.'))
        doc.set(CONFIRMATION, None)
        changes = {SOURCE_FIELDS[doc.doctype]: doc.name, 'status': 'Cleared' if leaf.status == 'Cleared' else 'Cancelled'}
    else:
        _check_leaf(doc, leaf, values, cleared_amendment)
        acknowledgement = _confirmation(doc, previous, values, leaf)
        void_target = VOID.get((doc.doctype, previous.get('workflow_state'))) if previous else None
        if void_target and state == void_target:
            if (not acknowledgement or acknowledgement.get('operation') != 'void' or
                    not _void_access(previous) or not cint(leaf.get('signed')) or
                    leaf.status not in ('Reserved', 'Issued') or cint(doc.docstatus) != 0):
                frappe.throw(_('Use the Finance void confirmation before preparing a replacement cheque.'))
            note = 'Cheque voided by {} on {}: {}'.format(
                acknowledgement['user'], acknowledgement['confirmed_on'], acknowledgement['reason'])
            changes = {'status': 'Cancelled',
                       'remarks': '{}{}{}'.format(leaf.get('remarks') or '', '\n' if leaf.get('remarks') else '', note)}
            doc.cheque_leaf = None
            doc.set(CONFIRMATION, None)
            _plans()[key] = {'releases': [], 'leaf': leaf, 'changes': changes, 'void_note': note}
            return
        changes = {field: None for field in register.PAYMENT_FIELDS}
        changes.update({SOURCE_FIELDS[doc.doctype]: doc.name, 'payee': values['payee'],
                        'amount': values['amount'], 'cheque_date': values['cheque_date'],
                        'status': 'Reserved' if leaf.status in ('Available', 'Reserved') else leaf.status})
        pair = SIGNING.get((doc.doctype, previous.get('workflow_state'))) if previous else None
        if pair and doc.get('workflow_state') == pair[1]:
            if not _approval_access(previous) or (not cleared_amendment and
                    (not acknowledgement or acknowledgement.get('operation') != 'sign')):
                frappe.throw(_('Confirm that the physical cheque is signed before approving.'))
            if not cint(leaf.get('signed')):
                changes.update({'signed': 1, 'signature_confirmed_by': acknowledgement['user'],
                                'signature_confirmed_on': acknowledgement['confirmed_on']})
            doc.set(CONFIRMATION, None)
        if cint(doc.docstatus) == 1 and not (cint(leaf.get('signed')) or changes.get('signed')):
            frappe.throw(_('Complete the cheque signing approval before submitting this payment.'))
        if (cint(doc.docstatus) == 1 and (not previous or cint(previous.docstatus) != 1) and
                not _has_payment_attachment(doc, leaf)):
            frappe.throw(_('Attach the signed cheque copy to this payment after signing and before completing reconciliation.'))
        if cint(doc.docstatus) == 1:
            changes.update({'status': 'Cleared', 'cleared_date': leaf.get('cleared_date') or
                            str(getdate(doc.get('clearance_date') or now()))})
        if cleared_amendment and _owner(leaf) == (doc.doctype, original.name):
            amendment_note = 'Cleared cheque retained from cancelled {} {} in amendment {}.'.format(
                doc.doctype, original.name, doc.name)
            changes['remarks'] = '{}{}{}'.format(leaf.get('remarks') or '',
                '\n' if leaf.get('remarks') else '', amendment_note)
        if (doc.doctype == 'Payment Entry' and previous and
                previous.get('workflow_state') == 'Handover Security Cheque' and
                doc.get('workflow_state') == 'Security Cheque Issued'):
            if not cint(leaf.get('signed')):
                frappe.throw(_('Confirm cheque signing before security cheque handover.'))
            changes['status'] = 'Issued'
    _plans()[key] = {'releases': releases, 'leaf': leaf, 'changes': changes,
                     'amendment_note': amendment_note}


@contextmanager
def _tracking_update(leaf, values):
    old = getattr(frappe.local, 'ws_cheque_leaf_update', None)
    frappe.local.ws_cheque_leaf_update = {'name': leaf.name, 'values': values}
    try:
        yield
    finally:
        frappe.local.ws_cheque_leaf_update = old


def _apply_leaf(leaf, values):
    if all((leaf.get(key) or None) == (value or None) or str(leaf.get(key)) == str(value)
           for key, value in values.items()):
        return
    with _tracking_update(leaf, values):
        leaf.update(values)
        # Access was checked on the payment and leaf read. Only validated
        # tracking fields are set here; this is not a manual leaf write grant.
        leaf.save(ignore_permissions=True)


def sync_payment(doc, method=None):
    plan = _plans().pop((doc.doctype, doc.name), None)
    if not plan:
        return
    for leaf in plan['releases']:
        values = {field: None for field in register.PAYMENT_FIELDS}
        values.update({'status': 'Available', 'payee': None, 'amount': 0, 'cheque_date': None})
        _apply_leaf(leaf, values)
    if plan['leaf']:
        _apply_leaf(plan['leaf'], plan['changes'])
    for field in ('void_note', 'amendment_note'):
        if plan.get(field):
            doc.add_comment('Comment', plan[field])


def before_cancel(doc, method=None):
    validate_payment(doc, 'before_cancel')


def before_delete(doc, method=None):
    if doc.get('cheque_leaf'):
        frappe.throw(_('Remove the unsigned cheque reservation before deleting a draft payment. Signed cheques must be cancelled.'))


@frappe.whitelist()
def get_signing_details(doctype, name, operation='sign'):
    if doctype not in SOURCE_FIELDS:
        frappe.throw(_('Unsupported cheque payment document.'), frappe.PermissionError)
    doc = frappe.get_doc(doctype, name)
    doc.check_permission('read')
    if operation not in ('sign', 'void'):
        frappe.throw(_('Unsupported cheque action.'))
    access = _void_access(doc) if operation == 'void' else _approval_access(doc)
    if not _outgoing(doc) or not access or not doc.get('cheque_leaf'):
        frappe.throw(_('This payment is not ready for cheque signing approval.'))
    leaf = frappe.get_doc('Cheque Leaf', doc.cheque_leaf)
    leaf.check_permission('read')
    values = _values(doc, leaf)
    cleared_amendment = _check_cleared_amendment(doc, leaf, _cleared_original(doc))
    _check_leaf(doc, leaf, values, cleared_amendment)
    if _owner(leaf) != (doc.doctype, doc.name) or not values['payee']:
        frappe.throw(_('Save the cheque reservation and payee before approving.'))
    if operation == 'void' and (not cint(leaf.get('signed')) or leaf.status not in ('Reserved', 'Issued')):
        frappe.throw(_('Only a signed, uncleared cheque can be voided through this action.'))
    values.update({'cheque_number': leaf.cheque_number, 'signed': cint(leaf.get('signed')), 'operation': operation,
                   'already_cleared': cleared_amendment and operation == 'sign'})
    return values


@frappe.whitelist()
def get_reconciliation_details(name):
    doc = frappe.get_doc('GL Payment', name)
    doc.check_permission('read')
    if (not _outgoing(doc) or cint(doc.docstatus) != 0 or
            doc.workflow_state != 'Pending Reconciliation' or not doc.get('cheque_leaf') or
            not _action_access(doc, 'Reconciled', 'Completed')):
        frappe.throw(_('This payment is not ready for cheque reconciliation.'))
    leaf = frappe.get_doc('Cheque Leaf', doc.cheque_leaf)
    leaf.check_permission('read')
    if _owner(leaf) != (doc.doctype, doc.name) or not cint(leaf.get('signed')):
        frappe.throw(_('Save and sign this payment cheque before reconciliation.'))
    return {'has_attachment': _has_payment_attachment(doc, leaf)}


@frappe.whitelist(methods=['POST'])
def upload_cheque_attachment():
    """Native FileUploader callback; cheque images must not default to public."""
    register._require_post()
    if frappe.form_dict.get('doctype') != 'GL Payment':
        frappe.throw(_('Upload a cheque copy only to its GL Payment.'))
    name = frappe.form_dict.get('docname')
    get_reconciliation_details(name)  # Native action, write and ownership checks.
    content = getattr(frappe.local, 'uploaded_file', None)
    filename = getattr(frappe.local, 'uploaded_filename', None)
    if not content or not filename:
        frappe.throw(_('Choose a file to upload for this cheque.'))
    return frappe.get_doc({'doctype': 'File', 'attached_to_doctype': 'GL Payment',
        'attached_to_name': name, 'file_name': filename, 'content': content,
        'is_private': 1, 'folder': 'Home/Attachments'}).insert()


@frappe.whitelist()
def get_leaf_attachments(leaf_name):
    leaf = frappe.get_doc('Cheque Leaf', leaf_name)
    leaf.check_permission('read')
    owner = _owner(leaf)
    result = {'files': [], 'restricted': False}
    if not owner:
        return result
    result.update({'payment_type': owner[0], 'payment_name': owner[1]})
    payment = frappe.get_doc(*owner)
    if not payment.has_permission('read'):
        result['restricted'] = True
        return result
    rows = frappe.get_all('File', filters={'attached_to_doctype': owner[0],
        'attached_to_name': owner[1], 'is_folder': 0, 'file_url': ['is', 'set']},
        fields=['name', 'file_name', 'file_url', 'is_private'], order_by='creation asc', limit_page_length=0)
    for row in rows:
        # File permissions can be stricter than payment/leaf access. Never turn
        # a leaf link into a grant to private files or unsafe external URLs.
        if (not row.file_url.startswith(('/files/', '/private/files/', 'https://', 'http://')) or
                not frappe.get_doc('File', row.name).has_permission('read')):
            continue
        result['files'].append({key: row.get(key) for key in ('name', 'file_name', 'file_url', 'is_private')})
    return result


@frappe.whitelist(methods=['POST'])
def activate_worker():
    """Administrator-only refresh of these cheque modules and app hooks."""
    register._require_post()
    if frappe.session.user != 'Administrator':
        frappe.throw(_('Only Administrator can activate cheque payment hooks.'), frappe.PermissionError)
    import importlib
    importlib.reload(register)
    importlib.reload(importlib.import_module('worldshading.api.purchase_order'))
    result = register.activate_worker()
    hooks = frappe.get_doc_hooks()
    for dt in SOURCE_FIELDS:
        if 'worldshading.api.cheque_payments.validate_payment' not in hooks.get(dt, {}).get('validate', []):
            frappe.throw(_('Cheque payment validation did not load.'))
    result['payment_hooks_loaded'] = True
    return result
