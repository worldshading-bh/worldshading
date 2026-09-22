# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import datetime
import unittest
from types import SimpleNamespace

try:
	from unittest.mock import MagicMock, patch
except ImportError:
	from mock import MagicMock, patch

import frappe

from worldshading.api import sijilat
from worldshading import hooks


class DummyCustomer(object):
	def __init__(self, **overrides):
		values = {
			"name": "CM0001",
			"disabled": 0,
			"customer_type": "Company",
			"territory": "Bahrain",
			"cr_no": "90666-1",
			"customer_name": "WORLD SHADING",
			"business_verification_status": "",
			"verified_business_details": "",
			"cr_expiry_date": None,
			"last_sijilat_check": None,
			"sijilat_recheck_attempts": 0,
			"default_price_list": "B2B Price - Test",
			"customer_price_list": "(B)Offer",
		}
		values.update(overrides)
		for fieldname, value in values.items():
			setattr(self, fieldname, value)
		self.flags = frappe._dict()
		self.save = MagicMock()


class TestExistingCustomerEligibility(unittest.TestCase):
	def setUp(self):
		self.checked_at = datetime.datetime(2026, 9, 17, 12, 0)

	def test_supported_cr_format_is_valid(self):
		self.assertTrue(sijilat._is_valid_customer_cr("90666-1"))

	def test_spaces_around_cr_and_branch_are_normalized(self):
		self.assertEqual(
			sijilat._normalize_customer_cr_input(" 78860 - 1 "),
			"78860-1"
		)
		self.assertTrue(sijilat._is_valid_customer_cr(" 78860 - 1 "))

	def test_missing_branch_is_invalid(self):
		self.assertFalse(sijilat._is_valid_customer_cr("90666"))

	def test_letters_are_invalid(self):
		self.assertFalse(sijilat._is_valid_customer_cr("90A66-1"))

	def test_eligible_historical_company_is_selected(self):
		self.assertTrue(sijilat._is_existing_customer_auto_verification_eligible(
			DummyCustomer(), self.checked_at))
		self.assertTrue(sijilat._is_existing_customer_auto_verification_eligible(
			DummyCustomer(sijilat_recheck_attempts=None), self.checked_at))

	def test_non_matching_customer_properties_are_ineligible(self):
		ineligible_customers = [
			DummyCustomer(disabled=1),
			DummyCustomer(customer_type="Individual"),
			DummyCustomer(territory="KSA"),
			DummyCustomer(cr_no=""),
			DummyCustomer(business_verification_status="Not Verified"),
			DummyCustomer(sijilat_recheck_attempts=3),
		]
		for customer in ineligible_customers:
			self.assertFalse(
				sijilat._is_existing_customer_auto_verification_eligible(
					customer, self.checked_at))

	def test_retry_requires_full_twenty_four_hour_cooldown(self):
		self.assertFalse(sijilat._is_existing_customer_auto_verification_eligible(
			DummyCustomer(last_sijilat_check=self.checked_at - datetime.timedelta(hours=23)),
			self.checked_at))
		self.assertTrue(sijilat._is_existing_customer_auto_verification_eligible(
			DummyCustomer(last_sijilat_check=self.checked_at - datetime.timedelta(hours=25)),
			self.checked_at))


class TestSijilatTemporaryFailureClassification(unittest.TestCase):
	@patch.object(sijilat.frappe, "log_error")
	@patch.object(sijilat.requests, "post")
	@patch.object(sijilat, "get_sijilat_token", return_value=None)
	def test_missing_token_is_temporary_and_skips_detail_request(
		self, get_token, post, log_error
	):
		with self.assertRaises(sijilat.SijilatTemporaryError):
			sijilat.fetch_cr_details("90666-1")
		post.assert_not_called()

	@patch.object(sijilat.frappe, "log_error")
	@patch.object(sijilat.requests, "post")
	@patch.object(sijilat, "get_sijilat_token", return_value="token")
	def test_malformed_json_shape_is_temporary(self, get_token, post, log_error):
		response = MagicMock()
		response.json.return_value = []
		post.return_value = response

		with self.assertRaises(sijilat.SijilatTemporaryError):
			sijilat.fetch_cr_details("90666-1")


