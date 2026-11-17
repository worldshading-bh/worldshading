"""Employee loan schedules reduce forward net salary, never actual slips twice."""
import unittest
from unittest.mock import patch,Mock
from types import SimpleNamespace
from datetime import date
from decimal import Decimal
import frappe
from worldshading.worldshading.report.cashflow_forecast.payroll import Payroll
from worldshading.worldshading.report.cashflow_forecast.sources import Sources

class PayrollLoanTests(unittest.TestCase):
    def source(self):
        source=Sources.__new__(Sources);source.company='Example';source.currency='BHD';source.payroll_account='Payroll'
        source.start=date(2026,11,17);source.end=date(2027,1,31)
        source.events=[];source.overdue=[];source.warnings=[];source.include_overdue=True
        employee=frappe._dict(name='EMP',date_of_joining=date(2020,1,1));employee.as_dict=lambda:dict(employee)
        assignment=frappe._dict(name='SSA',employee='EMP',from_date=date(2020,1,1),creation='2020',salary_structure='STRUCT',base=200,variable=0)
        component=frappe._dict(amount=200);component.as_dict=lambda:dict(component)
        structure=frappe._dict(payroll_frequency='Monthly',salary_slip_based_on_timesheet=0,earnings=[component],deductions=[])
        source.documents=lambda dt,filters=None:iter([assignment] if dt=='Salary Structure Assignment' else [employee] if dt=='Employee' and filters['status']=='Active' else [])
        source.read_document=lambda *args:structure
        source.journals=lambda:SimpleNamespace(reserve_payable=lambda *args,**kwargs:Decimal(0))
        return source

    def test_schedule_loader_scopes_company_employee_status_and_paid_rows(self):
        source=self.source();payroll=Payroll(source)
        loans=[frappe._dict(name='LOAN',applicant='EMP',total_payment=100,total_amount_paid=0)]
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_list',return_value=loans) as listing, \
             patch.object(frappe,'db',SimpleNamespace(sql=Mock(return_value=[frappe._dict(loan='LOAN',payment_date='2026-11-01',total_payment=50)]))) as db:
            result=payroll.loan_repayments(['EMP'],date(2026,10,20),date(2027,1,19))
        self.assertEqual(result['EMP'][0]['amount'],50)
        filters=listing.call_args[1]['filters']
        self.assertEqual(filters['company'],'Example');self.assertEqual(filters['docstatus'],1)
        self.assertEqual(filters['status'],'Disbursed');self.assertEqual(filters['repay_from_salary'],1)
        self.assertEqual(filters['applicant'],['in',['EMP']])
        self.assertIn('paid',db.sql.call_args[0][0]);self.assertEqual(db.sql.call_args[0][1][-2],date(2026,10,20))

    def test_deducts_only_each_period_and_skips_actual_slip_period(self):
        source=self.source();payroll=Payroll(source);payroll.cycle_day=20
        schedule={'EMP':[dict(loan='OLD',date=date(2026,5,1),amount=50),
                         dict(loan='L1',date=date(2026,11,1),amount=50),
                         dict(loan='L2',date=date(2026,11,19),amount=10),
                         dict(loan='L1',date=date(2026,12,1),amount=50)]}
        with patch.object(Payroll,'loan_repayments',return_value=schedule) as loader:
            payroll.estimates({('EMP','2026-12'):['submitted slip']})
        amounts={event['date']:event['amount'] for event in source.events}
        self.assertEqual(amounts,{date(2026,11,28):140,date(2027,1,28):200})
        first=source.events[0];self.assertEqual(first['loan_repayment'],60)
        self.assertEqual({r['name'] for r in first['related_documents']},{'L1','L2'})
        self.assertEqual(loader.call_count,1)

    def test_scheduled_payroll_is_matched_after_loan_deduction(self):
        source=self.source();source.end=date(2026,11,30);payroll=Payroll(source)
        reserve=Mock(return_value=Decimal(20));source.journals=lambda:SimpleNamespace(reserve_payable=reserve)
        with patch.object(Payroll,'loan_repayments',return_value={'EMP':[dict(loan='L',date=date(2026,11,1),amount=50)]}):payroll.estimates({})
        self.assertEqual(reserve.call_args[0][1],150)
        self.assertEqual(source.events[0]['amount'],130)

    def test_excess_deduction_does_not_create_cash_incoming(self):
        source=self.source();source.end=date(2026,11,30);payroll=Payroll(source)
        with patch.object(Payroll,'loan_repayments',return_value={'EMP':[dict(loan='L',date=date(2026,11,1),amount=250)]}):payroll.estimates({})
        self.assertEqual(source.events,[]);self.assertTrue(any('loan' in warning.lower() for warning in source.warnings))

    def test_no_loan_permission_is_explicit_and_does_not_query(self):
        source=self.source()
        with patch.object(frappe,'has_permission',return_value=False),patch.object(frappe,'get_list') as listing:
            result=Payroll(source).loan_repayments(['EMP'],date(2026,11,1),date(2026,11,30))
        self.assertEqual(dict(result),{});listing.assert_not_called();self.assertTrue(source.warnings)

    def test_cached_report_rechecks_loan_permissions(self):
        from worldshading.worldshading.report.cashflow_forecast.prepared_access import check_payroll_access
        saved=dict(result=[dict(_cashflow_context=dict(payroll_loan_names=['LOAN']))])
        with patch.object(frappe,'has_permission',return_value=False),patch.object(frappe,'throw',side_effect=PermissionError):
            with self.assertRaises(PermissionError):check_payroll_access(saved)

    def test_submitted_slip_net_pay_is_not_deducted_a_second_time(self):
        source=self.source();source.end=date(2026,11,30)
        slip=frappe._dict(name='SLIP',employee='EMP',start_date='2026-11-01',end_date='2026-11-30',net_pay=150)
        with patch.object(Payroll,'slips',return_value=[slip]),patch.object(Payroll,'booked_rows',return_value=[]), \
             patch.object(Payroll,'loan_repayments',return_value={'EMP':[dict(loan='L',date=date(2026,11,1),amount=50)]}), \
             patch.object(frappe,'has_permission',return_value=True):
            Payroll(source).collect()
        self.assertEqual(sum(event['amount'] for event in source.events),150)
        self.assertEqual(source.events[0]['doctype'],'Salary Slip')

    def test_fully_settled_loan_master_is_not_queried_for_installments(self):
        source=self.source();loan=frappe._dict(name='SETTLED',applicant='EMP',total_payment=100,total_amount_paid=100)
        sql=Mock(side_effect=AssertionError('Settled loan should not load installments'))
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_list',return_value=[loan]), \
             patch.object(frappe,'db',SimpleNamespace(sql=sql)):
            result=Payroll(source).loan_repayments(['EMP'],date(2026,11,1),date(2026,11,30))
        self.assertEqual(dict(result),{});sql.assert_not_called()

    def test_zero_total_master_cannot_create_a_salary_deduction(self):
        source=self.source();loan=frappe._dict(name='ZERO',applicant='EMP',total_payment=0,total_amount_paid=0)
        sql=Mock(side_effect=AssertionError('Zero-balance loan should not load installments'))
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_list',return_value=[loan]), \
             patch.object(frappe,'db',SimpleNamespace(sql=sql)):
            result=Payroll(source).loan_repayments(['EMP'],date(2026,11,1),date(2026,11,30))
        self.assertEqual(dict(result),{});sql.assert_not_called()

    def test_employee_without_any_assignment_is_silently_skipped(self):
        source=self.source();employee=list(source.documents('Employee',{'status':'Active'}))[0]
        source.documents=lambda dt,filters=None:iter([employee] if dt=='Employee' and filters['status']=='Active' else [])
        Payroll(source).estimates({})
        self.assertEqual(source.events,[])
        self.assertFalse(any('no assignment' in warning.lower() for warning in source.warnings))
