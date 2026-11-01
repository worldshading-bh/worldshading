import sys
import types
import unittest
from unittest.mock import Mock,patch
from adapter_support import adapter,PACKAGE
from test_item_links import Doc


class MigrationTests(unittest.TestCase):
    def run_migration(self,discard=False):
        context=adapter('install')
        install,frappe,_,_=context.__enter__()
        self.addCleanup(context.__exit__,None,None,None)
        links=types.ModuleType(PACKAGE+'.item_links')
        links.LINK='Link';links.TABLE='woo';links.CONFIG_FIELDS=['name','enabled']
        links.validate_item=Mock()
        saved={};children=[]
        previous=Doc(name='legacy1',item_code='ITEM-X',enabled=1)
        item=Mock()
        item.append.side_effect=lambda field,row:children.append(row)
        def save(**kwargs):
            if not discard:
                for row in children:
                    # v12 treats named children without __islocal as existing UPDATEs.
                    if row.get('__islocal'):saved[row['name']]=Doc(parent='ITEM-X',parenttype='Item',parentfield='woo')
        item.save.side_effect=save
        frappe.get_doc.return_value=item
        frappe.get_all=Mock(return_value=[previous])
        frappe.db.get_value.side_effect=lambda doctype,name,*args,**kwargs:saved.get(name)
        with patch.dict(sys.modules,{PACKAGE+'.item_links':links}):
            install.migrate_item_links()
        return saved,frappe

    def test_named_legacy_child_is_inserted_in_v12(self):
        saved,frappe=self.run_migration()
        self.assertIn('legacy1',saved)

    def test_failed_child_persistence_cannot_mark_migration_complete(self):
        with self.assertRaises(ValueError):self.run_migration(discard=True)

    def test_completed_migration_does_not_resurrect_removed_rows(self):
        with adapter('install') as (install,frappe,_,_):
            frappe.db.get_single_value.return_value=1
            install.migrate_item_links()
            frappe.get_doc.assert_not_called()
