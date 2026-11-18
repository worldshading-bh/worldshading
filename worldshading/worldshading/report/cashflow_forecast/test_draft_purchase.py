"""Draft PO planning reads; all Frappe access mocked, no business database."""
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
import frappe
from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report

def reject(message,*args,**kwargs):
    raise frappe.ValidationError(message)

class DraftPurchaseTests(unittest.TestCase):
    def draft(self,**values):
        doc=frappe._dict(name='DRAFT-1',company='Example',docstatus=0,supplier='SUP',supplier_name='Supplier',
            supplier_country='Kuwait',currency='USD',conversion_rate='0.377',base_grand_total='113.100',
            transaction_date='2026-10-01',eta_date='2026-11-25',customs_required=0,import_vat_required=1,
            payment_schedule=[frappe._dict(due_date='2026-10-15',payment_amount=100),frappe._dict(due_date='2026-12-15',payment_amount=200)])
        doc.update(values);doc.check_permission=Mock();return doc

    def load(self,doc):
        with patch.object(frappe,'throw',side_effect=reject),patch.object(report,'authorize') as auth,patch.object(report,'nowdate',return_value='2026-11-18'), \
             patch.object(frappe,'get_doc',return_value=doc),patch.object(frappe,'db',SimpleNamespace(get_value=lambda *args:'Bahrain')):
            result=report.get_draft_purchase('Example','DRAFT-1')
        auth.assert_called_once_with('Example');doc.check_permission.assert_called_once_with('read')
        return result

    def test_base_currency_schedule_and_only_past_dates_move_to_today(self):
        result=self.load(self.draft())
        self.assertEqual(result['payments'],[dict(date='2026-11-18',amount='37.700'),dict(date='2026-12-15',amount='75.400')])
        self.assertEqual(result['supplier'],'SUP');self.assertEqual(result['draft_po'],'DRAFT-1')
        self.assertEqual(result['customs_required'],0);self.assertEqual(result['import_vat_required'],1)
        self.assertEqual(result['import_vat_date'],'2026-11-25')
        self.assertEqual(result['moved_past_dates'],1)

    def test_rounded_foreign_currency_po_uses_payable_total_like_native_schedule(self):
        doc=self.draft(currency='SAR',conversion_rate='0.10023',grand_total='360414.375',
            rounded_total='360414.000',base_grand_total='36124.333',base_rounded_total='36124.295',
            payment_schedule=[frappe._dict(due_date='2026-11-27',payment_amount='180207.000'),
                              frappe._dict(due_date='2027-02-11',payment_amount='180207.000')])
        result=self.load(doc)
        self.assertEqual(result['payments'],[dict(date='2026-11-27',amount='18062.148'),dict(date='2027-02-11',amount='18062.148')])
        doc.payment_schedule=[];doc.check_permission.reset_mock()
        self.assertEqual(self.load(doc)['payments'],[dict(date='2026-11-18',amount='36124.295')])

    def test_local_po_never_adds_port_charges_even_if_flags_set(self):
        result=self.load(self.draft(supplier_country='Bahrain',customs_required=1))
        self.assertEqual(result['customs_required'],0);self.assertEqual(result['import_vat_required'],0)

    def test_no_schedule_uses_supplier_total_and_order_date(self):
        result=self.load(self.draft(payment_schedule=[]))
        self.assertEqual(result['payments'],[dict(date='2026-11-18',amount='113.100')])

    def test_missing_eta_keeps_charges_blank_for_manual_dates(self):
        result=self.load(self.draft(eta_date=None))
        self.assertIsNone(result['import_vat_date']);self.assertEqual(result['import_vat_required'],1)

    def test_wrong_company_and_submitted_or_cancelled_po_rejected(self):
        for values in [dict(company='Other'),dict(docstatus=1),dict(docstatus=2)]:
            with self.assertRaises(frappe.ValidationError):self.load(self.draft(**values))

    def test_denied_document_permission_does_not_return_data(self):
        doc=self.draft();doc.check_permission.side_effect=frappe.PermissionError
        with self.assertRaises(frappe.PermissionError):self.load(doc)

    def test_bad_exchange_rate_and_incomplete_schedule_rejected(self):
        for values in [dict(conversion_rate=0),dict(payment_schedule=[frappe._dict(due_date=None,payment_amount=100)]),
                       dict(payment_schedule=[frappe._dict(due_date='2026-12-01',payment_amount=100)])]:
            with self.assertRaises(frappe.ValidationError):self.load(self.draft(**values))

    def validate_scenario(self,doc,items):
        with patch.object(frappe,'throw',side_effect=reject),patch.object(report,'authorize'),patch.object(report,'selected_accounts',return_value=['BANK']), \
             patch.object(report,'nowdate',return_value='2026-11-18'),patch.object(frappe,'get_doc',return_value=doc):
            return report.validate(dict(company='Example',end_date='2027-11-18',purchase_scenario=dict(schema=5,purchases=items)))

    def test_scenario_rechecks_draft_status_and_rejects_duplicates(self):
        item=dict(draft_po='DRAFT-1',payments=[dict(date='2026-12-01',amount=100)])
        for doc,items in [(self.draft(docstatus=1),[item]),(self.draft(company='Other'),[item]),(self.draft(),[item,item])]:
            with self.assertRaisesRegex(frappe.ValidationError,'no longer a draft|only once'):self.validate_scenario(doc,items)
        doc=self.draft();doc.check_permission.side_effect=frappe.PermissionError
        with self.assertRaises(frappe.PermissionError):self.validate_scenario(doc,[item])

    def test_scenario_validation_preserves_manually_edited_schedule(self):
        doc=self.draft();item=dict(draft_po='DRAFT-1',payments=[dict(date='2026-12-20',amount=99)])
        result=self.validate_scenario(doc,[item])
        self.assertEqual(result[-1][0]['date'].isoformat(),'2026-12-20')
        self.assertEqual(result[-1][0]['amount'],99)
        doc.check_permission.assert_called_once_with('read')
