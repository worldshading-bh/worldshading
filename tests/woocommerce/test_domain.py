import base64
import hashlib
import hmac
import unittest
from decimal import Decimal

try:
    from worldshading.integration.woocommerce import domain as d
except ImportError:
    d = None


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(d, 'Connector domain module has not been implemented')

    def test_available_stock_subtracts_all_reservations_and_draft_holds(self):
        self.assertEqual(d.available_stock(100, 10, 5, 3, 2, 4, 2), 38)

    def test_negative_stock_is_zero(self):
        self.assertEqual(d.available_stock(-1), 0)

    def test_negative_reservation_cannot_create_extra_sellable_stock(self):
        self.assertEqual(d.available_stock(10,sales=-4),10)

    def test_sale_unit_rounds_down(self):
        self.assertEqual(d.available_stock('9.99', factor='2'), 4)

    def test_invalid_conversion_is_rejected(self):
        for factor in [0, -1, 'NaN', 'Infinity']:
            with self.assertRaises(ValueError):
                d.available_stock(10, factor=factor)

    def test_three_decimal_bhd_price(self):
        self.assertEqual(d.money('1.2345'), '1.235')

    def test_price_uses_sale_uom_before_stock_uom(self):
        prices = [{'price_list_rate': '2', 'uom': 'Meter'}, {'price_list_rate': '90', 'uom': 'Roll'}]
        self.assertEqual(d.choose_price(prices, 'Roll', 'Meter', 50), '90.000')

    def test_stock_uom_price_converts_to_sale_uom(self):
        self.assertEqual(d.choose_price([{'price_list_rate': '2', 'uom': 'Meter'}], 'Roll', 'Meter', 50), '100.000')

    def test_ambiguous_or_missing_prices_fail(self):
        for prices in [[], [{'price_list_rate': 1}, {'price_list_rate': 2}]]:
            with self.assertRaises(ValueError):
                d.choose_price(prices, 'Nos', 'Nos', 1)

    def test_variation_match_never_falls_back_to_parent(self):
        maps = [{'product_id': 10, 'variation_id': 0, 'item_code': 'P', 'sku': 'P'}]
        with self.assertRaises(ValueError):
            d.match_line({'product_id': 10, 'variation_id': 11, 'sku': 'P'}, maps)

    def test_sku_conflict_fails(self):
        with self.assertRaises(ValueError):
            d.match_line({'product_id': 10, 'sku': 'WRONG'}, [{'product_id': 10, 'variation_id': 0, 'sku': 'RIGHT'}])

    def test_exact_variation_match(self):
        mapping = {'product_id': 10, 'variation_id': 11, 'item_code': 'K3001', 'sku': 'K3001'}
        self.assertEqual(d.match_line({'product_id': 10, 'variation_id': 11, 'sku': 'K3001'}, [mapping]), mapping)

    def order(self):
        return {'id': 123, 'status': 'processing', 'currency': 'BHD', 'total': '21.450', 'total_tax': '1.950',
                'shipping_total': '1.000', 'shipping_tax': '0.100', 'line_items': [
                    {'id': 1, 'product_id': 10, 'quantity': 3, 'subtotal': '20.000', 'total': '18.500', 'total_tax': '1.850'}],
                'fee_lines': [], 'refunds': []}

    def test_order_preserves_discounted_net_line_and_shipping_tax(self):
        order = d.prepare_order(self.order())
        self.assertEqual(order['lines'][0]['rate'], Decimal('18.500') / Decimal(3))
        self.assertEqual(order['tax'], Decimal('1.950'))
        self.assertEqual(order['shipping'], Decimal('1.000'))

    def test_order_total_mismatch_fails(self):
        o = self.order(); o['total'] = '22.000'
        with self.assertRaises(ValueError): d.prepare_order(o)

    def test_zero_quantity_fails(self):
        o = self.order(); o['line_items'][0]['quantity'] = 0
        with self.assertRaises(ValueError): d.prepare_order(o)

    def test_other_currency_fails(self):
        o = self.order(); o['currency'] = 'USD'
        with self.assertRaises(ValueError): d.prepare_order(o)

    def test_refunds_are_review_only(self):
        o = self.order(); o['refunds'] = [{'id': 77}]
        with self.assertRaises(ValueError): d.prepare_order(o)

    def test_valid_signature_and_missing_signature(self):
        body = b'{"id":1}'
        sig = base64.b64encode(hmac.new(b'secret', body, hashlib.sha256).digest()).decode()
        self.assertTrue(d.verify_signature(body, sig, 'secret'))
        self.assertFalse(d.verify_signature(body, '', 'secret'))
        self.assertFalse(d.verify_signature(body, sig, ''))
        self.assertFalse(d.verify_signature(body+b' ', sig, 'secret'))

    def test_demo_host_guard(self):
        self.assertEqual(d.validate_store_url('https://testshop.worldshading.com/'), 'https://testshop.worldshading.com')
        for url in ['https://shop.worldshading.com', 'http://testshop.worldshading.com',
                    'https://testshop.worldshading.com.evil.test', 'https://user:pass@testshop.worldshading.com',
                    'https://testshop.worldshading.com/?secret=a', 'https://testshop.worldshading.com:8443']:
            with self.assertRaises(ValueError): d.validate_store_url(url)

    def test_fingerprint_ignores_status_but_detects_price_edit(self):
        o = self.order(); a = d.order_fingerprint(o); o['status'] = 'completed'
        self.assertEqual(a, d.order_fingerprint(o))
        o['line_items'][0]['total'] = '19'; self.assertNotEqual(a, d.order_fingerprint(o))

    def test_retry_backoff_is_bounded(self):
        self.assertEqual([d.retry_delay(i) for i in [1, 2, 3, 20]], [60, 120, 240, 3600])

    def test_customer_identity_is_normalized_and_registered_id_wins(self):
        self.assertTrue(hasattr(d,'customer_key'),'Customer identity helper is not implemented')
        guest={'id':1,'customer_id':0,'billing':{'email':' Buyer@Example.invalid '}}
        second={'id':2,'customer_id':0,'billing':{'email':'buyer@example.invalid'}}
        self.assertEqual(d.customer_key(guest, 'https://shop.example.com'),d.customer_key(second, 'https://shop.example.com'))
        guest['customer_id']=10;second['customer_id']=11
        self.assertNotEqual(d.customer_key(guest, 'https://shop.example.com'),d.customer_key(second, 'https://shop.example.com'))


if __name__ == '__main__': unittest.main()
