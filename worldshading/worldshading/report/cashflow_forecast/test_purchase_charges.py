"""Optional customs/import VAT use independent cash dates and company tax rules."""
import unittest
from datetime import date
from copy import deepcopy
from worldshading.worldshading.report.cashflow_forecast.scenarios import purchase_events
from worldshading.worldshading.report.cashflow_forecast import test_purchase_budget as fixtures

class PurchaseCharges(unittest.TestCase):
    def values(self,customs=1,vat=1):
        return dict(schema=5,purchases=[dict(payments=[dict(date='2026-12-20',amount=1000)],
            customs_required=customs,import_vat_required=vat,customs_date='2026-11-20',import_vat_date='2026-11-25')])

    def test_customs_and_vat_keep_independent_dates_before_supplier_payment(self):
        template=fixtures.PurchaseTests().taxes();original=deepcopy(template)
        events=purchase_events(self.values(),'2026-11-15','2026-12-31',template)
        self.assertEqual([(e['category'],e['date'],e['amount']) for e in events],
            [('proposed_purchase',date(2026,12,20),1000),('customs',date(2026,11,20),50),
             ('import_vat',date(2026,11,25),105),('vat_accrual',date(2026,11,25),-105)])
        self.assertEqual(template,original)
        self.assertTrue(all(e['purchase_number']==1 for e in events))

    def test_vat_only_excludes_customs_from_vat_base(self):
        events=purchase_events(self.values(0,1),'2026-11-15','2026-12-31',fixtures.PurchaseTests().taxes())
        self.assertEqual([(e['category'],e['amount']) for e in events],
                         [('proposed_purchase',1000),('import_vat',100),('vat_accrual',-100)])

    def test_customs_only_and_neither(self):
        events=purchase_events(self.values(1,0),'2026-11-15','2026-12-31',fixtures.PurchaseTests().taxes())
        self.assertEqual([(e['category'],e['amount']) for e in events],[('proposed_purchase',1000),('customs',50)])
        self.assertEqual(len(purchase_events(self.values(0,0),'2026-11-15','2026-12-31')),1)

    def test_selected_charge_requires_valid_in_period_date(self):
        for key,bad in [('customs_date',None),('import_vat_date','2027-01-01'),('customs_date','2026-11-14'),
                        ('customs_required',2),('import_vat_required','invalid')]:
            values=self.values();values['purchases'][0][key]=bad
            with self.assertRaises((ValueError,TypeError)):
                purchase_events(values,'2026-11-15','2026-12-31',fixtures.PurchaseTests().taxes())

    def test_old_international_purchase_keeps_both_charges_on_eta(self):
        values=dict(schema=4,purchases=[dict(payments=[dict(date='2026-12-20',amount=1000)],international=1,eta_date='2026-11-20')])
        events=purchase_events(values,'2026-11-15','2026-12-31',fixtures.PurchaseTests().taxes())
        self.assertEqual([(e['date'],e['amount']) for e in events if e['category']=='import_vat'],[(date(2026,11,20),105)])

    def test_report_validation_selects_company_template_for_vat_only(self):
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
        with patch.object(report,'authorize'),patch.object(report,'resolve_accounts',return_value=['Bank']), \
             patch.object(report,'nowdate',return_value='2026-11-15'), \
             patch.object(report,'get_company_import_rows',return_value=fixtures.PurchaseTests().taxes()) as template:
            result=report.validate(dict(company='Example',end_date='2026-12-31',purchase_scenario=self.values(0,1)))
        template.assert_called_once_with('Example')
        self.assertEqual([e['amount'] for e in result[4] if e['category']=='import_vat'],[100])

    def test_no_charges_needs_no_import_template(self):
        from unittest.mock import patch
        from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report
        with patch.object(report,'authorize'),patch.object(report,'resolve_accounts',return_value=['Bank']), \
             patch.object(report,'nowdate',return_value='2026-11-15'), \
             patch.object(report,'get_company_import_rows') as template:
            result=report.validate(dict(company='Example',end_date='2026-12-31',purchase_scenario=self.values(0,0)))
        template.assert_not_called()
        self.assertEqual(len(result[4]),1)
