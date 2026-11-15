"""PO tax choice adapters; native recalculation is isolated from site/database hooks."""
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import frappe
from worldshading.worldshading.report.cashflow_forecast.sources import Sources
from worldshading.worldshading.report.cashflow_forecast.engine import template_taxes

class Row(frappe._dict):
    def as_dict(self):return dict(self)

class Po(SimpleNamespace):
    def get(self,key,default=None):return getattr(self,key,default)
    def as_dict(self):
        return dict(name=self.name,taxes_and_charges=self.taxes_and_charges,base_net_total=1000,
                    taxes=[r.as_dict() for r in self.taxes],customs_required=self.customs_required,import_vat_required=self.import_vat_required)
    def set(self,key,value):setattr(self,key,value)
    def append(self,key,value):getattr(self,key).append(Row(value))

class PoTaxFlags(unittest.TestCase):
    def collect(self,customs,vat,missing=False,shipping_only=False,other_freight=False):
        rows=[Row(account_head='Freight',charge_type='Actual',tax_amount=0,base_tax_amount_after_discount_amount=0,category='Valuation and Total'),
              Row(account_head='Custom Duty - WS',charge_type='On Previous Row Total',row_id=1,rate=5,category='Valuation',base_tax_amount_after_discount_amount=50),
              Row(account_head='Input VAT – Import - WS',charge_type='On Previous Row Total',row_id=2,rate=10,category='Total',base_tax_amount_after_discount_amount=100)]
        po=Po(name='PO',taxes_and_charges='Template',taxes=deepcopy(rows[:1] if missing or shipping_only else rows),
              base_net_total=1000,customs_required=customs,import_vat_required=vat)
        if other_freight:
            po.taxes=[Row(account_head='Other Freight',charge_type='Actual',tax_amount=100,base_tax_amount_after_discount_amount=100,category='Valuation and Total')]
        original=deepcopy(po.as_dict())
        source=Sources.__new__(Sources);source.warnings=[];source.company='Example'
        source.read_document=lambda *args:SimpleNamespace(taxes=rows[:1] if shipping_only else rows)
        def clone(values):
            values['taxes']=[Row(r) for r in values['taxes']]
            return Po(**values)
        def calculate(doc):
            amounts=template_taxes(doc.base_net_total,[r.as_dict() for r in doc.taxes])
            for row,amount in zip(doc.taxes,amounts):row.base_tax_amount_after_discount_amount=amount
        with patch.object(frappe,'get_doc',side_effect=clone), \
             patch('worldshading.worldshading.report.cashflow_forecast.cashflow_forecast.get_company_import_rows',return_value=[r.as_dict() for r in rows]), \
             patch('erpnext.controllers.taxes_and_totals.calculate_taxes_and_totals',side_effect=calculate):
            taxes=source.tax_estimate(po)
        self.assertEqual(po.as_dict(),original,'The accounting PO and its tax rows must not change')
        return {r['account_head']:r['base_tax_amount_after_discount_amount'] for r in taxes}

    def test_vat_only_recalculates_base_without_customs(self):
        for missing in (False,True):
            amounts=self.collect(0,1,missing)
            self.assertEqual(amounts['Custom Duty - WS'],0)
            self.assertEqual(amounts['Input VAT – Import - WS'],100)

    def test_customs_only_and_both_charges(self):
        self.assertEqual(self.collect(1,0)['Input VAT – Import - WS'],0)
        self.assertEqual(self.collect(1,1)['Input VAT – Import - WS'],105)

    def test_shipping_only_po_uses_company_import_rules_when_required(self):
        amounts=self.collect(1,1,shipping_only=True)
        self.assertEqual(amounts['Custom Duty - WS'],50)
        self.assertEqual(amounts['Input VAT – Import - WS'],105)

    def test_company_fallback_preserves_supplier_shipping_under_another_account(self):
        amounts=self.collect(1,1,shipping_only=True,other_freight=True)
        self.assertEqual(amounts['Custom Duty - WS'],55)
        self.assertEqual(amounts['Input VAT – Import - WS'],115.5)
