import json
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
import requests
try:
    from worldshading.integration.woocommerce.client import Client, APIError
except ImportError:
    Client = None


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Client, 'REST client is not implemented')
        self.transport = Mock()
        self.client = Client('https://testshop.worldshading.com', 'ck_example', 'cs_private',
                             'gate', 'gate_private', session=self.transport)

    def response(self, status=200, body=None):
        r = requests.Response(); r.status_code = status
        r._content = json.dumps(body if body is not None else [{'id': 10}]).encode()
        self.transport.request.return_value = r
        return r

    def test_oauth_signature_never_puts_secrets_in_url(self):
        self.response(); result = self.client.get('products', {'sku': 'A B/C'})
        self.assertEqual(result, [{'id': 10}])
        args, kw = self.transport.request.call_args
        url = args[1]
        self.assertNotIn('cs_private', url); self.assertNotIn('gate_private', url)
        q = parse_qs(urlsplit(url).query)
        self.assertEqual(q['sku'], ['A B/C']); self.assertEqual(q['oauth_signature_method'], ['HMAC-SHA256'])
        self.assertTrue(q['oauth_signature'][0]); self.assertEqual(kw['auth'], ('gate', 'gate_private'))
        self.assertFalse(kw['allow_redirects'])

    def test_put_uses_json_body(self):
        self.response(body={'id': 10, 'stock_quantity': 7})
        self.assertEqual(self.client.put('products/10', {'stock_quantity': 7})['stock_quantity'], 7)
        self.assertEqual(self.transport.request.call_args[1]['json'], {'stock_quantity': 7})

    def test_auth_failure_is_sanitized(self):
        self.response(401, {'message': 'secret cs_private'})
        with self.assertRaises(APIError) as e: self.client.get('products')
        self.assertIn('401', str(e.exception)); self.assertNotIn('cs_private', str(e.exception))

    def test_redirect_is_rejected(self):
        self.response(302)
        with self.assertRaises(APIError): self.client.get('products')

    def test_timeout_has_no_secret_or_url(self):
        self.transport.request.side_effect = requests.Timeout('cs_private leaked in underlying exception')
        with self.assertRaises(APIError) as e: self.client.get('products')
        self.assertNotIn('cs_private', str(e.exception)); self.assertEqual(self.transport.request.call_count, 1)

    def test_endpoint_escape_rejected(self):
        for path in ['../users', 'https://evil.test', '/orders', 'products?x=y']:
            with self.assertRaises(ValueError): self.client.get(path)

    def test_non_json_rejected(self):
        r = self.response(); r._content = b'<html>proxy login</html>'
        with self.assertRaises(APIError): self.client.get('products')

    def test_connection_checks_products_orders_and_currency_without_writes(self):
        from worldshading.integration.woocommerce import client
        self.assertTrue(hasattr(client, 'check_connection'), 'Connection check is missing')
        self.transport.request.side_effect = [self.response(body={'value': 'BHD'}),
                                             self.response(body=[{'id': 10}]),
                                             self.response(body=[])]
        result = client.check_connection(self.client, 'BHD')
        self.assertTrue(result['connected'])
        self.assertTrue(result['orders_readable'])
        self.assertFalse(result['write_access_verified'])
        self.assertEqual(result['currency'], 'BHD')
        self.assertEqual([call[0][0] for call in self.transport.request.call_args_list], ['GET'] * 3)

    def test_connection_rejects_currency_and_malformed_access_results(self):
        from worldshading.integration.woocommerce import client
        self.assertTrue(hasattr(client, 'check_connection'), 'Connection check is missing')
        for bodies in [[{'value': 'USD'}], [{'value': 'BHD'}, {'message': 'not products'}],
                       [{'value': 'BHD'}, [], {'message': 'not orders'}]]:
            self.transport.request.side_effect = [self.response(body=body) for body in bodies]
            with self.assertRaises(APIError): client.check_connection(self.client, 'BHD')

    def test_permission_errors_give_safe_actionable_guidance(self):
        self.response(403, {'message': 'secret cs_private'})
        with self.assertRaises(APIError) as result: self.client.get('orders')
        self.assertIn('permission', str(result.exception).lower())
        self.assertNotIn('cs_private', str(result.exception))

    def test_modified_window_rescan_recovers_shifted_page_boundary(self):
        from worldshading.integration.woocommerce import client
        self.assertTrue(hasattr(client,'stable_order_window'), 'Stable pagination not implemented')
        class ChangingStore:
            def __init__(self): self.scan=0
            def get(self, endpoint, params):
                if params['page']==1: self.scan+=1
                # First pass: row 1 leaves the result between pages, shifting row 51 backwards.
                ids=list(range(1,101)) if self.scan==1 and params['page']==1 else list(range(2,101))
                start=(params['page']-1)*50
                return [{'id':i,'date_modified_gmt':'2026-10-29T09:00:00'} for i in ids[start:start+50]]
        rows=client.stable_order_window(ChangingStore(),{'modified_after':'2026-10-29T08:00:00'})
        self.assertEqual(set(r['id'] for r in rows),set(range(1,101)))

    def test_price_export_requires_net_bhd_three_decimal_configuration(self):
        from worldshading.integration.woocommerce.client import check_price_configuration
        from unittest.mock import Mock
        for values,accepted in [(['BHD','no','3'],True),(['USD','no','3'],False),(['BHD','yes','3'],False),(['BHD','no','2'],False)]:
            store=Mock();store.get.side_effect=[{'value':value} for value in values]
            if accepted:check_price_configuration(store,'BHD')
            else:
                with self.assertRaises(APIError):check_price_configuration(store,'BHD')
