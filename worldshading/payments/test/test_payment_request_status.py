# -*- coding: utf-8 -*-
"""Pure tests for Quotation Payment Request amount/status calculations.

These tests do not connect to a site, create records or modify the database.
"""
from __future__ import unicode_literals

import unittest

from worldshading.events.payment_request_status import (
	allocation_exceeds_request,
	is_fully_settled,
	is_paid_invoice,
	status_for_allocation,
)


class TestQuotationPaymentRequestStatus(unittest.TestCase):
	def test_unpaid_inward_request_is_requested(self):
		self.assertEqual(status_for_allocation("Inward", 100, 0, 3), "Requested")

	def test_partial_advance_is_partially_paid(self):
		self.assertEqual(status_for_allocation("Inward", 100, 40, 3), "Partially Paid")

	def test_fully_covered_advance_is_paid(self):
		self.assertEqual(status_for_allocation("Inward", 100, 100, 3), "Paid")

	def test_bhd_precision_is_respected(self):
		self.assertFalse(allocation_exceeds_request(10, 4.999, 5.001, 3))
		self.assertTrue(allocation_exceeds_request(10, 5.001, 5.001, 3))

	def test_zero_outstanding_is_fully_settled(self):
		self.assertTrue(is_fully_settled(0, 3))
		self.assertTrue(is_fully_settled(0.0004, 3))

	def test_nonzero_outstanding_is_not_fully_settled(self):
		self.assertFalse(is_fully_settled(0.001, 3))

	def test_submitted_paid_invoice_is_eligible_for_manual_sync(self):
		self.assertTrue(is_paid_invoice(1, "Paid", 0, 3))

	def test_credit_note_invoice_is_not_treated_as_manually_paid(self):
		self.assertFalse(is_paid_invoice(1, "Credit Note Issued", 0, 3))

	def test_cancelled_invoice_is_not_treated_as_manually_paid(self):
		self.assertFalse(is_paid_invoice(2, "Cancelled", 0, 3))


if __name__ == "__main__":
	unittest.main()
