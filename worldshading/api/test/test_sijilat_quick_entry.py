# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import unittest

try:
    from unittest.mock import MagicMock, patch
except ImportError:
    from mock import MagicMock, patch

import frappe

from worldshading.api import sijilat
from worldshading.api import sijilat_quick_entry


class TestSijilatQuickEntryPreview(unittest.TestCase):
    def setUp(self):
        frappe.local.session = frappe._dict({"user": "sales@example.com"})
        frappe.local.flags = frappe._dict({"in_test": True})
        frappe.local.db = MagicMock()
        frappe.local.db.get_system_setting.return_value = "Asia/Bahrain"
        frappe.local.cache = {}

    def tearDown(self):
        frappe.local.session = None
        frappe.local.flags = None
        frappe.local.db = None
        frappe.local.cache = None

    @patch.object(sijilat_quick_entry.frappe, "has_permission", return_value=True)
    def test_invalid_cr_format_does_not_call_sijilat(self, has_permission):
        with patch.object(sijilat, "fetch_cr_details") as fetch:
            result = sijilat_quick_entry.preview_customer_cr(
                "Example Company", "12345", "Company", "Bahrain"
            )

        self.assertEqual(result["outcome"], "invalid_format")
        fetch.assert_not_called()

    @patch.object(sijilat_quick_entry, "_find_duplicate_cr")
    @patch.object(sijilat_quick_entry.frappe, "has_permission", return_value=True)
    def test_duplicate_cr_is_rejected_before_sijilat(
        self, has_permission, find_duplicate
    ):
        find_duplicate.return_value = frappe._dict({
            "name": "CM0001",
            "customer_name": "Existing Company",
            "disabled": 0
        })

        with patch.object(sijilat, "fetch_cr_details") as fetch:
            result = sijilat_quick_entry.preview_customer_cr(
                "Example Company", "12345-1", "Company", "Bahrain"
            )

        self.assertEqual(result["outcome"], "duplicate")
        fetch.assert_not_called()

    @patch.object(sijilat_quick_entry, "_find_duplicate_cr", return_value=None)
    @patch.object(sijilat_quick_entry.frappe, "has_permission", return_value=True)
    def test_temporary_api_error_allows_controlled_bypass(
        self, has_permission, find_duplicate
    ):
        with patch.object(
            sijilat,
            "fetch_cr_details",
            side_effect=sijilat.SijilatTemporaryError("temporary")
        ):
            result = sijilat_quick_entry.preview_customer_cr(
                "Example Company", "12345-1", "Company", "Bahrain"
            )

        self.assertEqual(result["outcome"], "temporary_error")

    @patch.object(sijilat_quick_entry, "_find_duplicate_cr", return_value=None)
    @patch.object(sijilat_quick_entry.frappe, "has_permission", return_value=True)
    def test_unrelated_name_does_not_expose_official_identity(
        self, has_permission, find_duplicate
    ):
        api_result = {
            "formatted": {
                "Company Summary": {
                    "Commercial Name (EN)": "Completely Different Trading WLL",
                    "Commercial Name (AR)": "",
                    "CR No.": "12345-1",
                    "Expiration Date": "18/08/2027",
                    "Status": "ACTIVE"
                }
            }
        }
        with patch.object(sijilat, "fetch_cr_details", return_value=api_result):
            result = sijilat_quick_entry.preview_customer_cr(
                "Blue Workshop", "12345-1", "Company", "Bahrain"
            )

        self.assertEqual(result["outcome"], "name_mismatch")
        self.assertNotIn("official_customer_name", result)

    @patch.object(sijilat_quick_entry.frappe, "cache")
    @patch.object(sijilat_quick_entry, "_find_duplicate_cr", return_value=None)
    @patch.object(sijilat_quick_entry.frappe, "has_permission", return_value=True)
    def test_active_matching_cr_returns_verification_token(
        self, has_permission, find_duplicate, cache
    ):
        api_result = {
            "formatted": {
                "Company Summary": {
                    "Commercial Name (EN)": "Example Company W.L.L",
                    "Commercial Name (AR)": "",
                    "CR No.": "12345-1",
                    "Expiration Date": "18/08/2027",
                    "Status": "ACTIVE"
                },
                "Business Activities": [],
                "Commercial Address": {}
            }
        }
        with patch.object(sijilat, "fetch_cr_details", return_value=api_result):
            result = sijilat_quick_entry.preview_customer_cr(
                "Example Company", "12345-1", "Company", "Bahrain"
            )

        self.assertEqual(result["outcome"], "verified")
        self.assertTrue(result["verification_token"])
        cache.return_value.set_value.assert_called_once()


class TestSijilatQuickEntryFinalization(unittest.TestCase):
    def setUp(self):
        frappe.local.session = frappe._dict({"user": "sales@example.com"})

    def tearDown(self):
        frappe.local.session = None

    @patch.object(sijilat_quick_entry.frappe, "cache")
    @patch.object(sijilat_quick_entry.frappe, "get_doc")
    def test_matching_cached_preview_marks_customer_verified(self, get_doc, cache):
        customer = MagicMock()
        customer.name = "CM0001"
        customer.customer_type = "Company"
        customer.territory = "Bahrain"
        customer.customer_name = "Example Company WLL"
        customer.cr_no = "12345-1"
        customer.flags = frappe._dict()
        get_doc.return_value = customer
        cache.return_value.get_value.return_value = {
            "customer_name": "Example Company WLL",
            "cr_no": "12345-1",
            "customer_type": "Company",
            "territory": "Bahrain",
            "verified_business_details": "Status: ACTIVE",
            "cr_expiry_date": "2027-08-18",
            "checked_at": "2026-09-29 10:00:00"
        }

        result = sijilat_quick_entry.finalize_customer_cr("CM0001", "token")

        customer.check_permission.assert_called_once_with("write")
        self.assertEqual(customer.business_verification_status, "Verified")
        self.assertTrue(customer.flags.sijilat_verification)
        customer.save.assert_called_once_with()
        self.assertEqual(result["status"], "Verified")
