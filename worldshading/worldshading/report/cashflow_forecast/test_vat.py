import unittest
from datetime import date
from worldshading.worldshading.report.cashflow_forecast import vat
from worldshading.worldshading.report.cashflow_forecast.engine import build_forecast


class VatTests(unittest.TestCase):
    def test_calendar_and_explicit_reference(self):
        self.assertEqual(vat.due_date('2026-12-31'),date(2027,1,25))
        self.assertEqual(vat.referenced_quarter('VAT amount paid for Q1 2026.'),date(2026,1,1))
        self.assertIsNone(vat.referenced_quarter('VAT adjustment'))

    def test_tax_transfer_and_mixed_expense_are_not_settlements(self):
        rows=[dict(account='Output',debit=100),dict(account='Bank',credit=100)]
        self.assertEqual(vat.settlement_amount(rows,{'Bank'},{'Output','Input'}),100)
        rows=[dict(account='Output',debit=100),dict(account='Input',credit=100)]
        self.assertEqual(vat.settlement_amount(rows,{'Bank'},{'Output','Input'}),0)
        rows=[dict(account='Output',debit=100),dict(account='Expense',debit=10),dict(account='Bank',credit=110)]
        self.assertEqual(vat.settlement_amount(rows,{'Bank'},{'Output','Input'}),0)

    def test_explicit_payment_and_credit_carry_reconcile(self):
        book=vat.VatBook('2026-11-10',{'balances':{'2026-01-01':100,'2026-04-01':-30,'2026-07-01':80}})
        book.allocate('2026-04-30',100,'2026-01-01')
        self.assertEqual(book.balances()[date(2026,7,1)],50)
        self.assertEqual(book.total(),50)

    def test_payment_on_25th_excludes_new_quarter_activity(self):
        events=[dict(date='2026-12-31',category='vat_accrual',amount=20),
                dict(date='2027-01-01',category='vat_accrual',amount=7)]
        rows=build_forecast('2026-12-31','2027-01-25',1000,events,{},vat_opening=100)
        self.assertEqual(rows[0]['quarterly_vat'],0)
        self.assertEqual(rows[-1]['quarterly_vat'],120)
        self.assertEqual(rows[-1]['vat_position'],7)

    def test_known_later_payment_replaces_due_day_estimate(self):
        events=[dict(date='2027-02-15',category='vat_settlement',amount=80,vat_quarter='2026-10-01')]
        rows=build_forecast('2026-12-31','2027-02-15',1000,events,{},vat_opening=100)
        self.assertEqual(next(r for r in rows if str(r['date'])=='2027-01-25')['quarterly_vat'],20)
        self.assertEqual(rows[-1]['quarterly_vat'],80)
        self.assertEqual(sum(r['quarterly_vat'] for r in rows),100)

    def test_import_payment_is_not_government_quarter_payment(self):
        rows=[dict(account='Input',debit=100),dict(account='Bank',credit=100)]
        self.assertEqual(vat.settlement_amount(rows,{'Bank'},{'Output','Input'},'Output'),0)
        rows=[dict(account='Output',debit=100),dict(account='Bank',credit=100)]
        self.assertEqual(vat.settlement_amount(rows,{'Bank'},{'Output','Input'},'Output'),100)

    def test_opening_old_quarter_and_current_quarter_stay_separate(self):
        opening={'balances':{'2026-07-01':100,'2026-10-01':50}}
        events=[dict(date='2026-11-10',category='vat_settlement',amount=100,vat_quarter='2026-07-01')]
        rows=build_forecast('2026-11-10','2027-01-25',1000,events,{},vat_opening=opening)
        self.assertEqual(rows[0]['quarterly_vat'],100)
        self.assertEqual(rows[-1]['quarterly_vat'],50)
        self.assertEqual(sum(r['quarterly_vat'] for r in rows),150)

    def test_credit_carries_into_next_quarter_and_refund_not_assumed(self):
        opening={'balances':{'2026-10-01':-50}}
        events=[dict(date='2027-01-15',category='vat_accrual',amount=80)]
        rows=build_forecast('2026-12-31','2027-04-25',1000,events,{},vat_opening=opening)
        self.assertEqual(rows[1]['quarterly_vat'],0)
        self.assertEqual(rows[-1]['quarterly_vat'],30)

    def test_month_end_forecast_excludes_next_day_payment(self):
        rows=build_forecast('2026-12-01','2026-12-31',1000,[],{},vat_opening=100)
        self.assertEqual(sum(r['quarterly_vat'] for r in rows),0)


