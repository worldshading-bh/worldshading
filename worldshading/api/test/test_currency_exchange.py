# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import unittest

try:
	from unittest.mock import MagicMock, patch
except ImportError:
	from mock import MagicMock, patch

from worldshading.api import currency_exchange


class TestCurrencyExchange(unittest.TestCase):
	def test_pairs_accept_newlines_commas_and_colons(self):
		self.assertEqual(currency_exchange.parse_currency_pairs(
			"usd/bhd\nEUR:USD, gbp / bhd"), [
				("USD", "BHD"), ("EUR", "USD"), ("GBP", "BHD")])

	def test_duplicate_pairs_are_removed(self):
		self.assertEqual(currency_exchange.parse_currency_pairs(
			"USD/BHD\nusd:bhd"), [("USD", "BHD")])

	def test_same_currency_pair_is_ignored(self):
		self.assertEqual(currency_exchange.parse_currency_pairs("BHD/BHD"), [])

	def test_table_rows_use_only_enabled_pairs(self):
		self.assertEqual(currency_exchange.parse_currency_pairs([
			{"enabled": 1, "from_currency": "USD", "to_currency": "BHD"},
			{"enabled": 0, "from_currency": "SAR", "to_currency": "BHD"}
		]), [("USD", "BHD")])

	def test_invalid_pair_is_rejected(self):
		with self.assertRaises(ValueError):
			currency_exchange.parse_currency_pairs("US Dollars/BHD")

	def test_valid_provider_payload(self):
		result = currency_exchange._validate_payload({
			"date": "2026-08-21", "base": "USD", "quote": "BHD", "rate": 0.376
		}, "USD", "BHD")
		self.assertEqual(result["date"].isoformat(), "2026-08-21")
		self.assertEqual(result["rate"], 0.376)

	def test_zero_rate_is_rejected(self):
		with self.assertRaises(ValueError):
			currency_exchange._validate_payload({
				"date": "2026-08-21", "base": "USD", "quote": "BHD", "rate": 0
			}, "USD", "BHD")

	def test_missing_provider_date_is_rejected(self):
		with self.assertRaises(ValueError):
			currency_exchange._validate_payload({
				"base": "USD", "quote": "BHD", "rate": 0.376
			}, "USD", "BHD")

	def test_wrong_pair_is_rejected(self):
		with self.assertRaises(ValueError):
			currency_exchange._validate_payload({
				"date": "2026-08-21", "base": "EUR", "quote": "BHD", "rate": 0.44
			}, "USD", "BHD")

	@patch("worldshading.api.currency_exchange._existing_rate", return_value=None)
	@patch("worldshading.api.currency_exchange.frappe.new_doc")
	def test_stored_rate_is_valid_for_buying_and_selling(self, new_doc, existing_rate):
		doc = MagicMock()
		doc.name = "2026-08-22-USD-BHD-Selling-Buying"
		new_doc.return_value = doc

		result = currency_exchange.store_rate(
			currency_exchange.getdate("2026-08-22"), "USD", "BHD", 0.376)

		self.assertEqual(doc.for_buying, 1)
		self.assertEqual(doc.for_selling, 1)
		doc.insert.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(result["status"], "created")

	@patch("worldshading.api.currency_exchange.store_rate")
	@patch("worldshading.api.currency_exchange.fetch_rate")
	def test_fetch_pair_stores_direct_and_reverse_rates(self, fetch_rate, store_rate):
		fetch_rate.return_value = {
			"date": currency_exchange._utc_today(),
			"rate": 0.376
		}
		store_rate.side_effect = [
			{"status": "created", "name": "direct"},
			{"status": "created", "name": "reverse"}
		]

		fetched, rows = currency_exchange._fetch_pair("USD", "BHD", 4)

		self.assertEqual(fetched["rate"], 0.376)
		self.assertEqual(len(rows), 2)
		self.assertEqual(store_rate.call_args_list[0][0][1:], ("USD", "BHD", 0.376))
		self.assertAlmostEqual(store_rate.call_args_list[1][0][3], 1.0 / 0.376)
