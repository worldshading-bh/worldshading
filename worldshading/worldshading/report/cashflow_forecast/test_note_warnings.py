"""Requested note cleanup leaves financial events unchanged."""
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
import frappe
from worldshading.worldshading.report.cashflow_forecast.budgets import Budgets

class NoteWarningTests(unittest.TestCase):
    def test_no_budget_is_silent_and_produces_no_budget_events(self):
        warnings=[];events=[]
        source=SimpleNamespace(start=date(2026,11,17),end=date(2027,12,31),documents=lambda *args:iter([]),warn=warnings.append,event=lambda *args:events.append(args))
        with patch.object(frappe,'has_permission',return_value=True):Budgets(source).collect()
        self.assertEqual(warnings,[]);self.assertEqual(events,[])
