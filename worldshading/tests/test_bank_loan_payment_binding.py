"""One native JV link; server-owned breakdowns and accounting remain atomic."""
import json
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
import frappe
from worldshading.api import bank_loan_payments as api
from worldshading.api import bank_loan_setup as setup
from worldshading.tests import test_bank_loan_payment_api as fixture
Row=fixture.Row


class TestPaymentBinding(unittest.TestCase):
    def setUp(self):
        fixture.TestPaymentAPI.setUp(self)
        self.doc=fixture.TestPaymentAPI.document(self)
        self.doc.flags=Row()
        frappe.throw.side_effect=lambda message,*args,**kwargs: (_ for _ in ()).throw(ValueError(message))
        self.payment=Row(bank_loan='LOAN-1',journal_entry='JV-new',request_id='a'*32,
            payment_bank='Bank',before_tracking=0,reason=None,account_snapshot=json.dumps(self.mapping),
            allocations=json.dumps([dict(r) for r in self.doc.allocations]))
        # The native JV has only its Bank Loan link; remove former custom data entirely.
        for key in api.PAYMENT_FIELDS+('allocations',):self.doc.pop(key,None)

    def test_schema_adds_only_one_jv_field(self):
        self.assertEqual([r['fieldname'] for r in setup.FIELDS],['custom_bank_loan'])
        fields=json.loads(Path('worldshading/fixtures/custom_field.json').read_text())
        self.assertFalse(any(r.get('dt')=='Journal Entry' and r.get('fieldname') in setup.LEGACY_FIELDS for r in fields))

    def test_direct_link_without_breakdown_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Prepare or link'):api.validate_journal(self.doc)

    def test_new_payment_stores_normalized_breakdown_without_adding_jv_data(self):
        self.doc.flags.bank_loan_payment=self.payment
        with patch.object(api,'_store_payment') as store:
            api.validate_journal(self.doc)
        context=store.call_args[0][1]
        self.assertEqual(context.allocations[0].principal_amount,100)
        self.assertEqual(context.allocations[0].currency,'BHD')
        self.assertNotIn('allocations',self.doc)
        self.assertNotIn('snapshot',self.doc)

    def test_saved_payment_uses_server_record_not_client_breakdown(self):
        self.doc.allocations=[Row(principal_amount=999)]
        self.doc.get_doc_before_save=lambda:self.doc
        with patch.object(api,'_payment_record',return_value=self.payment),patch.object(api,'_store_payment') as store:
            api.validate_journal(self.doc)
        store.assert_not_called()

    def test_mismatched_native_posting_is_rejected(self):
        self.doc.accounts[0].debit=50
        self.doc.get_doc_before_save=lambda:self.doc
        with patch.object(api,'_payment_record',return_value=self.payment):
            with self.assertRaisesRegex(ValueError,'account amounts'):api.validate_journal(self.doc)

    def test_payment_cannot_bind_to_another_loan(self):
        self.payment.bank_loan='LOAN-2'
        with patch.object(api,'_payment_record',return_value=self.payment):
            with self.assertRaisesRegex(ValueError,'another Bank Loan'):api.validate_journal(self.doc)

    def test_cancel_keeps_payment_record(self):
        old=Row(self.doc);old.docstatus=1
        self.doc.get_doc_before_save=lambda:old;self.doc.docstatus=2
        with patch.object(api,'_payment_record',return_value=self.payment),patch.object(api,'_store_payment') as store:
            api.before_cancel(self.doc)
        store.assert_not_called()

    def test_draft_deletion_removes_only_its_payment_record(self):
        self.payment.name='PAY-1'
        with patch.object(api,'_payment_record',return_value=self.payment),patch.object(frappe,'delete_doc') as delete:
            api.protect_journal_delete(self.doc)
        delete.assert_called_once_with('Bank Loan Payment','PAY-1',ignore_permissions=True,flags={'from_bank_loan_service':True})

    def test_native_amendment_gets_fresh_payment_reference(self):
        self.doc.amended_from='JV-cancelled'
        db=Mock();db.get_value.return_value=Row(docstatus=2,custom_bank_loan='LOAN-1')
        def record(name,**kwargs):return self.payment if name=='JV-cancelled' else None
        with patch.object(frappe,'db',db,create=True),patch.object(api,'_payment_record',side_effect=record),patch.object(frappe,'generate_hash',return_value='b'*32),patch.object(api,'_store_payment') as store:
            api.validate_journal(self.doc)
        self.assertEqual(store.call_args[0][1].request_id,'b'*32)

    def test_retry_returns_same_saved_jv(self):
        db=Mock();db.sql.return_value=[Row(bank_loan='LOAN-1',journal_entry='JV-new')]
        journal=Mock();journal.as_dict.return_value={'name':'JV-new','docstatus':0}
        with patch.object(frappe,'db',db,create=True),patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_doc',return_value=journal):
            result=api.make_payment('LOAN-1',[],request_id='a'*32)
        self.assertEqual(result['name'],'JV-new');journal.insert.assert_not_called()
        journal.check_permission.assert_called_once_with('read')



