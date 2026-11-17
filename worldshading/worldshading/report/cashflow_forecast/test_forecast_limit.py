"""Three calendar years, including leap days, with the same bound everywhere."""
import unittest
from datetime import date
from unittest.mock import patch
from worldshading.worldshading.report.cashflow_forecast import engine,horizon,cashflow_forecast as report
from worldshading.worldshading.report.cashflow_forecast.scenarios import arrival_date

class ForecastLimitTests(unittest.TestCase):
    def test_exact_three_year_forecast_includes_leap_day(self):
        rows=engine.build_forecast('2026-11-17','2029-11-17',100,[],{})
        self.assertEqual(rows[-1]['date'],date(2029,11,17));self.assertEqual(len(rows),1097)
        with self.assertRaises(ValueError):engine.build_forecast('2026-11-17','2029-11-18',100,[],{})

    def test_limit_is_calendar_years_not_a_fixed_day_count(self):
        self.assertEqual(engine.maximum_forecast_date('2025-01-01'),date(2028,1,1))
        self.assertEqual(engine.maximum_forecast_date('2024-02-29'),date(2027,2,28))

    def test_generation_and_purchase_horizon_accept_same_boundary(self):
        self.assertEqual(horizon.adjust_end_date('2027-01-01','2026-11-17','2029-11-17'),date(2029,11,17))
        with self.assertRaises(ValueError):horizon.adjust_end_date('2027-01-01','2026-11-17','2029-11-18')
        with patch.object(report,'authorize'),patch.object(report,'resolve_accounts',return_value=['Bank']),patch.object(report,'nowdate',return_value='2026-11-17'):
            self.assertEqual(report.validate(dict(company='Example',end_date='2029-11-17'))[2],date(2029,11,17))
            with self.assertRaises(Exception):report.validate(dict(company='Example',end_date='2029-11-18'))

    def test_legacy_purchase_lead_times_allow_three_years(self):
        self.assertEqual(arrival_date('2026-11-17','Lead Time',lead=1096,unit='Days'),date(2029,11,17))
        self.assertEqual(arrival_date('2026-11-17','Lead Time',lead=36,unit='Months'),date(2029,11,17))
        for lead,unit in [(1097,'Days'),(37,'Months')]:
            with self.assertRaises(ValueError):arrival_date('2026-11-17','Lead Time',lead=lead,unit=unit)