class TestExistingCustomerDispatcher(unittest.TestCase):
	def setUp(self):
		self.now_patcher = patch.object(
			sijilat,
			"now_datetime",
			return_value=datetime.datetime(2026, 9, 17, 12, 0)
		)
		self.now_patcher.start()

	def tearDown(self):
		self.now_patcher.stop()

	@patch.object(sijilat.frappe, "enqueue")
	@patch.object(sijilat.frappe, "get_all")
	def test_dispatcher_enqueues_only_first_eligible_customer(self, get_all, enqueue):
		get_all.return_value = [
			SimpleNamespace(**DummyCustomer(name="CM0001").__dict__),
			SimpleNamespace(**DummyCustomer(name="CM0002").__dict__),
		]

		result = sijilat.enqueue_existing_customer_cr_verification()

		self.assertEqual(result, "CM0001")
		self.assertEqual(
			get_all.call_args[1]["order_by"],
			"last_sijilat_check asc, creation desc"
		)
		enqueue.assert_called_once_with(
			"worldshading.api.sijilat.auto_verify_existing_customer_cr",
			queue="short",
			timeout=60,
			job_name="sijilat_existing_customer_auto_verification|CM0001",
			customer="CM0001"
		)

	@patch.object(sijilat, "now_datetime")
	@patch.object(sijilat.frappe, "enqueue")
	@patch.object(sijilat.frappe, "get_all")
	def test_dispatcher_skips_customers_inside_cooldown(
		self, get_all, enqueue, now_datetime
	):
		checked_at = datetime.datetime(2026, 9, 17, 12, 0)
		now_datetime.return_value = checked_at
		get_all.return_value = [SimpleNamespace(**DummyCustomer(
			last_sijilat_check=checked_at - datetime.timedelta(hours=2)
		).__dict__)]

		self.assertIsNone(sijilat.enqueue_existing_customer_cr_verification())
		enqueue.assert_not_called()


