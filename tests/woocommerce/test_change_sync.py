import types
import unittest
from datetime import datetime,timedelta
from unittest.mock import Mock
from adapter_support import adapter
from test_item_links import Doc


class ChangeMarkerTests(unittest.TestCase):
    def test_stock_event_marks_only_enabled_stock_links_without_commit_or_network(self):
        with adapter('changes') as (m,f,c,o):
            m.mark_items=Mock()
            m.stock_changed(Doc(item_code='A',warehouse='MAIN'))
            m.mark_items.assert_called_once_with(['A'],'stock')
            f.db.commit.assert_not_called()

    def test_sales_order_marks_new_old_and_bundle_items(self):
        with adapter('changes') as (m,f,c,o):
            m.mark_items=Mock()
            f.get_all.return_value=[Doc(item_code='REMOVED')]
            doc=Doc(name='SO-1',items=[Doc(item_code='A')],packed_items=[Doc(item_code='PART')])
            m.sales_order_changed(doc)
            self.assertEqual(set(m.mark_items.call_args[0][0]),{'A','PART','REMOVED'})
            f.db.commit.assert_not_called()

    def test_markers_ignore_disabled_connector_and_unlinked_items(self):
        with adapter('changes') as (m,f,c,o):
            original_commit=f.db.commit
            f.conf=Doc(host_name='https://demo.worldshading.com')
            f.db.get_single_value.return_value=0
            m.mark_items(['A'],'stock')
            f.db.sql.assert_not_called()
            f.db.get_single_value.return_value=1
            f.get_all.return_value=[]
            m.mark_items(['UNLINKED'],'stock')
            f.db.sql.assert_not_called()
            f.get_all.return_value=[Doc(name='link',parent='A')]
            m.mark_items(['A'],'stock')
            self.assertIn('ON DUPLICATE KEY UPDATE',f.db.sql.call_args[0][0])
            self.assertIn('sync_stock',f.get_all.call_args[1]['filters'])
            original_commit.assert_not_called()


class MemoryStore:
    def __init__(self,states=None):self.states=states or {};self.failures=[]
    def prepare(self,mappings):
        for m in mappings:self.states.setdefault(m['name'],Doc(requested_version=1,synced_version=0,attempts=0))
        return self.states
    def ack(self,name,version,digest,now,verified=True):
        state=self.states[name];state.update(synced_version=version,last_payload_hash=digest,attempts=0,next_retry=None)
        if verified:state.update(last_verified=now,last_attempt=now)
    def hold(self,name,version):self.states[name].update(synced_version=version,last_payload_hash=None)
    def fail(self,name,version,error,now):
        state=self.states[name];state['last_attempt']=now
        if state.requested_version==version:
            state.update(attempts=state.attempts+1,next_retry=now+timedelta(minutes=2));self.failures.append(name)


