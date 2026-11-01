import base64
import hashlib
import hmac
import sys
import types
import contextlib
import unittest
from unittest.mock import Mock, patch
from adapter_support import adapter, PACKAGE


class ControlTests(unittest.TestCase):
    def test_worker_in_manual_mode_does_not_run_sync(self):
        with adapter('worker') as (worker, frappe, common, orders):
            common.settings.return_value = types.SimpleNamespace(enabled=1, automatic_sync=0)
            sync = types.ModuleType(PACKAGE + '.sync')
            sync.run_cycle = Mock(return_value={})
            with patch.dict(sys.modules, {PACKAGE + '.sync': sync}), patch.object(sys, 'argv', ['worker', '--site', 'demo']):
                worker.main()
            sync.run_cycle.assert_not_called()
            frappe.set_user.assert_not_called()
            frappe.destroy.assert_called_once()

    def test_worker_in_automatic_mode_runs_sync(self):
        with adapter('worker') as (worker, frappe, common, orders):
            common.settings.return_value = types.SimpleNamespace(enabled=1, automatic_sync=1, integration_user='connector')
            sync = types.ModuleType(PACKAGE + '.sync')
            sync.run_cycle = Mock(return_value={})
            with patch.dict(sys.modules, {PACKAGE + '.sync': sync}), patch.object(sys, 'argv', ['worker', '--site', 'demo']):
                worker.main()
            sync.run_cycle.assert_called_once_with(changes_only=True)

    def webhook(self, automatic=0, valid_signature=True, enabled=1, body=b'{"id":123,"date_created_gmt":"2026-10-29T10:00:00","date_modified_gmt":"2026-10-29T10:00:00","total":"1.000"}'):
        context = adapter('api')
        api, frappe, common, orders = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        common.settings.return_value = types.SimpleNamespace(enabled=enabled, automatic_sync=automatic,
            store_url='https://testshop.worldshading.com', integration_user='connector',
            order_since='2026-10-01 00:00:00',
            get_password=lambda *args, **kwargs: 'secret')
        frappe.request = types.SimpleNamespace(method='POST', get_data=lambda: body)
        signature = base64.b64encode(hmac.new(b'secret', body, hashlib.sha256).digest()).decode()
        headers = {'X-WC-Webhook-Signature': signature if valid_signature else 'invalid',
                   'X-WC-Webhook-Source': 'https://testshop.worldshading.com',
                   'X-WC-Webhook-Topic': 'order.created'}
        frappe.get_request_header = headers.get
        orders.store_payload.return_value = (types.SimpleNamespace(woo_order_id=123), True)
        return api, frappe, orders

    def test_signed_webhook_in_manual_mode_does_not_write_or_import(self):
        api, frappe, orders = self.webhook()
        result = api.webhook()
        self.assertTrue(result['paused'])
        self.assertFalse(result['accepted'])
        orders.store_payload.assert_not_called()
        frappe.set_user.assert_not_called()
        frappe.db.commit.assert_not_called()

    def test_disabled_connector_does_not_accept_webhook_work(self):
        api, frappe, orders = self.webhook(automatic=1, enabled=0)
        self.assertTrue(api.webhook()['paused'])
        orders.store_payload.assert_not_called()

    def test_manual_mode_still_rejects_forged_webhooks(self):
        api, frappe, orders = self.webhook(valid_signature=False)
        with self.assertRaises(PermissionError): api.webhook()
        orders.store_payload.assert_not_called()

    def test_automatic_mode_accepts_valid_webhook(self):
        api, frappe, orders = self.webhook(automatic=1)
        self.assertTrue(api.webhook()['accepted'])
        orders.store_payload.assert_called_once()

    def test_unsigned_initial_probe_is_harmless_in_manual_mode(self):
        api, frappe, orders = self.webhook(valid_signature=False, body=b'webhook_id=123')
        self.assertTrue(api.webhook()['ping'])
        orders.store_payload.assert_not_called()

    def test_automatic_webhook_excludes_orders_before_import_start(self):
        api,frappe,orders=self.webhook(automatic=1,body=b'{"id":123,"date_created_gmt":"2026-09-01T00:00:00","total":"1"}')
        result=api.webhook()
        self.assertFalse(result['accepted'])
        self.assertTrue(result['outside_import_window'])
        orders.store_payload.assert_not_called()

    def test_busy_webhook_returns_retryable_response_without_writes(self):
        api,frappe,orders=self.webhook(automatic=1)
        common=sys.modules[PACKAGE+'.common']
        @contextlib.contextmanager
        def lock(key):
            raise common.LockBusy('Already processing');yield
        common.lock=lock
        result=api.webhook()
        self.assertTrue(result['retry'])
        self.assertFalse(result['accepted'])
        self.assertEqual(frappe.local.response['http_status_code'],503)
        orders.store_payload.assert_not_called()

    def test_webhook_commits_inside_named_lock(self):
        api,frappe,orders=self.webhook(automatic=1)
        common=sys.modules[PACKAGE+'.common']
        @contextlib.contextmanager
        def lock(key):
            yield
            frappe.db.commit.assert_called_once()
        common.lock=lock
        api.webhook()

    def test_webhook_prepares_transaction_before_acquiring_source_lock(self):
        api,frappe,orders=self.webhook(automatic=1)
        events=[]
        api.start_operation.side_effect=lambda:events.append('start')
        common=sys.modules[PACKAGE+'.common']
        @contextlib.contextmanager
        def lock(key):
            events.append('lock');yield;events.append('unlock')
        common.lock=lock
        orders.store_payload.side_effect=lambda payload:(events.append('store') or types.SimpleNamespace(woo_order_id=123),True)
        frappe.db.commit.side_effect=lambda:events.append('commit')
        api.webhook()
        self.assertEqual(events,['start','lock','store','commit','unlock'])

    def test_ignore_commits_inside_named_lock(self):
        with adapter('api') as (api,frappe,common,orders):
            row=types.SimpleNamespace(sales_order=None,save=Mock())
            frappe.get_doc.return_value=row
            @contextlib.contextmanager
            def lock(key):
                yield
                frappe.db.commit.assert_called_once()
            common.lock=lock
            api.ignore_order('123','Explicit demo exclusion')

    def test_retry_does_not_reset_corrupt_record_to_pending(self):
        with adapter('api') as (api,frappe,common,orders):
            row=types.SimpleNamespace(payload='{bad',status='Needs Review',save=Mock())
            frappe.get_doc.return_value=row
            with self.assertRaises(ValueError):api.retry_order('123')
            row.save.assert_not_called()
