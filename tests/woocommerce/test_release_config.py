import copy
import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from adapter_support import adapter,PACKAGE
from test_item_links import Doc


class OriginConfigurationTests(unittest.TestCase):
    def test_settings_transport_reads_only_woo_api_credentials(self):
        with adapter('client') as (m,f,c,o):
            f.conf=Doc(host_name='https://erp.example.com',ws_woocommerce_erp_url='https://erp.example.com',ws_woocommerce_store_url='https://store.example.com')
            password=Mock(side_effect=lambda key:{'consumer_key':'ck_example','consumer_secret':'cs_example'}[key])
            config=Doc(store_url='https://store.example.com',get_password=password)
            with patch.object(m,'Client') as factory:
                m.from_settings(config)
            self.assertEqual([call[0][0] for call in password.call_args_list],['consumer_key','consumer_secret'])
            factory.assert_called_once_with('https://store.example.com','ck_example','cs_example',allowed_url='https://store.example.com')

    def test_demo_defaults_remain_restricted_to_demo_pair(self):
        with adapter('environment') as (m,f,c,o):
            f.conf=Doc(host_name='https://demo.worldshading.com')
            self.assertTrue(m.site_is_allowed())
            self.assertEqual(m.validate_store('https://testshop.worldshading.com/'),'https://testshop.worldshading.com')
            with self.assertRaises(ValueError):m.validate_store('https://shop.worldshading.com')
            f.conf['host_name']='https://erp.example.com'
            self.assertFalse(m.site_is_allowed())

    def test_production_requires_both_explicit_origins_and_exact_site(self):
        with adapter('environment') as (m,f,c,o):
            f.conf=Doc(host_name='https://erp.example.com',ws_woocommerce_erp_url='https://erp.example.com/',ws_woocommerce_store_url='https://store.example.com/')
            self.assertTrue(m.site_is_allowed())
            self.assertEqual(m.validate_store('https://store.example.com'),'https://store.example.com')
            self.assertEqual(m.webhook_url(),'https://erp.example.com/api/method/worldshading.integration.woocommerce.api.webhook')
            with self.assertRaises(ValueError):m.validate_store('https://testshop.worldshading.com')
            f.conf['host_name']='https://other.example.com'
            with self.assertRaises(ValueError):m.require_site()
            del f.conf['ws_woocommerce_store_url']
            with self.assertRaises(ValueError):m.configured_urls()

    def test_configured_origins_reject_credentials_ports_paths_queries_and_http(self):
        with adapter('environment') as (m,f,c,o):
            for unsafe in ['http://store.example.com','https://a:b@store.example.com','https://store.example.com:443','https://store.example.com/path','https://store.example.com?key=secret','https://store.example.com/#x']:
                f.conf=Doc(host_name='https://erp.example.com',ws_woocommerce_erp_url='https://erp.example.com',ws_woocommerce_store_url=unsafe)
                with self.assertRaises(ValueError):m.configured_urls()

    def test_transport_uses_the_configured_target_and_keeps_redirects_off(self):
        with adapter('client') as (m,f,c,o):
            session=Mock();session.request.return_value.status_code=200;session.request.return_value.json.return_value={}
            client=m.Client('https://store.example.com','ck_test','cs_test',session=session,allowed_url='https://store.example.com')
            client.get('products/1')
            self.assertTrue(session.request.call_args[0][1].startswith('https://store.example.com/wp-json/wc/v3/products/1?'))
            self.assertFalse(session.request.call_args[1]['allow_redirects'])

    def test_native_setup_has_no_legacy_table_dependency(self):
        with adapter('install') as (m,f,c,o):
            f.db.table_exists.return_value=False
            m.migrate_item_links()
            f.get_all.assert_not_called()
            f.db.set_value.assert_called_once()

    def test_item_validation_does_not_break_existing_items_before_scoped_setup(self):
        with adapter('item_links') as (m,f,c,o):
            f.db.table_exists.return_value=False
            m.validate_item(Doc(name='ITEM',ws_woocommerce_links=[]))
            f.get_all.assert_not_called()

    def test_setup_preflight_rejects_field_conflicts_before_any_schema_write(self):
        with adapter('install') as (m,f,c,o):
            f.conf=Doc(host_name='https://demo.worldshading.com')
            f.db.exists.return_value=False;f.reload_doc=Mock();f.clear_cache=Mock()
            f.db.get_value.return_value=Doc(fieldtype='Int',options=None)
            with self.assertRaises(ValueError):m.execute()
            f.reload_doc.assert_not_called();m.create_custom_fields.assert_not_called()

    def test_preflight_is_read_only_and_reports_only_connector_metadata(self):
        with adapter('install') as (m,f,c,o):
            f.conf=Doc(host_name='https://demo.worldshading.com')
            f.db.exists.return_value=False;f.db.get_value.return_value=None;f.reload_doc=Mock()
            result=m.preflight()
            self.assertEqual(len(result['doctypes']),6)
            self.assertEqual(set(result['custom_fields']),{'Item','Customer','Sales Order'})
            f.reload_doc.assert_not_called();f.db.commit.assert_not_called()

    def test_unconfigured_other_site_is_skipped_by_future_migrate_hook(self):
        with adapter('install') as (m,f,c,o):
            f.conf=Doc(host_name='https://unconfigured.example.com')
            m.execute=Mock();m.after_migrate()
            m.execute.assert_not_called()

    def test_blank_first_install_settings_can_show_dashboard_without_transport_configuration(self):
        with adapter('api') as (m,f,c,o):
            f.get_single=Mock(return_value=Doc(enabled=0,automatic_sync=0))
            c.settings.side_effect=ValueError('Store URL has not been filled yet')
            result=m.dashboard()
            self.assertFalse(result['enabled']);self.assertFalse(result['automatic_sync'])
            c.settings.assert_not_called()


