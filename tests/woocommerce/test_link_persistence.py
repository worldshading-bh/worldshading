import unittest
from unittest.mock import Mock
from adapter_support import adapter
from test_linking import Item
from test_item_links import Doc

class PersistenceTests(unittest.TestCase):
    def test_mapping_insert_preserves_unrelated_item_and_audits_only_link(self):
        with adapter('link_persistence') as (m,f,c,o):
            f.session=Doc(user='manager');f.clear_document_cache=Mock()
            row=Doc(name='link',product_id=7,variation_id=8,sku='SKU',sale_uom='Meter',enabled=0,sync_stock=1,sync_price=0)
            row.insert=Mock();row.save=Mock()
            row.as_dict=lambda:{k:v for k,v in row.items() if not callable(v)}
            item=Item(name='CM3004',stock_uom='Meter',uoms=[],ws_woocommerce_links=[row],modified='2026-11-01 12:00:00',
                website_image='/files/missing.jpg',thumbnail='/files/missing_small.jpg',item_name='PVC',save=Mock(),check_permission=Mock())
            f.db.sql.return_value=[Doc(modified='2026-11-01 12:00:00')]
            f.get_roles=Mock(return_value=['System Manager']);f.db.exists.return_value=False
            version=Mock();f.get_doc.return_value=version
            m.persist(item,row,'2026-11-01 12:00:00')
            item.save.assert_not_called()
            self.assertEqual((item.website_image,item.thumbnail,item.item_name),('/files/missing.jpg','/files/missing_small.jpg','PVC'))
            row.insert.assert_called_once_with(ignore_permissions=True)
            parent_write=f.db.set_value.call_args[0]
            self.assertEqual(set(parent_write[2]),{'modified','modified_by'})
            data=__import__('json').loads(f.get_doc.call_args[0][0]['data'])
            self.assertEqual(data['added'][0][0],'ws_woocommerce_links')
            version.insert.assert_called_once_with(ignore_permissions=True)
            f.db.commit.assert_not_called()

    def test_permission_failure_prevents_even_lock_or_child_write(self):
        with adapter('link_persistence') as (m,f,c,o):
            item=Item(name='A',check_permission=Mock(side_effect=PermissionError('Denied')))
            row=Doc(insert=Mock(),save=Mock())
            with self.assertRaises(PermissionError):m.persist(item,row,'2026-11-01 12:00:00')
            f.db.sql.assert_not_called();f.db.set_value.assert_not_called()
            row.insert.assert_not_called();row.save.assert_not_called()

    def test_stale_item_under_sql_lock_never_writes(self):
        with adapter('link_persistence') as (m,f,c,o):
            item=Item(name='A',check_permission=Mock());row=Doc(insert=Mock(),save=Mock())
            f.db.sql.return_value=[Doc(modified='2026-11-01 12:05:00')]
            with self.assertRaisesRegex(ValueError,'changed'):m.persist(item,row,'2026-11-01 12:00:00')
            row.insert.assert_not_called();f.db.set_value.assert_not_called()

if __name__=='__main__':unittest.main()
