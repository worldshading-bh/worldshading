"""Bank-loan forecast reconciliation; fixtures only, never initializes a site."""
import json
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch,Mock
import frappe
from worldshading.worldshading.report.cashflow_forecast.sources import Sources
from worldshading.worldshading.report.cashflow_forecast.journals import Journals
from worldshading.worldshading.report.cashflow_forecast.engine import money,as_date,build_forecast,monthly_rows
from worldshading.worldshading.report.cashflow_forecast.bank_loans import BankLoans

COMPONENTS=('principal_amount','interest_amount','charges_amount')
def row(name='I1',due='2026-12-19',principal=100,interest=10,charges=2):
    return dict(name=name,due_date=due,principal_amount=principal,interest_amount=interest,charges_amount=charges)
def allocation(key='I1',principal=100,interest=10,charges=2):
    return dict(installment=key,principal_amount=principal,interest_amount=interest,charges_amount=charges)
def loan(schedule=None,state='Approved',approved=True):
    schedule=[row()] if schedule is None else schedule
    plan=dict(company='Example',currency='BHD',opening_principal=1000,schedule=schedule)
    return frappe._dict(name='BL1',company='Example',currency='BHD',loan_name='Bank facility',status='Active',
        workflow_state=state,approved_plan=json.dumps(plan) if approved else None,schedule=schedule)
def payment(name='JV1',day='2026-12-20',status=0,state='Pending Reconciliation',allocations=None,before=False,cash=None):
    allocations=[allocation()] if allocations is None else allocations
    total=sum((money(a.get(k)) for a in allocations for k in COMPONENTS),money(0)) if cash is None else money(cash)
    doc=frappe._dict(name=name,company='Example',posting_date=day,docstatus=status,workflow_state=state,
        transaction_type='Other Expenses',custom_bank_loan='BL1',accounts=[frappe._dict(account='Bank',credit=total),frappe._dict(account='Loan',debit=total)])
    record=frappe._dict(name='PAY-'+name,bank_loan='BL1',journal_entry=name,before_tracking=int(before),allocations=json.dumps(allocations))
    return doc,record

