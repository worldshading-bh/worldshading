"""Account exclusions are scoped, permission checked, and retain company liabilities."""
import unittest
from unittest.mock import patch,Mock
from types import SimpleNamespace
from datetime import date
import frappe
from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
from worldshading.worldshading.report.cashflow_forecast.sources import Sources
from worldshading.worldshading.report.cashflow_forecast.journals import Journals
from worldshading.worldshading.report.cashflow_forecast import test_journals as journal_fixture,test_vat as vat_fixture

class ExcludedAccounts(unittest.TestCase):
    def test_default_all_and_scoped_deduplicated_exclusions(self):
        with patch.object(report,'resolve_accounts',return_value=['Bank','Cash','Deposit']):
            self.assertEqual(report.selected_accounts('Example',None),['Bank','Cash','Deposit'])
            self.assertEqual(report.selected_accounts('Example','["Deposit","Deposit"]'),['Bank','Cash'])
            for value in [['Other Company Bank'],['Bank Parent'],['Outside'],['Bank','Cash','Deposit'],[1],{}]:
                with patch.object(frappe,'throw',side_effect=ValueError),self.assertRaises(ValueError):
                    report.selected_accounts('Example',value)

    def test_validate_normalizes_and_applies_selected_accounts(self):
        with patch.object(report,'authorize'),patch.object(report,'nowdate',return_value='2026-11-15'), \
             patch.object(report,'resolve_accounts',return_value=['Bank','Cash','Deposit']):
            values,start,end,accounts,extra=report.validate(dict(company='Example',end_date='2027-01-01',excluded_accounts=['Deposit','Deposit']))
        self.assertEqual(accounts,['Bank','Cash']);self.assertEqual(values.excluded_accounts,['Deposit'])

    def test_opening_queries_full_pool_once_but_excluded_balance_not_available(self):
        source=Sources.__new__(Sources)
        source.company='Example';source.start=date(2026,11,15)
        source.accounts=['Bank'];source.liquidity_accounts=['Bank','Deposit'];source.accounts_breakdown=[]
        sql=Mock(return_value=[frappe._dict(account='Bank',balance=100),frappe._dict(account='Deposit',balance=200)])
        with patch.object(frappe,'db',SimpleNamespace(sql=sql)):
            source.opening()
        self.assertEqual(sql.call_count,1)
        self.assertEqual(source.opening_balance,100)
        self.assertEqual([r['account'] for r in source.accounts_breakdown],['Bank'])
        self.assertEqual(source.excluded_accounts_breakdown,[dict(account='Deposit',amount=200)])

    def test_account_dropdown_names_do_not_query_ledger_balances(self):
        sql=Mock(side_effect=AssertionError('Dropdown must not load ledger balances'))
        with patch.object(report,'authorize'),patch.object(report,'resolve_accounts',return_value=['Bank','Cash']), \
             patch.object(frappe,'db',SimpleNamespace(sql=sql)):
            options=report.get_accounts('Example',names_only=1)
        self.assertEqual([r['value'] for r in options],['Bank','Cash']);sql.assert_not_called()

    def test_excluded_bank_does_not_hide_supplier_journal_obligation(self):
        fixture=journal_fixture.JournalAdapterTests()
        doc=journal_fixture.journal(day='2026-12-01',rows=[dict(account='Bank',credit=500),
            dict(account='Payable',debit=500,reference_type='Purchase Invoice',reference_name='PI',party_type='Supplier')])
        source=fixture.source([doc],True);source.accounts=['Cash'];source.liquidity_accounts=['Bank','Cash']
        with patch.object(Journals,'workflow_states',return_value={'Pending Reconciliation'}), \
             patch.object(Journals,'account_info',side_effect=fixture.metadata):
            adapter=Journals(source)
            self.assertEqual(adapter.reserve('Purchase Invoice','PI',500),500)
            adapter.emit()
        self.assertEqual(sum(e['amount'] for e in source.events),500)

    def test_transfers_crossing_excluded_pool_have_selected_net_effect(self):
        fixture=journal_fixture.JournalAdapterTests()
        docs=[journal_fixture.journal('OUT',day='2026-12-01',rows=[dict(account='Cash',credit=100),dict(account='Bank',debit=100)]),
              journal_fixture.journal('IN',day='2026-12-02',rows=[dict(account='Bank',credit=200),dict(account='Cash',debit=200)])]
        source=fixture.source(docs,True);source.accounts=['Cash'];source.liquidity_accounts=['Bank','Cash']
        with patch.object(Journals,'workflow_states',return_value={'Pending Reconciliation'}), \
             patch.object(Journals,'account_info',side_effect=fixture.metadata):Journals(source).emit()
        self.assertEqual([(e['name'],e['category'],e['amount']) for e in source.events],
            [('OUT','other_payments',100),('IN','other_receipts',200)])

    def test_paid_vat_from_excluded_bank_still_clears_quarter(self):
        fixture=vat_fixture.VatSourceTests()
        source=fixture.source('2026-02-10','2026-04-30');source.accounts=['Cash'];source.liquidity_accounts=['Bank','Cash']
        doc=fixture.journal('JV-PAID','2026-01-15','Output VAT – Sales - WS',100,'VAT Q4 2025')
        candidates=[frappe._dict(voucher_type='Journal Entry',voucher_no=doc.name,posting_date=doc.posting_date,change_amount=-100)]
        periods=[frappe._dict(year=2025,period=4,amount=100),frappe._dict(year=2026,period=1,amount=-50)]
        account=SimpleNamespace(check_permission=lambda *args:None)
        sql=Mock(side_effect=[candidates,periods])
        with patch.object(frappe,'has_permission',return_value=True), \
             patch.object(frappe,'get_doc',side_effect=lambda dt,name:account if dt=='Account' else doc), \
             patch.object(frappe,'db',SimpleNamespace(exists=lambda *args:True,sql=sql)):
            source.tax_position()
        q4=next(row for row in source._vat_data.summary if row['quarter']=='Q4 2025')
        self.assertEqual(q4['paid'],'100.000');self.assertEqual(q4['balance'],'0.000')
        self.assertEqual(set(sql.call_args_list[0][0][1][-1]),{'Bank','Cash'})

    def test_incoming_to_excluded_bank_is_not_available_cash(self):
        fixture=journal_fixture.JournalAdapterTests()
        doc=journal_fixture.journal('FUTURE-IN',day='2026-12-01',status=1,state='Completed',
            rows=[dict(account='Bank',debit=200),dict(account='Income',credit=200)])
        source=fixture.source([doc],True);source.accounts=['Cash'];source.liquidity_accounts=['Bank','Cash']
        with patch.object(Journals,'account_info',side_effect=fixture.metadata):Journals(source).emit()
        self.assertEqual(source.events,[])
        for account,expected in [('Bank',0),('Cash',100)]:
            source.events=[]
            glp=journal_fixture.Doc(name='GL-IN',posting_date=date(2026,12,1),payment_type='Incoming',payment_account=account,total_amount=100)
            source.gl_payment(glp)
            self.assertEqual(sum(e['amount'] for e in source.events),expected)

    def test_horizon_receives_selected_cash_and_full_liquidity_for_obligations(self):
        with patch.object(report,'authorize'),patch.object(report,'nowdate',return_value='2026-11-15'), \
             patch.object(report,'resolve_accounts',return_value=['Bank','Deposit']), \
             patch.object(report,'minimum_purchase_end',return_value=None) as minimum:
            result,change=report.normalize_generation_filters(dict(company='Example',end_date='2027-01-01',excluded_accounts=['Deposit']))
        minimum.assert_called_once_with('Example',['Bank'],date(2026,11,15),['Bank','Deposit'])
        self.assertEqual(result['excluded_accounts'],['Deposit'])

    def test_exclusions_cannot_bypass_cached_api_company_account_validation(self):
        from worldshading.worldshading.report.cashflow_forecast import prepared_access
        with patch.object(prepared_access,'authorize'),patch.object(report,'resolve_accounts',return_value=['Bank']), \
             patch.object(frappe,'throw',side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                prepared_access.guard_request('Cashflow Forecast',dict(company='Example',excluded_accounts=['Foreign Bank']))

    def test_changed_exclusions_require_rebuild_before_purchase_replay(self):
        from worldshading.worldshading.report.cashflow_forecast import prepared_access
        base=dict(company='Example',end_date='2027-01-01')
        with patch.object(report,'authorize'),patch.object(report,'nowdate',return_value='2026-11-15'), \
             patch.object(report,'resolve_accounts',return_value=['Bank','Deposit']):
            normalized=report.validate(base)[0]
            saved=dict(result=[dict(_cashflow_context=dict(vat_policy='quarter-v4',today_policy='auto-v1',
                calculation_inputs={'opening_balance':100},base_filters=normalized))])
            def reject(message,*args):raise ValueError(message)
            with patch.object(prepared_access,'run',return_value=saved),patch.object(frappe,'throw',side_effect=reject):
                with self.assertRaisesRegex(ValueError,'Forecast filters have changed'):
                    report.recalculate_purchase('SAVED',dict(base,excluded_accounts=['Deposit']))