class ChangeWorkerTests(unittest.TestCase):
    def setup_case(self):
        context=adapter('changes');m,f,c,o=context.__enter__();self.addCleanup(context.__exit__,None,None,None)
        self.now=datetime(2026,11,1,10)
        self.maps=[dict(name='a',item_code='A',product_id=1,sku='A',sync_stock=1,sync_price=0),dict(name='b',item_code='B',product_id=2,sku='B',sync_stock=1,sync_price=0)]
        self.payloads={'A':dict(manage_stock=True,stock_quantity=10),'B':dict(manage_stock=True,stock_quantity=20)}
        m.product_payload=lambda mapping,config,snapshot=None:dict(self.payloads[mapping['item_code']])
        m.stock_holds=lambda:dict(items={},all=[],review_required=0)
        self.calls=[];self.store=MemoryStore()
        def sync(mapping,config,client,**kwargs):
            self.calls.append(mapping['item_code'])
            return dict(status='Updated',item_code=mapping['item_code'],payload=kwargs.get('payload_override',dict(self.payloads[mapping['item_code']])),stock_blocked=0)
        self.sync=sync
        self.m=m
        return m
    def run_cycle(self):
        return self.m.process_changes(self.maps,Doc(),Mock(),snapshot=object(),store=self.store,clock=self.now,sync_fn=self.sync)
    def test_bootstrap_then_idle_has_zero_product_calls_even_after_duplicate_events(self):
        self.setup_case();self.run_cycle();self.assertEqual(self.calls,['A','B'])
        self.calls[:]=[];self.store.states['a']['requested_version']+=5
        result=self.run_cycle()
        self.assertEqual(self.calls,[])
        self.assertEqual(result['locally_unchanged'],2)
        self.assertEqual(self.store.states['a'].synced_version,6)
    def test_only_changed_reservation_quantity_is_exported(self):
        self.setup_case();self.run_cycle();self.calls[:]=[]
        self.payloads['A']['stock_quantity']=7
        self.run_cycle();self.assertEqual(self.calls,['A'])
    def test_event_during_export_remains_pending(self):
        self.setup_case()
        def sync(mapping,config,client,**kwargs):
            state=self.store.states[mapping['name']];state['requested_version']+=1
            return dict(status='Updated',payload=kwargs.get('payload_override',dict(self.payloads[mapping['item_code']])))
        self.sync=sync;self.run_cycle()
        self.assertEqual(self.store.states['a'].requested_version,2)
        self.assertEqual(self.store.states['a'].synced_version,1)
    def test_hourly_reconciliation_checks_unchanged_target(self):
        self.setup_case();self.run_cycle();self.calls[:]=[]
        self.now+=timedelta(hours=1,seconds=1)
        self.run_cycle();self.assertEqual(self.calls,['A','B'])
    def test_failed_export_keeps_old_verified_hash_and_retries_later(self):
        self.setup_case();self.run_cycle();old=self.store.states['a'].last_payload_hash
        self.payloads['A']['stock_quantity']=8;original=self.sync
        def sync(mapping,config,client,**kwargs):
            if mapping['name']=='a':return dict(status='Failed',error='offline')
            return original(mapping,config,client,**kwargs)
        self.sync=sync;self.run_cycle()
        self.assertEqual(self.store.states['a'].last_payload_hash,old)
        self.assertEqual(self.store.failures,['a'])
        self.calls[:]=[];result=self.run_cycle();self.assertEqual(result['retry_deferred'],1)
        self.assertEqual(self.calls,[])
        self.now+=timedelta(minutes=3);self.sync=original;self.run_cycle();self.assertEqual(self.calls,['A'])
    def test_stock_hold_has_no_woo_calls_and_release_forces_check(self):
        m=self.setup_case();self.run_cycle();self.calls[:]=[]
        m.stock_holds=lambda:dict(items={'A':['123']},all=[],review_required=1)
        self.run_cycle();self.assertEqual(self.calls,[])
        m.stock_holds=lambda:dict(items={},all=[],review_required=0)
        self.run_cycle();self.assertEqual(self.calls,['A'])
    def test_malformed_one_item_does_not_stop_other_changed_item(self):
        m=self.setup_case()
        def payload(mapping,config,snapshot=None):
            if mapping['name']=='a':raise ValueError('Invalid UOM')
            return self.payloads['B']
        m.product_payload=payload
        result=self.run_cycle();self.assertEqual(self.calls,['B']);self.assertEqual(result['products'][0]['status'],'Failed')
    def test_many_invalid_items_are_bounded_without_starving_remaining_items(self):
        self.setup_case()
        self.maps=[dict(name='link%02d'%n,item_code='I%02d'%n,product_id=n+1,sku=str(n),sync_stock=1,sync_price=0) for n in range(30)]
        def invalid(*args,**kwargs):raise ValueError('Invalid UOM')
        self.m.product_payload=invalid
        result=self.run_cycle()
        self.assertEqual(len(result['products']),25)
        self.assertEqual(result['batch_deferred'],5)
        self.assertEqual(len(self.store.failures),25)

    def test_failed_target_is_reverified_even_if_erp_returns_to_previous_value(self):
        self.setup_case();self.run_cycle();self.calls[:]=[]
        original=self.sync
        self.payloads['A']['stock_quantity']=8
        self.sync=lambda *args,**kwargs:dict(status='Failed',error='Transport failed')
        self.run_cycle()
        self.payloads['A']['stock_quantity']=10;self.sync=original;self.now+=timedelta(minutes=3)
        self.run_cycle()
        self.assertEqual(self.calls,['A'])
        self.assertEqual(self.store.states['a'].attempts,0)

    def test_time_budget_does_not_start_another_target_after_cutoff(self):
        self.setup_case();self.m.monotonic=Mock(side_effect=[0,1,100])
        result=self.run_cycle()
        self.assertEqual(self.calls,['A'])
        self.assertEqual(result['batch_deferred'],1)

    def test_busy_failing_target_cannot_starve_unverified_healthy_target(self):
        self.setup_case();self.m.MAX_PRODUCTS_PER_RUN=1
        calls=[]
        def sync(mapping,config,client,**kwargs):
            calls.append(mapping['name'])
            if mapping['name']=='a':return dict(status='Failed',error='Wrong SKU')
            return dict(status='Updated',payload=self.payloads['B'])
        self.sync=sync;self.run_cycle()
        self.now+=timedelta(seconds=65)
        self.store.states['a'].update(requested_version=2,next_retry=None,attempts=0)
        self.run_cycle()
        self.assertEqual(calls,['a','b'])

    def test_live_export_recomputes_stock_after_the_candidate_snapshot(self):
        self.setup_case()
        original=self.sync
        def sync(mapping,config,client,**kwargs):
            self.payloads[mapping['item_code']]['stock_quantity']=3
            return original(mapping,config,client,**kwargs)
        self.sync=sync
        self.run_cycle()
        expected=self.m.payload_hash(self.maps[0],self.payloads['A'])
        self.assertEqual(self.store.states['a'].last_payload_hash,expected)

    def test_bootstrap_is_bounded_and_remaining_items_are_not_starved(self):
        self.setup_case()
        self.maps=[dict(name='link%02d'%n,item_code='I%02d'%n,product_id=n+1,sku=str(n),sync_stock=1,sync_price=0) for n in range(30)]
        self.payloads={m['item_code']:dict(stock_quantity=10) for m in self.maps}
        first=self.run_cycle();self.assertEqual(len(self.calls),25);self.assertEqual(first['batch_deferred'],5)
        self.calls[:]=[];self.run_cycle();self.assertEqual(len(self.calls),5)
        self.calls[:]=[];self.run_cycle();self.assertEqual(self.calls,[])

    def test_unchanged_local_check_does_not_extend_remote_verification_time(self):
        self.setup_case();self.run_cycle();verified=self.store.states['a'].last_verified
        self.now+=timedelta(minutes=30);self.run_cycle()
        self.assertEqual(self.store.states['a'].last_verified,verified)

if __name__=='__main__':unittest.main()
