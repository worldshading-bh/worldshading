import types
import unittest
from unittest.mock import Mock
from adapter_support import adapter
from test_item_links import Doc


class Item(Doc):
    __setattr__ = dict.__setitem__
    def append(self, field, values):
        row = Doc(values)
        self[field].append(row)
        return row


class LinkingTests(unittest.TestCase):
    def setUp(self):
        self.context = adapter('linking')
        self.m, self.f, self.c, unused = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.c.settings.return_value = Doc(store_url='https://shop.example.com')
        self.client = Mock()
        self.m.from_settings = Mock(return_value=self.client)
        self.parent = dict(id=33166, type='variable', name='Pagoda Tent')
        self.variation = dict(id=33168, sku='DCPT0003', attributes=[dict(name='Size', option='3m')])
        def get(endpoint, *args):
            return [self.variation] if endpoint.endswith('/variations') else self.variation if '/variations/' in endpoint else self.parent
        self.client.get.side_effect = get
        self.f.db.get_value.return_value = None
        self.item = Item(name='TENT3', item_name='Tent 3m', stock_uom='Nos', disabled=0, has_variants=0,
                         is_sales_item=1, uoms=[Doc(uom='Set', conversion_factor=2)],
                         ws_woocommerce_links=[], modified='2026-11-01 12:00:00',
                         flags=Doc(),
                         check_permission=Mock(), save=Mock())
        self.f.get_doc.return_value = self.item
        self.targets = lambda *args, **kwargs: self.m.product_targets(*args,source_host='shop.example.com',**kwargs)

    def save(self, **args):
        values = dict(item_code='TENT3', sale_uom='Nos', product_id=33166, variation_id=33168,
                      source_host='shop.example.com', expected_sku='DCPT0003', expected_modified='2026-11-01 12:00:00')
        values.update(args)
        return self.m.save_link(**values)

    def test_denied_user_cannot_read_or_save_anything(self):
        self.c.manager_only.side_effect = PermissionError('Denied')
        for fn, args in [(self.targets, (33166,)), (self.m.item_uoms, ('TENT3',)),
                         (self.m.search_items, ('Item', 'tent', 'name', 0, 20))]:
            with self.assertRaises(PermissionError): fn(*args)
        with self.assertRaises(PermissionError): self.save()
        self.m.from_settings.assert_not_called()
        self.f.get_doc.assert_not_called()

    def test_target_list_uses_pinned_store_and_remote_identity_without_writes(self):
        result = self.targets('33166')
        self.assertEqual(result['targets'][0]['variation_id'], 33168)
        self.assertEqual(result['targets'][0]['sku'], 'DCPT0003')
        self.client.put.assert_not_called()
        self.f.db.commit.assert_not_called()
        self.c.manager_only.assert_called_once_with()

    def test_direct_variation_link_does_not_scan_other_variation_pages(self):
        result = self.targets('33166',variation_id='33168')
        self.assertEqual([r['variation_id'] for r in result['targets']],[33168])
        self.assertFalse(result['has_more'])
        self.assertEqual(self.client.get.call_count,2)

    def test_other_store_cannot_supply_a_linking_target(self):
        with self.assertRaisesRegex(ValueError,'store'):
            self.m.product_targets(33166,source_host='different.example.com')
        with self.assertRaisesRegex(ValueError,'store'):
            self.save(source_host='different.example.com')
        self.client.get.assert_not_called()
        self.item.save.assert_not_called()

    def test_invalid_ids_do_not_reach_woo(self):
        for value in ['0', '-1', '3.5', '../1', '1?secret=x']:
            with self.assertRaises(ValueError): self.targets(value)
        self.client.get.assert_not_called()

    def test_item_uoms_use_native_conversions_and_check_item_permission(self):
        result = self.m.item_uoms('TENT3')
        self.assertEqual(result['uoms'], [dict(uom='Nos', conversion_factor=1.0), dict(uom='Set', conversion_factor=2.0)])
        self.item.check_permission.assert_called_once_with('read')
        self.assertEqual(result['modified'], self.item.modified)

    def test_disabled_or_template_item_cannot_be_linked(self):
        for field in ['disabled', 'has_variants']:
            self.item[field] = 1
            with self.assertRaises(ValueError): self.m.item_uoms('TENT3')
            self.item[field] = 0
        self.item['is_sales_item'] = 0
        with self.assertRaises(ValueError): self.save()
        self.item.save.assert_not_called()

    def test_new_link_is_inactive_and_does_not_publish_anything(self):
        def save_without_publishing():
            self.assertTrue(self.item.flags.get('ws_woo_link_only'))
        self.item.save.side_effect = save_without_publishing
        result = self.save()
        row = self.item.ws_woocommerce_links[0]
        self.assertEqual((row['product_id'], row['variation_id'], row['sku'], row['sale_uom']), (33166,33168,'DCPT0003','Nos'))
        self.assertEqual((row['enabled'],row['sync_stock'],row['sync_price'],row['clear_sale_price']), (0,1,0,0))
        self.assertFalse(result['enabled'])
        self.item.check_permission.assert_called_with('write')
        self.item.save.assert_called_once_with()
        self.client.put.assert_not_called()
        self.f.db.commit.assert_called_once()
        self.c.manager_only.assert_called_once_with(write=True)
        self.assertFalse(self.item.flags.get('ws_woo_link_only'))

    def test_save_returns_current_timestamp_for_next_inactive_edit(self):
        self.item.save.side_effect = lambda: self.item.set('modified','2026-11-01 12:01:00')
        result = self.save()
        self.assertEqual(result['modified'],'2026-11-01 12:01:00')
        self.f.db.get_value.return_value = Doc(self.item.ws_woocommerce_links[0],name='link1',parent='TENT3',parenttype='Item',parentfield='ws_woocommerce_links')
        self.item.ws_woocommerce_links[0].set('name','link1')
        self.save(sale_uom='Set',expected_modified=result['modified'])
        self.assertEqual(self.item.ws_woocommerce_links[0].sale_uom,'Set')

    def test_link_only_flag_restored_after_save_failure(self):
        self.item.save.side_effect = ValueError('save failed')
        with self.assertRaisesRegex(ValueError,'save failed'): self.save()
        self.assertFalse(self.item.flags.get('ws_woo_link_only'))
        self.f.db.commit.assert_not_called()

    def test_stale_item_or_unknown_uom_does_not_save(self):
        with self.assertRaisesRegex(ValueError, 'changed'): self.save(expected_modified='2026-11-01 11:00:00')
        with self.assertRaisesRegex(ValueError, 'UOM'): self.save(sale_uom='Meter')
        self.item.save.assert_not_called()

    def test_changed_or_forged_woo_sku_does_not_save(self):
        with self.assertRaisesRegex(ValueError, 'SKU'): self.save(expected_sku='WRONG')
        self.variation['sku']=''
        with self.assertRaises(ValueError): self.save()
        self.item.save.assert_not_called()

    def test_target_owned_by_other_item_cannot_be_reassigned(self):
        self.f.db.get_value.return_value = Doc(name='old', parent='OTHER', parenttype='Item', parentfield='ws_woocommerce_links')
        with self.assertRaisesRegex(ValueError, 'already linked'): self.save()
        self.item.save.assert_not_called()

    def existing(self, enabled=0, uom='Nos'):
        row = Doc(name='link1', product_id=33166, variation_id=33168, sku='DCPT0003', sale_uom=uom,
                  enabled=enabled, sync_stock=1, sync_price=0, clear_sale_price=0)
        self.item.ws_woocommerce_links.append(row)
        self.f.db.get_value.return_value = Doc(row, parent='TENT3', parenttype='Item', parentfield='ws_woocommerce_links')
        return row

    def test_retry_of_same_link_is_noop_even_with_old_timestamp(self):
        self.existing()
        result = self.save(expected_modified='old')
        self.assertTrue(result['unchanged'])
        self.item.save.assert_not_called()

    def test_enabled_link_cannot_be_edited(self):
        self.existing(enabled=1)
        with self.assertRaisesRegex(ValueError, 'Disable'): self.save(sale_uom='Set')
        self.item.save.assert_not_called()

    def test_inactive_link_can_update_uom_without_changing_sync_switches(self):
        row = self.existing()
        self.save(sale_uom='Set')
        self.assertEqual(row['sale_uom'],'Set')
        self.assertEqual((row['enabled'],row['sync_price']),(0,0))
        self.item.save.assert_called_once_with()

    def test_search_honours_item_permissions_with_bounded_results(self):
        self.f.get_list = Mock(return_value=[Doc(name='TENT3',item_name='Tent 3m')])
        self.assertEqual(self.m.search_items('Item','tent','name',0,1000),[['TENT3','Tent 3m']])
        self.assertEqual(self.f.get_list.call_args[1]['limit_page_length'],20)
        self.f.get_all.assert_not_called()


if __name__=='__main__': unittest.main()


class LinkingUpgradeTests(unittest.TestCase):
    def test_page_upgrade_has_no_schema_or_business_data_writes(self):
        with adapter('install') as (m,f,c,unused):
            f.conf=Doc(host_name='https://demo.worldshading.com')
            f.db.exists.return_value=True
            f.db.get_value.side_effect=lambda dt,*args,**kwargs:Doc(module='Worldshading',custom=0) if dt=='DocType' else None
            f.reload_doc=Mock();f.clear_cache=Mock()
            m.upgrade_linking()
            f.reload_doc.assert_called_once_with('worldshading','page','ws_woocommerce_link',force=True)
            f.db.set_value.assert_not_called()
            m.create_custom_fields.assert_not_called()
