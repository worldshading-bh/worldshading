# -*- coding: utf-8 -*-
"""Outgoing cheque inventory. Payment-side lifecycle integration is separate."""
from __future__ import unicode_literals

import re
from collections import Counter

import frappe
from frappe import _
from frappe.utils import cint, getdate


STATUSES = ('Available', 'Reserved', 'Issued', 'Cleared', 'Cancelled', 'Bounced')
PAYMENT_FIELDS = ('payment_entry', 'gl_payment', 'journal_entry')
FINANCIAL_FIELDS = PAYMENT_FIELDS + ('amount', 'cheque_date', 'payee', 'cleared_date')


def leaf_numbers(first, last):
    """Preserve printed zero padding; reject ambiguous or unbounded ranges."""
    first, last = str(first or '').strip(), str(last or '').strip()
    if not re.match(r'^[0-9]+$', first) or not re.match(r'^[0-9]+$', last):
        raise ValueError('Cheque numbers must contain digits 0 to 9 only.')
    if max(len(first), len(last)) > 30:
        raise ValueError('Cheque numbers cannot exceed 30 digits.')
    start, end = int(first), int(last)
    if start < 1 or end < start or end - start >= 50:
        raise ValueError('A cheque book must contain between 1 and 50 leaves in ascending order.')
    padded = first.startswith('0') or last.startswith('0')
    if padded and len(first) != len(last):
        raise ValueError('Use the same number of digits for both padded cheque numbers.')
    return [str(n).zfill(len(first)) if padded else str(n) for n in range(start, end + 1)]


def ranges_overlap(first, last, other_first, other_last):
    return int(first) <= int(other_last) and int(other_first) <= int(last)


def inventory_summary(expected, leaves):
    counts = Counter(row.get('status') or 'Available' for row in leaves)
    return {'total': len(leaves), 'expected': cint(expected),
            'missing': max(0, cint(expected) - len(leaves)),
            'counts': {status: counts.get(status, 0) for status in STATUSES}}


def _numbers(book):
    try:
        return leaf_numbers(book.first_leaf_no, book.last_leaf_no)
    except ValueError as error:
        frappe.throw(_(str(error)))


def _lock_account(account):
    # v12 locks saved documents BEFORE validation. A waiting Account row lock
    # would invert that order in generation. Instead take a non-waiting,
    # connection-scoped MariaDB advisory lock; a competing operation must retry.
    # Frappe.destroy() closes the connection after commit/rollback for web
    # requests and jobs, automatically releasing every recursive acquisition.
    # SQL is required: the v12 ORM has no equivalent. DATABASE() scopes sites.
    rows = frappe.db.sql('''SELECT GET_LOCK(
        SHA2(CONCAT(DATABASE(), ':ws-cheque:', %s), 256), 0)''', (account,))
    if not rows or rows[0][0] != 1:
        frappe.throw(_('Another cheque operation is using this bank account. Please try again.'))


def _account(account):
    result = frappe.db.get_value('Account', account,
        ['account_type', 'is_group', 'company', 'account_currency'], as_dict=True)
    if not result or result.account_type != 'Bank' or cint(result.is_group):
        frappe.throw(_('Select a bank ledger account that is not a group.'))
    return result


def _book_leaves(book, locked=False):
    if locked:
        # Current reads are required after a lock wait under MariaDB's
        # REPEATABLE READ isolation; ORM reads could retain an old snapshot.
        return frappe.db.sql('''SELECT name, cheque_number, status, payment_entry,
            gl_payment, journal_entry FROM `tabCheque Leaf`
            WHERE cheque_book=%s FOR UPDATE''', (book,), as_dict=True)
    return frappe.get_all('Cheque Leaf', filters={'cheque_book': book},
        fields=['name', 'cheque_number', 'status'] + list(PAYMENT_FIELDS))


def _account_books(account):
    return frappe.db.sql('''SELECT name, account, first_leaf_no, last_leaf_no
        FROM `tabCheque Book` WHERE account=%s FOR UPDATE''', (account,), as_dict=True)


def _account_leaves(account):
    return frappe.db.sql('''SELECT leaf.name, leaf.cheque_number
        FROM `tabCheque Leaf` leaf INNER JOIN `tabCheque Book` book
        ON book.name=leaf.cheque_book WHERE book.account=%s FOR UPDATE''',
        (account,), as_dict=True)


def _current_book(book_name, expected_account):
    rows = frappe.db.sql('SELECT * FROM `tabCheque Book` WHERE name=%s FOR UPDATE',
                         (book_name,), as_dict=True)
    if not rows or rows[0].account != expected_account:
        frappe.throw(_('Cheque book changed while waiting. Reload and try again.'))
    values = dict(rows[0], doctype='Cheque Book')
    return frappe.get_doc(values)


