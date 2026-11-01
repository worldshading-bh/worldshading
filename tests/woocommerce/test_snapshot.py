import unittest
from adapter_support import adapter
from test_item_links import Doc


class SnapshotTests(unittest.TestCase):
    def test_snapshot_groups_queries_and_keeps_reservations_and_drafts(self):
        with adapter('snapshot') as (m,f,c,o):
            m.stock_warehouses=lambda config:['MAIN','SECOND']
            data={
              'Item':[Doc(name='A',stock_uom='Each',is_stock_item=1,is_sales_item=1,disabled=0,has_variants=0),Doc(name='B',stock_uom='Each',is_stock_item=1,is_sales_item=1,disabled=0,has_variants=0)],
              'UOM Conversion Detail':[Doc(parent='A',uom='Box',conversion_factor=5)],
              'Bin':[Doc(item_code='A',actual_qty=20,reserved_qty=3,reserved_qty_for_production=2),Doc(item_code='A',actual_qty=10,reserved_qty=1),Doc(item_code='B',actual_qty=2,reserved_qty=2)],
              'Item Price':[Doc(item_code='A',currency='BHD',price_list_rate=1,uom='Each',valid_from=None,valid_upto=None)]}
            calls=[]
            def get_all(doctype,**kwargs):calls.append(doctype);return data[doctype]
            f.get_all=get_all;f.db.sql.return_value=[Doc(item_code='A',qty=4)]
            maps=[dict(item_code='A',sync_price=1),dict(item_code='B',sync_price=0)]
            snapshot=m.Snapshot(maps,Doc(price_list='Online Price'))
            self.assertEqual(snapshot.drafts('A'),4)
            self.assertEqual(snapshot.item('A').uoms[0].conversion_factor,5)
            self.assertEqual(len(snapshot.bins('A')),2)
            self.assertEqual(snapshot.prices('A')[0].price_list_rate,1)
            self.assertEqual(calls.count('Bin'),1)
            f.db.sql.assert_called_once()
            self.assertIn('GROUP BY',f.db.sql.call_args[0][0])

if __name__=='__main__':unittest.main()
