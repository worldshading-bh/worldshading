import json
import unittest
from unittest.mock import Mock
from adapter_support import adapter
from test_item_links import Doc


class OrderReviewTests(unittest.TestCase):
    def test_new_woo_payload_repairs_corrupt_stored_payload(self):
        with adapter('orders') as (module,frappe,common,unused):
            record=Doc(name='123',payload='{bad',source_modified=None,save=Mock(),status='Needs Review')
            frappe.db.exists.return_value=True
            frappe.get_doc.return_value=record
            payload={'id':123,'status':'processing','currency':'BHD','total':'0','line_items':[],'date_created_gmt':'2026-10-29T10:00:00'}
            inbox,fresh=module.store_payload(payload)
            self.assertTrue(fresh)
            self.assertEqual(inbox.status,'Pending')
            self.assertEqual(json.loads(inbox.payload),payload)

    def test_corrupt_due_payload_is_reviewed_without_aborting_other_orders(self):
        with adapter('orders') as (module,frappe,common,unused):
            common.settings.return_value=Doc(max_attempts=5,order_since='2026-10-01 00:00:00')
            frappe.db.sql.return_value=[Doc(name='123',payload='{bad',attempts=0,next_retry=None),
                                        Doc(name='124',payload=json.dumps({'id':124,'total':'1','date_created_gmt':'2026-10-29T10:00:00'}),attempts=0,next_retry=None)]
            record=Doc(name='123',payload='{bad',status='Needs Review',save=Mock())
            frappe.get_doc.return_value=record
            module.import_order=Mock()
            self.assertEqual(module.retry_due(),2)
            self.assertEqual(module.import_order.call_args[0][0]['id'],124)
            self.assertEqual(record.status,'Needs Review')
            self.assertEqual(record.attempts,5)

    def test_invalid_numeric_or_date_retry_does_not_stop_healthy_order(self):
        for bad in [dict(total='NaN',date_created_gmt='2026-10-29T10:00:00'),dict(total='1',date_created_gmt='invalid')]:
            with adapter('orders') as (module,frappe,common,unused):
                common.settings.return_value=Doc(max_attempts=5,order_since='2026-10-01 00:00:00')
                raw=json.dumps(dict(bad,id=123))
                frappe.db.sql.return_value=[Doc(name='123',payload=raw,attempts=0,next_retry=None),Doc(name='124',payload=json.dumps(dict(id=124,total='1',date_created_gmt='2026-10-29T10:00:00')),attempts=0,next_retry=None)]
                record=Doc(name='123',payload=raw,status='Failed',save=Mock())
                frappe.get_doc.return_value=record
                module.import_order=Mock(side_effect=lambda payload: (_ for _ in ()).throw(ValueError('Corrupt source')) if payload['id']==123 else None)
                self.assertEqual(module.retry_due(),2)
                self.assertEqual(record.status,'Needs Review')
                self.assertEqual(module.import_order.call_count,1)

    def test_ignored_and_deferred_imports_commit_before_releasing_lock(self):
        import contextlib
        for status in ['Ignored','Needs Review']:
            with adapter('orders') as (module,frappe,common,unused):
                config=Doc(max_attempts=5,order_since='2026-10-01 00:00:00')
                common.settings.return_value=config
                row=Doc(status=status,attempts=5,next_retry=None,sales_order=None,error='Review')
                module.store_payload=Mock(return_value=(row,True))
                @contextlib.contextmanager
                def lock(key):
                    yield
                    frappe.db.commit.assert_called_once()
                module.lock=lock
                result=module.import_order(dict(id=123,total='1',date_created_gmt='2026-10-29T10:00:00'))
                self.assertEqual(result['status'],status)

    def test_malformed_checklist_line_does_not_hide_other_missing_products(self):
        with adapter('api') as (module,frappe,common,orders):
            record=Doc(payload=json.dumps({'line_items':[None,dict(product_id=99,name='Net')]}),check_permission=Mock())
            frappe.get_doc.return_value=record
            frappe.get_all=Mock(return_value=[])
            result=module.order_review('123')
            self.assertEqual(len(result['lines']),2)
            self.assertTrue(all(row['error'] for row in result['lines']))
            self.assertEqual(result['lines'][1]['name'],'Net')
            common.mappings.assert_not_called()

    def test_invalid_json_checklist_returns_readable_error(self):
        with adapter('api') as (module,frappe,common,orders):
            frappe.get_doc.return_value=Doc(payload='{bad',check_permission=Mock())
            result=module.order_review('123')
            self.assertTrue(result['error'])
            self.assertEqual(result['lines'],[])

    def test_unchanged_order_refreshes_payment_method_metadata(self):
        with adapter('orders') as (module,frappe,common,unused):
            from worldshading.integration.woocommerce import domain as d
            payload=dict(id=123,status='processing',currency='BHD',total='1',total_tax='0',shipping_total='0',
                         date_created_gmt='2026-10-29T10:00:00',payment_method='cod-updated',customer_id=12,
                         line_items=[dict(product_id=10,quantity=1,total='1')])
            common.settings.return_value=Doc(currency='BHD',max_attempts=8,order_since='2026-10-01 00:00:00')
            row=Doc(status='Imported',attempts=0,sales_order='SO-1',fingerprint=d.order_fingerprint(payload),save=Mock())
            module.store_payload=Mock(return_value=(row,True))
            frappe.db.get_value.side_effect=lambda doctype,name,field:0 if field=='docstatus' else 'CUSTOMER' if field=='customer' else d.customer_key(payload)
            self.assertEqual(module.import_order(payload)['status'],'Unchanged')
            self.assertEqual(frappe.db.set_value.call_args[0][2]['ws_woo_payment_method'],'cod-updated')
