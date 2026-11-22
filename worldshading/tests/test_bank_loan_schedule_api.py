"""Preview permissions and serialization; external database boundaries only are mocked."""
import unittest
from unittest.mock import patch, Mock
import frappe
from worldshading.api.bank_loan_schedule import preview_schedule
from worldshading.tests.test_bank_loan_generator import loan, options


class TestSchedulePreviewAPI(unittest.TestCase):
    def setUp(self):
        for name,value in [('session',frappe._dict(user='maker@example.com')),
                           ('get_roles',Mock(return_value=['Maker - ACC (Workflow)'])),
                           ('has_permission',Mock(return_value=True)),
                           ('throw',Mock(side_effect=ValueError))]:
            p=patch.object(frappe,name,value,create=True);p.start();self.addCleanup(p.stop)
        p=patch('worldshading.api.bank_loan_schedule.get_field_precision',return_value=3)
        p.start();self.addCleanup(p.stop)
        p=patch.object(frappe,'get_meta',return_value=Mock());p.start();self.addCleanup(p.stop)
        p=patch('worldshading.api.bank_loan_schedule.nowdate',return_value='2026-11-19')
        p.start();self.addCleanup(p.stop)

    def test_new_preview_returns_rows_without_creating_documents(self):
        result=preview_schedule(loan(),options())
        self.assertEqual(result['scheduled_interest'],390)
        self.assertEqual(len(result['rows']),12)
        self.assertEqual(result['retained_rows'],0)

    def test_installment_preview_keeps_source_rate_and_cash_amount(self):
        source=loan(annual_interest_rate=9)
        result=preview_schedule(source,options(method='Equal Installments',calculation_mode='Installment Amount',installment_amount=1060))
        self.assertEqual(source['annual_interest_rate'],9)
        self.assertEqual(result['scheduled_total'],12720)
        self.assertEqual(result['calculation_mode'],'Installment Amount')
        self.assertTrue(all(r['total_amount']==1060 for r in result['rows']))

    def test_rejects_wrong_role_state_or_create_permission(self):
        for state in ['Approved','Pending Loan - App','Closed']:
            with self.assertRaises(ValueError):preview_schedule(loan(workflow_state=state),options())
        with patch.object(frappe,'get_roles',return_value=['Accounts User']):
            with self.assertRaises(ValueError):preview_schedule(loan(),options())
        with patch.object(frappe,'has_permission',return_value=False):
            with self.assertRaises(ValueError):preview_schedule(loan(),options())

    def test_saved_state_is_checked_instead_of_client_claim(self):
        saved=Mock(workflow_state='Approved',docstatus=0)
        with patch.object(frappe,'get_doc',return_value=saved):
            with self.assertRaises(ValueError):
                preview_schedule(loan(name='BLN-1',workflow_state='Draft'),options())
        saved.workflow_state='Draft'
        saved.check_permission.side_effect=ValueError('denied')
        with patch.object(frappe,'get_doc',return_value=saved):
            with self.assertRaises(ValueError):preview_schedule(loan(name='BLN-1'),options())

    def test_installment_amount_cannot_replace_a_linked_installment(self):
        from worldshading.worldshading.doctype.bank_loan.generator import generate_schedule
        source=loan(name='BLN-1',workflow_state='Draft')
        source['schedule']=generate_schedule(loan(),options(),3,'2026-11-19')['rows']
        for i,row in enumerate(source['schedule']):row['name']='ROW-'+str(i)
        saved=Mock(workflow_state='Draft',docstatus=0)
        payments=[dict(docstatus=1,allocations=[dict(installment='ROW-0')])]
        with patch.object(frappe,'get_doc',return_value=saved),patch('worldshading.api.bank_loan_payments.payment_documents',return_value=payments):
            with self.assertRaises(ValueError):
                preview_schedule(source,options(method='Equal Installments',calculation_mode='Installment Amount',installment_amount=1060))

    def test_recorded_zero_rate_settlement_preview_is_read_only(self):
        import copy
        source=loan(annual_interest_rate=0,maturity_date='2026-12-19')
        original=copy.deepcopy(source)
        result=preview_schedule(source,options(method='Equal Installments',calculation_mode='Installment Amount',
            rate_source='Use Recorded Rate',installment_amount=5000,periods=1))
        self.assertEqual(source,original)
        self.assertEqual(result['scheduled_principal'],12000)
        self.assertEqual(result['scheduled_interest'],0)
        self.assertEqual(result['maturity_date'],'2027-01-19')
        self.assertEqual(result['rows'][-1]['total_amount'],7000)

    def test_json_inputs_and_invalid_shape(self):
        import json
        result=preview_schedule(json.dumps(loan()),json.dumps(options()))
        self.assertEqual(result['scheduled_principal'],12000)
        for bad in [[], 'null', '[]']:
            with self.assertRaises(ValueError):preview_schedule(bad,options())


if __name__=='__main__':unittest.main()
