import importlib
import importlib.util
import sys
import types
from pathlib import Path
import unittest
from datetime import datetime
from unittest.mock import Mock, patch
from adapter_support import adapter
from test_item_links import Doc
from worldshading.integration.woocommerce import domain as d


class SettingsDoc(Doc):
    __setattr__ = dict.__setitem__


class CustomerIdentityTests(unittest.TestCase):
    order = {'id': 12, 'customer_id': 7, 'billing': {'email': 'buyer@example.com'}}

    def test_customer_identity_is_store_scoped_and_canonical(self):
        a = d.customer_key(self.order, 'https://shop.example.com/')
        self.assertTrue(a.startswith('woo:'))
        self.assertEqual(a, d.customer_key(self.order, 'https://shop.example.com'))
        self.assertNotEqual(a, d.customer_key(self.order, 'https://another.example.com'))

    def test_customer_identity_never_embeds_personal_details(self):
        key = d.customer_key({'id': 1, 'billing': {'email': ' Buyer@Example.com '}}, 'https://shop.example.com')
        self.assertNotIn('buyer', key)
        self.assertEqual(key, d.customer_key({'id': 2, 'billing': {'email': 'buyer@example.com'}}, 'https://shop.example.com'))

    def test_existing_legacy_customer_is_reused_without_creating_or_rekeying(self):
        with adapter('orders') as (m, f, c, unused):
            f.db.get_value.side_effect = lambda dt, filters, field: 'OLD' if filters['ws_woo_customer_key'] == d.legacy_customer_key(self.order) else None
            self.assertEqual(m.customer_for(self.order, Doc(store_url='https://shop.example.com')), 'OLD')
            f.get_doc.assert_not_called()
            f.db.set_value.assert_not_called()

    def test_conflicting_legacy_and_scoped_customers_require_review(self):
        with adapter('orders') as (m, f, c, unused):
            f.db.get_value.side_effect = ['NEW', 'OLD']
            with self.assertRaisesRegex(ValueError, 'customer'):
                m.customer_for(self.order, Doc(store_url='https://shop.example.com'))
            f.get_doc.assert_not_called()

    def test_new_customer_uses_scoped_key(self):
        with adapter('orders') as (m, f, c, unused):
            f.db.get_value.return_value = None
            customer = Doc(name='NEW', insert=Mock())
            f.get_doc.return_value = customer
            payload = {'id': 21, 'customer_id': 5, 'billing': {}}
            config = Doc(store_url='https://shop.example.com', customer_group='Online', territory='Bahrain')
            self.assertEqual(m.customer_for(payload, config), 'NEW')
            self.assertEqual(f.get_doc.call_args[0][0]['ws_woo_customer_key'], d.customer_key(payload, config.store_url))
            customer.insert.assert_called_once_with(ignore_permissions=True)

    def test_legacy_key_is_still_valid_for_linked_order_updates(self):
        self.assertTrue(d.customer_key_matches(d.legacy_customer_key(self.order), self.order, 'https://shop.example.com'))
        self.assertFalse(d.customer_key_matches('unrelated', self.order, 'https://shop.example.com'))


