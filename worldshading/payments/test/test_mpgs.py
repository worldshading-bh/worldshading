# -*- coding: utf-8 -*-
"""Pure unit tests for the KFH MPGS request identifiers."""
from __future__ import unicode_literals

import unittest

from worldshading.payments.mpgs import merchant_references, transaction_audit_values


class TestMerchantReferences(unittest.TestCase):
	def test_references_are_derived_from_the_unique_attempt_id(self):
		references = merchant_references("260812000001")

		self.assertEqual(references["order"], "ORD-260812000001")
		self.assertEqual(references["transaction"], "TXN-260812000001")

	def test_different_attempts_get_different_references(self):
		first = merchant_references("260812000001")
		second = merchant_references("260812000002")

		self.assertNotEqual(first["order"], second["order"])
		self.assertNotEqual(first["transaction"], second["transaction"])


class TestTransactionAuditValues(unittest.TestCase):
	def test_extracts_payment_identifiers(self):
		values = transaction_audit_values({
			"transaction": {
				"id": "1",
				"receipt": "622413077470",
				"authorizationCode": "077470",
			}
		})

		self.assertEqual(values["transaction_id"], "1")
		self.assertEqual(values["reference_number"], "622413077470")
		self.assertEqual(values["auth_code"], "077470")

	def test_missing_identifiers_are_empty(self):
		self.assertEqual(transaction_audit_values({}), {
			"transaction_id": "",
			"reference_number": "",
			"auth_code": "",
		})
