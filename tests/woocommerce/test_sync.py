import types
import unittest
from unittest.mock import Mock
from adapter_support import adapter
from test_item_links import Doc


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.context = adapter('sync')
        self.sync, self.frappe, self.common, self.orders = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.config = types.SimpleNamespace(store_url='https://testshop.worldshading.com',currency='BHD')
        self.common.settings.return_value = self.config
        self.sync.from_settings = Mock()
        self.sync.poll_orders = Mock(return_value=2)
        self.maps = [{'name': 'one', 'item_code': 'A4003'}, {'name': 'two', 'item_code': 'B7003'}]
        self.common.mappings.return_value = self.maps
        self.holds = {'items': {}, 'all': [], 'review_required': 0}
        self.sync.stock_holds = Mock(side_effect=lambda: self.holds)
        self.sync.stock_warehouses = Mock(return_value=['Warehouse'])
        self.sync.check_price_configuration = Mock()

    def test_selected_mapping_does_not_export_other_products(self):
        self.sync.sync_product = Mock(return_value={'status': 'Unchanged'})
        result = self.sync.run_cycle(mapping_name='one')
        self.assertEqual(len(result['products']), 1)
        self.assertEqual(self.sync.sync_product.call_args[0][0]['name'], 'one')
        self.assertEqual(self.sync.sync_product.call_count, 1)
        self.sync.poll_orders.assert_called_once()

    def test_unknown_or_disabled_mapping_stops_before_imports_and_exports(self):
        self.sync.sync_product = Mock()
        with self.assertRaises(ValueError): self.sync.run_cycle(mapping_name='disabled')
        self.sync.poll_orders.assert_not_called()
        self.sync.sync_product.assert_not_called()

    def test_import_only_never_exports_products(self):
        self.sync.sync_product = Mock()
        result = self.sync.run_cycle(export_products=False)
        self.assertEqual(result['orders'], 2)
        self.assertEqual(result['products'], [])
        self.sync.sync_product.assert_not_called()

    def test_import_summary_keeps_unresolved_orders_visible(self):
        self.holds['review_required'] = 1
        result = self.sync.run_cycle(export_products=False)
        self.assertEqual(result['review_required'], 1)
        values = self.frappe.db.set_value.call_args[0][2]
        self.assertIn('Orders requiring review: 1', values['last_result'])

    def test_order_poll_failure_prevents_any_export(self):
        self.sync.poll_orders.side_effect = ValueError('Unavailable orders')
        self.sync.sync_product = Mock()
        with self.assertRaises(ValueError): self.sync.run_cycle(mapping_name='one')
        self.sync.sync_product.assert_not_called()

    def test_unrelated_order_does_not_stop_selected_export(self):
        self.holds.update(review_required=1,items={'B7003':['123']})
        self.sync.sync_product = Mock(return_value={'status':'Unchanged'})
        result = self.sync.run_cycle(mapping_name='one')
        self.assertEqual(result['review_required'], 1)
        self.assertEqual(len(result['products']), 1)
        self.sync.sync_product.assert_called_once()

    def preview(self, current, blocked=0):
        self.assertTrue(hasattr(self.sync, 'preview_product'), 'Read-only preview is missing')
        mapping = dict(name='one', item_code='A4003', product_id=10, variation_id=0,
                       sku='SKU-A', enabled=1, sync_stock=1)
        client = Mock()
        client.get.return_value = current
        if blocked:self.holds.update(review_required=blocked,items={'A4003':['123']})
        self.sync.product_payload = Mock(return_value={'regular_price': '4.125', 'stock_quantity': 8})
        result = self.sync.preview_product(mapping, self.config, client)
        return result, client

    def test_preview_reports_difference_without_writes_or_imports(self):
        result, client = self.preview({'sku': 'SKU-A', 'type': 'simple', 'regular_price': '4.000', 'stock_quantity': 8})
        self.assertEqual(result['changed_fields'], ['regular_price'])
        self.assertEqual(result['expected']['regular_price'], '4.125')
        client.put.assert_not_called()
        self.sync.poll_orders.assert_not_called()
        self.frappe.db.set_value.assert_not_called()
        self.frappe.db.commit.assert_not_called()
        self.common.log.assert_not_called()

    def test_preview_links_to_store_permalink_and_rejects_external_or_unsafe_urls(self):
        base=dict(sku='SKU-A',type='simple',regular_price='4.125',stock_quantity=8)
        url='https://testshop.worldshading.com/product/quick-link/?attribute_pa_size=8mm'
        result,client=self.preview(dict(base,permalink=url))
        self.assertEqual(result['product_url'],url)
        for unsafe in ['javascript:alert(1)','https://other.example/product/','https://testshop.worldshading.com@other.example/']:
            result,client=self.preview(dict(base,permalink=unsafe))
            self.assertEqual(result['product_url'],'https://testshop.worldshading.com/?p=10')

    def test_preview_reports_stock_block_without_hiding_expected_values(self):
        result, client = self.preview({'sku': 'SKU-A', 'type': 'simple', 'regular_price': '4.125', 'stock_quantity': 8}, blocked=1)
        self.assertEqual(result['stock_blocked'], 1)
        self.assertEqual(result['expected']['stock_quantity'], 8)
        self.assertEqual(result['stock_orders'], ['123'])
        client.put.assert_not_called()

    def test_unrelated_preview_is_not_blocked(self):
        self.holds.update(review_required=1,items={'OTHER':['123']})
        result,client=self.preview({'sku':'SKU-A','type':'simple','regular_price':'4.125','stock_quantity':8})
        self.assertEqual(result['stock_blocked'],0)

    def test_affected_item_exports_price_without_any_stock_fields(self):
        self.holds.update(review_required=1,items={'A4003':['123']})
        mapping=dict(name='one',item_code='A4003',product_id=10,variation_id=0,sku='SKU-A',sync_stock=1,sync_price=1)
        self.sync.product_payload=Mock(return_value={'regular_price':'4.125'})
        client=Mock()
        client.get.side_effect=[dict(sku='SKU-A',type='simple',regular_price='4.000'),dict(sku='SKU-A',type='simple',regular_price='4.125')]
        result=self.sync.sync_product(mapping,self.config,client)
        self.assertEqual(result['status'],'Updated')
        self.assertEqual(result['stock_orders'],['123'])
        client.put.assert_called_once_with('products/10',{'regular_price':'4.125'})
        self.assertFalse(self.sync.product_payload.call_args[0][0]['sync_stock'])

    def test_stock_only_held_item_never_calls_woo_or_computes_payload(self):
        self.holds.update(review_required=1,items={'A4003':['123']})
        mapping=dict(name='one',item_code='A4003',product_id=10,sync_stock=1,sync_price=0)
        self.sync.product_payload=Mock()
        client=Mock()
        result=self.sync.sync_product(mapping,self.config,client)
        self.assertEqual(result['status'],'Stock Held')
        client.put.assert_not_called()
        self.sync.product_payload.assert_not_called()

    def test_global_unreadable_order_hold_still_exports_price(self):
        self.holds.update(review_required=1,all=['CORRUPT'])
        mapping=dict(name='one',item_code='A4003',product_id=10,variation_id=0,sku='SKU-A',sync_stock=1,sync_price=1)
        self.sync.product_payload=Mock(return_value={'regular_price':'4.125'})
        client=Mock()
        client.get.side_effect=[dict(sku='SKU-A',type='simple',regular_price='4.000'),dict(sku='SKU-A',type='simple',regular_price='4.125')]
        result=self.sync.sync_product(mapping,self.config,client)
        self.assertEqual(result['status'],'Updated')
        self.assertEqual(result['stock_orders'],['CORRUPT'])
        client.put.assert_called_once_with('products/10',{'regular_price':'4.125'})

    def test_preview_rejects_wrong_sku_and_variable_parent(self):
        for current in [{'sku': 'OTHER', 'type': 'simple'}, {'sku': 'SKU-A', 'type': 'variable'}]:
            with self.assertRaises(ValueError): self.preview(current)

    def test_success_failure_and_no_change_never_save_item_or_child(self):
        item=Doc(name='A4003',stock_uom='Each',is_stock_item=1,is_sales_item=1,disabled=0,has_variants=0,uoms=[])
        item['save']=Mock()
        mapping=Doc(name='one',item_code='A4003',enabled=1,product_id=10,variation_id=0,
                    sku='SKU-A',sale_uom='Each',sync_stock=1,sync_price=1,clear_sale_price=0)
        self.config=types.SimpleNamespace(price_list='Online Price',currency='BHD',warehouse='Warehouse',safety_stock=0)
        self.frappe.get_doc.return_value=item
        self.frappe.get_all=Mock(side_effect=lambda doctype,**kw:[Doc(actual_qty=10)] if doctype=='Bin' else [Doc(currency='BHD',uom='Each',price_list_rate=4.125,valid_from=None,valid_upto=None)])
        self.frappe.db.get_value.return_value={'actual_qty':10}
        self.frappe.db.sql.return_value=[[2]]
        current=dict(sku='SKU-A',type='simple',regular_price='4.125',manage_stock=True,stock_quantity=8,stock_status='instock',backorders='no')
        for outcome in ['Updated','Unchanged','Failed']:
            client=Mock()
            if outcome=='Updated':client.get.side_effect=[dict(current,regular_price='4.000'),current]
            elif outcome=='Failed':client.get.side_effect=ValueError('Store unavailable')
            else:client.get.return_value=current
            result=self.sync.sync_product(mapping,self.config,client)
            self.assertEqual(result['status'],outcome)
            self.frappe.db.set_value.assert_not_called()
            item.save.assert_not_called()
            self.assertEqual(self.common.log.call_args[1]['item_link'],'one')

    def test_combined_stock_queries_only_selected_warehouses_and_pools_drafts(self):
        self.sync.stock_warehouses.return_value=['MAIN','SECOND']
        item=Doc(name='A',stock_uom='Each',is_stock_item=1,is_sales_item=1,disabled=0,has_variants=0,uoms=[])
        self.frappe.get_doc.return_value=item
        self.frappe.get_all=Mock(return_value=[Doc(actual_qty=0),Doc(actual_qty=10)])
        self.frappe.db.sql.return_value=[[6]]
        mapping=dict(name='one',item_code='A',product_id=10,sku='A',sale_uom='Each',sync_stock=1,sync_price=0)
        payload=self.sync.product_payload(mapping,Doc(safety_stock=1))
        self.assertEqual(payload['stock_quantity'],3)
        self.assertEqual(self.frappe.get_all.call_args[1]['filters']['warehouse'],['in',['MAIN','SECOND']])
        self.assertEqual(self.frappe.db.sql.call_args[0][1],['A','MAIN','SECOND'])

    def test_nonstock_item_is_made_purchasable_without_quantity(self):
        self.frappe.get_doc.return_value=Doc(name='SERVICE',stock_uom='Each',is_stock_item=0,is_sales_item=1,disabled=0,has_variants=0,uoms=[])
        mapping=dict(name='one',item_code='SERVICE',product_id=10,sku='SERVICE',sale_uom='Each',sync_stock=1,sync_price=0)
        self.assertEqual(self.sync.product_payload(mapping,Doc()),dict(manage_stock=False,stock_status='instock',backorders='no'))

    def test_invalid_price_basis_prevents_writes(self):
        self.sync.check_price_configuration.side_effect=ValueError('Prices must be entered excluding VAT')
        self.sync.product_payload=Mock(return_value={'regular_price':'1.000'})
        mapping=dict(name='one',item_code='A',product_id=10,sku='A',sync_stock=0,sync_price=1)
        client=Mock()
        result=self.sync.sync_product(mapping,self.config,client)
        self.assertEqual(result['status'],'Failed')
        self.sync.check_price_configuration.assert_called_once_with(client,'BHD')
        client.put.assert_not_called()