class CutoffTimezoneTests(unittest.TestCase):
    def module(self):
        return importlib.import_module('worldshading.integration.woocommerce.timezones')

    def test_bahrain_now_is_converted_to_utc(self):
        m = self.module()
        self.assertEqual(m.site_to_utc('2026-11-01 15:17:32', 'Asia/Bahrain'), datetime(2026, 11, 1, 12, 17, 32))
        self.assertEqual(m.utc_to_site('2026-11-01 12:17:32', 'Asia/Bahrain'), datetime(2026, 11, 1, 15, 17, 32))

    def test_day_boundary_and_utc_site(self):
        m = self.module()
        self.assertEqual(m.site_to_utc('2026-11-01 01:00:00', 'Asia/Bahrain'), datetime(2026, 10, 31, 22))
        self.assertEqual(m.site_to_utc('2026-11-01 01:00:00', 'UTC'), datetime(2026, 11, 1, 1))

    def test_dst_invalid_or_ambiguous_time_requires_explicit_valid_selection(self):
        m = self.module()
        for value in ['2026-03-08 02:30:00', '2026-11-01 01:30:00']:
            with self.assertRaises(ValueError): m.site_to_utc(value, 'America/New_York')

    def test_repeated_roundtrip_does_not_shift_cutoff(self):
        m = self.module()
        value = datetime(2026, 11, 1, 12, 17, 32)
        for _ in range(3): value = m.site_to_utc(m.utc_to_site(value, 'Asia/Bahrain'), 'Asia/Bahrain')
        self.assertEqual(value, datetime(2026, 11, 1, 12, 17, 32))

    def test_settings_save_derives_utc_from_picker_not_old_hidden_value(self):
        with adapter('timezones') as (m, f, c, unused):
            import pytz
            m._zone = lambda unused=None: pytz.timezone('Asia/Bahrain')
            doc = SettingsDoc(order_since_local='2026-11-01 15:17:32', order_since='2026-11-01 15:17:32', poll_cursor='unchanged')
            m.update_order_cutoff(doc)
            self.assertEqual(doc.order_since, datetime(2026, 11, 1, 12, 17, 32))
            m.update_order_cutoff(doc)
            self.assertEqual(doc.order_since, datetime(2026, 11, 1, 12, 17, 32))
            self.assertEqual(doc.poll_cursor, 'unchanged')

    def test_settings_save_preserves_legacy_utc_when_picker_is_missing(self):
        with adapter('timezones') as (m, f, c, unused):
            import pytz
            m._zone = lambda unused=None: pytz.timezone('Asia/Bahrain')
            doc = SettingsDoc(order_since='2026-11-01 12:17:32')
            m.update_order_cutoff(doc)
            self.assertEqual(doc.order_since_local, datetime(2026, 11, 1, 15, 17, 32))
            self.assertEqual(doc.order_since, datetime(2026, 11, 1, 12, 17, 32))

    def test_ambiguous_backfilled_legacy_cutoff_is_preserved_on_save(self):
        with adapter('timezones') as (m, f, c, unused):
            import pytz
            m._zone = lambda unused=None: pytz.timezone('America/New_York')
            doc = SettingsDoc(order_since='2026-11-01 06:30:00')
            m.update_order_cutoff(doc)
            self.assertEqual(doc.order_since_local, datetime(2026, 11, 1, 1, 30))
            self.assertEqual(str(doc.order_since), '2026-11-01 06:30:00')

    def test_cutoff_picker_boundary_matches_woo_utc_orders(self):
        cutoff = self.module().site_to_utc('2026-11-01 15:17:32', 'Asia/Bahrain')
        self.assertFalse(d.order_in_window({'date_created_gmt':'2026-11-01T12:17:31'}, cutoff))
        self.assertTrue(d.order_in_window({'date_created_gmt':'2026-11-01T12:17:32'}, cutoff))
        self.assertTrue(d.order_in_window({'date_created_gmt':'2026-11-01T12:17:33'}, cutoff))

    def test_scoped_upgrade_only_reloads_connector_metadata(self):
        with adapter('install') as (m, f, c, unused):
            f.conf = Doc(host_name='https://demo.worldshading.com')
            f.db.exists.return_value = True
            f.db.get_value.side_effect = lambda dt, *args, **kwargs: Doc(module='Worldshading', custom=0) if dt=='DocType' else None
            f.reload_doc = Mock()
            f.clear_cache = Mock()
            f.db.get_single_value.return_value = None
            result = m.upgrade_refinements()
            self.assertTrue(result['cutoff_preserved'])
            self.assertEqual(f.reload_doc.call_count, 7)
            self.assertTrue(all(call[0][0]=='worldshading' for call in f.reload_doc.call_args_list))
            m.create_custom_fields.assert_not_called()
            f.db.set_value.assert_not_called()
            f.db.commit.assert_called_once()

    def test_actual_settings_validator_converts_now_and_repeat_save_preserves_utc(self):
        with adapter('timezones') as (timezone_module, f, c, unused):
            sys.modules['frappe.utils'].get_time_zone = lambda: 'Asia/Bahrain'
            model = types.ModuleType('frappe.model.document')
            model.Document = SettingsDoc
            inventory = types.ModuleType('worldshading.integration.woocommerce.inventory')
            inventory.stock_warehouses = Mock(return_value=['MAIN'])
            f.conf = Doc(host_name='https://demo.worldshading.com')
            def value(dt, *args, **kwargs):
                if dt == 'Price List': return Doc(currency='BHD', selling=1, enabled=1)
                if dt == 'Company': return 'BHD'
                if dt == 'Account': return Doc(company='WS', is_group=0, disabled=0)
            f.db.get_value.side_effect = value
            path = Path(__file__).resolve().parents[2] / 'worldshading/worldshading/doctype/ws_woocommerce_settings/ws_woocommerce_settings.py'
            with patch.dict(sys.modules, {'frappe.model.document':model, inventory.__name__:inventory}):
                spec = importlib.util.spec_from_file_location('settings_under_test', str(path))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                doc = module.WSWooCommerceSettings(doctype='WS WooCommerce Settings',
                    order_since_local='2026-11-01 15:17:32', order_since='2026-11-01 15:17:32',
                    store_url='https://testshop.worldshading.com', company='WS', currency='BHD',
                    price_list='Online', safety_stock=0, delivery_days=2, max_attempts=5)
                doc.validate()
                self.assertEqual(doc.get('order_since'), datetime(2026, 11, 1, 12, 17, 32))
                doc.validate()
                self.assertEqual(doc.get('order_since'), datetime(2026, 11, 1, 12, 17, 32))
                self.assertEqual(doc.store_url, 'https://testshop.worldshading.com')

    def test_upgrade_backfills_local_picker_without_changing_utc_cursor_or_switches(self):
        with adapter('install') as (m, f, c, unused):
            f.db.get_single_value.side_effect = lambda dt, field: {'order_since': '2026-11-01 12:17:32', 'order_since_local': None}.get(field)
            # Explicit timezone injection keeps this test independent of a real site.
            self.assertTrue(m.migrate_order_cutoff(time_zone='Asia/Bahrain'))
            args = f.db.set_value.call_args
            self.assertEqual(args[0][2], 'order_since_local')
            self.assertEqual(args[0][3], datetime(2026, 11, 1, 15, 17, 32))
            self.assertFalse(args[1]['update_modified'])
            f.db.get_single_value.side_effect = lambda dt, field: '2026-11-01 15:17:32'
            f.db.set_value.reset_mock()
            self.assertFalse(m.migrate_order_cutoff(time_zone='Asia/Bahrain'))
            f.db.set_value.assert_not_called()


if __name__ == '__main__': unittest.main()
