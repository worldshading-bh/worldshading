"""Database-free checks. Run with Python unittest, never bench test on production."""
import unittest
from unittest.mock import patch
from contextlib import ExitStack

import frappe
from worldshading.api import cheque_register as service


class Doc(frappe._dict):
    def get_doc_before_save(self):
        return self.get('_previous')

    def is_new(self):
        return not self.get('_previous')

    def check_permission(self, permission):
        if permission in self.get('_denied', []):
            raise frappe.PermissionError


class TestChequeNumbers(unittest.TestCase):
    def test_preserves_padding_and_inclusive_end(self):
        self.assertEqual(service.leaf_numbers('000098', '000100'),
                         ['000098', '000099', '000100'])
        self.assertEqual(service.leaf_numbers('9', '11'), ['9', '10', '11'])
        self.assertEqual(service.leaf_numbers('7', '7'), ['7'])

    def test_rejects_invalid_or_oversized_ranges(self):
        for first, last in [('10', '9'), ('0', '5'), ('-1', '4'), ('1.0', '4'),
                            ('1', '51'), ('', '4'), ('001', '50'), ('١', '٣')]:
            with self.assertRaises(ValueError):
                service.leaf_numbers(first, last)

    def test_overlap_compares_numbers_and_includes_boundary(self):
        self.assertTrue(service.ranges_overlap('001', '050', '50', '99'))
        self.assertFalse(service.ranges_overlap('001', '050', '51', '99'))

    def test_dashboard_counts_missing_and_unusable_inventory(self):
        result = service.inventory_summary(5, [
            {'status': 'Available'}, {'status': 'Reserved'},
            {'status': 'Cancelled'}, {'status': 'Cleared'}])
        self.assertEqual(result['total'], 4)
        self.assertEqual(result['missing'], 1)
        self.assertEqual(result['counts']['Available'], 1)
        self.assertEqual(result['counts']['Issued'], 0)


