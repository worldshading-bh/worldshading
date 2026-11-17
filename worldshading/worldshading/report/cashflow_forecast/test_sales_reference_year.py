"""Forecast years repeat a single completed reference year's calendar sales."""
import unittest
from unittest.mock import patch,Mock
from datetime import date
from types import SimpleNamespace
import frappe
from worldshading.worldshading.report.cashflow_forecast.sources import Sources

class SalesReferenceYearTests(unittest.TestCase):
    def source(self,start,end):
        source=Sources.__new__(Sources);source.company='Example';source.start=start;source.end=end
        source.historical={};source.sales_tax={};source.warnings=[]
        return source

    def test_current_and_next_forecast_year_use_same_completed_reference(self):
        source=self.source(date(2026,11,17),date(2027,12,31))
        prior=frappe._dict(name='REF',posting_date=date(2025,11,18),base_grand_total=110)
        today=frappe._dict(name='TODAY',posting_date=source.start,base_grand_total=25)
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_list',side_effect=[[prior],[today],[frappe._dict(posting_date=date(2025,1,1))]]) as listing, \
             patch.object(frappe,'db',SimpleNamespace(sql=Mock(return_value=[frappe._dict(parent='REF',amount=10)]))):
            source.historical_sales()
        self.assertEqual(source.historical['2026-11-18'],110)
        self.assertEqual(source.historical['2027-11-18'],110)
        self.assertEqual(source.sales_tax['2026-11-18'],10)
        self.assertEqual(source.sales_tax['2027-11-18'],10)
        self.assertEqual(source.actual_sales_today,25)
        self.assertEqual(source.historical_reference_year,2025)
        self.assertFalse(any('beyond available' in warning for warning in source.warnings))
        self.assertEqual(listing.call_args_list[0][1]['filters']['posting_date'],['between',[date(2025,1,1),date(2025,12,31)]])

    def test_leap_day_uses_february_28_when_reference_year_is_not_leap(self):
        source=self.source(date(2027,11,17),date(2028,3,1))
        prior=frappe._dict(name='REF',posting_date=date(2026,2,28),base_grand_total=55)
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_list',side_effect=[[prior],[],[frappe._dict(posting_date=date(2026,1,1))]]), \
             patch.object(frappe,'db',SimpleNamespace(sql=Mock(return_value=[]))):source.historical_sales()
        self.assertEqual(source.historical['2028-02-29'],55)
        self.assertEqual(source.historical['2028-02-28'],55)

    def test_no_reference_invoices_still_warns_and_does_not_invent_sales(self):
        source=self.source(date(2026,11,17),date(2026,11,18))
        today=frappe._dict(name='TODAY',posting_date=source.start,base_grand_total=25)
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_list',side_effect=[[],[today],[]]), \
             patch.object(frappe,'db',SimpleNamespace(sql=Mock(return_value=[]))):source.historical_sales()
        self.assertEqual(source.historical['2026-11-18'],0)
        self.assertTrue(any('2025' in warning for warning in source.warnings))

    def test_first_invoice_on_january_2_is_not_an_incomplete_history_warning(self):
        source=self.source(date(2026,11,17),date(2027,12,31))
        prior=frappe._dict(name='REF',posting_date=date(2025,1,2),base_grand_total=55)
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_list',side_effect=[[prior],[],[frappe._dict(posting_date=date(2025,1,2))]]), \
             patch.object(frappe,'db',SimpleNamespace(sql=Mock(return_value=[]))):source.historical_sales()
        self.assertFalse(any('coverage starts' in warning for warning in source.warnings))
        self.assertEqual(source.historical['2027-01-01'],0)
        self.assertEqual(source.historical['2027-01-02'],55)
