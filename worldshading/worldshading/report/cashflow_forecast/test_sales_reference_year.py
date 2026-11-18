"""Use the latest historical matching calendar date, never an unrecorded future date."""
import unittest
from unittest.mock import patch, Mock
from datetime import date
from types import SimpleNamespace
import frappe
from worldshading.worldshading.report.cashflow_forecast.sources import Sources

class SalesReferenceYearTests(unittest.TestCase):
    def source(self,start,end):
        source=Sources.__new__(Sources);source.company='Example';source.start=start;source.end=end
        source.historical={};source.sales_tax={};source.warnings=[]
        return source

    def load(self,source,records,taxes=None):
        listing=Mock(side_effect=[records,[]])
        with patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_list',listing), \
             patch.object(frappe,'db',SimpleNamespace(sql=Mock(return_value=taxes or []))):
            source.historical_sales()
        return listing

    def test_previous_year_when_historical_and_fallback_only_after_today(self):
        source=self.source(date(2026,11,18),date(2027,12,31))
        rows=[frappe._dict(name='OLD',posting_date=date(2025,11,19),base_grand_total=110),
              frappe._dict(name='JAN',posting_date=date(2026,1,2),base_grand_total=220),
              frappe._dict(name='BOUNDARY',posting_date=date(2026,11,18),base_grand_total=25),
              frappe._dict(name='FUTURE',posting_date=date(2026,11,19),base_grand_total=999)]
        listing=self.load(source,rows,[frappe._dict(parent='JAN',amount=20),frappe._dict(parent='OLD',amount=10)])
        self.assertEqual(source.historical['2027-01-02'],220)
        self.assertEqual(source.sales_tax['2027-01-02'],20)
        self.assertEqual(source.historical['2027-11-18'],25)
        self.assertEqual(source.historical['2027-11-19'],110)
        self.assertEqual(source.sales_tax['2027-11-19'],10)
        self.assertEqual(source.historical['2026-11-19'],110)
        self.assertEqual(source.actual_sales_today,25)
        fallback=[p for p in source.historical_reference_periods if p['fallback']]
        self.assertEqual(fallback,[dict(forecast_from='2027-11-19',forecast_to='2027-12-31',reference_from='2025-11-19',reference_to='2025-12-31',fallback=True)])
        query=listing.call_args_list[0][1]['filters']['posting_date'][1]
        self.assertLessEqual(query[1],source.start)
        self.assertLessEqual(listing.call_count,2)

    def test_zero_sales_day_is_not_replaced_with_older_sales(self):
        source=self.source(date(2026,11,18),date(2027,1,3))
        self.load(source,[frappe._dict(name='OLD',posting_date=date(2025,1,2),base_grand_total=55)])
        self.assertEqual(source.historical['2027-01-02'],0)

    def test_leap_day_uses_february_28_of_latest_historical_year(self):
        source=self.source(date(2026,11,18),date(2028,3,1))
        self.load(source,[frappe._dict(name='FEB',posting_date=date(2026,2,28),base_grand_total=55)])
        self.assertEqual(source.historical['2028-02-29'],55)
        self.assertEqual(source.historical['2028-02-28'],55)

    def test_no_reference_invoices_warns_without_inventing_sales(self):
        source=self.source(date(2026,11,18),date(2026,11,19))
        self.load(source,[])
        self.assertEqual(source.historical['2026-11-19'],0)
        self.assertTrue(source.warnings)