def validate_book(doc, method=None):
    numbers = _numbers(doc)
    bank = _account(doc.account)
    previous = doc.get_doc_before_save()
    for account in sorted(set([doc.account] + ([previous.account] if previous else []))):
        _lock_account(account)
    if previous:
        current = _current_book(doc.name, previous.account)
        if str(current.modified) != str(previous.modified):
            frappe.throw(_('Cheque book changed while waiting. Reload and try again.'))
    doc.company, doc.currency = bank.company, bank.account_currency
    doc.no_of_leaves = len(numbers)
    doc.status = doc.status or 'Active'
    if doc.status not in ('Active', 'Closed', 'Completed'):
        frappe.throw(_('Invalid cheque book status.'))
    if doc.valid_from and doc.valid_to and getdate(doc.valid_to) < getdate(doc.valid_from):
        frappe.throw(_('Valid To cannot be before Valid From.'))
    leaves = _book_leaves(doc.name, locked=True)
    if previous and leaves:
        for field in ('book_name', 'account', 'first_leaf_no', 'last_leaf_no'):
            if doc.get(field) != previous.get(field):
                frappe.throw(_('Account, book name and number range cannot change after leaves exist.'))
    for other in _account_books(doc.account):
        if other.name != doc.name:
            _numbers(other)
            if ranges_overlap(doc.first_leaf_no, doc.last_leaf_no,
                              other.first_leaf_no, other.last_leaf_no):
                frappe.throw(_('This range overlaps another cheque book for the same bank account.'))
    if doc.status == 'Completed' and (len(leaves) != len(numbers) or
            any(row.status not in ('Cleared', 'Cancelled') for row in leaves)):
        frappe.throw(_('Complete a book only after all its leaves are cleared or cancelled.'))


def validate_leaf(doc, method=None):
    book = frappe.get_doc('Cheque Book', doc.cheque_book)
    _lock_account(book.account)
    book = _current_book(doc.cheque_book, book.account)
    account = _account(book.account)
    previous = doc.get_doc_before_save()
    numbers = _numbers(book)
    number = str(doc.cheque_number or '')
    legacy_match = (previous and number == previous.cheque_number and
                    re.match(r'^[0-9]+$', number) and int(number) in [int(n) for n in numbers])
    if number not in numbers and not legacy_match:
        frappe.throw(_('Cheque number must match a printed number in this book range.'))
    if previous:
        for field in ('cheque_book', 'cheque_number'):
            if doc.get(field) != previous.get(field):
                frappe.throw(_('An existing cheque leaf cannot change its book or cheque number.'))
    elif book.status != 'Active':
        frappe.throw(_('New leaves can only be added to an Active cheque book.'))

    doc.account, doc.company, doc.currency = book.account, account.company, account.account_currency
    doc.cheque_number_key = str(int(doc.cheque_number))
    # Include legacy leaves not yet backfilled with account/normalized key.
    for other in _account_leaves(book.account):
        if other.name != doc.name and str(other.cheque_number or '').isdigit() and \
                int(other.cheque_number) == int(doc.cheque_number):
            frappe.throw(_('This cheque number already exists for this bank account.'))

    doc.status = doc.status or 'Available'
    if doc.status not in STATUSES:
        frappe.throw(_('Invalid cheque leaf status.'))
    if sum(bool(doc.get(field)) for field in PAYMENT_FIELDS) > 1:
        frappe.throw(_('A cheque leaf can link to only one payment document.'))
    # Readonly metadata is not server security. Until payment integration owns
    # these values, neither a form nor a direct API save may manufacture them.
    for field in FINANCIAL_FIELDS:
        old = previous.get(field) if previous else None
        if (doc.get(field) or None) != (old or None):
            frappe.throw(_('Payment details must be updated through the linked payment document.'))
    old_status = (previous.status or 'Available') if previous else 'Available'
    if doc.status != old_status:
        if not (old_status == 'Available' and doc.status == 'Cancelled' and
                not any(doc.get(field) for field in PAYMENT_FIELDS) and doc.remarks):
            frappe.throw(_('This status change requires the payment integration.'))
    if cint(doc.damaged):
        if any(doc.get(field) for field in PAYMENT_FIELDS) or old_status not in ('Available', 'Cancelled'):
            frappe.throw(_('Handle a damaged linked or issued cheque through its payment document.'))
        if not str(doc.remarks or '').strip():
            frappe.throw(_('Enter a reason for the damaged cheque.'))
        doc.status = 'Cancelled'
    if doc.status == 'Cancelled' and old_status == 'Available' and not str(doc.remarks or '').strip():
        frappe.throw(_('Enter a reason for cancelling this cheque leaf.'))


def protect_book_deletion(doc, method=None):
    _lock_account(doc.account)
    if _book_leaves(doc.name, locked=True):
        frappe.throw(_('A cheque book with leaves cannot be deleted. Close it instead.'))


def protect_leaf_deletion(doc, method=None):
    frappe.throw(_('Preserve cheque history: cancel an unused leaf instead of deleting it.'))