class TestExistingCustomerWorker(unittest.TestCase):
	def setUp(self):
		frappe.local.db = MagicMock()
		self.now_patcher = patch.object(
			sijilat,
			"now_datetime",
			return_value=datetime.datetime(2026, 9, 17, 12, 0)
		)
		self.now_patcher.start()

	def tearDown(self):
		self.now_patcher.stop()
		frappe.local.db = None

	def _verification(self, status="Verified"):
		return {
			"status": status,
			"official_customer_name": "WORLD SHADING W.L.L",
			"official_customer_name_ar": "عالم المظلات",
			"details": "Commercial Name (EN): WORLD SHADING W.L.L",
			"expiry_date": datetime.date(2027, 8, 18),
		}

	@patch.object(sijilat, "_get_business_name_match")
	@patch.object(sijilat, "_fetch_customer_cr_verification")
	@patch.object(sijilat, "_validate_unique_customer_cr")
	@patch.object(sijilat.frappe.db, "commit")
	@patch.object(sijilat.frappe.db, "set_value")
	@patch.object(sijilat.frappe, "get_doc")
	def test_verified_match_renames_customer_without_changing_price_lists(
		self, get_doc, set_value, commit, validate_unique, fetch, name_match
	):
		customer = DummyCustomer(cr_no=" 90666 - 1 ")
		customer.is_fresh = False
		customer.reload = MagicMock(
			side_effect=lambda: setattr(customer, "is_fresh", True)
		)

		def save_only_fresh_document():
			if not customer.is_fresh:
				raise frappe.TimestampMismatchError("stale Customer")

		customer.save.side_effect = save_only_fresh_document
		get_doc.return_value = customer
		fetch.return_value = self._verification()
		name_match.return_value = {"score": 50.01, "level": "approved"}

		result = sijilat.auto_verify_existing_customer_cr(customer.name)

		self.assertEqual(result, "Verified")
		self.assertEqual(customer.customer_name, "WORLD SHADING W.L.L")
		self.assertEqual(customer.business_verification_status, "Verified")
		self.assertEqual(customer.cr_no, "90666-1")
		self.assertEqual(customer.sijilat_recheck_attempts, 0)
		self.assertEqual(customer.default_price_list, "B2B Price - Test")
		self.assertEqual(customer.customer_price_list, "(B)Offer")
		self.assertTrue(customer.flags.get("sijilat_verification"))
		customer.reload.assert_called_once_with()
		customer.save.assert_called_once_with()

	@patch.object(sijilat, "_get_business_name_match")
	@patch.object(sijilat, "_fetch_customer_cr_verification")
	@patch.object(sijilat, "_validate_unique_customer_cr")
	@patch.object(sijilat.frappe.db, "commit")
	@patch.object(sijilat.frappe.db, "set_value")
	@patch.object(sijilat.frappe, "get_doc")
	def test_exactly_fifty_percent_is_not_verified_without_identity_disclosure(
		self, get_doc, set_value, commit, validate_unique, fetch, name_match
	):
		customer = DummyCustomer()
		get_doc.return_value = customer
		fetch.return_value = self._verification()
		name_match.return_value = {"score": 50.0, "level": "blocked"}

		result = sijilat.auto_verify_existing_customer_cr(customer.name)

		self.assertEqual(result, "Not Verified")
		self.assertEqual(customer.customer_name, "WORLD SHADING")
		customer.save.assert_not_called()
		final_values = set_value.call_args_list[-1][0][2]
		self.assertEqual(final_values["business_verification_status"], "Not Verified")
		self.assertNotIn("verified_business_details", final_values)
		self.assertNotIn("cr_expiry_date", final_values)

	@patch.object(sijilat, "_fetch_customer_cr_verification")
	@patch.object(sijilat.frappe.db, "commit")
	@patch.object(sijilat.frappe.db, "set_value")
	@patch.object(sijilat.frappe, "get_doc")
	def test_invalid_cr_is_rejected_without_sijilat_call(
		self, get_doc, set_value, commit, fetch
	):
		get_doc.return_value = DummyCustomer(cr_no="90666")

		result = sijilat.auto_verify_existing_customer_cr("CM0001")

		self.assertEqual(result, "Not Verified")
		fetch.assert_not_called()

	@patch.object(sijilat, "_fetch_customer_cr_verification")
	@patch.object(sijilat, "_validate_unique_customer_cr")
	@patch.object(sijilat.frappe.db, "commit")
	@patch.object(sijilat.frappe.db, "set_value")
	@patch.object(sijilat.frappe, "get_doc")
	def test_duplicate_cr_is_rejected_without_sijilat_call(
		self, get_doc, set_value, commit, validate_unique, fetch
	):
		get_doc.return_value = DummyCustomer()
		validate_unique.side_effect = frappe.ValidationError("duplicate")

		result = sijilat.auto_verify_existing_customer_cr("CM0001")

		self.assertEqual(result, "Not Verified")
		fetch.assert_not_called()

	@patch.object(sijilat, "_get_business_name_match")
	@patch.object(sijilat, "_fetch_customer_cr_verification")
	@patch.object(sijilat, "_validate_unique_customer_cr")
	@patch.object(sijilat.frappe.db, "commit")
	@patch.object(sijilat.frappe.db, "set_value")
	@patch.object(sijilat.frappe, "get_doc")
	def test_expired_name_match_is_saved_for_monthly_rechecks(
		self, get_doc, set_value, commit, validate_unique, fetch, name_match
	):
		customer = DummyCustomer(cr_no=" 90666 - 1 ")
		customer.reload = MagicMock()
		get_doc.return_value = customer
		verification = self._verification(status="Expired")
		verification["expiry_date"] = datetime.date(2026, 5, 4)
		fetch.return_value = verification
		name_match.return_value = {"score": 98.41, "level": "approved"}

		result = sijilat.auto_verify_existing_customer_cr("CM0001")

		self.assertEqual(result, "Expired")
		self.assertEqual(customer.customer_name, "WORLD SHADING W.L.L")
		self.assertEqual(customer.cr_no, "90666-1")
		self.assertEqual(
			customer.verified_business_details,
			"Commercial Name (EN): WORLD SHADING W.L.L"
		)
		self.assertEqual(customer.cr_expiry_date, datetime.date(2026, 5, 4))
		self.assertEqual(customer.business_verification_status, "Expired")
		self.assertEqual(customer.sijilat_recheck_attempts, 0)
		customer.reload.assert_called_once_with()
		customer.save.assert_called_once_with()

	@patch.object(sijilat, "_fetch_customer_cr_verification")
	@patch.object(sijilat, "_validate_unique_customer_cr")
	@patch.object(sijilat.frappe, "log_error")
	@patch.object(sijilat.frappe.db, "commit")
	@patch.object(sijilat.frappe.db, "set_value")
	@patch.object(sijilat.frappe, "get_doc")
	def test_first_temporary_failure_remains_eligible_for_later_retry(
		self, get_doc, set_value, commit, log_error, validate_unique, fetch
	):
		get_doc.return_value = DummyCustomer(sijilat_recheck_attempts=0)
		fetch.side_effect = sijilat.SijilatTemporaryError("temporary")

		result = sijilat.auto_verify_existing_customer_cr("CM0001")

		self.assertEqual(result, "Retry Pending")
		claim_values = set_value.call_args_list[0][0][2]
		self.assertEqual(claim_values["sijilat_recheck_attempts"], 1)
		self.assertNotIn("business_verification_status", claim_values)

	@patch.object(sijilat, "_fetch_customer_cr_verification")
	@patch.object(sijilat, "_validate_unique_customer_cr")
	@patch.object(sijilat.frappe, "log_error")
	@patch.object(sijilat.frappe.db, "commit")
	@patch.object(sijilat.frappe.db, "set_value")
	@patch.object(sijilat.frappe, "get_doc")
	def test_third_temporary_failure_becomes_not_verified(
		self, get_doc, set_value, commit, log_error, validate_unique, fetch
	):
		get_doc.return_value = DummyCustomer(sijilat_recheck_attempts=2)
		fetch.side_effect = sijilat.SijilatTemporaryError("temporary")

		result = sijilat.auto_verify_existing_customer_cr("CM0001")

		self.assertEqual(result, "Not Verified")
		final_values = set_value.call_args_list[-1][0][2]
		self.assertEqual(final_values["business_verification_status"], "Not Verified")
		self.assertEqual(final_values["sijilat_recheck_attempts"], 3)

	@patch.object(sijilat, "_fetch_customer_cr_verification")
	@patch.object(sijilat.frappe.db, "set_value")
	@patch.object(sijilat.frappe, "get_doc")
	def test_worker_rechecks_eligibility_before_api_call(self, get_doc, set_value, fetch):
		get_doc.return_value = DummyCustomer(business_verification_status="Verified")

		self.assertIsNone(sijilat.auto_verify_existing_customer_cr("CM0001"))
		fetch.assert_not_called()
		set_value.assert_not_called()


class TestExistingCustomerSchedulerHook(unittest.TestCase):
	def test_dispatcher_is_registered_in_five_minute_cron_group(self):
		self.assertIn(
			"worldshading.api.sijilat.enqueue_existing_customer_cr_verification",
			hooks.scheduler_events["cron"]["*/5 * * * *"]
		)


if __name__ == "__main__":
	unittest.main()
