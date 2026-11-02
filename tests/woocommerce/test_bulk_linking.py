import unittest
from unittest.mock import Mock
from adapter_support import adapter
from test_linking import Item
from test_item_links import Doc


class BulkLinkTests(unittest.TestCase):
    def setUp(self):
        self.ctx=adapter('bulk_linking')
        self.m,self.f,self.c,_=self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__,None,None,None)
        self.item=Item(name='CODE',item_code='CODE',stock_uom='Each',sales_uom='',uoms=[],disabled=0,has_variants=0,is_sales_item=1,
                       modified='2026-11-01 12:00:00',ws_woocommerce_links=[],flags=Doc(),check_permission=Mock(),save=Mock())
        self.f.get_doc.return_value=self.item
        self.f.get_list=Mock(return_value=[Doc(name='CODE',item_code='CODE')])
        self.f.db.exists.return_value=False
        self.f.db.get_value.return_value=None
        self.config=Doc(store_url='https://shop.example.com',enabled=1,automatic_sync=0,auto_link_skus=0)
        self.c.settings.return_value=self.config
        self.client=Mock()
        self.m.from_settings=Mock(return_value=self.client)
        self.client.get.side_effect=lambda path,*args: [dict(id=10,type='simple',sku='CODE',name='Product')] if path=='products' else dict(id=10,type='simple',sku='CODE')

    def test_preview_is_read_only_and_selects_sole_valid_uom(self):
        result=self.m.preview()
        self.assertEqual(result['rows'][0]['sale_uom'],'Each')
        self.assertEqual(result['rows'][0]['status'],'Ready')
        self.item.save.assert_not_called()
        self.f.db.commit.assert_not_called()

    def test_sales_uom_requires_real_conversion_and_ambiguous_uoms_skip(self):
        self.item.uoms=[Doc(uom='Box',conversion_factor=10)]
        self.assertIn('UOM',self.m.preview()['rows'][0]['reason'])
        self.item.sales_uom='Box'
        self.assertEqual(self.m.preview()['rows'][0]['sale_uom'],'Box')
        self.item.sales_uom='Roll'
        self.assertEqual(self.m.preview()['rows'][0]['status'],'Review')

    def test_case_sensitive_match_and_occupied_item_are_skipped(self):
        self.f.get_list.return_value=[Doc(name='CODE',item_code='code')]
        self.assertEqual(self.m.preview()['rows'][0]['status'],'Skipped')
        self.f.get_list.return_value=[Doc(name='CODE',item_code='CODE')]
        self.f.db.exists.return_value=True
        self.assertEqual(self.m.preview()['rows'][0]['status'],'Review')

    def test_inherited_sku_never_suggests_an_item(self):
        self.client.get.side_effect=lambda path,*args: [dict(id=10,type='variable',sku='CODE')] if path=='products' else [dict(id=11,sku='CODE'),dict(id=12,sku='')]
        result=self.m.preview()
        self.assertTrue(all(r['status']=='Skipped' for r in result['rows']))
        self.f.get_doc.assert_not_called()

    def test_apply_revalidates_sku_uom_and_timestamp_before_creating_active_stock_only(self):
        row=self.m.preview()['rows'][0]
        self.m.apply([row])
        saved=self.item.ws_woocommerce_links[0]
        self.assertEqual((saved.enabled,saved.sync_stock,saved.sync_price),(1,1,0))
        self.item.save.assert_called_once()

    def test_apply_rejects_tampered_preview_and_stale_item(self):
        row=self.m.preview()['rows'][0]
        row['item_code']='OTHER'
        self.assertEqual(self.m.apply([row])['rows'][0]['status'],'Failed')
        row['item_code']='CODE';row['modified']='2026-10-01 12:00:00'
        self.assertEqual(self.m.apply([row])['rows'][0]['status'],'Failed')
        self.item.save.assert_not_called()

    def test_existing_target_is_never_modified(self):
        row=self.m.preview()['rows'][0]
        self.f.db.get_value.return_value=Doc(name='link',parent='OTHER',parenttype='Item',parentfield='ws_woocommerce_links')
        self.assertEqual(self.m.apply([row])['rows'][0]['status'],'Skipped')
        self.item.save.assert_not_called()

    def test_automatic_scan_requires_both_switches(self):
        self.assertEqual(self.m.recover(self.config),{'skipped':True})
        self.client.get.assert_not_called()

    def test_preview_rejects_invalid_cursor_and_manager_denied(self):
        for page in (0,-1,100001,'abc'):
            with self.assertRaises(ValueError):self.m.preview(page)
        self.c.manager_only.side_effect=PermissionError('denied')
        with self.assertRaises(PermissionError):self.m.preview()
        with self.assertRaises(PermissionError):self.m.apply([])

    def test_stored_sku_ambiguity_and_remote_change_block_application(self):
        row=self.m.preview()['rows'][0]
        original=self.client.get.side_effect
        self.client.get.side_effect=lambda path,*args: [dict(id=10,type='simple',sku='CODE'),dict(id=20,type='simple',sku='CODE')] if path=='products' else original(path,*args)
        self.assertEqual(self.m.apply([row])['rows'][0]['status'],'Failed')
        self.item.save.assert_not_called()

    def test_recovery_failure_keeps_cursor_and_successes_are_idempotent(self):
        self.config.update(automatic_sync=1,auto_link_skus=1)
        self.f.db.get_single_value.return_value=None
        self.m.apply_rows=Mock(return_value=dict(rows=[dict(status='Failed')]))
        self.m.recover(self.config)
        self.f.db.set_value.assert_not_called()

    def test_completed_scan_restarts_after_hour_and_not_every_stock_event(self):
        self.config.update(automatic_sync=1,auto_link_skus=1)
        self.f.db.get_single_value.return_value=None
        self.client.get.return_value=[];self.client.get.side_effect=None
        self.m.recover(self.config)
        saved=self.f.db.set_value.call_args[0][3]
        self.assertIn('next_scan',saved)
        self.client.get.reset_mock()
        self.f.db.get_single_value.return_value=saved
        self.m.recover(self.config)
        self.client.get.assert_not_called()

    def test_recovery_requires_all_three_switches_and_never_calls_manual_endpoint(self):
        for enabled,automatic,link in [(0,1,1),(1,0,1),(1,1,0)]:
            self.config.update(enabled=enabled,automatic_sync=automatic,auto_link_skus=link)
            self.assertEqual(self.m.recover(self.config),dict(skipped=True))
        self.c.manager_only.assert_not_called()
        self.client.get.assert_not_called()

    def test_cursor_continues_variations_before_advancing_parent(self):
        self.client.get.side_effect=lambda path,*args: [dict(id=10,type='variable',sku='PARENT')] if path=='products' else [dict(id=i+100,sku='') for i in range(25)]
        data=self.m.preview(3,2)
        self.assertEqual((data['page'],data['variation_page']),(3,3))
        self.assertEqual(len(data['rows']),25)

    def test_apply_is_post_gated_and_bounded(self):
        for rows in [[],[{}]*26,{},[None]]:
            with self.assertRaises(ValueError):self.m.apply(rows)
        self.c.manager_only.assert_called_with(write=True)
        self.item.save.assert_not_called()

    def test_slow_discovery_still_applies_one_candidate_instead_of_starving(self):
        self.config.update(automatic_sync=1,auto_link_skus=1)
        self.f.db.get_single_value.return_value=None
        self.m.catalog_chunk=Mock(return_value=dict(rows=[dict(status='Ready')],page=2,variation_page=1,done=False))
        self.m.apply_rows=Mock(return_value=dict(rows=[dict(status='Linked')]))
        self.m.monotonic=Mock(side_effect=[0,65,66])
        result=self.m.recover(self.config)
        self.m.apply_rows.assert_called_once()
        self.assertEqual(result['rows'][0]['status'],'Linked')
        self.f.db.set_value.assert_called_once()


class BulkUpgradeTests(unittest.TestCase):
    def test_upgrade_reloads_only_settings_and_two_pages_without_activation(self):
        with adapter('install') as (m,f,c,unused):
            m.preflight=Mock()
            f.db.exists.return_value=True
            f.reload_doc=Mock();f.clear_cache=Mock()
            result=m.upgrade_bulk_linking()
            self.assertEqual([call[0][:3] for call in f.reload_doc.call_args_list],[
                ('worldshading','doctype','ws_woocommerce_settings'),
                ('worldshading','page','ws_woocommerce_link'),
                ('worldshading','page','ws_woocommerce_guide')])
            self.assertFalse(result['automatic_sync_changed'])
            self.assertFalse(result['auto_link_skus_changed'])
            f.db.set_value.assert_not_called()
            m.create_custom_fields.assert_not_called()
