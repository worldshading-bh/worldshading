import types
import unittest
from unittest.mock import Mock
from adapter_support import adapter
from test_item_links import Doc


class DocumentRulesTests(unittest.TestCase):
    def test_only_connector_owned_order_uses_exact_woo_total(self):
        with adapter('document_rules') as (module,frappe,common,orders):
            original=Mock(return_value=False)
            ordinary=Doc(name='ORDINARY',flags=types.SimpleNamespace(),is_rounded_total_disabled=original)
            module.preserve_woo_total(ordinary)
            self.assertIs(ordinary.is_rounded_total_disabled,original)
            linked=Doc(name='WOO-1',ws_woo_order_id='123',flags=types.SimpleNamespace())
            frappe.db.get_value.return_value='WOO-1'
            module.preserve_woo_total(linked)
            self.assertTrue(linked.is_rounded_total_disabled())
            unlinked=Doc(name='OTHER',ws_woo_order_id='123',flags=types.SimpleNamespace(),is_rounded_total_disabled=original)
            module.preserve_woo_total(unlinked)
            self.assertIs(unlinked.is_rounded_total_disabled,original)

    def test_new_import_can_apply_policy_before_inbox_links_sales_order(self):
        with adapter('document_rules') as (module,frappe,common,orders):
            doc=Doc(name=None,ws_woo_order_id='123',flags=types.SimpleNamespace(ws_woo_import=True))
            module.preserve_woo_total(doc)
            self.assertTrue(doc.is_rounded_total_disabled())
