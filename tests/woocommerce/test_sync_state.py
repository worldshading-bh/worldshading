import unittest
from datetime import datetime
from adapter_support import adapter
from test_item_links import Doc


class StateStoreTests(unittest.TestCase):
    def test_acknowledged_stock_hold_clears_due_failure_to_prevent_requeue_loop(self):
        with adapter('sync_state') as (m,f,c,o):
            m.StateStore().hold('link',3)
            sql,params=f.db.sql.call_args[0]
            for clause in ['attempts=0','next_retry=NULL','last_error=NULL','OR attempts<>0','OR next_retry IS NOT NULL']:
                self.assertIn(clause,sql)
            self.assertNotIn('requested_version=',sql)

    def test_failed_attempt_invalidates_verification_even_when_new_event_arrived(self):
        with adapter('sync_state') as (m,f,c,o):
            f.db.get_value.return_value=Doc(attempts=0,requested_version=2)
            now=datetime(2026,11,1,10)
            m.StateStore().fail('link',1,'Readback failed',now)
            fields=f.db.set_value.call_args[0][2]
            self.assertEqual(fields,dict(last_attempt=now,last_verified=None))
            f.db.sql.assert_not_called()

    def test_manual_or_automatic_attempt_invalidates_only_its_existing_link(self):
        with adapter('sync_state') as (m,f,c,o):
            f.db.table_exists.return_value=True
            m.invalidate_verification('link-A')
            query,params=f.db.sql.call_args[0]
            self.assertIn('last_verified=NULL',query)
            self.assertEqual(params,('link-A',))
            self.assertNotIn('last_payload_hash=',query)
            self.assertNotIn('requested_version=',query)
            f.db.commit.assert_called_once()

    def test_acknowledgement_never_overwrites_a_new_requested_revision(self):
        with adapter('sync_state') as (m,f,c,o):
            m.StateStore().ack('link',3,'digest',datetime(2026,11,1,10))
            fields=f.db.set_value.call_args[0][2]
            self.assertEqual(fields['synced_version'],3)
            self.assertNotIn('requested_version',fields)

    def test_idle_state_load_does_not_insert_or_commit(self):
        with adapter('sync_state') as (m,f,c,o):
            f.get_all.return_value=[Doc(name='link')]
            states=m.StateStore().prepare([dict(name='link',item_code='A')])
            self.assertIn('link',states)
            f.db.sql.assert_not_called();f.db.commit.assert_not_called()

if __name__=='__main__':unittest.main()