class ReleaseHookTests(unittest.TestCase):
    def test_reloaded_submitted_woo_order_is_protected_before_existing_rounding_handler(self):
        with adapter('document_rules') as (m,f,c,o):
            sys.modules['worldshading'].__version__='test'
            root=Path(__file__).resolve().parents[2]
            hooks={'__name__':'worldshading.hooks','__package__':'worldshading'}
            exec(compile((root/'worldshading/hooks.py').read_text(encoding='utf-8'),'hooks.py','exec'),hooks)
            # Execute the actual production handler, with no ERP/database init.
            tree=ast.parse((root/'worldshading/api/dynamic_rounding.py').read_text(encoding='utf-8'))
            tree.body=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='sync_dynamic_rounding_after_submit']
            namespace={'frappe':f};exec(compile(tree,'dynamic_rounding.py','exec'),namespace)
            f.get_single=Mock(side_effect=AssertionError('Unexpected recalculation of the charged Woo total'))
            f.db.get_value.return_value='WOO-1'
            doc=Doc(doctype='Sales Order',name='WOO-1',docstatus=1,ws_woo_order_id='123',flags=types.SimpleNamespace(),is_rounded_total_disabled=Mock(return_value=False))
            for handler in hooks['doc_events']['Sales Order'].get('before_update_after_submit',[]):
                if handler==PACKAGE+'.document_rules.preserve_woo_total':m.preserve_woo_total(doc)
            self.assertFalse(namespace['sync_dynamic_rounding_after_submit'](doc))
            f.get_single.assert_not_called();f.db.set_value.assert_not_called()

    def test_connector_hooks_preserve_every_existing_hook_and_item_script(self):
        with adapter('domain'):
            sys.modules['worldshading'].__version__='test'
            path=Path(__file__).resolve().parents[2]/'worldshading/hooks.py'
            source=path.read_text(encoding='utf-8')
            self.assertIn('# BEGIN WS WOOCOMMERCE CONNECTOR',source)
            namespace={'__name__':'worldshading.hooks','__package__':'worldshading'}
            exec(compile(source.split('# BEGIN WS WOOCOMMERCE CONNECTOR')[0],str(path),'exec'),namespace)
            original=copy.deepcopy({k:namespace[k] for k in ['doc_events','doctype_js','after_migrate','scheduler_events','override_whitelisted_methods']})
            exec(compile(source,str(path),'exec'),namespace)
            for dt,events in original['doc_events'].items():
                for event,handlers in events.items():
                    before=handlers if isinstance(handlers,list) else [handlers]
                    after=namespace['doc_events'][dt][event]
                    after=after if isinstance(after,list) else [after]
                    self.assertEqual(after[:len(before)],before,(dt,event))
            self.assertEqual(namespace['doctype_js']['Item'],[original['doctype_js']['Item'],'public/js/woocommerce_item.js'])
            self.assertEqual(namespace['override_whitelisted_methods'],original['override_whitelisted_methods'])
            for event,handlers in original['scheduler_events'].items():
                if event!='cron':self.assertEqual(namespace['scheduler_events'][event],handlers)
                else:
                    for expression,jobs in handlers.items():
                        self.assertEqual(namespace['scheduler_events']['cron'][expression][:len(jobs)],jobs)
            recovery=namespace['scheduler_events']['cron']['*/10 * * * *']
            self.assertIn(PACKAGE+'.worker.scheduled_recovery',recovery)
            self.assertEqual(namespace['after_migrate'][:-1],original['after_migrate'])
            # Repeat registration must not duplicate hooks or scripts.
            block=source.split('# BEGIN WS WOOCOMMERCE CONNECTOR')[1]
            exec(compile(block,str(path),'exec'),namespace)
            self.assertEqual(namespace['doctype_js']['Item'].count('public/js/woocommerce_item.js'),1)
            self.assertEqual(namespace['scheduler_events']['cron']['*/10 * * * *'].count(PACKAGE+'.worker.scheduled_recovery'),1)


if __name__=='__main__':unittest.main()
