import unittest
import importlib.util
import sys
import types
from unittest.mock import Mock,patch
from adapter_support import adapter,ROOT,PACKAGE
from test_item_links import Doc
from worldshading.integration.woocommerce import domain as d


class CombinedStockTests(unittest.TestCase):
    def test_reservations_drafts_and_buffer_deducted_once_then_uom_rounding(self):
        bins=[dict(actual_qty=10,reserved_qty=2),dict(actual_qty=7,reserved_qty_for_production=1,reserved_qty_for_sub_contract=1)]
        self.assertEqual(d.combined_stock(bins,drafts=3,buffer=1,factor=2),4)

    def test_negative_local_stock_cannot_consume_other_physical_stock(self):
        self.assertEqual(d.combined_stock([dict(actual_qty=-10),dict(actual_qty=8)]),8)

    def test_draft_on_default_warehouse_is_deducted_from_whole_pool(self):
        self.assertEqual(d.combined_stock([dict(actual_qty=0),dict(actual_qty=10)],drafts=6),4)

    def test_fractional_stock_is_combined_before_rounding(self):
        self.assertEqual(d.combined_stock([dict(actual_qty='.6'),dict(actual_qty='.6')]),1)

    def test_single_warehouse_retains_existing_result(self):
        self.assertEqual(d.combined_stock([dict(actual_qty=10,reserved_qty=1)],drafts=2,buffer=1),6)


class WarehouseSelectionTests(unittest.TestCase):
    def config(self,warehouses=None):
        return Doc(company='WS',warehouse='MAIN',stock_warehouses=warehouses or [])

    def test_empty_selection_falls_back_to_existing_order_warehouse(self):
        with adapter('inventory') as (module,frappe,common,orders):
            frappe.db.get_value.return_value=Doc(company='WS',is_group=0,disabled=0)
            self.assertEqual(module.stock_warehouses(self.config()),['MAIN'])

    def test_explicit_selection_is_unique_same_company_active_leaf_and_includes_default(self):
        with adapter('inventory') as (module,frappe,common,orders):
            frappe.db.get_value.return_value=Doc(company='WS',is_group=0,disabled=0)
            config=self.config([Doc(warehouse='MAIN'),Doc(warehouse='SECOND')])
            self.assertEqual(module.stock_warehouses(config),['MAIN','SECOND'])
            for rows in [[Doc(warehouse='MAIN'),Doc(warehouse='MAIN')],[Doc(warehouse='SECOND')],[Doc(warehouse=None)]]:
                with self.assertRaises(ValueError):module.stock_warehouses(self.config(rows))
            for data in [None,Doc(company='OTHER'),Doc(company='WS',is_group=1),Doc(company='WS',disabled=1)]:
                frappe.db.get_value.return_value=data
                with self.assertRaises(ValueError):module.stock_warehouses(config)


class WarehouseChildTests(unittest.TestCase):
    def setUp(self):
        self.context=adapter('inventory')
        self.inventory,self.frappe,self.common,_=self.context.__enter__()
        self.addCleanup(self.context.__exit__,None,None,None)
        self.patch=patch.dict(sys.modules,{PACKAGE+'.inventory':self.inventory})
        self.patch.start();self.addCleanup(self.patch.stop)
        document=types.ModuleType('frappe.model.document');document.Document=Doc
        path=ROOT.parents[1]/'worldshading/doctype/ws_woocommerce_warehouse/ws_woocommerce_warehouse.py'
        with patch.dict(sys.modules,{'frappe.model.document':document}):
            spec=importlib.util.spec_from_file_location('warehouse_child_controller',str(path))
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.child=module.WSWooCommerceWarehouse(name='row1',doctype='WS WooCommerce Warehouse',parent='Settings',parenttype='Settings',parentfield='stock_warehouses',warehouse='MAIN')
        self.config=Doc(company='WS',warehouse='MAIN',stock_warehouses=[self.child,Doc(name='row2',warehouse='SECOND')],check_permission=Mock())
        self.frappe.get_single=Mock(return_value=self.config)
        self.frappe.db.get_value=Mock(side_effect=lambda doctype,*a,**kw:Doc(company='WS',is_group=0,disabled=0) if doctype=='Warehouse' else None)

    def test_save_and_delete_require_manager(self):
        self.common.manager_only.side_effect=PermissionError('Manager required')
        for action in [self.child.validate,self.child.on_trash]:
            with self.assertRaises(PermissionError):action()

    def test_forged_or_reassigned_parent_is_rejected(self):
        self.child['parentfield']='OTHER'
        with self.assertRaises(ValueError):self.child.validate()
        self.child['parentfield']='stock_warehouses'
        self.frappe.db.get_value.return_value=Doc(parent='OTHER',parenttype='Settings',parentfield='stock_warehouses')
        self.frappe.db.get_value.side_effect=None
        with self.assertRaises(ValueError):self.child.validate()

    def test_direct_delete_cannot_exclude_default_from_remaining_selection(self):
        with self.assertRaises(ValueError):self.child.on_trash()

    def test_direct_child_requires_parent_settings_write_permission(self):
        self.config['check_permission']=Mock(side_effect=PermissionError('No parent access'))
        with self.assertRaises(PermissionError):self.child.validate()
