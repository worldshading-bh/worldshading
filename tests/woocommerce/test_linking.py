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
        self.f.get_list = Mock(return_value=[])
        self.m.persist=Mock()
        self.f.db.exists.return_value = False
        self.targets = lambda *args, **kwargs: self.m.product_targets(*args,source_host='shop.example.com',**kwargs)

    def sku_catalog(self, rows):
        previous = self.client.get.side_effect
        self.client.get.side_effect = lambda endpoint,*args: rows if endpoint=='products' else previous(endpoint,*args)

    def test_find_variation_by_own_sku_fills_ids_without_writes(self):
        self.sku_catalog([dict(self.variation,type='variation',parent_id=33166)])
        result = self.m.find_by_sku('DCPT0003')
        self.assertEqual((result['targets'][0]['product_id'],result['targets'][0]['variation_id']),(33166,33168))
        self.assertEqual(result['source_host'],'shop.example.com')
        self.assertEqual(self.client.get.call_args_list[0][0][1]['context'],'edit')
        self.item.save.assert_not_called()
        self.f.db.commit.assert_not_called()

    def test_find_simple_by_sku_and_reject_parent_sku(self):
        self.parent.update(type='simple',sku='PARENT')
        self.sku_catalog([self.parent])
        self.assertEqual(self.m.find_by_sku('PARENT')['targets'][0]['variation_id'],0)
        self.parent['type']='variable'
        with self.assertRaisesRegex(ValueError,'variation'): self.m.find_by_sku('PARENT')

    def test_sku_lookup_fails_closed_on_missing_duplicate_or_incomplete_results(self):
        for rows in [[],[dict(self.variation,type='variation',parent_id=33166)]*2,[dict(self.variation)]*100]:
            self.sku_catalog(rows)
            with self.assertRaises(ValueError): self.m.find_by_sku('DCPT0003')
        self.item.save.assert_not_called()

    def test_sku_lookup_rejects_wrong_case_and_changed_canonical_sku(self):
        self.sku_catalog([dict(self.variation,type='variation',parent_id=33166)])
        with self.assertRaises(ValueError): self.m.find_by_sku('dcpt0003')
        self.variation['sku']=''
        with self.assertRaisesRegex(ValueError,'SKU'): self.m.find_by_sku('DCPT0003')

    def test_exact_sku_preselects_eligible_item_but_never_saves(self):
        self.sku_catalog([dict(self.variation,type='variation',parent_id=33166)])
        self.item['name']=self.item['item_code']='DCPT0003'
        self.f.get_list.return_value=[Doc(name='DCPT0003',item_code='DCPT0003')]
        result=self.m.match_item(33166,33168,'shop.example.com')
        self.assertEqual(result['item_code'],'DCPT0003')
        self.item.save.assert_not_called()
        self.client.put.assert_not_called()

    def test_inherited_sku_does_not_match_parent_item_code(self):
        self.parent['sku']='DCPT0003';self.variation['sku']=''
        result=self.m.match_item(33166,33168,'shop.example.com')
        self.assertFalse(result.get('item_code'))
        self.assertIn('own SKU',result['reason'])
        self.f.get_list.assert_not_called()
        # Woo v3's variation response can ignore edit context and inherit SKU.
        self.variation['sku']='DCPT0003'
        result=self.m.match_item(33166,33168,'shop.example.com')
        self.assertFalse(result.get('item_code'))
        self.f.get_list.assert_not_called()
        target=self.targets(33166)['targets'][0]
        self.assertTrue(target['sku_inherited'])

    def test_auto_match_refuses_conflicting_item_links_and_casefold_matches(self):
        self.sku_catalog([dict(self.variation,type='variation',parent_id=33166)])
        self.f.get_list.return_value=[Doc(name='dcpt0003',item_code='dcpt0003')]
        self.assertFalse(self.m.match_item(33166,33168,'shop.example.com').get('item_code'))
        self.f.get_list.return_value=[Doc(name='DCPT0003',item_code='DCPT0003')]
        self.f.db.exists.return_value=True
        self.assertFalse(self.m.match_item(33166,33168,'shop.example.com').get('item_code'))

    def test_existing_target_is_never_reassigned_by_sku(self):
        self.f.db.get_value.return_value=Doc(name='existing',parent='OTHER',parenttype='Item',parentfield='ws_woocommerce_links')
        result=self.m.match_item(33166,33168,'shop.example.com')
        self.assertFalse(result.get('item_code'))
        self.client.get.assert_not_called()

    def test_sku_methods_require_manager_and_reject_wrong_source(self):
        self.c.manager_only.side_effect=PermissionError('Denied')
        with self.assertRaises(PermissionError):self.m.find_by_sku('DCPT0003')
        with self.assertRaises(PermissionError):self.m.match_item(33166,33168,'shop.example.com')
        self.c.manager_only.side_effect=None
        with self.assertRaises(ValueError):self.m.match_item(33166,33168,'evil.example.com')
        self.client.get.assert_not_called()

    def test_sku_lookup_rejects_invalid_input_and_malformed_identity(self):
        for sku in ['',None,' '*4,'x'*141]:
            with self.assertRaises(ValueError):self.m.find_by_sku(sku)
        self.client.get.assert_not_called()
        self.sku_catalog([dict(self.variation,type='variation',parent_id=0)])
        with self.assertRaises(ValueError):self.m.find_by_sku('DCPT0003')

    def test_matching_rechecks_current_item_eligibility_and_permissions(self):
        self.sku_catalog([dict(self.variation,type='variation',parent_id=33166)])
        self.f.get_list.return_value=[Doc(name='DCPT0003',item_code='DCPT0003')]
        self.item['disabled']=1
        with self.assertRaises(ValueError):self.m.match_item(33166,33168,'shop.example.com')
        self.item['disabled']=0
        self.item.check_permission.side_effect=PermissionError('Denied')
        with self.assertRaises(PermissionError):self.m.match_item(33166,33168,'shop.example.com')
        self.item.save.assert_not_called()

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

    def test_target_list_marks_inherited_sku_without_breaking_manual_linking(self):
        self.parent['sku']='PARENT-SKU';self.variation['sku']=''
        row=self.targets('33166')['targets'][0]
        self.assertTrue(row['sku_inherited'])
        self.assertEqual(row['sku'],'PARENT-SKU')
        self.assertTrue(row['linkable'])
        self.assertEqual(self.client.get.call_args[0][1]['context'],'edit')

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
        self.m.persist.assert_called_once()
        self.client.put.assert_not_called()
        self.f.db.commit.assert_called_once()
        self.c.manager_only.assert_called_once_with(write=True)
        self.assertFalse(self.item.flags.get('ws_woo_link_only'))

    def test_save_returns_current_timestamp_for_next_inactive_edit(self):
        self.m.persist.side_effect = lambda *args: self.item.set('modified','2026-11-01 12:01:00')
        result = self.save()
        self.assertEqual(result['modified'],'2026-11-01 12:01:00')
        self.f.db.get_value.return_value = Doc(self.item.ws_woocommerce_links[0],name='link1',parent='TENT3',parenttype='Item',parentfield='ws_woocommerce_links')
        self.item.ws_woocommerce_links[0].set('name','link1')
        self.save(sale_uom='Set',expected_modified=result['modified'])
        self.assertEqual(self.item.ws_woocommerce_links[0].sale_uom,'Set')

    def test_persistence_failure_is_not_committed(self):
        self.m.persist.side_effect = ValueError('save failed')
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
        self.m.persist.assert_called_once()

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
