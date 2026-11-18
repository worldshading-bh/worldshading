"""Database-free payment/cheque business checks. Never run bench test on production."""
import copy
import json
import unittest
from types import SimpleNamespace
from contextlib import ExitStack
from unittest.mock import patch

import frappe
from worldshading.api import cheque_payments as service


class Doc(frappe._dict):
    def add_comment(self, kind, text):
        self.setdefault('_test_comments', []).append((kind, text))

    def as_dict(self):
        return {k: v for k, v in self.items() if k != '_previous'}

    def set(self, field, value):
        self[field] = value

    def get_doc_before_save(self):
        return self.get('_previous')

    def is_new(self):
        return not self.get('_previous')

    def has_permission(self, permission):
        return permission not in self.get('_denied', [])

    def check_permission(self, permission):
        if permission in self.get('_denied', []):
            raise frappe.PermissionError

    def precision(self, field):
        return 3


class TestChequePayments(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(service.frappe, 'throw', side_effect=ValueError))
        self.stack.enter_context(patch.object(service.frappe, 'local', SimpleNamespace()))
        self.stack.enter_context(patch.object(service.frappe, 'session', frappe._dict(user='approver')))
        self.stack.enter_context(patch.object(service.register, '_lock_account'))
        self.stack.enter_context(patch.object(service, '_company_currency', return_value='BHD'))
        self.stack.enter_context(patch.object(service, '_party_payee',
            side_effect=lambda doc: ('Supplier One' if doc.get('party') == 'SUP' else 'Other Supplier')
                if doc.get('party') else doc.get('cheque_payee')))
        self.stack.enter_context(patch.object(service, '_approval_access', return_value=True))
        self.stack.enter_context(patch.object(service, '_void_access', return_value=True))
        self.stack.enter_context(patch.object(service, 'now', return_value='2026-11-18 10:00:00'))
        self.book = Doc(doctype='Cheque Book', name='CB-1', account='BANK', company='Company',
                        currency='BHD', status='Active', valid_from=None, valid_to=None)
        self.sources = {}
        self.files = [Doc(doctype='File', name='FILE-'+dt, file_name='cheque.pdf',
            file_url='/private/files/cheque.pdf', is_folder=0, is_private=1,
            attached_to_doctype=dt, attached_to_name=name, creation='2026-11-18 10:01:00')
            for dt, name in [('Payment Entry','PE-1'),('GL Payment','GL-1')]]
        self.stack.enter_context(patch.object(service.frappe, 'get_all', side_effect=self.file_rows))
        self.leaves = {
            name: Doc(doctype='Cheque Leaf', name=name, account='BANK', company='Company', currency='BHD',
                      cheque_book='CB-1', cheque_number=number, status='Available', signed=0,
                      damaged=0, amount=0, payment_entry=None, gl_payment=None, journal_entry=None,
                      signature_confirmed_by=None, signature_confirmed_on=None)
            for name, number in [('CL-1', '000101'), ('CL-2', '000102')]
        }
        self.stack.enter_context(patch.object(service, '_current_leaf',
            side_effect=lambda name: self.leaves[name]))
        self.stack.enter_context(patch.object(service.frappe, 'get_doc', side_effect=self.get_doc))
        self.stack.enter_context(patch.object(service, '_apply_leaf', side_effect=self.apply_leaf))

    def file_rows(self, dt, filters=None, **kwargs):
        if dt != 'File':
            raise AssertionError('Unexpected query: '+dt)
        rows = list(self.files)
        for key, value in (filters or {}).items():
            if isinstance(value, (list, tuple)):
                if value[0] == '>=':
                    rows = [r for r in rows if str(r.get(key) or '') >= str(value[1])]
                elif value == ['is', 'set']:
                    rows = [r for r in rows if r.get(key)]
                else:
                    raise AssertionError('Unsupported test filter')
            else:
                rows = [r for r in rows if r.get(key) == value]
        limit = kwargs.get('limit_page_length')
        return rows[:limit] if limit else rows

    def get_doc(self, dt, name):
        if dt == 'File':
            return next(r for r in self.files if r.name == name)
        if dt == 'Cheque Leaf':
            return self.leaves[name]
        if dt == 'Cheque Book':
            return self.book
        if (dt, name) in self.sources:
            return self.sources[(dt, name)]
        raise AssertionError('Unexpected document lookup: ' + dt)

    def apply_leaf(self, leaf, values):
        leaf.update(values)

    def payment(self, dt='Payment Entry', **values):
        doc = Doc(doctype=dt, name='PE-1' if dt == 'Payment Entry' else 'GL-1', docstatus=0,
                  company='Company', mode_of_payment='Cheque', cheque_leaf='CL-1',
                  payment_type='Pay' if dt == 'Payment Entry' else 'Outgoing',
                  paid_from='BANK', payment_account='BANK', paid_from_account_currency='BHD',
                  party_type='Supplier', party='SUP', party_name='Supplier One',
                  paid_amount=100, total_amount=100, received_amount=100,
                  reference_no='000101', reference_date='2026-11-20',
                  workflow_state='Draft', custom_cheque_signing_confirmation=None)
        doc.update(values)
        return doc

    def validate_save(self, doc):
        service.validate_payment(doc)
        service.sync_payment(doc)
        doc._previous = Doc({k: v for k, v in doc.items() if k != '_previous'})
        return doc

    def reserved(self, dt='Payment Entry'):
        doc = self.payment(dt)
        self.validate_save(doc)
        doc.workflow_state = 'Pending Cheque Payment - App'
        self.validate_save(doc)
        return doc

    def confirm(self, doc):
        doc.custom_cheque_signing_confirmation = 'confirm'
        self.validate_save(doc)
        return doc

    def signed(self, dt='Payment Entry'):
        doc = self.confirm(self.reserved(dt))
        doc.workflow_state = 'Pending Reconciliation'
        self.validate_save(doc)
        return doc

    def cancelled_cleared(self, dt='GL Payment'):
        doc = self.signed(dt)
        # Fixture represents a previously submitted/reconciled bank cheque.
        doc.update(dict(docstatus=2, workflow_state='Cancelled'))
        self.leaves['CL-1'].update(dict(status='Cleared', cleared_date='2026-11-22'))
        self.sources[(dt, doc.name)] = Doc(doc.as_dict())
        return self.sources[(dt, doc.name)]

    def amendment(self, original, **changes):
        doc = self.payment(original.doctype, name=original.name + '-1',
                           amended_from=original.name, posting_date='2026-11-23')
        doc.update(changes)
        # Native v12 copies the original attachments on amendment insertion.
        for item in list(self.files):
            if item.attached_to_doctype == original.doctype and item.attached_to_name == original.name:
                copied = Doc(item); copied.name += '-'+doc.name; copied.attached_to_name = doc.name
                self.files.append(copied)
        return doc

    def test_submission_clears_signed_cheque_and_uses_clearance_date(self):
        for dt in ('Payment Entry', 'GL Payment'):
            with self.subTest(dt=dt):
                # Each source type has its own independent leaf fixture.
                self.leaves['CL-1'].update(dict(status='Available', signed=0, payment_entry=None,
                                          gl_payment=None, signature_confirmed_by=None))
                doc = self.signed(dt)
                doc.update(dict(docstatus=1, workflow_state='Completed', clearance_date='2026-11-22'))
                self.validate_save(doc)
                leaf = self.leaves['CL-1']
                self.assertEqual((leaf.status, str(leaf.cleared_date)), ('Cleared', '2026-11-22'))
                doc.clearance_date = '2026-11-25'
                self.validate_save(doc)
                self.assertEqual(str(leaf.cleared_date), '2026-11-22')

    def test_submission_without_bank_clearance_date_uses_confirmation_day(self):
        doc = self.signed('GL Payment')
        doc.update(dict(docstatus=1, workflow_state='Completed'))
        self.validate_save(doc)
        self.assertEqual(str(self.leaves['CL-1'].cleared_date), '2026-11-18')

    def test_cancel_cleared_payment_preserves_bank_fact_signature_and_owner(self):
        doc = self.cancelled_cleared()
        # Model native cancellation: previous document is still submitted.
        doc._previous = Doc(doc.as_dict()); doc._previous.docstatus = 1
        service.before_cancel(doc)
        service.sync_payment(doc)
        leaf = self.leaves['CL-1']
        self.assertEqual((leaf.status, leaf.gl_payment, leaf.signed), ('Cleared', 'GL-1', 1))
        self.assertEqual((leaf.cleared_date, leaf.signature_confirmed_by), ('2026-11-22', 'approver'))

    def test_amendment_transfers_only_after_successful_save_and_preserves_history(self):
        for dt in ('GL Payment', 'Payment Entry'):
            with self.subTest(dt=dt):
                self.leaves['CL-1'].update(dict(status='Available', signed=0, payment_entry=None, gl_payment=None))
                old = self.cancelled_cleared(dt)
                doc = self.amendment(old, posting_date='2026-11-24', remarks='Corrected expense account')
                service.prepare_payment(doc)
                service.validate_payment(doc)
                leaf = self.leaves['CL-1']
                self.assertEqual(leaf.get(service.SOURCE_FIELDS[dt]), old.name,
                                 'Validation/failed payment saves must not transfer ownership')
                service.sync_payment(doc)
                self.assertEqual(leaf.get(service.SOURCE_FIELDS[dt]), doc.name)
                self.assertEqual((leaf.status, leaf.cleared_date, leaf.signed), ('Cleared', '2026-11-22', 1))
                self.assertEqual(old.cheque_leaf, 'CL-1')
                self.assertIn(old.name, doc._test_comments[0][1])

    def test_missing_leaf_is_restored_only_for_verified_cleared_amendment(self):
        old = self.cancelled_cleared()
        doc = self.amendment(old, cheque_leaf=None)
        service.prepare_payment(doc)
        self.assertEqual((doc.cheque_leaf, doc.reference_no), ('CL-1', '000101'))

    def test_amendment_cannot_select_another_leaf_or_change_physical_details(self):
        old = self.cancelled_cleared()
        for changes in ({'cheque_leaf': 'CL-2'}, {'payment_account': 'OTHER BANK'},
                        {'company': 'Other Company'}, {'total_amount': 101},
                        {'reference_date': '2026-11-21'}, {'party': 'OTHER'},
                        {'mode_of_payment': 'Cash'}, {'payment_type': 'Incoming'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                doc = self.amendment(old, **changes)
                service.prepare_payment(doc)
                service.validate_payment(doc)
        self.assertEqual(self.leaves['CL-1'].gl_payment, old.name)

    def test_duplicate_wrong_parent_unsigned_or_non_cancelled_source_cannot_claim_leaf(self):
        old = self.cancelled_cleared()
        with self.assertRaises(ValueError):
            service.validate_payment(self.payment('GL Payment', name='DUPLICATE'))
        other = Doc(old); other.name = 'OTHER'; other.cheque_leaf = 'CL-2'
        self.sources[('GL Payment', 'OTHER')] = other
        with self.assertRaises(ValueError):
            service.validate_payment(self.amendment(old, amended_from='OTHER'))
        for changes in ({'docstatus': 1}, {'docstatus': 0}):
            old.update(changes)
            with self.assertRaises(ValueError):
                service.validate_payment(self.amendment(old))
        old.docstatus = 2
        self.leaves['CL-1'].signed = 0
        with self.assertRaises(ValueError):
            service.validate_payment(self.amendment(old))

    def test_amendment_requires_permission_on_cancelled_source(self):
        old = self.cancelled_cleared()
        old._denied = ['amend']
        with self.assertRaises(frappe.PermissionError):
            service.validate_payment(self.amendment(old))

    def test_two_amendments_cannot_claim_same_cleared_leaf(self):
        old = self.cancelled_cleared()
        first = self.validate_save(self.amendment(old))
        with self.assertRaises(ValueError):
            service.validate_payment(self.amendment(old, name='GL-1-OTHER'))
        self.assertEqual(self.leaves['CL-1'].gl_payment, first.name)

    def test_cleared_amendment_keeps_existing_workflow_without_resigning(self):
        old = self.cancelled_cleared()
        doc = self.validate_save(self.amendment(old))
        doc.workflow_state = 'Pending Cheque Payment - App'
        self.validate_save(doc)
        self.sources[(doc.doctype, doc.name)] = doc
        details = service.get_signing_details(doc.doctype, doc.name)
        self.assertTrue(details['already_cleared'])
        doc.workflow_state = 'Pending Reconciliation'
        self.validate_save(doc)
        self.assertEqual(self.leaves['CL-1'].signature_confirmed_on, '2026-11-18 10:00:00')
        self.assertEqual(self.leaves['CL-1'].status, 'Cleared')
        doc.update(dict(docstatus=1, workflow_state='Completed'))
        self.validate_save(doc)
        self.assertEqual(self.leaves['CL-1'].cleared_date, '2026-11-22')

    def test_cleared_amendment_still_requires_native_signing_action_permission(self):
        old = self.cancelled_cleared()
        doc = self.validate_save(self.amendment(old))
        doc.workflow_state = 'Pending Cheque Payment - App'
        self.validate_save(doc)
        doc.workflow_state = 'Pending Reconciliation'
        with patch.object(service, '_approval_access', return_value=False):
            with self.assertRaises(ValueError):
                service.validate_payment(doc)
        self.assertEqual(self.leaves['CL-1'].status, 'Cleared')

    def test_saved_amendment_cannot_detach_leaf_or_change_ancestry(self):
        old = self.cancelled_cleared()
        doc = self.validate_save(self.amendment(old))
        for changes in ({'cheque_leaf': None}, {'cheque_leaf': 'CL-2'}, {'amended_from': None}):
            changed = Doc(doc); changed.update(changes)
            with self.assertRaises(ValueError):
                service.validate_payment(changed)

    def test_repeated_cancel_amend_chain_preserves_physical_cheque(self):
        old = self.cancelled_cleared()
        first = self.validate_save(self.amendment(old))
        first.docstatus = 1; first.workflow_state = 'Completed'
        self.validate_save(first)
        first.docstatus = 2; first.workflow_state = 'Cancelled'
        service.before_cancel(first); service.sync_payment(first)
        self.sources[(first.doctype, first.name)] = Doc(first.as_dict())
        second = self.validate_save(self.amendment(first))
        self.assertEqual((self.leaves['CL-1'].gl_payment, self.leaves['CL-1'].status), (second.name, 'Cleared'))
        self.assertEqual(self.leaves['CL-1'].cleared_date, '2026-11-22')

    def test_submission_requires_current_cheque_attachment_before_mutating_leaf(self):
        for dt in ('GL Payment', 'Payment Entry'):
            with self.subTest(dt=dt):
                self.leaves['CL-1'].update(dict(status='Available', signed=0, gl_payment=None, payment_entry=None))
                doc = self.signed(dt)
                doc.update(dict(docstatus=1, workflow_state='Completed'))
                for file in self.files:
                    file.creation = '2026-11-18 09:00:00'
                with self.assertRaises(ValueError):
                    service.validate_payment(doc)
                self.assertEqual(self.leaves['CL-1'].status, 'Reserved')
                for file in self.files:
                    file.creation = '2026-11-18 10:01:00'
                self.validate_save(doc)
                self.assertEqual(self.leaves['CL-1'].status, 'Cleared')

    def test_missing_attachment_does_not_block_draft_cancel_or_historical_updates(self):
        doc = self.signed('GL Payment')
        self.files = []
        self.validate_save(doc)
        doc.docstatus = 2
        service.before_cancel(doc); service.sync_payment(doc)
        self.assertEqual(self.leaves['CL-1'].status, 'Cancelled')
        # A previously cleared/submitted document remains editable in allowed fields.
        doc.docstatus = 1; doc._previous = Doc(doc.as_dict())
        self.leaves['CL-1'].status = 'Cleared'
        self.validate_save(doc)

    def test_cleared_amendment_requires_its_inherited_or_new_attachment(self):
        old = self.cancelled_cleared()
        doc = self.validate_save(self.amendment(old))
        doc.update(dict(docstatus=1, workflow_state='Completed'))
        self.files = [r for r in self.files if r.attached_to_name != doc.name]
        with self.assertRaises(ValueError):
            service.validate_payment(doc)
        inherited = Doc(next(r for r in self.files if r.attached_to_doctype == doc.doctype)); inherited.name='INHERITED'; inherited.attached_to_name=doc.name
        inherited.creation='2026-11-01 00:00:00'
        self.files.append(inherited)
        self.validate_save(doc)
        self.assertEqual(self.leaves['CL-1'].status, 'Cleared')

    def test_leaf_lists_payment_files_with_source_and_file_permissions(self):
        doc = self.validate_save(self.payment('GL Payment'))
        self.sources[(doc.doctype,doc.name)] = doc
        item = Doc(self.files[-1]); item.name='DENIED'; item._denied=['read']; self.files.append(item)
        unsafe = Doc(self.files[-2]); unsafe.name='UNSAFE'; unsafe.file_url='javascript:alert(1)'; self.files.append(unsafe)
        result = service.get_leaf_attachments('CL-1')
        self.assertEqual(result['payment_name'], 'GL-1')
        self.assertEqual([r['name'] for r in result['files']], ['FILE-GL Payment'])
        doc._denied=['read']
        result = service.get_leaf_attachments('CL-1')
        self.assertTrue(result['restricted']); self.assertEqual(result['files'], [])
        self.leaves['CL-1']._denied=['read']
        with self.assertRaises(frappe.PermissionError):
            service.get_leaf_attachments('CL-1')

    def test_unlinked_leaf_and_journal_attachment_view(self):
        self.assertEqual(service.get_leaf_attachments('CL-2')['files'], [])
        leaf=self.leaves['CL-2']; leaf.journal_entry='JV-1'
        self.sources[('Journal Entry','JV-1')] = Doc(doctype='Journal Entry',name='JV-1')
        self.files.append(Doc(doctype='File',name='JV-FILE',file_name='proof.pdf',file_url='/files/proof.pdf',
                              attached_to_doctype='Journal Entry',attached_to_name='JV-1',is_folder=0))
        result=service.get_leaf_attachments('CL-2')
        self.assertEqual(result['payment_type'], 'Journal Entry')
        self.assertEqual([r['name'] for r in result['files']], ['JV-FILE'])

    def test_gl_reconciliation_precheck_reports_attachment_without_advancing_workflow(self):
        doc=self.signed('GL Payment'); self.sources[(doc.doctype,doc.name)]=doc
        with patch.object(service,'_action_access',return_value=True):
            result=service.get_reconciliation_details(doc.name)
            self.assertTrue(result['has_attachment'])
            self.files=[]
            self.assertFalse(service.get_reconciliation_details(doc.name)['has_attachment'])
        self.assertEqual(doc.workflow_state,'Pending Reconciliation')
        with patch.object(service,'_action_access',return_value=False), self.assertRaises(ValueError):
            service.get_reconciliation_details(doc.name)

    def test_save_reserves_one_leaf_and_copies_bank_details(self):
        doc = self.payment()
        service.validate_payment(doc)
        self.assertEqual(self.leaves['CL-1'].status, 'Available', 'Validation must not mutate a leaf')
        service.sync_payment(doc)
        leaf = self.leaves['CL-1']
        self.assertEqual((leaf.status, leaf.payment_entry, leaf.amount, leaf.payee, leaf.cheque_date),
                         ('Reserved', 'PE-1', 100, 'Supplier One', '2026-11-20'))
        self.assertFalse(leaf.signed)

    def test_same_leaf_cannot_be_used_by_gl_or_journal_entry_owner(self):
        self.validate_save(self.payment())
        with self.assertRaises(ValueError):
            service.validate_payment(self.payment('GL Payment'))
        leaf = self.leaves['CL-2']
        leaf.update(dict(status='Reserved', journal_entry='JV-1'))
        with self.assertRaises(ValueError):
            service.validate_payment(self.payment(cheque_leaf='CL-2'))

    def test_wrong_account_company_and_currency_are_rejected(self):
        for changes in ({'paid_from': 'OTHER BANK'}, {'company': 'Other Company'},
                        {'paid_from_account_currency': 'USD'}):
            with self.assertRaises(ValueError):
                service.validate_payment(self.payment(**changes))

    def test_changed_unsigned_selection_releases_old_leaf_atomically(self):
        doc = self.validate_save(self.payment())
        doc.cheque_leaf = 'CL-2'
        self.validate_save(doc)
        self.assertEqual((self.leaves['CL-1'].status, self.leaves['CL-1'].payment_entry), ('Available', None))
        self.assertEqual((self.leaves['CL-2'].status, self.leaves['CL-2'].payment_entry), ('Reserved', 'PE-1'))

    def test_approval_needs_confirmation_and_successful_transition(self):
        doc = self.reserved()
        doc.workflow_state = 'Pending Reconciliation'
        with self.assertRaises(ValueError):
            service.validate_payment(doc)
        self.assertFalse(self.leaves['CL-1'].signed)
        doc.workflow_state = 'Pending Cheque Payment - App'
        self.confirm(doc)
        self.assertFalse(self.leaves['CL-1'].signed, 'Saving acknowledgement alone is not signing')
        doc.workflow_state = 'Pending Reconciliation'
        service.validate_payment(doc)
        self.assertFalse(self.leaves['CL-1'].signed, 'A later payment validation may still fail')
        service.sync_payment(doc)
        leaf = self.leaves['CL-1']
        self.assertEqual((leaf.signed, leaf.signature_confirmed_by, leaf.signature_confirmed_on),
                         (1, 'approver', '2026-11-18 10:00:00'))
        self.assertEqual(leaf.status, 'Reserved', 'Signing is not handover or bank clearance')

    def test_gl_uses_same_rule_and_confirmation_is_consumed(self):
        doc = self.signed('GL Payment')
        self.assertTrue(self.leaves['CL-1'].signed)
        self.assertEqual(self.leaves['CL-1'].gl_payment, 'GL-1')
        self.assertFalse(doc.custom_cheque_signing_confirmation)

    def test_confirmation_cannot_be_forged_or_used_by_another_user(self):
        doc = self.reserved()
        doc.custom_cheque_signing_confirmation = json.dumps({'user': 'approver', 'confirmed': True})
        with self.assertRaises(ValueError):
            service.validate_payment(doc)
        doc.custom_cheque_signing_confirmation = None
        self.confirm(doc)
        with patch.object(service.frappe, 'session', frappe._dict(user='other approver')):
            doc.workflow_state = 'Pending Reconciliation'
            with self.assertRaises(ValueError):
                service.validate_payment(doc)

    def test_changed_details_invalidate_confirmation(self):
        doc = self.confirm(self.reserved())
        doc.paid_amount = 110
        self.validate_save(doc)
        self.assertFalse(doc.custom_cheque_signing_confirmation)
        doc.workflow_state = 'Pending Reconciliation'
        with self.assertRaises(ValueError):
            service.validate_payment(doc)

    def test_confirmation_requires_native_workflow_approval_permission(self):
        doc = self.reserved()
        doc.custom_cheque_signing_confirmation = 'confirm'
        with patch.object(service, '_approval_access', return_value=False):
            with self.assertRaises(ValueError):
                service.validate_payment(doc)

    def test_signed_details_cannot_change_or_detach(self):
        doc = self.signed()
        for field, value in [('cheque_leaf', None), ('paid_from', 'OTHER'), ('party', 'OTHER'),
                             ('paid_amount', 110), ('reference_date', '2026-11-21'),
                             ('mode_of_payment', 'Cash')]:
            changed = Doc(doc)
            changed[field] = value
            with self.assertRaises(ValueError):
                service.validate_payment(changed)

    def test_signed_cancellation_preserves_link_and_audit(self):
        doc = self.signed()
        doc.docstatus = 2
        service.before_cancel(doc)
        service.sync_payment(doc)
        leaf = self.leaves['CL-1']
        self.assertEqual((leaf.status, leaf.signed, leaf.payment_entry), ('Cancelled', 1, 'PE-1'))
        self.assertEqual(leaf.signature_confirmed_by, 'approver')

    def test_finance_void_returns_draft_for_replacement_and_keeps_old_history(self):
        for dt, target in [('Payment Entry', 'Pending Payment - Maker'), ('GL Payment', 'Draft')]:
            if dt == 'GL Payment':
                self.leaves['CL-1'].update(dict(status='Available', signed=0, payment_entry=None,
                    gl_payment=None, signature_confirmed_by=None, signature_confirmed_on=None))
                self.leaves['CL-2'].update(dict(status='Available', signed=0, payment_entry=None, gl_payment=None))
            doc = self.signed(dt)
            doc.custom_cheque_signing_confirmation = 'void:Wrong cheque date'
            self.validate_save(doc)
            self.assertEqual(self.leaves['CL-1'].status, 'Reserved', 'Saving void acknowledgement alone cannot void')
            doc.workflow_state = target
            self.validate_save(doc)
            leaf = self.leaves['CL-1']
            self.assertEqual((doc.docstatus, doc.cheque_leaf, leaf.status, leaf.signed), (0, None, 'Cancelled', 1))
            self.assertEqual(leaf.signature_confirmed_by, 'approver')
            self.assertIn('Wrong cheque date', leaf.remarks)
            self.assertEqual(leaf.get(service.SOURCE_FIELDS[dt]), doc.name)
            doc.cheque_leaf = 'CL-2'
            service.prepare_payment(doc)
            self.validate_save(doc)
            self.assertEqual((self.leaves['CL-2'].status, self.leaves['CL-2'].signed), ('Reserved', 0))
            self.assertEqual(doc.reference_no, '000102')

    def test_void_requires_finance_permission_reason_and_saved_acknowledgement(self):
        doc = self.signed()
        doc.custom_cheque_signing_confirmation = 'void:   '
        with self.assertRaises(ValueError):
            service.validate_payment(doc)
        doc.custom_cheque_signing_confirmation = 'void:Wrong date'
        with patch.object(service, '_void_access', return_value=False):
            with self.assertRaises(ValueError):
                service.validate_payment(doc)
        doc.custom_cheque_signing_confirmation = None
        doc.workflow_state = 'Pending Payment - Maker'
        with self.assertRaises(ValueError):
            service.validate_payment(doc)
        self.assertEqual(self.leaves['CL-1'].status, 'Reserved')

    def test_security_void_keeps_security_flag_and_returns_to_security_preparation(self):
        doc = self.validate_save(self.payment(is_security_cheque=1))
        doc.workflow_state = 'Pending Security Cheque - App'
        self.validate_save(doc); self.confirm(doc)
        doc.workflow_state = 'Handover Security Cheque'
        self.validate_save(doc)
        doc.custom_cheque_signing_confirmation = 'void:Returned unused'
        self.validate_save(doc)
        doc.workflow_state = 'Prepare Security Cheque'
        self.validate_save(doc)
        self.assertEqual((doc.docstatus, doc.is_security_cheque, doc.cheque_leaf), (0, 1, None))
        self.assertEqual(self.leaves['CL-1'].status, 'Cancelled')

    def test_submitted_payment_cannot_use_draft_void_path(self):
        doc = self.signed()
        doc.docstatus = 1; doc.workflow_state = 'Completed'
        self.validate_save(doc)
        doc.custom_cheque_signing_confirmation = 'void:Wrong date'
        with self.assertRaises(ValueError):
            service.validate_payment(doc)

    def test_closing_or_expiring_book_does_not_rewrite_existing_signed_cheque(self):
        doc = self.signed()
        self.book.status = 'Closed'
        self.book.valid_to = '2026-11-19'
        self.validate_save(doc)
        self.assertEqual(self.leaves['CL-1'].cheque_date, '2026-11-20')

    def test_reference_and_party_display_name_are_supplied_from_records(self):
        doc = self.payment('GL Payment', reference_no='PO-1', party_name='Unrelated Name')
        service.prepare_payment(doc)
        self.assertEqual((doc.reference_no, doc.party_name), ('000101', 'Supplier One'))

    def test_client_document_flags_cannot_manufacture_a_sync_plan(self):
        doc = self.payment(flags={'ws_cheque_payment_plans': {'signed': 1}})
        service.sync_payment(doc)
        self.assertEqual(self.leaves['CL-1'].status, 'Available')

    def test_incoming_and_historical_unlinked_payments_are_unchanged(self):
        incoming = self.payment(payment_type='Receive', cheque_leaf=None, workflow_state='Completed', docstatus=1)
        service.validate_payment(incoming)
        historical = self.payment(cheque_leaf=None, workflow_state='Completed', docstatus=1)
        historical._previous = Doc(historical)
        service.validate_payment(historical)
        self.assertEqual(self.leaves['CL-1'].status, 'Available')

    def test_scheduled_draft_without_leaf_remains_allowed(self):
        for state in (None, 'Draft', 'Scheduled', 'Pending Payment - Maker'):
            service.validate_payment(self.payment(cheque_leaf=None, workflow_state=state))
        with self.assertRaises(ValueError):
            service.validate_payment(self.payment(cheque_leaf=None, workflow_state='Pending Cheque Payment - Chkr'))

    def test_security_approval_and_handover_preserve_draft_status(self):
        doc = self.validate_save(self.payment(is_security_cheque=1))
        doc.workflow_state = 'Pending Security Cheque - App'
        self.validate_save(doc)
        self.confirm(doc)
        doc.workflow_state = 'Handover Security Cheque'
        self.validate_save(doc)
        self.assertTrue(self.leaves['CL-1'].signed)
        self.assertEqual(doc.docstatus, 0)
        doc.workflow_state = 'Security Cheque Issued'
        self.validate_save(doc)
        self.assertEqual((self.leaves['CL-1'].status, doc.docstatus), ('Issued', 0))

    def test_partyless_gl_needs_a_payee_before_signing(self):
        doc = self.payment('GL Payment', party=None, party_name=None, cheque_payee='Government Office')
        self.validate_save(doc)
        self.assertEqual(self.leaves['CL-1'].payee, 'Government Office')
        doc.workflow_state = 'Pending Cheque Payment - App'
        self.validate_save(doc)
        doc.cheque_payee = ''
        doc.custom_cheque_signing_confirmation = 'confirm'
        with self.assertRaises(ValueError):
            service.validate_payment(doc)

    def test_party_name_payload_does_not_control_gl_payee(self):
        doc = self.payment('GL Payment', party_name='Unrelated Person')
        self.validate_save(doc)
        self.assertEqual(self.leaves['CL-1'].payee, 'Supplier One')

    def test_leaf_cannot_be_used_from_closed_book_or_if_damaged(self):
        self.book.status = 'Closed'
        with self.assertRaises(ValueError):
            service.validate_payment(self.payment())
        self.book.status = 'Active'
        self.leaves['CL-1'].damaged = 1
        with self.assertRaises(ValueError):
            service.validate_payment(self.payment())

    def test_linked_payment_deletion_is_blocked(self):
        doc = self.validate_save(self.payment())
        with self.assertRaises(ValueError):
            service.before_delete(doc)


class TestPrivateChequeUpload(unittest.TestCase):
    def test_native_upload_bytes_are_saved_privately_only_to_authorized_gl(self):
        captured = []
        def file_doc(values):
            captured.append(values)
            return SimpleNamespace(insert=lambda: values)
        with patch.object(service.frappe, 'local', SimpleNamespace(uploaded_file=b'signed copy',uploaded_filename='cheque.png')), \
                patch.object(service.frappe, 'form_dict', frappe._dict(doctype='GL Payment',docname='GL-1')), \
                patch.object(service, 'get_reconciliation_details', return_value={'has_attachment':False}), \
                patch.object(service.frappe, 'get_doc', side_effect=file_doc):
            result=service.upload_cheque_attachment()
        self.assertEqual(result['is_private'],1)
        self.assertEqual((result['attached_to_doctype'],result['attached_to_name']),('GL Payment','GL-1'))
        self.assertEqual(result['content'],b'signed copy')

    def test_empty_upload_never_creates_a_file(self):
        with patch.object(service.frappe,'throw',side_effect=ValueError), \
                patch.object(service.frappe,'local',SimpleNamespace(uploaded_file=b'',uploaded_filename='empty.png')), \
                patch.object(service.frappe,'form_dict',frappe._dict(doctype='GL Payment',docname='GL-1')), \
                patch.object(service,'get_reconciliation_details',return_value={'has_attachment':False}), \
                patch.object(service.frappe,'get_doc',side_effect=AssertionError('Must not create File')), \
                self.assertRaises(ValueError):
            service.upload_cheque_attachment()

    def test_upload_denies_wrong_document_and_unpermitted_workflow(self):
        with patch.object(service.frappe,'throw',side_effect=ValueError), \
                patch.object(service.frappe,'form_dict',frappe._dict(doctype='Journal Entry',docname='JV-1')), \
                self.assertRaises(ValueError):
            service.upload_cheque_attachment()
        with patch.object(service.frappe,'form_dict',frappe._dict(doctype='GL Payment',docname='GL-1')), \
                patch.object(service,'get_reconciliation_details',side_effect=frappe.PermissionError), \
                self.assertRaises(frappe.PermissionError):
            service.upload_cheque_attachment()


class TestNativeApprovalLookup(unittest.TestCase):
    def test_void_is_finance_only_even_with_a_transition_available(self):
        doc = Doc(doctype='GL Payment', name='GL-1', workflow_state='Pending Reconciliation',
                  docstatus=0, owner='maker')
        transition = Doc(action='Void Cheque', next_state='Draft', allow_self_approval=0)
        with patch.object(service, 'get_transitions', return_value=[transition]), \
                patch.object(service.frappe, 'session', frappe._dict(user='reviewer')), \
                patch.object(service.frappe, 'get_roles', return_value=['Approver - ACC (Workflow)']):
            self.assertFalse(service._void_access(doc))
        with patch.object(service, 'get_transitions', return_value=[transition]), \
                patch.object(service.frappe, 'session', frappe._dict(user='finance')), \
                patch.object(service.frappe, 'get_roles', return_value=['Finance (Workflow)']):
            self.assertTrue(service._void_access(doc))

    def test_party_payee_uses_the_linked_master_title(self):
        doc = Doc(doctype='GL Payment', party_type='Supplier', party='SUP', party_name='Forged Name')
        def value(dt, name, field):
            if (dt, name, field) != ('Supplier', 'SUP', 'supplier_name'):
                raise AssertionError('Wrong party lookup')
            return 'Authoritative Supplier'
        with patch.object(service.frappe, 'get_meta', return_value=SimpleNamespace(get_title_field=lambda: 'supplier_name')), \
                patch.object(service.frappe, 'db', frappe._dict(get_value=value)):
            self.assertEqual(service._party_payee(doc), 'Authoritative Supplier')

    def test_permission_lookup_does_not_reload_the_payment_being_saved(self):
        doc = Doc(doctype='Payment Entry', name='PE-1', workflow_state='Pending Cheque Payment - App',
                  owner='maker', paid_amount=110, modified='new timestamp')
        def native_transitions(argument):
            # Native v12 reloads a Document argument in place. A dict produces a
            # separate document, so the caller's pending save must be untouched.
            target = argument if isinstance(argument, Doc) else Doc(argument)
            target.paid_amount = 100
            target.modified = 'old timestamp'
            return [Doc(action='Approve', next_state='Pending Reconciliation', allow_self_approval=0)]
        with patch.object(service, 'get_transitions', side_effect=native_transitions), \
                patch.object(service.frappe, 'session', frappe._dict(user='approver')):
            self.assertTrue(service._approval_access(doc))
        self.assertEqual((doc.paid_amount, doc.modified), (110, 'new timestamp'))

    def test_native_self_approval_policy_is_preserved(self):
        doc = Doc(doctype='GL Payment', name='GL-1', workflow_state='Pending Cheque Payment - App', owner='approver')
        transition = Doc(action='Paid', next_state='Pending Reconciliation', allow_self_approval=0)
        with patch.object(service, 'get_transitions', return_value=[transition]), \
                patch.object(service.frappe, 'session', frappe._dict(user='approver')):
            self.assertFalse(service._approval_access(doc))
            transition.allow_self_approval = 1
            self.assertTrue(service._approval_access(doc))


if __name__ == '__main__':
    unittest.main()