class VatSourceTests(unittest.TestCase):
    def source(self,start,end):
        import frappe
        from worldshading.worldshading.report.cashflow_forecast.sources import Sources
        source=Sources.__new__(Sources)
        source.company='Example';source.accounts=['Bank'];source.payroll_account=None
        source.start=vat.as_date(start);source.end=vat.as_date(end)
        source.events=[];source.overdue=[];source.warnings=[];source.include_overdue=True
        return source

    def journal(self,name,posting,account,amount,remark=''):
        import frappe
        doc=frappe._dict(name=name,docstatus=1,posting_date=vat.as_date(posting),user_remark=remark)
        doc.check_permission=lambda *args:None
        doc.accounts=[frappe._dict(account=account,debit=amount,credit=0),frappe._dict(account='Bank',debit=0,credit=amount)]
        for row in doc.accounts:row.as_dict=lambda row=row:dict(row)
        return doc

    def test_latest_quarter_paid_je_has_no_historical_adjustment_warnings(self):
        import frappe
        from types import SimpleNamespace
        from unittest.mock import patch,Mock
        source=self.source('2026-05-01','2026-07-25')
        paid=self.journal('JV-PAID','2026-04-25','Output VAT – Sales - WS',95)
        adjustment=self.journal('JV-ADJUST','2026-01-10','Output VAT – Sales - WS',5)
        # Net VAT includes the ordinary adjustment; only the clear bank/tax JE is settlement proof.
        adjustment.accounts[1].account='Expense'
        candidates=[frappe._dict(voucher_type='Journal Entry',voucher_no=d.name,posting_date=d.posting_date,change_amount=-amount)
                    for d,amount in [(adjustment,5),(paid,95)]]
        periods=[frappe._dict(year=2026,period=1,amount=95),frappe._dict(year=2026,period=2,amount=-95)]
        docs={d.name:d for d in (adjustment,paid)}
        account=SimpleNamespace(check_permission=lambda *args:None)
        db=SimpleNamespace(exists=lambda *args:True,sql=Mock(side_effect=[candidates,periods]))
        with patch.object(frappe,'has_permission',return_value=True), \
             patch.object(frappe,'get_doc',side_effect=lambda dt,name:account if dt=='Account' else docs[name]), \
             patch.object(frappe,'db',db):
            source.tax_position();source._vat_data.finalize()
        self.assertEqual(source.warnings,[])
        self.assertEqual(source.overdue,[])
        row=next(r for r in source._vat_data.summary if r['quarter']=='Q1 2026')
        self.assertEqual(row['balance'],'0.000')
        self.assertEqual(row['documents'],[dict(doctype='Journal Entry',name='JV-PAID')])
        self.assertEqual(vat.VatBook(source.start,source.vat_opening).total(),0)

    def test_settlement_search_is_journal_only_but_gl_vat_stays_in_ledger(self):
        import frappe
        from types import SimpleNamespace
        from unittest.mock import patch,Mock
        source=self.source('2026-05-01','2026-07-25')
        account=SimpleNamespace(check_permission=lambda *args:None)
        db=SimpleNamespace(exists=lambda *args:True,sql=Mock(side_effect=[[],[frappe._dict(year=2026,period=1,amount=90)]]))
        with patch.object(frappe,'get_doc',return_value=account),patch.object(frappe,'db',db):
            source.tax_position();source._vat_data.finalize()
        query=db.sql.call_args_list[0][0][0]
        self.assertIn("voucher_type='Journal Entry'",query)
        self.assertNotIn("'GL Payment'",query)
        self.assertEqual(source.vat_ledger_balance,90)
        self.assertEqual([r['amount'] for r in source.overdue],[90])

    def test_submitted_payment_clears_referenced_quarter_not_current_sales(self):
        import frappe
        from types import SimpleNamespace
        from unittest.mock import patch,Mock
        source=self.source('2026-02-10','2026-04-30')
        doc=self.journal('JV-PAID','2026-01-15','Output VAT – Sales - WS',100,'VAT Q4 2025')
        candidates=[frappe._dict(voucher_type='Journal Entry',voucher_no=doc.name,posting_date=doc.posting_date,change_amount=-100)]
        periods=[frappe._dict(year=2025,period=4,amount=100),frappe._dict(year=2026,period=1,amount=-50)]
        account=SimpleNamespace(check_permission=lambda *args:None)
        with patch.object(frappe,'has_permission',return_value=True), \
             patch.object(frappe,'get_doc',side_effect=lambda dt,name:account if dt=='Account' else doc), \
             patch.object(frappe,'db',SimpleNamespace(exists=lambda *args:True,sql=Mock(side_effect=[candidates,periods]))):
            source.tax_position()
        self.assertEqual(vat.VatBook(source.start,source.vat_opening).total(),50)
        q4=[r for r in source._vat_data.summary if r['quarter']=='Q4 2025'][0]
        self.assertEqual(q4['paid'],'100.000');self.assertEqual(q4['balance'],'0.000')
        self.assertEqual(q4['documents'][0]['name'],'JV-PAID')

    def test_future_import_journal_produces_one_credit_not_a_settlement(self):
        import frappe
        from types import SimpleNamespace
        from unittest.mock import patch,Mock
        from worldshading.worldshading.report.cashflow_forecast.journals import Journals
        source=self.source('2026-05-01','2026-07-25')
        doc=self.journal('JV-IMPORT','2026-05-15','Input VAT – Import - WS',100)
        source.documents=lambda dt,filters=None:iter([doc] if filters.get('docstatus')==1 else [])
        periods=[frappe._dict(year=2026,period=2,amount=200)]
        future=[frappe._dict(posting_date=doc.posting_date,voucher_type='Journal Entry',voucher_no=doc.name,amount=-100)]
        account=SimpleNamespace(check_permission=lambda *args:None)
        db=SimpleNamespace(exists=lambda *args:True,sql=Mock(side_effect=[[],periods,future]),
                           get_value=lambda *args,**kwargs:frappe._dict(account_name='Input VAT',account_type='Tax'))
        with patch.object(frappe,'has_permission',return_value=True), \
             patch.object(frappe,'get_doc',side_effect=lambda dt,name:account if dt=='Account' else doc),patch.object(frappe,'db',db):
            source.tax_position();source.future_tax_events();Journals(source).emit()
        self.assertEqual(len([e for e in source.events if e['category']=='vat_accrual']),1)
        self.assertFalse([e for e in source.events if e['category']=='vat_settlement'])
        rows=build_forecast(source.start,source.end,1000,source.events,{},vat_opening=source.vat_opening)
        self.assertEqual(rows[-1]['quarterly_vat'],100)
        self.assertEqual(rows[-1]['closing_cash'],800)

    def test_gl_payment_is_cash_not_quarterly_settlement_proof(self):
        import frappe
        from types import SimpleNamespace
        source=self.source('2026-05-01','2026-07-25')
        doc=SimpleNamespace(name='GL-TAX-ADJUSTMENT',docstatus=0,posting_date='2026-05-15',
            payment_type='Outgoing',total_amount=10,
            items=[frappe._dict(account='Output VAT – Sales - WS',net_amount=10,tax_amount=0,total_amount=10)])
        doc.get=lambda key:getattr(doc,key,None)
        source.gl_payment(doc)
        self.assertEqual([(e['category'],e['amount']) for e in source.events],[('other_payments',10)])
        self.assertEqual(source.warnings,[])

    def test_pending_taxable_gl_includes_gross_cash_and_one_input_credit(self):
        import frappe
        source=self.source('2026-05-01','2026-07-25')
        from types import SimpleNamespace
        doc=SimpleNamespace(name='GL-PENDING',docstatus=0,posting_date='2026-05-15',payment_type='Outgoing',total_amount=1.54,
                        items=[frappe._dict(account='Office',account_head='Input VAT – Local - WS',net_amount=1.4,tax_amount=.14,total_amount=1.54)])
        doc.get=lambda key:getattr(doc,key,None)
        source.gl_payment(doc)
        self.assertEqual(sum(e['amount'] for e in source.events if e['category']=='other_payments'),vat.money('1.540'))
        self.assertEqual(sum(e['amount'] for e in source.events if e['category']=='vat_accrual'),vat.money('-.140'))

    def test_future_posted_government_je_replaces_old_quarter_commitment_once(self):
        import frappe
        from types import SimpleNamespace
        from unittest.mock import patch,Mock
        from worldshading.worldshading.report.cashflow_forecast.journals import Journals
        source=self.source('2026-05-01','2026-07-25')
        doc=self.journal('JV-GOV','2026-05-15','Output VAT – Sales - WS',100,'VAT Q1 2026')
        source.documents=lambda dt,filters=None:iter([doc] if filters.get('docstatus')==1 else [])
        candidates=[frappe._dict(voucher_type='Journal Entry',voucher_no=doc.name,posting_date=doc.posting_date,change_amount=-100)]
        periods=[frappe._dict(year=2026,period=1,amount=100)]
        future=[frappe._dict(posting_date=doc.posting_date,voucher_type='Journal Entry',voucher_no=doc.name,amount=-100)]
        account=SimpleNamespace(check_permission=lambda *args:None)
        db=SimpleNamespace(exists=lambda *args:True,sql=Mock(side_effect=[candidates,periods,future]),
                           get_value=lambda *args,**kwargs:frappe._dict(account_name='Output VAT',account_type='Tax'))
        with patch.object(frappe,'has_permission',return_value=True), \
             patch.object(frappe,'get_doc',side_effect=lambda dt,name:account if dt=='Account' else doc),patch.object(frappe,'db',db):
            source.tax_position();source.future_tax_events();Journals(source).emit();source._vat_data.finalize()
        self.assertEqual(len(source.events),1)
        self.assertEqual(source.events[0]['category'],'vat_settlement')
        rows=build_forecast(source.start,source.end,1000,source.events,{},vat_opening=source.vat_opening)
        self.assertEqual(sum(r['quarterly_vat'] for r in rows),100)
        self.assertEqual(rows[-1]['closing_cash'],900)

    def test_pending_settlement_without_period_has_review_note(self):
        import frappe
        from types import SimpleNamespace
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast.journals import Journals
        source=self.source('2026-05-01','2026-07-25')
        doc=self.journal('JV-PENDING','2026-05-15','Output VAT – Sales - WS',100)
        doc.docstatus=0;doc.workflow_state='Pending Payment'
        source.documents=lambda dt,filters=None:iter([doc] if filters.get('docstatus')==0 else [])
        with patch.object(Journals,'workflow_states',return_value={'Pending Payment'}), \
             patch.object(frappe,'db',SimpleNamespace(get_value=lambda *args,**kwargs:frappe._dict(account_name='Output VAT'))):
            Journals(source).emit()
        self.assertTrue(any('VAT quarter missing' in warning for warning in source.warnings))
        self.assertIn('VAT quarter missing',source.events[0]['review_note'])