class TestRegisterControls(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(service.frappe, 'throw', side_effect=ValueError))
        self.stack.enter_context(patch.object(service, '_lock_account'))
        self.stack.enter_context(patch.object(service.frappe, 'has_permission', return_value=True))
        self.books = [Doc(doctype='Cheque Book', name='BOOK', book_name='BOOK',
                          account='BANK', first_leaf_no='001', last_leaf_no='003',
                          no_of_leaves=3, status='Active')]
        self.leaves = []
        self.account = frappe._dict(account_type='Bank', is_group=0,
                                    company='Company', account_currency='BHD')
        self.stack.enter_context(patch.object(service.frappe, 'get_all', side_effect=self.get_all))
        self.stack.enter_context(patch.object(service.frappe, 'get_list', side_effect=self.get_all))
        self.stack.enter_context(patch.object(service.frappe, 'get_doc', side_effect=self.get_doc))
        self.stack.enter_context(patch.object(service.frappe, 'db',
            frappe._dict(get_value=self.get_value, sql=lambda query, values, **kwargs:
                [self.get_doc('Cheque Leaf', values[0])])))
        self.stack.enter_context(patch.object(service, '_current_book',
            side_effect=lambda name, account: self.get_doc('Cheque Book', name)))
        self.stack.enter_context(patch.object(service, '_account_books',
            side_effect=lambda account: self.get_all('Cheque Book', {'account': account})))
        self.stack.enter_context(patch.object(service, '_account_leaves',
            side_effect=lambda account: [r for r in self.leaves
                if self.get_doc('Cheque Book', r.cheque_book).account == account]))
        self.stack.enter_context(patch.object(service, '_book_leaves',
            side_effect=lambda name, locked=False: self.get_all('Cheque Leaf', {'cheque_book': name})))

    def get_all(self, doctype, filters=None, **kwargs):
        rows = self.books if doctype == 'Cheque Book' else self.leaves
        def matches(row):
            for key, value in (filters or {}).items():
                if isinstance(value, (list, tuple)):
                    if value[0] == 'in' and row.get(key) not in value[1]:
                        return False
                    if value[0] == '!=' and row.get(key) == value[1]:
                        return False
                elif row.get(key) != value:
                    return False
            return True
        return [r for r in rows if matches(r)]

    def get_value(self, doctype, name, fields=None, **kwargs):
        if doctype == 'Account':
            return self.account
        raise AssertionError('Unexpected lookup: ' + doctype)

    def get_doc(self, doctype, name=None):
        if isinstance(doctype, dict):
            if doctype.get('name'):
                return self.get_doc(doctype['doctype'], doctype['name'])
            doc = Doc(doctype)
            doc.name = 'GENERATED-' + str(len(self.leaves))
            def insert():
                service.validate_leaf(doc)
                self.leaves.append(doc)
                return doc
            doc.insert = insert
            return doc
        rows = self.books if doctype == 'Cheque Book' else self.leaves
        return next(r for r in rows if r.name == name)

    def leaf(self, **values):
        doc = Doc(doctype='Cheque Leaf', name='LEAF', cheque_book='BOOK',
                  cheque_number='001', status='Available', signed=0, damaged=0)
        doc.update(values)
        return doc

    def test_book_sets_count_and_rejects_non_bank_accounts(self):
        service.validate_book(self.books[0])
        self.assertEqual(self.books[0].no_of_leaves, 3)
        self.account.account_type = 'Cash'
        with self.assertRaises(ValueError):
            service.validate_book(self.books[0])

    def test_overlapping_book_same_account_is_rejected(self):
        self.books.append(Doc(name='OTHER', account='BANK', first_leaf_no='3', last_leaf_no='5'))
        with self.assertRaises(ValueError):
            service.validate_book(self.books[0])
        self.books[-1].account = 'OTHER BANK'
        service.validate_book(self.books[0])

    def test_populated_book_identity_cannot_change(self):
        self.leaves.append(self.leaf())
        self.books[0]._previous = Doc(self.books[0])
        self.books[0].last_leaf_no = '004'
        with self.assertRaises(ValueError):
            service.validate_book(self.books[0])

    def test_invalid_dates_and_premature_completion_are_rejected(self):
        book = self.books[0]
        book.update(dict(valid_from='2026-12-01', valid_to='2026-11-01'))
        with self.assertRaises(ValueError):
            service.validate_book(book)
        book.update(dict(valid_from=None, valid_to=None, status='Completed'))
        with self.assertRaises(ValueError):
            service.validate_book(book)

    def test_leaf_derives_bank_context_and_checks_range(self):
        leaf = self.leaf(account='TAMPERED', company='WRONG', currency='USD')
        service.validate_leaf(leaf)
        self.assertEqual((leaf.account, leaf.company, leaf.currency, leaf.cheque_number_key),
                         ('BANK', 'Company', 'BHD', '1'))
        leaf.cheque_number = '004'
        with self.assertRaises(ValueError):
            service.validate_leaf(leaf)

    def test_duplicate_is_account_scoped_and_ignores_padding(self):
        self.leaves.append(self.leaf(name='OLD', cheque_number='1'))
        with self.assertRaises(ValueError):
            service.validate_leaf(self.leaf())
        self.books.append(Doc(name='OTHER', account='OTHER BANK', first_leaf_no='001',
                              last_leaf_no='003', status='Active'))
        service.validate_leaf(self.leaf(cheque_book='OTHER'))

    def test_new_leaf_cannot_forge_status_or_payment_links(self):
        for values in ({'status': 'Issued'}, {'status': 'Cleared'}, {'amount': 100},
                       {'payment_entry': 'PE'}, {'gl_payment': 'GL'},
                       {'journal_entry': 'JE'}, {'cleared_date': '2026-11-17'}):
            with self.assertRaises(ValueError):
                service.validate_leaf(self.leaf(**values))

    def test_saved_leaf_identity_and_financial_fields_are_protected(self):
        for field, value in [('cheque_number', '002'), ('gl_payment', 'GL'),
                             ('journal_entry', 'JE'), ('status', 'Cleared')]:
            leaf = self.leaf()
            leaf._previous = Doc(leaf)
            leaf[field] = value
            with self.assertRaises(ValueError):
                service.validate_leaf(leaf)

    def test_damaged_leaf_requires_reason_and_cannot_stay_available(self):
        leaf = self.leaf(damaged=1)
        with self.assertRaises(ValueError):
            service.validate_leaf(leaf)
        leaf.remarks = 'Torn during preparation'
        service.validate_leaf(leaf)
        self.assertEqual(leaf.status, 'Cancelled')

    def test_existing_book_and_leaf_cannot_be_deleted(self):
        self.leaves.append(self.leaf())
        with self.assertRaises(ValueError):
            service.protect_book_deletion(self.books[0])
        with self.assertRaises(ValueError):
            service.protect_leaf_deletion(self.leaves[0])

    def test_manual_signature_and_audit_values_are_rejected(self):
        for field, value in [('signed', 1), ('signature_confirmed_by', 'approver'),
                             ('signature_confirmed_on', '2026-11-18 10:00:00')]:
            with self.assertRaises(ValueError):
                service.validate_leaf(self.leaf(**{field: value}))

    def test_validated_payment_context_can_update_tracking_fields(self):
        from worldshading.api.cheque_payments import _tracking_update
        leaf = self.leaf()
        leaf._previous = Doc(leaf)
        changes = {'payment_entry': 'PE-1', 'status': 'Reserved', 'amount': 100,
                   'payee': 'Supplier', 'cheque_date': '2026-11-20', 'signed': 1,
                   'signature_confirmed_by': 'approver',
                   'signature_confirmed_on': '2026-11-18 10:00:00'}
        leaf.update(changes)
        with _tracking_update(leaf, changes):
            service.validate_leaf(leaf)
        self.assertEqual((leaf.status, leaf.signed), ('Reserved', 1))
        self.assertFalse(getattr(service.frappe.local, 'ws_cheque_leaf_update', None))

    def test_generation_preserves_existing_leaf_and_is_repeatable(self):
        self.leaves.append(self.leaf(name='LEGACY', cheque_number='1'))
        self.assertEqual(service.generate_leaves('BOOK')['created'], 2)
        self.assertEqual([r.cheque_number for r in self.leaves], ['1', '002', '003'])
        self.assertEqual(self.leaves[0].name, 'LEGACY')
        self.assertEqual(service.generate_leaves('BOOK')['created'], 0)

    def test_generation_requires_book_write_and_leaf_create(self):
        self.books[0]._denied = ['write']
        with self.assertRaises(frappe.PermissionError):
            service.generate_leaves('BOOK')
        self.books[0]._denied = []
        with patch.object(service.frappe, 'has_permission', return_value=False):
            with self.assertRaises(ValueError):
                service.generate_leaves('BOOK')
        self.assertEqual(self.leaves, [])

    def test_closed_book_cannot_generate(self):
        self.books[0].status = 'Closed'
        with self.assertRaises(ValueError):
            service.generate_leaves('BOOK')
        self.assertEqual(self.leaves, [])

    def test_cancel_unused_leaf_requires_reason_and_preserves_it(self):
        leaf = self.leaf(remarks='Existing note')
        leaf._previous = Doc(leaf)
        leaf.save = lambda: service.validate_leaf(leaf)
        self.leaves.append(leaf)
        with self.assertRaises(ValueError):
            service.cancel_unused_leaf('LEAF', '  ')
        service.cancel_unused_leaf('LEAF', 'Torn corner', damaged=1)
        self.assertEqual((leaf.status, leaf.damaged), ('Cancelled', 1))
        self.assertEqual(leaf.remarks, 'Existing note\nTorn corner')
        with self.assertRaises(ValueError):
            service.cancel_unused_leaf('LEAF', 'Repeat')

    def test_cannot_cancel_a_linked_leaf(self):
        self.leaves.append(self.leaf(journal_entry='JV'))
        with self.assertRaises(ValueError):
            service.cancel_unused_leaf('LEAF', 'Unused')

    def test_legacy_padding_can_be_preserved_when_cancelling(self):
        leaf = self.leaf(cheque_number='1')
        leaf._previous = Doc(leaf)
        leaf.save = lambda: service.validate_leaf(leaf)
        self.leaves.append(leaf)
        service.cancel_unused_leaf('LEAF', 'Unused legacy leaf')
        self.assertEqual((leaf.cheque_number, leaf.status), ('1', 'Cancelled'))

    def test_summary_requires_read_access(self):
        with patch.object(service.frappe, 'has_permission', return_value=False):
            with self.assertRaises(ValueError):
                service.get_book_summary('BOOK')
        self.leaves.append(self.leaf())
        self.assertEqual(service.get_book_summary('BOOK')['expected'], 3)

    def test_dashboard_does_not_count_restricted_leaves_as_missing(self):
        self.leaves.extend([self.leaf(), self.leaf(name='HIDDEN', status='Reserved')])
        with patch.object(service.frappe, 'get_list', return_value=[self.leaves[0]]):
            result = service.get_book_summary('BOOK')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['counts']['Reserved'], 0)
        self.assertNotIn('missing', result)


class TestAccountSerialization(unittest.TestCase):
    def test_worker_activation_is_administrator_only(self):
        with patch.object(service.frappe, 'session', frappe._dict(user='Accounts User')), \
                patch.object(service.frappe, 'throw', side_effect=ValueError):
            with self.assertRaises(ValueError):
                service.activate_worker()

    def test_busy_account_fails_immediately_instead_of_waiting_on_a_row_lock(self):
        def sql(query, values):
            if 'GET_LOCK' not in query or ', 0)' not in query:
                self.fail('Account serialization must fail fast to avoid v12 document-lock cycles')
            return [(0,)]
        with patch.object(service.frappe, 'db', frappe._dict(sql=sql)), \
                patch.object(service.frappe, 'throw', side_effect=ValueError):
            with self.assertRaises(ValueError):
                service._lock_account('BANK')


if __name__ == '__main__':
    unittest.main()
