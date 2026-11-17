"""Optional supplier setup reads existing master data without document writes."""
import unittest
from unittest.mock import patch,Mock
from types import SimpleNamespace
import frappe
from worldshading.worldshading.report.cashflow_forecast import cashflow_forecast as report

class SupplierDefaultsTests(unittest.TestCase):
    def test_supplier_country_and_existing_payment_template(self):
        supplier=frappe._dict(supplier_name='Example Trading',country='Kuwait',payment_terms='50/50')
        supplier.check_permission=Mock()
        terms=frappe._dict(terms=[frappe._dict(invoice_portion=50,due_date_based_on='Day(s) after invoice date',credit_days=n) for n in [0,30]])
        terms.check_permission=Mock()
        with patch.object(report,'authorize'),patch.object(frappe,'get_doc',side_effect=lambda dt,name:supplier if dt=='Supplier' else terms), \
             patch.object(frappe,'db',SimpleNamespace(get_value=lambda *args:'Bahrain')):
            result=report.get_supplier_defaults('Example','SUP-1')
        self.assertEqual(result['supplier_name'],'Example Trading')
        self.assertTrue(result['international'])
        self.assertEqual([r['credit_days'] for r in result['terms']],[0,30])
        supplier.check_permission.assert_called_with('read');terms.check_permission.assert_called_with('read')

    def test_no_template_preserves_manual_mode_and_local_country(self):
        supplier=frappe._dict(supplier_name='Local',country=' bAhRaIn ',payment_terms=None)
        supplier.check_permission=lambda *args:None
        with patch.object(report,'authorize'),patch.object(frappe,'get_doc',return_value=supplier), \
             patch.object(frappe,'db',SimpleNamespace(get_value=lambda *args:'Bahrain')):
            result=report.get_supplier_defaults('Example','SUP-1')
        self.assertEqual(result['terms'],[]);self.assertFalse(result['international'])

    def test_date_only_defaults_do_not_reject_percentage_rounding(self):
        supplier=frappe._dict(supplier_name='Example',country='Bahrain',payment_terms='Thirds')
        supplier.check_permission=lambda *args:None
        template=frappe._dict(terms=[frappe._dict(invoice_portion=portion,due_date_based_on='Day(s) after invoice date',credit_days=i*30)
                                      for i,portion in enumerate([33.333333,33.333333,33.333334])])
        template.check_permission=lambda *args:None
        with patch.object(report,'authorize'),patch.object(frappe,'get_doc',side_effect=lambda dt,name:supplier if dt=='Supplier' else template), \
             patch.object(frappe,'db',SimpleNamespace(get_value=lambda *args:'Bahrain')):
            result=report.get_supplier_defaults('Example','SUP')
        self.assertEqual(len(result['terms']),3)
