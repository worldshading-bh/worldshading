import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
import frappe
from worldshading.worldshading.doctype.fixed_expense.fixed_expense import normalize_expense_identity, expense_identity_key, FixedExpense

class TestExpenseIdentity(unittest.TestCase):
    def test_phone_or_billing_account_preserved_without_length_rules(self):
        for value in ['33123456', '1234567', '001234567890123', '97312345678', 'STC-12345']:
            self.assertEqual(normalize_expense_identity('Telephone Bill', ' ' + value + ' ', 'Bahrain'), value)

    def test_email_case_and_spaces(self):
        self.assertEqual(normalize_expense_identity('AI Subscription', ' Team@Example.COM '), 'team@example.com')

    def test_invalid_identifiers_rejected(self):
        with patch('frappe.throw', side_effect=ValueError):
            for category, value, country in [('Telephone Bill', '', 'Bahrain'), 
                 ('AI Subscription', '', None), ('AI Subscription', 'not-an-email', None),
                ('AI Subscription', 'a@example.com,b@example.com', None)]:
                with self.assertRaises(ValueError):
                    normalize_expense_identity(category, value, country)

    def test_keys_are_company_and_category_scoped(self):
        key = expense_identity_key('A', 'AI Subscription', 'team@example.com')
        self.assertEqual(key, expense_identity_key('A', 'AI Subscription', 'team@example.com'))
        self.assertNotEqual(key, expense_identity_key('B', 'AI Subscription', 'team@example.com'))
        self.assertNotEqual(key, expense_identity_key('A', 'Other', 'team@example.com'))

    def test_active_key_and_closed_release(self):
        doc = SimpleNamespace(name='FEX-1', company='A', category='Telephone Bill',
                              mobile_number='33123456', status='Active')
        doc.get = lambda key: getattr(doc, key, None)
        doc.set = lambda key, value: setattr(doc, key, value)
        with patch.object(frappe, 'db', Mock(), create=True) as db, patch.object(frappe, 'get_all', return_value=[]) as query:
            db.get_value.return_value = 'Bahrain'
            FixedExpense.validate_expense_identity(doc)
            self.assertEqual(doc.mobile_number, '33123456')
            self.assertTrue(doc.active_expense_identity)
            query.assert_called_once()
            query.reset_mock()
            doc.status = 'Closed'
            FixedExpense.validate_expense_identity(doc)
            self.assertIsNone(doc.active_expense_identity)
            query.assert_not_called()

    def test_duplicate_is_blocked_with_existing_record_link(self):
        doc = SimpleNamespace(name='FEX-2', company='A', category='AI Subscription', ai_service='ChatGPT',
                              registered_email='TEAM@example.com', status='Active')
        doc.get = lambda key: getattr(doc, key, None)
        doc.set = lambda key, value: setattr(doc, key, value)
        with patch.object(frappe, 'db', Mock(), create=True), patch.object(frappe, 'get_all', return_value=[frappe._dict(name='FEX-1')]), \
             patch('frappe.utils.get_link_to_form', return_value='link-to-FEX-1'), patch.object(frappe, 'throw', side_effect=ValueError) as error:
            with self.assertRaises(ValueError):
                FixedExpense.validate_expense_identity(doc)
            self.assertIn('link-to-FEX-1', error.call_args[0][0])

    def test_other_categories_do_not_require_identity(self):
        doc = SimpleNamespace(category='Rent', active_expense_identity='old')
        doc.get = lambda key: getattr(doc, key, None)
        FixedExpense.validate_expense_identity(doc)
        self.assertIsNone(doc.active_expense_identity)

    def test_same_email_allowed_for_different_services(self):
        keys = [expense_identity_key('A', 'AI Subscription', 'team@example.com', service)
                for service in ('ChatGPT', 'Claude', 'Gemini')]
        self.assertEqual(len(set(keys)), 3)
        self.assertEqual(keys[0], expense_identity_key('A', 'AI Subscription', 'team@example.com', 'ChatGPT'))

    def test_missing_or_unsupported_service_is_rejected(self):
        for service in (None, '', 'Other'):
            doc = SimpleNamespace(category='AI Subscription', ai_service=service)
            doc.get = lambda key: getattr(doc, key, None)
            with patch.object(frappe, 'throw', side_effect=ValueError):
                with self.assertRaises(ValueError):
                    FixedExpense.validate_expense_identity(doc)

if __name__ == '__main__':
    unittest.main()