def protect_rename(doc, method=None, *args, **kwargs):
    if doc.doctype == 'Cheque Leaf':
        frappe.throw(_('Cheque identities with inventory cannot be renamed or merged.'))
    _lock_account(doc.account)
    if _book_leaves(doc.name, locked=True):
        frappe.throw(_('Cheque identities with inventory cannot be renamed or merged.'))


def _require_post():
    request = getattr(frappe.local, 'request', None)
    if request and request.method != 'POST':
        frappe.throw(_('Use POST for this action.'), frappe.PermissionError)


@frappe.whitelist(methods=['POST'])
def generate_leaves(book_name):
    _require_post()
    book = frappe.get_doc('Cheque Book', book_name)
    book.check_permission('write')
    if not frappe.has_permission('Cheque Leaf', 'create'):
        frappe.throw(_('You cannot create cheque leaves.'), frappe.PermissionError)
    _lock_account(book.account)
    # Re-read after waiting for another request's lock.
    book = _current_book(book_name, book.account)
    book.check_permission('write')
    validate_book(book)
    if book.status != 'Active':
        frappe.throw(_('Only Active cheque books can generate leaves.'))
    existing = set(str(int(row.cheque_number)) for row in _book_leaves(book.name, locked=True))
    created = 0
    for number in _numbers(book):
        if str(int(number)) not in existing:
            frappe.get_doc({'doctype': 'Cheque Leaf', 'cheque_book': book.name,
                            'cheque_number': number, 'status': 'Available'}).insert()
            created += 1
    return {'created': created, 'existing': len(existing)}


@frappe.whitelist(methods=['POST'])
def cancel_unused_leaf(leaf_name, reason, damaged=0):
    _require_post()
    leaf = frappe.get_doc('Cheque Leaf', leaf_name)
    leaf.check_permission('write')
    book = frappe.get_doc('Cheque Book', leaf.cheque_book)
    _lock_account(book.account)
    rows = frappe.db.sql('SELECT * FROM `tabCheque Leaf` WHERE name=%s FOR UPDATE',
                         (leaf_name,), as_dict=True)
    if not rows or rows[0].cheque_book != book.name:
        frappe.throw(_('Cheque leaf changed while waiting. Reload and try again.'))
    leaf = frappe.get_doc(dict(rows[0], doctype='Cheque Leaf'))
    leaf.check_permission('write')
    if leaf.status != 'Available' or any(leaf.get(field) for field in PAYMENT_FIELDS):
        frappe.throw(_('Only an Available, unlinked leaf can be cancelled here.'))
    reason = str(reason or '').strip()
    if not reason:
        frappe.throw(_('Enter a cancellation reason.'))
    leaf.status, leaf.damaged = 'Cancelled', cint(damaged)
    leaf.remarks = '{}{}{}'.format(leaf.remarks or '', '\n' if leaf.remarks else '', reason)
    leaf.save()
    return leaf.name


@frappe.whitelist()
def get_book_summary(book_name):
    book = frappe.get_doc('Cheque Book', book_name)
    book.check_permission('read')
    if not frappe.has_permission('Cheque Leaf', 'read'):
        frappe.throw(_('You cannot view cheque inventory.'), frappe.PermissionError)
    leaves = frappe.get_list('Cheque Leaf', filters={'cheque_book': book.name},
        fields=['name', 'status'], limit_page_length=0)
    result = inventory_summary(len(_numbers(book)), leaves)
    # Restricted leaves must not be described as inventory that was never
    # generated. Capacity is public to readers of this book; totals are visible
    # records only, matching the permission-filtered leaf list.
    result.pop('missing')
    return result


@frappe.whitelist(methods=['POST'])
def activate_worker():
    """Load this deployment's hooks in a preloaded worker without restarting it.

    Administrator-only; changes no documents or services. Call once per worker
    after the two DocType definitions are synchronized. Normal users never need
    this maintenance action.
    """
    _require_post()
    if frappe.session.user != 'Administrator':
        frappe.throw(_('Only Administrator can activate cheque register hooks.'), frappe.PermissionError)
    import importlib
    import os
    import worldshading.hooks as app_hooks

    importlib.reload(app_hooks)
    if hasattr(frappe.local, 'doc_events_hooks'):
        del frappe.local.doc_events_hooks
    expected = {
        'Cheque Book': 'worldshading.api.cheque_register.validate_book',
        'Cheque Leaf': 'worldshading.api.cheque_register.validate_leaf'
    }
    active = frappe.get_doc_hooks()
    for doctype, validator in expected.items():
        if validator not in active.get(doctype, {}).get('validate', []):
            frappe.throw(_('Cheque validation hook did not load.'))
    return {'pid': os.getpid(), 'validators_loaded': True,
            'form_scripts': {doctype: app_hooks.doctype_js.get(doctype) for doctype in expected}}
