"""Standalone adapter fixtures. No site init, DB access or Frappe test hooks."""
import unittest
from unittest.mock import patch
from datetime import date
from decimal import Decimal
from collections import defaultdict
from types import SimpleNamespace
import frappe
from worldshading.worldshading.report.cashflow_forecast.sources import Sources
from worldshading.worldshading.report.cashflow_forecast.engine import money


class PayrollFixtureTests(unittest.TestCase):
    def test_frappe_employee_mapping_can_build_payroll_context(self):
        employee = frappe._dict(name='EMP-TEST', date_of_joining=date(2020, 1, 1), relieving_date=None)
        employee.as_dict = lambda: frappe._dict(employee)
        assignment = frappe._dict(name='ASSIGN-TEST', employee='EMP-TEST', from_date=date(2020, 1, 1),
            creation='2020-01-01', salary_structure='STRUCT-TEST', base=300, variable=0)
        structure = frappe._dict(payroll_frequency='Monthly', salary_slip_based_on_timesheet=0,
            earnings=[frappe._dict(amount=300)], deductions=[])
        structure.check_permission = lambda *args: None
        structure.earnings[0].as_dict = lambda: {'amount': 300}
        source = Sources.__new__(Sources)
        source.start, source.end = date(2026, 11, 9), date(2026, 11, 30)
        source.events, source.warnings, source.include_overdue = [], [], True
        source.documents = lambda dt, filters=None: iter({'Employee': [employee],
            'Salary Structure Assignment': [assignment], 'Salary Slip': []}[dt])
        from worldshading.worldshading.report.cashflow_forecast.payroll import Payroll
        source.payroll_account='Payroll';source.journals=lambda:SimpleNamespace(reserve_payable=lambda *args,**kwargs:Decimal(0))
        with patch.object(frappe, 'has_permission', return_value=True), patch.object(frappe, 'get_doc', return_value=structure), \
             patch.object(Payroll,'slips',return_value=[]),patch.object(Payroll,'booked_rows',return_value=[]):
            source.payroll()
        self.assertEqual(source.events[0]['amount'], 300)
        self.assertEqual(source.events[0]['date'], date(2026, 11, 28))

    def test_departed_employee_unpaid_final_salary_is_retained(self):
        employee = frappe._dict(name='EMP-LEFT', status='Left', date_of_joining=date(2020, 1, 1), relieving_date=date(2026, 10, 31))
        employee.as_dict = lambda: frappe._dict(employee)
        slip = frappe._dict(name='SLIP-FINAL', employee='EMP-LEFT', start_date=date(2026, 10, 1),
            rounded_total=200, net_pay=200, payroll_entry=None)
        source = Sources.__new__(Sources)
        source.start, source.end = date(2026, 11, 9), date(2026, 11, 30)
        source.events, source.warnings, source.include_overdue = [], [], True
        source.documents = lambda dt, filters=None: iter({'Employee': [],
            'Salary Structure Assignment': [], 'Salary Slip': [slip]}[dt])
        from worldshading.worldshading.report.cashflow_forecast.payroll import Payroll
        source.payroll_account='Payroll';source.journals=lambda:SimpleNamespace(reserve_payable=lambda *args:Decimal(0))
        with patch.object(frappe, 'has_permission', return_value=True),patch.object(Payroll,'slips',return_value=[slip]), \
             patch.object(Payroll,'booked_rows',return_value=[dict(date='2026-10-28',doctype='Journal Entry',name='BOOK',credit=200,debit=0)]):
            source.payroll()
        self.assertEqual(sum(e['amount'] for e in source.events), 200)
        self.assertEqual(source.events[0]['date'], date(2026, 11, 9))


