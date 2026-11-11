"""Standalone journal adapter tests; all documents are fixtures, no DB/site."""
import unittest
from unittest.mock import patch
from datetime import date
from types import SimpleNamespace
import frappe
from worldshading.worldshading.report.cashflow_forecast.sources import Sources
try:
    from worldshading.worldshading.report.cashflow_forecast.journals import Journals
except ImportError:
    Journals = None


class Doc(SimpleNamespace):
    def get(self,key,default=None): return getattr(self,key,default)


def journal(name='JV-1',day='2026-11-01',status=0,state='Pending Reconciliation',rows=None):
    return Doc(name=name,posting_date=day,docstatus=status,workflow_state=state,transaction_type='Bank Transfer',
               accounts=[frappe._dict(r) for r in (rows or [dict(account='Bank',credit=500),dict(account='Expense',debit=500)])])


class JournalAdapterTests(unittest.TestCase):
    def source(self, docs, include=False):
        s=Sources.__new__(Sources)
        s.company,s.currency,s.accounts='Example','BHD',['Bank','Cash']
        s.start,s.end=date(2026,11,9),date(2026,12,31)
        s.events,s.overdue,s.warnings=[],[],[]
        s.include_overdue=include
        s.documents=lambda dt,filters=None: iter([d for d in docs if dt=='Journal Entry' and d.docstatus==filters['docstatus']])
        return s

    def adapter(self,s):
        return Journals(s)

    def metadata(self,account):
        return frappe._dict(account_name=account,account_type='Payable' if account=='Payable' else '',root_type='Expense' if account=='Expense' else 'Liability')

    def test_pending_outgoing_je_enters_overdue_but_plain_draft_and_rejected_do_not(self):
        source=self.source([journal(),journal('DRAFT',state='Draft'),journal('REJECTED',state='Rejected')])
        with patch.object(Journals,'workflow_states',return_value={'Pending Reconciliation'}),patch.object(Journals,'account_info',side_effect=self.metadata):
            self.adapter(source).emit()
        self.assertEqual([r['name'] for r in source.overdue],['JV-1'])
        self.assertEqual(source.events,[])

    def test_checked_overdue_is_today_and_future_journal_stays_future(self):
        source=self.source([journal(),journal('JV-FUTURE',day='2026-12-01')],True)
        with patch.object(Journals,'workflow_states',return_value={'Pending Reconciliation'}),patch.object(Journals,'account_info',side_effect=self.metadata):
            self.adapter(source).emit()
        self.assertEqual([r['date'] for r in source.events],[date(2026,11,9),date(2026,12,1)])
        self.assertEqual(sum(r['amount'] for r in source.events),1000)

    def test_internal_noncash_and_draft_incoming_do_not_create_payments(self):
        docs=[journal('TRANSFER',rows=[dict(account='Bank',credit=500),dict(account='Cash',debit=500)]),
              journal('NONCASH',rows=[dict(account='Expense',debit=500),dict(account='Payable',credit=500)]),
              journal('RECEIPT',rows=[dict(account='Bank',debit=500),dict(account='Income',credit=500)])]
        source=self.source(docs,True)
        with patch.object(Journals,'workflow_states',return_value={'Pending Reconciliation'}),patch.object(Journals,'account_info',side_effect=self.metadata):
            self.adapter(source).emit()
        self.assertEqual(source.events,[])
        self.assertEqual(source.overdue,[])

    def test_explicit_invoice_payment_is_reserved_once_even_when_unchecked(self):
        source=self.source([journal(rows=[dict(account='Bank',credit=500),dict(account='Payable',debit=500,
             reference_type='Purchase Invoice',reference_name='PI-1',party_type='Supplier',party='SUP-1')])])
        with patch.object(Journals,'workflow_states',return_value={'Pending Reconciliation'}),patch.object(Journals,'account_info',side_effect=self.metadata):
            adapter=self.adapter(source)
            reserved=adapter.reserve('Purchase Invoice','PI-1',500)
            adapter.emit()
        self.assertEqual(reserved,500)
        self.assertEqual(sum(r['amount'] for r in source.overdue),500)
        self.assertEqual(source.overdue[0]['doctype'],'Journal Entry')
        self.assertEqual(source.overdue[0]['related_name'],'PI-1')

    def test_salary_without_payroll_reference_is_flagged_without_guessing_period(self):
        source=self.source([journal(rows=[dict(account='Bank',credit=500),dict(account='Payroll Payable',debit=500)])])
        with patch.object(Journals,'workflow_states',return_value={'Pending Reconciliation'}),patch.object(Journals,'account_info',side_effect=self.metadata):
            self.adapter(source).emit()
        self.assertEqual(source.overdue[0]['category'],'payroll')
        self.assertIn('Payroll Entry',source.overdue[0]['review_note'])
        self.assertTrue(source.warnings)

    def test_already_posted_today_not_readded_and_future_posted_retained(self):
        source=self.source([journal('POSTED',status=1,day='2026-11-01',state='Completed'),
             journal('POSTED-FUTURE',status=1,day='2026-12-01',state='Completed')],True)
        with patch.object(Journals,'account_info',side_effect=self.metadata):
            self.adapter(source).emit()
        self.assertEqual([r['name'] for r in source.events],['POSTED-FUTURE'])
        self.assertEqual(source.overdue,[])

    def test_competing_or_already_covered_invoice_is_flagged(self):
        source=self.source([journal(rows=[dict(account='Bank',credit=500),dict(account='Payable',debit=500,
            reference_type='Purchase Invoice',reference_name='PI-1',party_type='Supplier')])])
        with patch.object(Journals,'workflow_states',return_value={'Pending Reconciliation'}),patch.object(Journals,'account_info',side_effect=self.metadata):
            adapter=self.adapter(source)
            adapter.reserve('Purchase Invoice','PI-1',0)
            adapter.emit()
        self.assertEqual(sum(r['amount'] for r in source.overdue),500)
        self.assertIn('competing',source.overdue[0]['review_note'])

    def test_same_reference_cannot_consume_more_than_its_explicit_amount(self):
        source=self.source([journal(rows=[dict(account='Bank',credit=500),dict(account='Payable',debit=300,
            reference_type='Purchase Invoice',reference_name='PI-1'),dict(account='Expense',debit=200)])])
        with patch.object(Journals,'workflow_states',return_value={'Pending Reconciliation'}),patch.object(Journals,'account_info',side_effect=self.metadata):
            adapter=self.adapter(source)
            self.assertEqual(adapter.reserve('Purchase Invoice','PI-1',300),300)
            self.assertEqual(adapter.reserve('Purchase Invoice','PI-1',300),0)


if __name__=='__main__': unittest.main()
