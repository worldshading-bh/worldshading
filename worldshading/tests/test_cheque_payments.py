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

    def get_doc(self, dt, name):
        if dt == 'Cheque Leaf':
            return self.leaves[name]
        if dt == 'Cheque Book':
            return self.book
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
