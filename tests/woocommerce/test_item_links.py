import types
import importlib.util
import sys
import unittest
from unittest.mock import Mock,patch
from adapter_support import adapter,ROOT,PACKAGE


class Doc(dict):
    def __getattr__(self,key):
        return self.get(key)

    def set(self,key,value):
        self[key]=value


class ItemLinkTests(unittest.TestCase):
    def setUp(self):
        self.context=adapter('item_links')
        self.links,self.frappe,self.common,_=self.context.__enter__()
        self.addCleanup(self.context.__exit__,None,None,None)
        self.frappe.get_roles=lambda: ['System Manager']
        self.frappe.db.exists.return_value=False
        self.frappe.db.get_value.return_value=None
        self.row=Doc(name='link1',enabled=1,product_id=10,variation_id=0,sku='ERPDEMO-X',sale_uom='Kg',sync_stock=1,sync_price=1,clear_sale_price=0)
        self.item=Doc(name='ITEM-X',stock_uom='Each',disabled=0,has_variants=0,is_sales_item=1,
                      uoms=[Doc(uom='Each',conversion_factor=1),Doc(uom='Kg',conversion_factor=196)],ws_woocommerce_links=[self.row])

    def test_conversion_is_derived_from_current_item_uoms(self):
        self.assertEqual(self.links.normalize(self.item,self.row)['conversion_factor'],196)
        self.item.uoms[1]['conversion_factor']=200
        self.assertEqual(self.links.normalize(self.item,self.row)['conversion_factor'],200)
        self.assertNotIn('conversion_factor',self.row)

    def test_listing_does_not_normalize_unrelated_broken_uom(self):
        self.frappe.get_all=Mock(return_value=[Doc(self.row,parent='ITEM-X')])
        self.frappe.get_doc.side_effect=ValueError('Unrelated Item UOM invalid')
        result=self.links.all_mappings()
        self.assertEqual(result[0]['item_code'],'ITEM-X')
        self.frappe.get_doc.assert_not_called()

    def test_stock_uom_uses_factor_one_without_duplicate_configuration(self):
        self.row['sale_uom']='Each'
        self.assertEqual(self.links.normalize(self.item,self.row)['conversion_factor'],1)

    def test_missing_ambiguous_or_nonpositive_uom_stops_sync(self):
        for uoms in [[],[Doc(uom='Kg',conversion_factor=0)],
                     [Doc(uom='Kg',conversion_factor=196),Doc(uom='Kg',conversion_factor=200)]]:
            self.item['uoms']=uoms
            with self.assertRaises(ValueError):self.links.normalize(self.item,self.row)

    def test_second_stock_link_is_rejected(self):
        self.item.ws_woocommerce_links.append(Doc(self.row,name='link2',product_id=11))
        with self.assertRaises(ValueError):self.links.validate_item(self.item)

    def test_duplicate_target_in_same_item_is_rejected_even_if_disabled(self):
        self.item.ws_woocommerce_links.append(Doc(self.row,name='link2',enabled=0))
        with self.assertRaises(ValueError):self.links.validate_item(self.item)

    def test_global_duplicate_target_is_rejected(self):
        self.frappe.db.exists.return_value=True
        with self.assertRaises(ValueError):self.links.validate_item(self.item)

    def test_child_validation_uses_document_setter(self):
        values=dict(self.row)
        child=types.SimpleNamespace(get=values.get,set=lambda key,value:values.update({key:value}))
        self.item['ws_woocommerce_links']=[child]
        self.links.validate_item(self.item)
        self.assertEqual(values['target_key'],'10:0')

    def test_link_config_changes_require_manager_but_ordinary_edits_do_not(self):
        self.frappe.get_roles=lambda: ['Stock User']
        self.frappe.get_all=Mock(return_value=[])
        with self.assertRaises(PermissionError):self.links.validate_item(self.item)
        self.frappe.get_all.return_value=[self.row.copy()]
        self.links.validate_item(self.item)

    def test_child_outside_item_table_cannot_be_used(self):
        self.frappe.get_doc.return_value=Doc(parent='ITEM-X',parenttype='Sales Order',parentfield='items')
        with self.assertRaises(ValueError):self.links.get_mapping('link1')

    def test_status_retains_previous_success_and_latest_error_without_item_writes(self):
        self.frappe.get_all=Mock(side_effect=[
            [Doc(name='link1',sku='ERPDEMO-X',enabled=1)],
            [Doc(creation='2026-10-29 12:00:00',status='Failed',message='Store unavailable')],
            [Doc(creation='2026-10-29 11:00:00')]])
        status=self.links.status_for_item('ITEM-X')[0]
        self.assertEqual(status['last_success'],'2026-10-29 11:00:00')
        self.assertEqual(status['last_checked'],'2026-10-29 12:00:00')
        self.assertEqual(status['error'],'Store unavailable')
        self.frappe.get_doc.assert_not_called()
        self.frappe.db.set_value.assert_not_called()
        self.frappe.db.commit.assert_not_called()

    def controller(self):
        document=types.ModuleType('frappe.model.document');document.Document=Doc
        path=ROOT.parents[1]/'worldshading/doctype/ws_woocommerce_item_link/ws_woocommerce_item_link.py'
        with patch.dict(sys.modules,{'frappe.model.document':document,PACKAGE+'.item_links':self.links}):
            spec=importlib.util.spec_from_file_location('item_link_controller',str(path))
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            child=module.WSWooCommerceItemLink(dict(self.row,parent='ITEM-X',parenttype='Item',parentfield='ws_woocommerce_links'))
            return child

    def test_direct_child_save_cannot_bypass_manager_permissions(self):
        self.frappe.get_roles=lambda:['Stock User']
        child=self.controller()
        with self.assertRaises(PermissionError):child.validate()

    def test_direct_child_save_cannot_bypass_parent_stock_allocation(self):
        child=self.controller();child['name']='link2';child['product_id']=11
        self.item['check_permission']=Mock()
        self.frappe.get_doc.return_value=self.item
        with patch.dict(sys.modules,{PACKAGE+'.item_links':self.links}):
            with self.assertRaises(ValueError):child.validate()

    def test_direct_child_delete_requires_parent_item_write_access(self):
        child=self.controller()
        self.item['check_permission']=Mock(side_effect=PermissionError('Item access denied'))
        self.frappe.get_doc.return_value=self.item
        with self.assertRaises(PermissionError):child.on_trash()

    def test_direct_child_update_cannot_reassign_existing_parent(self):
        child=self.controller();child['parent']='OTHER-ITEM'
        self.frappe.db.get_value.return_value=Doc(parent='ITEM-X',parenttype='Item',parentfield='ws_woocommerce_links')
        with self.assertRaises(ValueError):child.validate()
