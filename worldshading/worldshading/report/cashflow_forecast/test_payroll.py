"""Payroll accounting controls; standalone only, no site initialization."""
import unittest
from datetime import date
from decimal import Decimal
from worldshading.worldshading.report.cashflow_forecast.payroll import payable_lots, salary_period

class PayrollAccountingTests(unittest.TestCase):
    def test_bookings_less_payments_preserve_exact_residual(self):
        rows=[dict(date='2026-05-25',credit='7764.606',name='MAY'),dict(date='2026-06-04',debit='7764.606',name='PAID-MAY'),
              dict(date='2026-06-28',credit='7799.084',name='JUNE'),dict(date='2026-07-02',debit='7799.070',name='PAID-JUNE')]
        lots,credit=payable_lots(rows)
        self.assertEqual(len(lots),1);self.assertEqual(lots[0]['amount'],Decimal('.014'))
        self.assertEqual(lots[0]['name'],'JUNE');self.assertEqual(credit,0)

    def test_prepayment_and_adjustment_do_not_create_extra_debt(self):
        rows=[dict(date='2026-01-01',debit=50,name='ADVANCE'),dict(date='2026-01-20',credit=100,name='BOOK'),dict(date='2026-01-21',debit=20,name='ADJUST')]
        lots,credit=payable_lots(rows);self.assertEqual(sum(r['amount'] for r in lots),30);self.assertEqual(credit,0)
        lots,credit=payable_lots([dict(date='2026-01-01',debit=50,name='ADVANCE')]);self.assertEqual(lots,[]);self.assertEqual(credit,50)

    def test_salary_period_is_end_month(self):
        self.assertEqual(salary_period(dict(start_date='2026-05-20',end_date='2026-06-19')),'2026-06')

