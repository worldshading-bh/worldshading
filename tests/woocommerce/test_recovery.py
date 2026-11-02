import unittest
import contextlib
import types
from unittest.mock import Mock, patch
from adapter_support import adapter, PACKAGE
from test_item_links import Doc

class RecoveryTests(unittest.TestCase):
    def setup_case(self):
        ctx=adapter('worker');m,f,c,o=ctx.__enter__();self.addCleanup(ctx.__exit__,None,None,None)
        m.site_is_allowed=Mock(return_value=True)
        f.session=Doc(user='Administrator');f.local.site='example';f.enqueue=Mock()
        c.settings.return_value=Doc(enabled=1,automatic_sync=1,integration_user='connector',auto_link_skus=0)
        return m,f,c

    def test_native_tick_coalesces_and_uses_long_worker(self):
        m,f,c=self.setup_case();redis=Mock();m.queue_connection=Mock(return_value=redis)
        m.scheduled_recovery();m.scheduled_recovery()
        self.assertEqual(f.enqueue.call_args[1]['queue'],'long')
        self.assertGreater(f.enqueue.call_args[1]['timeout'],300)
        redis.set.return_value=False;f.enqueue.reset_mock();m.scheduled_recovery();f.enqueue.assert_not_called()

    def test_foreign_and_disabled_sites_never_queue_or_poll(self):
        m,f,c=self.setup_case();m.site_is_allowed.return_value=False
        self.assertEqual(m.scheduled_recovery(),{'skipped':True})
        c.settings.assert_not_called();f.enqueue.assert_not_called()
        m.site_is_allowed.return_value=True;c.settings.return_value.automatic_sync=0
        self.assertEqual(m.recover(),{'skipped':True})
        self.assertNotIn(('connector',),[call[0] for call in f.set_user.call_args_list])

    def test_recovery_serializes_both_entry_paths_and_restores_identity(self):
        m,f,c=self.setup_case();sequence=[]
        @contextlib.contextmanager
        def locked(key):
            sequence.append(key);yield
        m.lock=locked
        sync=types.ModuleType(PACKAGE+'.sync');sync.run_cycle=Mock(return_value={})
        with patch.dict(__import__('sys').modules,{PACKAGE+'.sync':sync}):
            m.recover()
        self.assertIn('recovery',sequence)
        self.assertEqual(f.set_user.call_args_list[-1][0],('Administrator',))
        sync.run_cycle.assert_called_once_with(changes_only=True)

    def test_busy_recovery_is_skipped_without_hot_loop(self):
        m,f,c=self.setup_case()
        @contextlib.contextmanager
        def busy(key):raise c.LockBusy('busy');yield
        m.lock=busy
        self.assertEqual(m.recover(),{'busy':True})
        f.enqueue.assert_not_called()

    def test_enqueue_failure_releases_only_owned_lease(self):
        m,f,c=self.setup_case();redis=Mock();m.queue_connection=Mock(return_value=redis)
        f.enqueue.side_effect=ConnectionError('down')
        with self.assertRaises(ConnectionError):m.scheduled_recovery()
        self.assertIn("redis.call('get'",redis.eval.call_args[0][0])

    def test_upgrade_clears_native_schedule_cache_without_running_business_actions(self):
        with adapter('install') as (m,f,c,o):
            m.preflight=Mock();f.db.exists.return_value=True
            f.reload_doc=Mock();f.clear_cache=Mock();f.cache=Mock()
            result=m.upgrade_hardening()
            self.assertEqual(result['recovery_cron'],'*/5 * * * *')
            f.cache.return_value.delete_value.assert_called_once_with('scheduler_events')
            self.assertEqual(len(f.reload_doc.call_args_list),3)
            f.db.set_value.assert_not_called();m.create_custom_fields.assert_not_called()

if __name__=='__main__':unittest.main()