class PaymentFixtureTests(unittest.TestCase):
    def test_future_submitted_payment_is_cash_even_if_reference_is_handled(self):
        pe = frappe._dict(name='PE-FUTURE', company='Example', docstatus=1,
            posting_date=date(2026, 12, 1), payment_type='Pay', base_paid_amount=50,
            references=[frappe._dict(reference_doctype='Purchase Invoice', reference_name='PI-TEST')])
        source = Sources.__new__(Sources)
        source.start, source.end = date(2026, 11, 9), date(2026, 12, 31)
        source.events, source.warnings, source.include_overdue = [], [], True
        source.handled_pe, source.handled_glp = {'PE-FUTURE'}, set()
        source.documents = lambda dt, filters=None: iter([pe] if dt == 'Payment Entry' else [])
        source.pending_documents = lambda dt: iter([pe] if dt == 'Payment Entry' else [])
        source.other_payments()
        self.assertEqual(len(source.events), 1)
        self.assertEqual(source.events[0]['amount'], 50)
        self.assertEqual(source.events[0]['date'], date(2026, 12, 1))


    def test_internal_transfer_leaving_selected_pool_reduces_liquidity(self):
        pe = frappe._dict(name='PE-TRANSFER', docstatus=1, posting_date=date(2026, 12, 1),
            payment_type='Internal Transfer', paid_from='Selected', paid_to='Excluded',
            base_paid_amount=5000, base_received_amount=5000, references=[])
        source = Sources.__new__(Sources)
        source.start, source.end = date(2026, 11, 9), date(2026, 12, 31)
        source.accounts = ['Selected']
        source.documents = lambda *args, **kwargs: iter([])
        source.events, source.warnings, source.include_overdue = [], [], True
        source.handled_pe, source.handled_glp = set(), set()
        source.pending_documents = lambda dt: iter([pe] if dt == 'Payment Entry' else [])
        source.other_payments()
        self.assertEqual(len(source.events), 1)
        self.assertEqual(source.events[0]['amount'], 5000)
        self.assertEqual(source.events[0]['category'], 'other_payments')