class PayrollAdapterTests(unittest.TestCase):
    def source(self,start='2026-11-11',end='2026-12-31'):
        import frappe
        from types import SimpleNamespace
        from unittest.mock import Mock
        from worldshading.worldshading.report.cashflow_forecast.sources import Sources
        s=Sources.__new__(Sources);s.company='Example';s.payroll_account='Payroll';s.accounts=['Bank']
        s.start=date.fromisoformat(start) if hasattr(date,'fromisoformat') else __import__('datetime').datetime.strptime(start,'%Y-%m-%d').date()
        s.end=__import__('datetime').datetime.strptime(end,'%Y-%m-%d').date()
        s.events=[];s.overdue=[];s.warnings=[];s.include_overdue=True
        s.documents=lambda dt,filters=None:iter([])
        journals=SimpleNamespace(reserve_payable=Mock(return_value=Decimal(0)),reserve=Mock(return_value=Decimal(0)),reserve_future_payroll=Mock(return_value=Decimal(0)))
        s.journals=lambda:journals
        return s

    def run_payroll(self,s,slips,rows):
        import frappe
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast.payroll import Payroll
        with patch.object(Payroll,'slips',return_value=slips),patch.object(Payroll,'booked_rows',return_value=rows),patch.object(frappe,'has_permission',return_value=True):
            s.payroll()

    def test_old_paid_slips_do_not_create_historical_overdue(self):
        import frappe
        s=self.source()
        slip=frappe._dict(name='SS',employee='E',start_date='2026-05-20',end_date='2026-06-19',net_pay=100,rounded_total=99,journal_entry='BOOK',payroll_entry='RUN')
        rows=[dict(date='2026-06-28',doctype='Journal Entry',name='BOOK',credit=100,debit=0),dict(date='2026-07-02',doctype='Journal Entry',name='PAID',credit=0,debit=100)]
        self.run_payroll(s,[slip],rows)
        self.assertEqual(s.events,[]);self.assertEqual(s.payroll_reconciliation['balance'],'0.000')

    def test_partial_paid_booked_salary_retains_exact_residual(self):
        import frappe
        s=self.source()
        slip=frappe._dict(name='SS',employee='E',start_date='2026-05-20',end_date='2026-06-19',net_pay=100,journal_entry='BOOK')
        rows=[dict(date='2026-06-28',doctype='Journal Entry',name='BOOK',credit=100,debit=0),dict(date='2026-07-02',doctype='Journal Entry',name='PAID',credit=0,debit='99.882')]
        self.run_payroll(s,[slip],rows)
        self.assertEqual(sum(e['amount'] for e in s.events),Decimal('.118'))
        self.assertEqual(s.events[0]['doctype'],'Account')
        self.assertEqual(s.events[0]['date'],s.start)

    def test_unbooked_future_slip_uses_net_pay_and_end_month(self):
        import frappe
        s=self.source('2026-06-01','2026-06-30')
        slip=frappe._dict(name='SS',employee='E',start_date='2026-05-20',end_date='2026-06-19',net_pay='100.123',rounded_total=100,journal_entry='FUTURE-BOOK',payroll_entry='RUN')
        self.run_payroll(s,[slip],[])
        self.assertEqual(s.events[0]['date'],date(2026,6,28));self.assertEqual(s.events[0]['amount'],Decimal('100.123'))
        s.journals().reserve.assert_called_once_with('Payroll Entry','RUN',Decimal('100.123'))

    def test_past_unverified_slip_is_flagged_not_assumed_unpaid_or_paid(self):
        import frappe
        s=self.source()
        slip=frappe._dict(name='UNLINKED',employee='E',start_date='2026-05-01',end_date='2026-05-31',net_pay=100)
        self.run_payroll(s,[slip],[])
        self.assertEqual(s.events,[]);self.assertTrue(any('UNLINKED' in warning for warning in s.warnings))

    def test_duplicate_current_slips_are_not_silently_selected(self):
        import frappe
        s=self.source()
        slips=[frappe._dict(name=name,employee='E',start_date='2026-11-01',end_date='2026-11-30',net_pay=100) for name in ('SS1','SS2')]
        self.run_payroll(s,slips,[])
        self.assertEqual(s.events,[]);self.assertTrue(any('multiple submitted' in warning for warning in s.warnings))

    def test_scheduled_payable_cash_is_capped_across_multiple_lots(self):
        import frappe
        from worldshading.worldshading.report.cashflow_forecast.journals import Journals
        s=self.source();j=Journals(s);j.loaded=True
        doc=frappe._dict(name='FUTURE',posting_date='2026-11-30')
        j.entries=[dict(doc=doc,pending=False,cash=Decimal(60),rows=[dict(account='Payroll',debit=50),dict(account='Other',debit=10),dict(account='Bank',credit=60)])]
        self.assertEqual(j.reserve_payable('Payroll',30),30)
        self.assertEqual(j.reserve_payable('Payroll',40),20)
        self.assertEqual(j.reserve_payable('Payroll',20),0)
        self.assertEqual(sum(e['amount'] for e in s.events),50)

    def test_future_submitted_linked_bank_payment_replaces_actual_cash_once(self):
        import frappe
        from worldshading.worldshading.report.cashflow_forecast.journals import Journals
        s=self.source();j=Journals(s);j.loaded=True
        doc=frappe._dict(name='FUTURE',posting_date='2026-11-30')
        j.entries=[dict(doc=doc,pending=False,cash=Decimal(100),rows=[dict(account='Payroll',debit=100,reference_type='Payroll Entry',reference_name='RUN')])]
        self.assertEqual(j.reserve_future_payroll('RUN',100),100)
        self.assertEqual(j.reserve_future_payroll('RUN',100),0)
        self.assertEqual(sum(e['amount'] for e in s.events),100)

    def test_future_reference_allocation_cannot_be_used_twice_in_mixed_journal(self):
        import frappe
        from worldshading.worldshading.report.cashflow_forecast.journals import Journals
        s=self.source();j=Journals(s);j.loaded=True
        doc=frappe._dict(name='MIXED-FUTURE',posting_date='2026-11-30')
        j.entries=[dict(doc=doc,pending=False,cash=Decimal(200),rows=[dict(account='Payroll',debit=100,reference_type='Payroll Entry',reference_name='RUN'),dict(account='Other',debit=100)])]
        self.assertEqual(j.reserve_future_payroll('RUN',100),100)
        self.assertEqual(j.reserve_future_payroll('RUN',100),0)

    def test_saved_account_only_payroll_control_rechecks_payroll_permissions(self):
        import frappe
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast.prepared_access import check_payroll_access
        saved={'result':[{'sources':[{'doctype':'Account','name':'Payroll'}],'_cashflow_context':{'payroll_reconciliation':{'account':'Payroll','balance':'0.118'}}}]}
        with patch.object(frappe,'has_permission',return_value=False),patch.object(frappe,'throw',side_effect=PermissionError):
            with self.assertRaises(PermissionError):check_payroll_access(saved)

    def test_reference_and_unlinked_reservations_share_payable_debit_cap(self):
        import frappe
        from worldshading.worldshading.report.cashflow_forecast.journals import Journals
        s=self.source();j=Journals(s);j.loaded=True
        doc=frappe._dict(name='MIXED',posting_date='2026-11-30')
        j.entries=[dict(doc=doc,pending=False,cash=Decimal(200),rows=[dict(account='Payroll',debit=100,reference_type='Payroll Entry',reference_name='RUN'),dict(account='Other',debit=100)])]
        self.assertEqual(j.reserve_future_payroll('RUN',100),100)
        self.assertEqual(j.reserve_payable('Payroll',100,not_before=date(2026,11,1)),0)

    def test_old_unlinked_draft_does_not_replace_future_month_salary(self):
        import frappe
        from worldshading.worldshading.report.cashflow_forecast.journals import Journals
        s=self.source();j=Journals(s);j.loaded=True
        j.entries=[dict(doc=frappe._dict(name='OLD',posting_date='2026-07-25'),pending=True,cash=Decimal(100),rows=[dict(account='Payroll',debit=100)])]
        self.assertEqual(j.reserve_payable('Payroll',100,not_before=date(2026,11,1)),0)

    def test_payroll_cycle_20_to_19_prorates_actual_salary_period(self):
        from worldshading.worldshading.report.cashflow_forecast.payroll import cycle_start_day,period_bounds
        slips=[dict(start_date='2026-05-20',end_date='2026-06-19',payroll_entry='RUN')]
        self.assertEqual(cycle_start_day(slips),20)
        self.assertEqual(period_bounds('2026-07',20),(date(2026,6,20),date(2026,7,19)))
        self.assertEqual(period_bounds('2026-12',1),(date(2026,12,1),date(2026,12,31)))

    def test_december_unlinked_payment_cannot_replace_november_salary(self):
        import frappe
        from worldshading.worldshading.report.cashflow_forecast.journals import Journals
        s=self.source();j=Journals(s);j.loaded=True
        j.entries=[dict(doc=frappe._dict(name='DECEMBER',posting_date='2026-12-28'),pending=True,cash=Decimal(100),rows=[dict(account='Payroll',debit=100)])]
        self.assertEqual(j.reserve_payable('Payroll',100,not_before=date(2026,11,1),not_after=date(2026,11,30)),0)
        self.assertEqual(j.reserve_payable('Payroll',100,not_before=date(2026,12,1),not_after=date(2026,12,31)),100)

    def test_explicit_other_batch_not_consumed_by_unlinked_month_matching(self):
        import frappe
        from worldshading.worldshading.report.cashflow_forecast.journals import Journals
        s=self.source();j=Journals(s);j.loaded=True
        j.entries=[dict(doc=frappe._dict(name='LINKED',posting_date='2026-11-28'),pending=True,cash=Decimal(100),rows=[dict(account='Payroll',debit=100,reference_type='Payroll Entry',reference_name='OTHER')])]
        self.assertEqual(j.reserve_payable('Payroll',100,not_before=date(2026,11,1),not_after=date(2026,11,30)),0)

    def test_left_employee_within_salary_cycle_gets_prorated_final_estimate(self):
        import frappe
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast.payroll import Payroll
        s=self.source('2026-11-11','2026-11-30')
        employee=frappe._dict(name='LEFT',status='Left',date_of_joining=date(2020,1,1),relieving_date=date(2026,11,5))
        employee.as_dict=lambda:dict(employee)
        assignment=frappe._dict(name='SSA',employee='LEFT',from_date=date(2020,1,1),creation='2020',salary_structure='STRUCT',base=300,variable=0)
        row=frappe._dict(amount=300,depends_on_payment_days=1);row.as_dict=lambda:dict(row)
        structure=frappe._dict(payroll_frequency='Monthly',salary_slip_based_on_timesheet=0,earnings=[row],deductions=[])
        def documents(dt,filters=None):
            if dt=='Employee':return iter([employee] if filters.get('status')=='Left' else [])
            return iter([assignment])
        s.documents=documents;s.read_document=lambda *args:structure
        payroll=Payroll(s);payroll.cycle_day=20
        payroll.estimates({})
        self.assertEqual(s.events[0]['date'],date(2026,11,28))
        self.assertEqual(s.events[0]['amount'],Decimal('164.516'))

    def test_forward_estimates_keep_november_cash_when_december_payment_exists(self):
        import frappe
        from worldshading.worldshading.report.cashflow_forecast.payroll import Payroll
        from worldshading.worldshading.report.cashflow_forecast.journals import Journals
        s=self.source();j=Journals(s);j.loaded=True;s.journals=lambda:j
        j.entries=[dict(doc=frappe._dict(name='DEC-PAY',posting_date='2026-12-28'),pending=True,cash=Decimal(100),rows=[dict(account='Payroll',debit=100)])]
        employee=frappe._dict(name='ACTIVE',status='Active',date_of_joining=date(2020,1,1),relieving_date=None);employee.as_dict=lambda:dict(employee)
        assignment=frappe._dict(name='SSA',employee='ACTIVE',from_date=date(2020,1,1),creation='2020',salary_structure='STRUCT',base=100,variable=0)
        row=frappe._dict(amount=100);row.as_dict=lambda:dict(row)
        structure=frappe._dict(payroll_frequency='Monthly',salary_slip_based_on_timesheet=0,earnings=[row],deductions=[])
        s.documents=lambda dt,filters=None:iter([assignment] if dt=='Salary Structure Assignment' else ([employee] if filters.get('status')=='Active' else []))
        s.read_document=lambda *args:structure
        Payroll(s).estimates({})
        totals={}
        for event in s.events:totals[event['date']]=totals.get(event['date'],0)+event['amount']
        self.assertEqual(totals,{date(2026,11,28):100,date(2026,12,28):100})