class TestPaymentHistory(unittest.TestCase):
    def test_join_reads_allocations_and_native_status_in_one_query(self):
        db=Mock();db.sql.return_value=[Row(name='JV-1',docstatus=2,before_tracking=0,allocations='[]')]
        with patch.object(frappe,'db',db,create=True):rows=api.payment_documents('LOAN-1',for_update=True)
        self.assertEqual(rows[0]['docstatus'],2)
        self.assertEqual(rows[0]['allocations'],[])
        db.sql.assert_called_once()
        self.assertIn('inner join',db.sql.call_args[0][0])
        self.assertTrue(db.sql.call_args[0][0].endswith('for update'))


class TestPaymentMigration(unittest.TestCase):
    def test_legacy_breakdown_is_copied_before_fields_are_removed(self):
        db=Mock();db.exists.side_effect=lambda dt,filters: dt=='Custom Field'
        legacy=Row(name='JV-legacy',custom_loan_request='a'*32,custom_loan_bank_account='Bank',
            custom_loan_before_tracking=1,custom_loan_variance_reason='Historical',
            custom_loan_snapshot='{}',custom_loan_allocations=[Row(principal_amount=10)])
        with patch.object(frappe,'db',db,create=True),patch.object(frappe,'get_all',return_value=[Row(name=legacy.name)]),patch.object(frappe,'get_doc',return_value=legacy),patch.object(api,'_store_payment') as store:
            setup.migrate_payment_details()
        store.assert_called_once()
        self.assertEqual(store.call_args[0][1].allocations,[{'principal_amount':10}])
        self.assertEqual(store.call_args[0][1].request_id,'a'*32)
        self.assertEqual(store.call_args[0][1].before_tracking,1)

    def test_server_owned_record_rejects_direct_edits_and_deletion(self):
        from worldshading.worldshading.doctype.bank_loan_payment.bank_loan_payment import BankLoanPayment
        obj=Row(flags=Row())
        with patch.object(frappe,'throw',side_effect=ValueError):
            with self.assertRaises(ValueError):BankLoanPayment.validate(obj)
            with self.assertRaises(ValueError):BankLoanPayment.on_trash(obj)
        obj.flags.from_bank_loan_service=True
        BankLoanPayment.validate(obj)
        BankLoanPayment.on_trash(obj)

