import json
import unittest
from unittest.mock import Mock
from adapter_support import adapter
from test_item_links import Doc
from worldshading.integration.woocommerce import domain as d


class StockIdentityTests(unittest.TestCase):
    def setUp(self):
        self.maps=[dict(product_id=10,variation_id=11,item_code='A',sku='S'),
                   dict(product_id=10,variation_id=12,item_code='B',sku='S')]

    def test_mixed_order_holds_only_mapped_items_even_with_sku_conflict(self):
        payload={'line_items':[dict(product_id=10,variation_id=11,sku='CHANGED'),dict(product_id=99)]}
        self.assertEqual(d.affected_stock_items(payload,self.maps),{'A'})

    def test_variations_do_not_implicate_siblings_with_same_sku(self):
        self.assertEqual(d.affected_stock_items({'line_items':[dict(product_id=10,variation_id=12)]},self.maps),{'B'})

    def test_all_duplicate_target_candidates_are_held(self):
        self.maps.append(dict(product_id=10,variation_id=11,item_code='C'))
        self.assertEqual(d.affected_stock_items({'line_items':[dict(product_id=10,variation_id=11)]},self.maps),{'A','C'})

    def test_malformed_or_deleted_identity_fails_closed(self):
        for payload in [None,{}, {'line_items':[]},{'line_items':[None]},
                        {'line_items':[{'product_id':0}]},{'line_items':[{'product_id':10,'variation_id':-1}]},
                        {'line_items':[{'product_id':'bad'}]}]:
            with self.assertRaises(ValueError):d.affected_stock_items(payload,self.maps)

    def test_valid_unmapped_order_does_not_hold_unrelated_catalogue(self):
        self.assertEqual(d.affected_stock_items({'line_items':[dict(product_id=999,variation_id=0)]},self.maps),set())

    def test_full_mapping_review_reports_all_bad_lines(self):
        lines=[dict(product_id=99,name='Net'),dict(product_id=98,name='Fabric'),
               dict(product_id=10,variation_id=11,sku='CHANGED',name='Link')]
        with self.assertRaises(ValueError) as error:d.match_order_lines(lines,self.maps)
        for name in ['Net','Fabric','Link']:self.assertIn(name,str(error.exception))


class StockHoldReaderTests(unittest.TestCase):
    def test_reader_includes_disabled_links_and_old_sales_order_items(self):
        with adapter('stock_holds') as (module,frappe,common,orders):
            def rows(doctype,**kwargs):
                if doctype==common.ORDER:return [Doc(name='123',payload=json.dumps({'line_items':[dict(product_id=10)]}),sales_order='SO-1')]
                if doctype=='WS WooCommerce Item Link':
                    self.assertNotIn('enabled',kwargs['filters'])
                    return [Doc(product_id=10,variation_id=0,parent='A')]
                if doctype=='Sales Order Item':return [Doc(item_code='OLD')]
                raise AssertionError(doctype)
            frappe.get_all=Mock(side_effect=rows)
            holds=module.stock_holds()
            self.assertEqual(module.stock_orders('A',holds),['123'])
            self.assertEqual(module.stock_orders('OLD',holds),['123'])
            self.assertEqual(module.stock_orders('UNRELATED',holds),[])

    def test_unreadable_order_holds_all_stock_and_identifies_order(self):
        with adapter('stock_holds') as (module,frappe,common,orders):
            frappe.get_all=Mock(side_effect=lambda doctype,**kwargs:[Doc(name='123',payload='{bad',sales_order=None)] if doctype==common.ORDER else [])
            self.assertEqual(module.stock_orders('ANY',module.stock_holds()),['123'])

    def test_missing_old_sales_order_items_fails_closed(self):
        with adapter('stock_holds') as (module,frappe,common,orders):
            frappe.get_all=Mock(side_effect=lambda doctype,**kwargs:[Doc(name='123',payload=json.dumps({'line_items':[dict(product_id=99)]}),sales_order='DELETED')] if doctype==common.ORDER else [])
            self.assertEqual(module.stock_orders('ANY',module.stock_holds()),['123'])