class BankLoanTests(unittest.TestCase):
    def collect(self,loans=None,payments=None,include=False,end='2027-02-28',permitted=True):
        loans=[loan()] if loans is None else loans;payments=payments or []
        source=Sources.__new__(Sources);source.company='Example';source.currency='BHD';source.accounts=['Bank'];source.liquidity_accounts=['Bank']
        source.start=date(2026,11,21);source.end=as_date(end)
        source.events=[];source.overdue=[];source.warnings=[];source.include_overdue=include
        docs={( 'Bank Loan',d.name):d for d in loans};docs.update({('Journal Entry',d.name):d for d,p in payments})
        def read(dt,name):
            doc=docs[(dt,name)]
            if doc.get('denied'):raise frappe.PermissionError('Denied')
            return doc
        source.read_document=read
        def documents(dt,filters=None):
            if dt=='Bank Loan':return iter(loans)
            if dt=='Journal Entry':
                return iter(d for d,p in payments if d.docstatus==filters['docstatus'] and (d.docstatus==0 or source.start<as_date(d.posting_date)<=source.end))
            return iter([])
        source.documents=documents
        def listing(dt,**kwargs):
            self.assertEqual(dt,'Bank Loan Payment');return [p for d,p in payments]
        with patch.object(frappe,'has_permission',return_value=permitted),patch.object(frappe,'db',SimpleNamespace(exists=lambda *args:True)), \
             patch.object(frappe,'get_list',side_effect=listing) as query,patch.object(Journals,'workflow_states',return_value={'Pending Reconciliation'}), \
             patch.object(Journals,'account_info',side_effect=lambda account:frappe._dict(account_name=account)):
            BankLoans(source).collect();source.loan_loaded_journals=source.journals().loaded;source.journals().emit()
        source.payment_query_count=query.call_count
        return source

    def test_unpaid_schedule_includes_principal_interest_and_charges(self):
        s=self.collect();self.assertEqual([(e['date'],e['category'],e['amount']) for e in s.events],[(date(2026,12,19),'bank_loan_repayments',112)])
        self.assertEqual(s.events[0]['principal_amount'],100);self.assertEqual(s.events[0]['interest_amount'],10);self.assertEqual(s.events[0]['charges_amount'],2)
        self.assertEqual(s.payment_query_count,1)

    def test_posted_through_today_paid_once_and_historical_not_duplicated(self):
        for day in ['2026-11-19','2026-11-21']:
            s=self.collect(payments=[payment(day=day,status=1,state='Completed')]);self.assertFalse(s.events);self.assertFalse(s.overdue)

    def test_future_posted_uses_jv_date_not_schedule_and_never_other_payments(self):
        s=self.collect(payments=[payment(day='2027-01-15',status=1,state='Completed')])
        self.assertEqual([(e['date'],e['amount'],e['category']) for e in s.events],[(date(2027,1,15),112,'bank_loan_repayments')])

    def test_pending_partial_replaces_only_allocated_components(self):
        s=self.collect(payments=[payment(allocations=[allocation(principal=40,interest=5,charges=0)])])
        self.assertEqual([(e['date'],e['amount']) for e in s.events],[(date(2026,12,20),45),(date(2026,12,19),67)])
        self.assertEqual(s.events[1]['interest_amount'],5);self.assertFalse(any(e['category']=='other_payments' for e in s.events))

    def test_plain_draft_or_cancelled_payment_does_not_clear_schedule(self):
        for p in [payment(state='Draft'),payment(status=2,state='Cancelled')]:
            s=self.collect(payments=[p]);self.assertEqual(sum(e['amount'] for e in s.events),112);self.assertEqual(s.events[0]['date'],date(2026,12,19))

    def test_cancelled_and_amended_jv_count_once(self):
        s=self.collect(payments=[payment(name='CANCELLED',status=2),payment(name='AMENDED',status=1)])
        self.assertEqual(sum(e['amount'] for e in s.events),112)

    def test_before_tracking_historical_payment_not_deducted_again(self):
        s=self.collect(payments=[payment(day='2026-01-01',status=1,before=True)])
        self.assertEqual(sum(e['amount'] for e in s.events),112)

    def test_payment_after_forecast_end_still_replaces_earlier_installment(self):
        for status in [0,1]:
            s=self.collect(payments=[payment(day='2027-03-01',status=status)])
            self.assertFalse(s.events);self.assertFalse(s.overdue)

    def test_pending_revision_uses_approved_snapshot(self):
        item=loan(state='Draft');item.schedule=[row(principal=999)]
        self.assertEqual(sum(e['amount'] for e in self.collect(loans=[item]).events),112)
        self.assertFalse(self.collect(loans=[loan(state='Draft',approved=False)]).events)

    def test_no_future_loan_jv_does_not_eagerly_load_the_general_journal_list(self):
        s=self.collect(payments=[payment(day='2026-11-19',status=1,state='Completed')])
        self.assertFalse(s.loan_loaded_journals)

    def test_pending_currency_revision_keeps_the_last_approved_company_currency_plan(self):
        item=loan(state='Draft');item.currency='USD'
        s=self.collect(loans=[item]);self.assertEqual(sum(e['amount'] for e in s.events),112)

    def test_multi_installment_jv_and_partial_paid_component_matching(self):
        item=loan([row('I1'),row('I2','2027-01-19',200,20,0)])
        s=self.collect(loans=[item],payments=[payment(allocations=[allocation('I1'),allocation('I2',principal=100,interest=20,charges=0)])])
        self.assertEqual(sum(e['amount'] for e in s.events),332)
        self.assertEqual(sum(e['amount'] for e in s.events if e['date']==date(2027,1,19)),100)

    def test_overdue_follows_include_toggle_and_retains_original_due(self):
        item=loan([row(due='2026-10-19')])
        for include in [False,True]:
            s=self.collect(loans=[item],include=include);self.assertEqual(sum(e['amount'] for e in s.overdue),112)
            self.assertEqual(sum(e['amount'] for e in s.events),112 if include else 0)
            if include:self.assertEqual(s.events[0]['date'],s.start)

    def test_denied_loan_source_warns_and_hidden_journal_is_not_assumed_paid(self):
        s=self.collect(permitted=False);self.assertFalse(s.events);self.assertTrue(s.warnings)
        p=payment(status=1,day='2026-11-19');p[0].denied=True
        with self.assertRaises(frappe.PermissionError):self.collect(payments=[p])

    def test_closed_unpaid_loan_not_silently_written_off(self):
        item=loan(state='Closed');item.status='Closed'
        s=self.collect(loans=[item]);self.assertEqual(sum(e['amount'] for e in s.events),112);self.assertTrue(s.warnings)

    def test_discrepancy_is_not_allowed_to_erase_generic_cash(self):
        s=self.collect(payments=[payment(cash=200)])
        self.assertTrue(s.warnings);self.assertEqual(sum(e['amount'] for e in s.events if e['category']=='other_payments'),200)

    def test_forecast_daily_monthly_and_payment_totals_include_loans(self):
        s=self.collect();rows=build_forecast(s.start,s.end,1000,s.events,{})
        day=next(r for r in rows if r['date']==date(2026,12,19))
        self.assertEqual(day['bank_loan_repayments'],112);self.assertEqual(day['total_payments'],112)
        self.assertEqual(day['closing_cash'],888)
        month=next(r for r in monthly_rows(rows) if r['month']=='2026-12')
        self.assertEqual(month['bank_loan_repayments'],112)

    def test_column_snapshot_inputs_and_overdue_group(self):
        from worldshading.worldshading.report.cashflow_forecast.cashflow_forecast import columns,calculation_inputs
        from worldshading.worldshading.report.cashflow_forecast.rules import group_overdue_review
        s=self.collect(loans=[loan([row(due='2026-10-19')])],include=True)
        self.assertTrue(any(c['fieldname']=='bank_loan_repayments' and c['label']=='Bank Loan Repayments' for c in columns()))
        self.assertEqual(calculation_inputs(s)['bank_loan_names'],['BL1'])
        self.assertEqual(group_overdue_review(s.overdue)[0]['id'],'bank_loan_due')

    def test_cached_snapshot_rechecks_bank_loan_and_payment_permissions(self):
        from worldshading.worldshading.report.cashflow_forecast.prepared_access import check_payroll_access
        context=dict(bank_loan_names=['BL1'],bank_loan_payment_names=['PAY1'],bank_loan_journal_names=['JV1'],calculation_inputs={'company':'Example'})
        saved={'result':[{'_cashflow_context':context}]}
        def reject(message,*args,**kwargs):raise PermissionError(message)
        with patch.object(frappe,'has_permission',return_value=False),patch.object(frappe,'throw',side_effect=reject):
            with self.assertRaises(PermissionError):check_payroll_access(saved)
        seen=[]
        def read(kind,name):
            seen.append((kind,name));return frappe._dict(company='Example',bank_loan='BL1',custom_bank_loan='BL1',check_permission=lambda *args:None)
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_doc',side_effect=read):
            check_payroll_access(saved)
        self.assertEqual(set(seen),{('Bank Loan','BL1'),('Bank Loan Payment','PAY1'),('Journal Entry','JV1')})
