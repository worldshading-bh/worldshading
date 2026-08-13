# -*- coding: utf-8 -*-
"""Pure unit tests for the BENEFIT gateway.

No database, no network, no records created -- safe to run against any site. Every
case here is a place the integration can silently produce a wrong result rather than
an error, which is why they are worth testing at all:

  * the AES envelope, where a missing URL-encode step yields a valid-looking hex
    string that the gateway rejects as IPAY0100013
  * amount precision, where BHD's three decimals turn 12.5 into the wrong number
  * splitting "<paymentId>:<url>", where the url has a colon of its own

Run:

    bench --site erp.worldshading.com run-tests --module worldshading.payments.test.test_benefit
"""
from __future__ import unicode_literals

import unittest

from six.moves.urllib.parse import unquote_plus

import frappe

from worldshading.payments import benefit, crypto
from worldshading.payments.utils import currency_decimals, format_amount

# 32 characters -> AES-256, the same SHAPE as a Terminal Resource Key but not a real
# one. These tests only check round-trips, so any valid-length key works.
#
# Never put an actual resource key here. Source files get committed, and a key in git
# history stays there. The vendor onboarding emails are gitignored for the same reason.
KEY = "TESTKEYTESTKEYTESTKEYTESTKEY1234"


class TestBenefitCrypto(unittest.TestCase):
	def test_round_trip(self):
		plaintext = '[{"amt":"12.000","action":"1","trackId":"260809000001"}]'
		self.assertEqual(crypto.decrypt(KEY, crypto.encrypt(KEY, plaintext)), plaintext)

	def test_ciphertext_is_uppercase_hex(self):
		out = crypto.encrypt(KEY, "hello")
		self.assertEqual(out, out.upper())
		self.assertTrue(all(c in "0123456789ABCDEF" for c in out))
		# AES is a block cipher: output is always a whole number of 16-byte blocks.
		self.assertEqual(len(out) % 32, 0)

	def test_plaintext_is_url_encoded_before_encryption(self):
		"""The step the guide states twice and that is easy to drop.

		Decrypting without the matching URL-decode must still show the encoded form,
		proving the encode actually happened on the way in.
		"""
		plaintext = '[{"a":"b c"}]'
		raw = crypto.decrypt(KEY, crypto.encrypt(KEY, plaintext))
		self.assertEqual(raw, plaintext)

		# Round-trip through decrypt gives the original back, so re-encode to inspect.
		encrypted = crypto.encrypt(KEY, plaintext)
		import binascii

		from cryptography.hazmat.backends import default_backend
		from cryptography.hazmat.primitives import padding
		from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

		cipher = Cipher(
			algorithms.AES(KEY.encode("utf-8")),
			modes.CBC(crypto.BENEFIT_IV),
			backend=default_backend(),
		)
		decryptor = cipher.decryptor()
		padded = decryptor.update(binascii.unhexlify(encrypted)) + decryptor.finalize()
		unpadder = padding.PKCS7(128).unpadder()
		on_the_wire = (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")

		self.assertNotEqual(on_the_wire, plaintext)
		self.assertNotIn(" ", on_the_wire)
		self.assertEqual(unquote_plus(on_the_wire), plaintext)

	def test_rejects_wrong_key_length(self):
		for bad in ("", "short", "a" * 31):
			self.assertRaises(ValueError, crypto.encrypt, bad, "x")

	def test_accepts_all_valid_aes_key_lengths(self):
		for length in (16, 24, 32):
			key = "k" * length
			self.assertEqual(crypto.decrypt(key, crypto.encrypt(key, "abc")), "abc")


class TestAmountFormatting(unittest.TestCase):
	def test_bhd_carries_three_decimals(self):
		self.assertEqual(currency_decimals("BHD"), 3)
		self.assertEqual(format_amount(12.5, "BHD"), "12.500")
		self.assertEqual(format_amount(1, "BHD"), "1.000")
		self.assertEqual(format_amount(60, "BHD"), "60.000")

	def test_other_currencies_default_to_two(self):
		self.assertEqual(format_amount(12.5, "USD"), "12.50")
		self.assertEqual(format_amount(12.5, "EUR"), "12.50")

	def test_zero_decimal_currency(self):
		self.assertEqual(format_amount(1500, "JPY"), "1500")

	def test_rounds_rather_than_truncates(self):
		self.assertEqual(format_amount(12.5678, "BHD"), "12.568")

	def test_rejects_non_positive(self):
		self.assertRaises(frappe.ValidationError, format_amount, 0, "BHD")
		self.assertRaises(frappe.ValidationError, format_amount, -1, "BHD")


class TestInitResponseParsing(unittest.TestCase):
	def test_accepts_the_form_the_gateway_actually_returns(self):
		"""Verbatim from the test terminal on 2026-08-09.

		The guide documents "<paymentId>:<url>"; the live gateway returns the whole
		URL with PaymentID already embedded. Parsing it the documented way took
		"https" as the payment id and produced a duplicate query parameter.
		"""
		body = (
			'[{"result":"https://test.benefit-gateway.bh/payment/paymentpage.htm'
			'?PaymentID=119202622138483730","status":"1"}]'
		)
		payment_id, url = benefit.parse_init_response(body)

		self.assertEqual(payment_id, "119202622138483730")
		self.assertEqual(
			url,
			"https://test.benefit-gateway.bh/payment/paymentpage.htm"
			"?PaymentID=119202622138483730",
		)
		# The bug that reached production: PaymentID must appear exactly once.
		self.assertEqual(url.count("PaymentID="), 1)
		self.assertNotIn("PaymentID=https", url)

	def test_url_form_without_a_payment_id_raises(self):
		body = '[{"status":"1","result":"https://test.benefit-gateway.bh/pay"}]'
		self.assertRaises(frappe.ValidationError, benefit.parse_init_response, body)

	def test_splits_payment_id_from_url_containing_a_colon(self):
		"""The url has its own colon after "https" -- split once, not on every colon."""
		body = (
			'[{"status":"1",'
			'"result":"100201931620827468:https://test.BENEFIT-Gateway.bh",'
			'"error":null,"errorText":null}]'
		)
		payment_id, url = benefit.parse_init_response(body)

		self.assertEqual(payment_id, "100201931620827468")
		self.assertEqual(
			url, "https://test.BENEFIT-Gateway.bh?PaymentID=100201931620827468"
		)

	def test_appends_with_ampersand_when_url_already_has_a_query(self):
		body = (
			'[{"status":"1","result":"999:https://pg.example.bh/pay?lang=en"}]'
		)
		_payment_id, url = benefit.parse_init_response(body)
		self.assertEqual(url, "https://pg.example.bh/pay?lang=en&PaymentID=999")

	def test_accepts_a_bare_object_as_well_as_an_array(self):
		body = '{"status":"1","result":"5:https://pg.example.bh"}'
		payment_id, _url = benefit.parse_init_response(body)
		self.assertEqual(payment_id, "5")

	def test_failure_status_raises_with_the_gateway_error(self):
		body = (
			'[{"status":"2","error":"IPAY0100015",'
			'"errorText":"Invalid tranportal password","result":null}]'
		)
		self.assertRaises(frappe.ValidationError, benefit.parse_init_response, body)

	def test_unreadable_body_raises(self):
		self.assertRaises(frappe.ValidationError, benefit.parse_init_response, "<html>502</html>")

	def test_malformed_result_raises(self):
		body = '[{"status":"1","result":"no-colon-here"}]'
		self.assertRaises(frappe.ValidationError, benefit.parse_init_response, body)


class TestResultMapping(unittest.TestCase):
	def test_only_captured_is_success(self):
		self.assertEqual(benefit._STATUS_BY_RESULT["CAPTURED"], "Captured")

		for result in ("NOT CAPTURED", "HOST TIMEOUT"):
			self.assertEqual(benefit._STATUS_BY_RESULT[result], "Failed")

		self.assertEqual(benefit._STATUS_BY_RESULT["DENIED BY RISK"], "Denied By Risk")
		self.assertEqual(benefit._STATUS_BY_RESULT["VOIDED"], "Voided")

	def test_unknown_result_is_not_treated_as_success(self):
		self.assertNotIn("SOMETHING NEW", benefit._STATUS_BY_RESULT)

	def test_currency_code_is_iso_numeric(self):
		self.assertEqual(benefit.currency_code("BHD"), "048")
		self.assertEqual(benefit.currency_code("bhd"), "048")
		self.assertRaises(frappe.ValidationError, benefit.currency_code, "USD")
