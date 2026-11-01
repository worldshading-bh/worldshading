import types
import unittest
from unittest.mock import Mock,patch
from adapter_support import adapter,PACKAGE
from test_item_links import Doc


class EventTests(unittest.TestCase):
    def setup_case(self):
        ctx=adapter('events');m,f,c,o=ctx.__enter__();self.addCleanup(ctx.__exit__,None,None,None)
        f.conf=Doc(host_name='https://demo.worldshading.com')
        f.local.site='erp.worldshading.com'
        f.db.get_single_value.return_value=1
        f.enqueue=Mock();f.logger=Mock()
        self.m,self.f,self.c=m,f,c
        return m,f

    def test_commit_first_one_notification_per_transaction(self):
        m,f=self.setup_case();order=[]
        original=Mock(side_effect=lambda:order.append('commit'));f.db.commit=original
        m.notify=Mock(side_effect=lambda:order.append('notify'))
        m.request_drain();m.request_drain()
        self.assertEqual(order,[])
        f.db.commit()
        self.assertEqual(order,['commit','notify'])
        self.assertIs(f.db.commit,original)
        m.request_drain();f.db.commit()
        self.assertEqual(order,['commit','notify','commit','notify'])

    def test_queue_failure_does_not_fail_completed_business_commit(self):
        m,f=self.setup_case();original=f.db.commit
        m.notify=Mock(side_effect=ConnectionError('Redis unavailable'))
        m.request_drain();f.db.commit()
        original.assert_called_once_with()
        self.assertIs(f.db.commit,original)

    def test_failed_commit_never_notifies(self):
        m,f=self.setup_case();f.db.commit.side_effect=RuntimeError('deadlock');m.notify=Mock()
        m.request_drain()
        with self.assertRaises(RuntimeError):f.db.commit()
        m.notify.assert_not_called()

    def test_manual_mode_and_recursive_drain_do_not_register(self):
        m,f=self.setup_case();original=f.db.commit
        f.db.get_single_value.return_value=0;m.request_drain()
        self.assertIs(f.db.commit,original)
        f.db.get_single_value.return_value=1;f.flags.ws_woo_draining=True;m.request_drain()
        self.assertIs(f.db.commit,original)

    def test_no_committed_work_means_no_queue_even_if_rollback_left_callback(self):
        m,f=self.setup_case();m.has_work=Mock(return_value=False);m.queue_connection=Mock()
        m.notify()
        m.queue_connection.assert_not_called();f.enqueue.assert_not_called()

    def test_queue_lease_coalesces_notifications_and_uses_bounded_worker(self):
        m,f=self.setup_case();m.has_work=Mock(return_value=True)
        redis=Mock();redis.set.return_value=True;m.queue_connection=Mock(return_value=redis)
        m.notify();self.assertEqual(f.enqueue.call_count,1)
        self.assertEqual(f.enqueue.call_args[1]['timeout'],300)
        self.assertEqual(redis.set.call_args[1],dict(nx=True,ex=360))
        redis.set.return_value=False;m.notify();self.assertEqual(f.enqueue.call_count,1)

    def test_failed_enqueue_releases_only_its_lease(self):
        m,f=self.setup_case();m.has_work=Mock(return_value=True)
        redis=Mock();m.queue_connection=Mock(return_value=redis)
        f.enqueue.side_effect=ConnectionError('queue down');m.release=Mock()
        with self.assertRaises(ConnectionError):m.notify()
        m.release.assert_called_once()

    def test_drain_checks_mode_and_persisted_work_before_any_cycle(self):
        m,f=self.setup_case();m.release=Mock();m.has_work=Mock(return_value=False)
        with patch(PACKAGE+'.sync.run_cycle') as cycle:
            m.drain('lease');cycle.assert_not_called()
        m.release.assert_called_once_with('lease')

    def test_successful_drain_releases_then_notifies_followup_under_integration_user(self):
        m,f=self.setup_case();self.c.settings.return_value=Doc(enabled=1,automatic_sync=1,integration_user='connector')
        m.has_work=Mock(return_value=True);sequence=[]
        m.release=Mock(side_effect=lambda token:sequence.append('release'))
        m.notify=Mock(side_effect=lambda:sequence.append('notify'))
        with patch(PACKAGE+'.sync.run_cycle',return_value={'products':[]}) as cycle:
            m.drain('lease')
        cycle.assert_called_once_with(changes_only=True,pending_only=True)
        f.set_user.assert_called_once_with('connector')
        self.assertEqual(sequence,['release','notify'])
        self.assertFalse(f.flags.ws_woo_draining)

    def test_failed_or_busy_cycle_does_not_hot_loop(self):
        m,f=self.setup_case();self.c.settings.return_value=Doc(enabled=1,automatic_sync=1,integration_user='connector')
        m.has_work=Mock(return_value=True);m.release=Mock();m.notify=Mock()
        with patch(PACKAGE+'.sync.run_cycle',side_effect=self.c.LockBusy('busy')):
            m.drain('lease')
        m.notify.assert_not_called();m.release.assert_called_once_with('lease')

    def test_pending_query_filters_disabled_links_backoff_and_acknowledged_holds(self):
        m,f=self.setup_case();f.db.sql.return_value=[('link-a',)]
        self.assertEqual(m.pending_links(),{'link-a'})
        sql=f.db.sql.call_args[0][0]
        for text in ['l.enabled=1','requested_version>s.synced_version','next_retry','s.attempts>0','last_payload_hash IS NOT NULL']:
            self.assertIn(text,sql)

    def test_inbox_hook_marks_current_and_previous_exposure(self):
        m,f=self.setup_case();m.request_drain=Mock()
        f.get_all.side_effect=[[Doc(parent='A',product_id=1,variation_id=0)],[Doc(item_code='OLD')]]
        with patch(PACKAGE+'.changes.mark_items') as mark:
            m.order_changed(Doc(payload='{"line_items":[{"product_id":1,"variation_id":0}]}',sales_order='SO'))
        self.assertEqual(set(mark.call_args[0][0]),{'A','OLD'})
        m.request_drain.assert_called_once()

    def test_repeated_identical_inbox_poll_does_not_mark_or_wake(self):
        m,f=self.setup_case();m.request_drain=Mock()
        doc=Doc(name='1',payload='{}',sales_order='SO',status='Imported')
        f.db.get_value.return_value=doc
        with patch(PACKAGE+'.changes.mark_items') as mark:
            m.order_changed(doc)
        mark.assert_not_called();m.request_drain.assert_not_called()

    def test_marker_registers_wakeup_only_for_actual_linked_work(self):
        with adapter('changes') as (m,f,c,o):
            f.conf=Doc(host_name='https://demo.worldshading.com');f.db.get_single_value.return_value=1
            with patch(PACKAGE+'.events.request_drain') as request:
                m.mark_items(['A']);request.assert_not_called()
                f.get_all.return_value=[Doc(name='a',parent='A')]
                m.mark_items(['A']);request.assert_called_once_with()

    def test_pending_targets_selected_after_order_reconciliation(self):
        with adapter('sync') as (m,f,c,o):
            sequence=[]
            m.mappings=Mock(return_value=[dict(name='a'),dict(name='b')])
            m.poll_orders=Mock(side_effect=lambda *args:sequence.append('orders') or 0)
            m.stock_holds=Mock(return_value=dict(review_required=0));m.from_settings=Mock()
            def pending():sequence.append('pending');return {'b'}
            result=dict(products=[],local_checked=1,locally_unchanged=1,retry_deferred=0,batch_deferred=0)
            with patch(PACKAGE+'.events.pending_links',side_effect=pending),patch(PACKAGE+'.changes.process_changes',return_value=result) as process:
                m.run_cycle(changes_only=True,pending_only=True)
            self.assertEqual(sequence,['orders','pending'])
            self.assertEqual(process.call_args[0][0],[dict(name='b')])

    def test_manual_cycle_hands_pending_work_to_queue_after_releasing_lock(self):
        with adapter('sync') as (m,f,c,o):
            with patch.object(m,'_run_cycle',return_value={'ok':True}) as cycle,patch(PACKAGE+'.events.notify') as notify:
                self.assertEqual(m.run_cycle(),{'ok':True})
                notify.assert_called_once_with()
            self.assertFalse(f.flags.ws_woo_draining)

    def test_nested_background_cycle_leaves_followup_to_drain(self):
        with adapter('sync') as (m,f,c,o):
            f.flags.ws_woo_draining=True
            with patch.object(m,'_run_cycle',return_value={}),patch(PACKAGE+'.events.notify') as notify:
                m.run_cycle()
            notify.assert_not_called();self.assertTrue(f.flags.ws_woo_draining)


if __name__=='__main__':unittest.main()