class DocumentFixture(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


class PoObligationFixtureTests(unittest.TestCase):
    def collect(self, remaining, state='Completed', overdue=True, currency='BHD', customs=0, installments=None, horizon=False):
        po = DocumentFixture(name='PO-RESIDUAL', base_grand_total=100,
            advance_paid=0, currency=currency, party_account_currency=currency,
            conversion_rate=1, workflow_state=state, supplier='SUPPLIER-TEST',
            eta_date=date(2026, 12, 1), taxes=[], supplier_country='Other',
            payment_schedule=[frappe._dict(due_date=due, payment_amount=amount)
                for due, amount in (installments or [(date(2026, 10, 1) if overdue else date(2026, 12, 1),100)])])
        source = Sources.__new__(Sources)
        source.company, source.currency, source.accounts = 'Example', currency, []
        source.start, source.end = date(2026, 11, 9), date(2026, 12, 31)
        source.events, source.overdue, source.warnings, source.include_overdue = [], [], [], True
        source.handled_glp, source.handled_pe = set(), set()
        source.invoiced, source.applied_advances, source.import_credited = [defaultdict(Decimal) for _ in range(3)]
        source.invoiced[po.name] = money(100)-money(remaining)
        source._supplier_horizon_only=horizon
        if horizon:source.end=date.max
        source.documents = lambda dt, filters=None: iter([po] if dt == 'Purchase Order' else [])
        source.pending_reference_payments = lambda *args: []
        source.journals = lambda: SimpleNamespace(reserve=lambda *args: money(0))
        source.tax_estimate = lambda po: [dict(account_head='Custom Duty - WS',base_tax_amount_after_discount_amount=customs)]
        source.purchase_orders()
        return source

    def test_legal_dispute_po_has_no_forecast_or_overdue_commitment(self):
        source=self.collect(4800,state='Legal Dispute',customs=10)
        self.assertEqual(source.events,[])
        self.assertEqual(source.overdue,[])

    def test_sub_dinar_po_residual_is_ignored_past_and_future(self):
        for amount in ('0.010','0.200','0.999'):
            for overdue in (True,False):
                source=self.collect(amount,overdue=overdue)
                self.assertFalse([e for e in source.events+source.overdue if e['category']=='supplier_payments'])

    def test_one_dinar_and_on_hold_po_are_still_included(self):
        for state in ('Completed','On Hold'):
            source=self.collect(1,state=state)
            self.assertEqual(sum(e['amount'] for e in source.events if e['category']=='supplier_payments'),1)
            self.assertEqual(len(source.overdue),1)

    def test_small_installments_on_larger_total_are_retained(self):
        source=self.collect(1,installments=[(date(2026,12,1),Decimal('99.250')),
                                           (date(2026,12,2),Decimal('0.750'))])
        self.assertEqual([e['amount'] for e in source.events if e['category']=='supplier_payments'],
                         [Decimal('0.250'),Decimal('0.750')])

    def test_supplier_tolerance_does_not_remove_customs_or_other_currency(self):
        source=self.collect('0.200',customs=10)
        self.assertEqual([e['amount'] for e in source.events if e['category']=='customs'],[10])
        source=self.collect('0.200',currency='USD')
        self.assertEqual(sum(e['amount'] for e in source.events if e['category']=='supplier_payments'),Decimal('0.200'))


class TaxFixtureTests(unittest.TestCase):
    def test_partial_customs_document_retains_both_eta_residuals(self):
        po = DocumentFixture(name='PO-TEST', base_grand_total=1000, advance_paid=1000,
            currency='BHD', party_account_currency='BHD', conversion_rate=1, workflow_state='Shipped',
            eta_date=date(2026, 12, 1), taxes=[], payment_schedule=[], supplier_country='Other')
        glp = DocumentFixture(name='GLP-PARTIAL', docstatus=1, posting_date=date(2026, 11, 1),
            payment_type='Outgoing', total_amount=100,
            items=[DocumentFixture(account='Custom Duty - WS', total_amount=100, net_amount=100)])
        source = Sources.__new__(Sources)
        source.company, source.currency, source.accounts = 'Example', 'BHD', []
        source.start, source.end = date(2026, 11, 9), date(2026, 12, 31)
        source.events, source.warnings, source.include_overdue = [], [], True
        source.handled_glp, source.handled_pe = set(), set()
        source.invoiced, source.applied_advances, source.import_credited = [defaultdict(Decimal) for _ in range(3)]
        source.documents = lambda dt, filters=None: iter([po] if dt == 'Purchase Order' else [glp])
        source.pending_reference_payments = lambda *args: []
        source.tax_estimate = lambda po: [dict(account_head='Custom Duty - WS', base_tax_amount_after_discount_amount=500),
            dict(account_head='Input VAT – Import - WS', base_tax_amount_after_discount_amount=1050)]
        source.purchase_orders()
        self.assertEqual(sum(e['amount'] for e in source.events if e['category']=='customs'), 400)
        self.assertEqual(sum(e['amount'] for e in source.events if e['category']=='import_vat'), 1050)

    def test_future_posted_purchase_tax_reduces_quarterly_liability(self):
        from worldshading.worldshading.report.cashflow_forecast.engine import build_forecast
        source = Sources.__new__(Sources)
        source.company, source.start, source.end = 'Example', date(2026, 11, 9), date(2027, 1, 25)
        source.events = []
        from worldshading.worldshading.report.cashflow_forecast.vat_sources import VatSources
        source._vat_loaded = True
        source._vat_data = VatSources(source)
        row = frappe._dict(posting_date=date(2026, 12, 1), voucher_type='Purchase Invoice', voucher_no='PI-FUTURE', amount=-100)
        with patch.object(frappe, 'db', SimpleNamespace(sql=lambda *args, **kwargs: [row])):
            source.future_tax_events()
        rows = build_forecast(source.start, source.end, 1000, source.events, {}, vat_opening=200)
        self.assertEqual(rows[-1]['quarterly_vat'], 100)


class RequestFixtureTests(unittest.TestCase):
    def test_nonfinancial_user_cannot_query_balances(self):
        from worldshading.worldshading.report.cashflow_forecast.cashflow_forecast import authorize
        with patch.object(frappe, 'session', frappe._dict(user='test@example.invalid')), \
             patch.object(frappe, 'get_roles', return_value=['Sales User']), \
             patch.object(frappe, 'throw', side_effect=PermissionError):
            with self.assertRaises(PermissionError): authorize('Example')

    def test_missing_account_access_is_rejected_before_source_queries(self):
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
        with patch.object(report, 'authorize'), patch.object(report, 'nowdate', return_value='2026-11-09'), \
             patch.object(report, 'resolve_accounts', side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                report.validate(dict(company='Example', end_date='2026-12-31'))


class PreparedFixtureTests(unittest.TestCase):
    def test_compact_and_detailed_columns_preserve_access_to_breakdown(self):
        from worldshading.worldshading.report.cashflow_forecast.cashflow_forecast import columns
        visible = [c['fieldname'] for c in columns() if not c.get('hidden')]
        self.assertIn('fixed_expenses',visible)
        self.assertIn('supplier_payments',visible)
        self.assertNotIn('previous_year_sales',visible)
        self.assertNotIn('available_above_reserve',visible)
        reserve = [c['fieldname'] for c in columns(minimum_reserve=100) if not c.get('hidden')]
        self.assertIn('available_above_reserve',reserve)
        detailed = [c['fieldname'] for c in columns(detailed_view=1)]
        self.assertIn('supplier_payments', detailed)
        self.assertIn('source_details', detailed)
        self.assertNotIn('adjusted_sales', detailed)
        self.assertNotIn('actual_sales_today', detailed)
        self.assertNotIn('total_receipts', detailed)
        for name in ('proposed_purchase','baseline_closing_cash','purchase_impact'):
            self.assertTrue(next(c for c in columns(detailed_view=1) if c['fieldname']==name)['hidden'])
            self.assertFalse(next(c for c in columns(detailed_view=1,has_purchase=True) if c['fieldname']==name)['hidden'])

    def test_prepared_rows_retain_summary_and_coverage_without_recalculation(self):
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
        filters = frappe._dict(company='Example', end_date='2026-11-10')
        source = DocumentFixture(opening_balance=100, actual_sales_today=75, events=[], historical={}, sales_tax={}, vat_opening=0,
            currency='BHD', start=date(2026,11,9), warnings=['Missing source fixture'], accounts_breakdown=[])
        source.collect = lambda: source
        with patch.object(report, 'normalize_generation_filters', side_effect=lambda values:(values,None)), \
             patch.object(report, 'validate', return_value=(filters,date(2026,11,9),date(2026,11,10),['Bank'],[])), \
             patch.object(report, 'Sources', return_value=source):
            result = report.execute(filters)
        context = result[1][0].get('_cashflow_context', {})
        self.assertEqual(result[1][0]['actual_sales_today'], 75)
        self.assertIsNone(result[1][1]['actual_sales_today'])
        self.assertEqual(result[1][0]['closing_cash'], 100)
        self.assertIn('Missing source fixture', context.get('message',''))
        self.assertEqual(context.get('report_summary'), result[4])
        self.assertEqual(context.get('chart'), result[3])
        self.assertEqual(context.get('forecast_date'), '2026-11-09')

    def test_other_owner_cannot_restore_prepared_scenario(self):
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
        saved = DocumentFixture(report_name='Cashflow Forecast', status='Completed', owner='someone-else', filters='{}')
        with patch.object(frappe, 'session', frappe._dict(user='finance-user')), \
             patch.object(frappe, 'get_roles', return_value=['Accounts Manager']), \
             patch.object(frappe, 'get_doc', return_value=saved), \
             patch.object(frappe, 'throw', side_effect=PermissionError):
            with self.assertRaises(PermissionError): report.get_prepared_filters('SAVED-TEST')


class PreparedAccessFixtureTests(unittest.TestCase):
    def test_cashflow_snapshot_cannot_be_requested_through_another_report(self):
        from worldshading.worldshading.report.cashflow_forecast import prepared_access
        with patch.object(frappe, 'db', SimpleNamespace(get_value=lambda *args: 'Cashflow Forecast')), \
             patch.object(frappe, 'throw', side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                prepared_access.guard_request('Purchase Plan', {'prepared_report_name': 'PRIVATE-SNAPSHOT'})

    def test_cached_payroll_does_not_bypass_revoked_payroll_permissions(self):
        from worldshading.worldshading.report.cashflow_forecast import prepared_access
        with patch.object(frappe, 'has_permission', return_value=False), \
             patch.object(frappe, 'throw', side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                prepared_access.check_payroll_access({'result': [{'sources': [{'doctype': 'Salary Structure Assignment'}]}]})


class AutomaticAccountFixtureTests(unittest.TestCase):
    def test_all_nested_ledgers_in_both_parents_include_untyped_and_disabled(self):
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
        rows = [frappe._dict(name='Banks', account_name='Bank Accounts',company='Example',is_group=1,lft=10,rgt=30),
            frappe._dict(name='Cash',account_name='Cash In Hand',company='Example',is_group=1,lft=40,rgt=60),
            frappe._dict(name='Nested',company='Example',is_group=1,lft=20,rgt=25),
            frappe._dict(name='Bank Disabled',company='Example',is_group=0,lft=12,rgt=13,disabled=1),
            frappe._dict(name='Nested Untyped',company='Example',is_group=0,lft=22,rgt=23,account_type=''),
            frappe._dict(name='Cash Leaf',company='Example',is_group=0,lft=42,rgt=43),
            frappe._dict(name='Outside',company='Example',is_group=0,lft=32,rgt=33)]
        def query(dt,filters=None,**kwargs):
            result=[r for r in rows if r.is_group==filters['is_group'] and r.company==filters['company']]
            if filters.get('account_name'): result=[r for r in result if r.get('account_name') in filters['account_name'][1]]
            if filters.get('lft'): result=[r for r in result if r.lft>filters['lft'][1] and r.rgt<filters['rgt'][1]]
            return result
        def get_doc(dt,name):
            r=next(r for r in rows if r.name==name)
            return DocumentFixture(**dict(r),check_permission=lambda *args:None)
        with patch.object(frappe,'get_all',side_effect=query),patch.object(frappe,'get_doc',side_effect=get_doc):
            self.assertEqual(report.resolve_accounts('Example'),['Bank Disabled','Cash Leaf','Nested Untyped'])

    def test_missing_parent_does_not_fall_back_to_other_bank_accounts(self):
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
        with patch.object(frappe,'get_all',return_value=[]),patch.object(frappe,'throw',side_effect=ValueError):
            with self.assertRaises(ValueError): report.resolve_accounts('Example')

    def test_new_request_ignores_client_supplied_account_selection(self):
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
        with patch.object(report,'authorize'),patch.object(report,'nowdate',return_value='2026-11-09'), \
             patch.object(report,'resolve_accounts',return_value=['Auto Bank','Auto Cash']):
            result=report.validate(dict(company='Example',end_date='2026-12-31',accounts=['Other Company Bank']))
        self.assertEqual(result[3],['Auto Bank','Auto Cash'])


class OverdueReviewFixtureTests(unittest.TestCase):
    def make_source(self, include):
        source = Sources.__new__(Sources)
        source.start, source.end = date(2026,11,9), date(2026,12,31)
        source.events, source.warnings, source.overdue = [], [], []
        source.include_overdue = include
        return source

    def test_unchecked_retains_unpaid_overdue_for_review_but_not_cash(self):
        source=self.make_source(False)
        source.event(source.due('2026-11-01','PE-TEST'), 'supplier_payments', 500,
            'Payment Entry','PE-TEST','Unpaid scheduled installment')
        self.assertEqual(source.events,[])
        self.assertEqual(len(source.overdue),1)
        self.assertEqual(source.overdue[0]['amount'],500)
        self.assertEqual(source.overdue[0]['date'],date(2026,11,1))
        self.assertEqual(source.overdue[0]['name'],'PE-TEST')

    def test_checked_places_overdue_payment_today_with_original_date(self):
        source=self.make_source(True)
        source.event(source.due('2026-11-01','PE-TEST'), 'supplier_payments', 500,
            'Payment Entry','PE-TEST','Unpaid scheduled installment')
        self.assertEqual(source.events[0]['date'],date(2026,11,9))
        self.assertEqual(source.events[0]['original_due_date'],date(2026,11,1))
        self.assertEqual(source.events[0]['amount'],500)

    def test_future_or_zero_or_tax_credit_does_not_create_overdue_commitment(self):
        source=self.make_source(False)
        source.event(source.due('2026-11-10','PI-FUTURE'),'supplier_payments',500)
        source.event(source.due('2026-11-01','PAID'),'supplier_payments',0)
        source.event(source.due('2026-11-01','VAT'),'vat_accrual',-50)
        self.assertEqual(source.overdue,[])
        self.assertEqual(len(source.events),1)

    def test_matched_overdue_payment_is_not_repeated_as_unmatched(self):
        for include in (False, True):
            source=self.make_source(include)
            source.handled_glp=set()
            pe=frappe._dict(name='PE-TEST',docstatus=0,workflow_state='Scheduled',payment_type='Pay',
                posting_date=date(2026,11,1),base_paid_amount=500,
                references=[frappe._dict(reference_doctype='Purchase Invoice',reference_name='PI-TEST')])
            source.pending_documents=lambda dt:iter([pe] if dt=='Payment Entry' else [])
            source.documents=lambda *args,**kwargs:iter([])
            source.event(source.due(pe.posting_date,pe.name),'supplier_payments',500,'Payment Entry',pe.name,'Matched invoice payment')
            source.other_payments()
            self.assertEqual(sum(row['amount'] for row in source.overdue),500)
            self.assertEqual(source.warnings,[])
            self.assertEqual(sum(row['amount'] for row in source.events),500 if include else 0)

    def test_unchecked_blocks_enqueue_instead_of_creating_prepared_record(self):
        from worldshading.worldshading.report.cashflow_forecast import prepared_access
        with patch.object(prepared_access,'guard_request',return_value=True), \
             patch.object(prepared_access,'normalize_generation_filters',return_value=({},None)), \
             patch.object(prepared_access,'get_overdue_commitments',return_value={'items':[{'name':'PE-TEST'}]}), \
             patch('frappe.desk.query_report.background_enqueue_run') as original:
            result=prepared_access.background_enqueue_run('Cashflow Forecast','{}')
        self.assertTrue(result['blocked'])
        original.assert_not_called()


if __name__ == '__main__': unittest.main()