class TestDraftAdjustment(unittest.TestCase):
    setUp=TestPaymentBinding.setUp
    def test_adjustment_rebuilds_ledger_and_saves_breakdown_atomically(self):
        self.doc.modified='original';self.doc.posting_date='2026-12-19'
        self.doc.set=lambda key,value:self.doc.__setitem__(key,value)
        self.doc.append=lambda key,value:self.doc[key].append(Row(value))
        self.doc.check_permission=Mock();self.doc.save=Mock()
        self.mapping['cost_center']='Main'
        self.source.currency='BHD'
        record=Row(self.payment);record.flags=Row();record.save=Mock()
        db=Mock()
        rows=[dict(installment='row-1',principal_amount=0,interest_amount=10,charges_amount=3)]
        with patch.object(api,'_editable_payment',return_value=(self.source,self.doc,record)),patch.object(frappe,'db',db,create=True):
            api.update_draft_payment('JV-new',rows,'original',posting_date='2026-12-19',reason='Interest only plus bank fee')
        posting={r.account:r.debit-r.credit for r in self.doc.accounts}
        self.assertEqual(posting,{'Interest':10,'Fees':3,'Bank':-13})
        saved=json.loads(record.allocations)
        self.assertEqual(saved[0]['principal_amount'],0)
        self.assertEqual(saved[0]['charges_amount'],3)
        self.assertEqual(record.reason,'Interest only plus bank fee')
        self.doc.save.assert_called_once();record.save.assert_called_once()

    def test_failed_native_save_rolls_back_payment_record_change(self):
        self.doc.modified='original';self.doc.set=lambda k,v:self.doc.__setitem__(k,v)
        self.doc.append=lambda k,v:self.doc[k].append(Row(v))
        self.doc.save=Mock(side_effect=ValueError('native permission refused'))
        record=Row(self.payment);record.flags=Row();record.save=Mock()
        db=Mock()
        with patch.object(api,'_editable_payment',return_value=(self.source,self.doc,record)),patch.object(frappe,'db',db,create=True):
            with self.assertRaisesRegex(ValueError,'native permission'):
                api.update_draft_payment('JV-new',json.loads(record.allocations),'original',reason='Correction')
        self.assertIn(('rollback to savepoint bank_loan_adjustment',),[c[0] for c in db.sql.call_args_list])

    def test_adjustment_rejects_stale_and_changed_installment_and_requires_reason(self):
        self.doc.modified='newer'
        record=Row(self.payment);record.flags=Row();record.save=Mock()
        with patch.object(api,'_editable_payment',return_value=(self.source,self.doc,record)):
            with self.assertRaisesRegex(ValueError,'changed'):api.update_draft_payment('JV-new',[],'older',reason='x')
            with self.assertRaisesRegex(ValueError,'reason'):api.update_draft_payment('JV-new',[],'newer')
            with self.assertRaisesRegex(ValueError,'installment'):api.update_draft_payment('JV-new',[dict(installment='different',principal_amount=100)],'newer',reason='x')

class TestAutomaticPaymentService(unittest.TestCase):
    def setUp(self):
        self.db=Mock();self.db.sql.return_value=[Row(name='LOAN-1')]
        p=patch.object(frappe,'db',self.db,create=True);p.start();self.addCleanup(p.stop)
        self.source=Row(name='LOAN-1',workflow_state='Approved',status='Active')
        self.source.precision=lambda field:3
        self.terms=dict(opening_principal=1000,tracking_start_date='2026-01-01',schedule=[
            dict(name='row-1',due_date='2026-12-19',principal_amount=100,interest_amount=10,charges_amount=2)])
        for name,value in [('_source',self.source),('approved_terms',self.terms),('payment_documents',[]),('nowdate','2026-12-17')]:
            p=patch.object(api,name,return_value=value);p.start();self.addCleanup(p.stop)

    def test_job_uses_due_date_and_stable_reference_on_retry(self):
        with patch.object(api,'make_payment') as make:
            api.create_due_payments();api.create_due_payments()
        first=make.call_args_list[0]
        self.assertEqual(first[0][0],'LOAN-1')
        self.assertEqual(first[0][1][0]['principal_amount'],100)
        self.assertEqual(first[0][1][0]['interest_amount'],10)
        self.assertEqual(first[1]['posting_date'],'2026-12-19')
        self.assertEqual(first[1]['request_id'],make.call_args_list[1][1]['request_id'])
        self.assertLessEqual(len(first[1]['request_id']),64)
        self.assertEqual(self.db.commit.call_count,2)

    def test_job_recovers_from_one_bad_loan_without_committing_its_partial_jvs(self):
        self.db.sql.return_value=[Row(name='LOAN-1'),Row(name='LOAN-2')]
        first=Row(self.source);second=Row(self.source);second.name='LOAN-2'
        with patch.object(api,'_source',side_effect=[first,second]),patch.object(api,'make_payment',side_effect=[ValueError('bad ledger'),{}]) as make,patch.object(frappe,'log_error',create=True),patch.object(frappe,'get_traceback',return_value='error'):
            api.create_due_payments()
        self.assertEqual(make.call_count,2)
        self.db.rollback.assert_called_once();self.db.commit.assert_called_once()

    def test_changed_loan_state_is_rechecked_under_lock(self):
        self.source.workflow_state='Draft'
        with patch.object(frappe,'throw',side_effect=ValueError),patch.object(api,'make_payment') as make,patch.object(frappe,'log_error',create=True),patch.object(frappe,'get_traceback',return_value='error'):
            api.create_due_payments()
        make.assert_not_called();self.db.rollback.assert_called_once()
