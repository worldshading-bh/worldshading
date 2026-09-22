# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import unittest
from unittest.mock import patch

from worldshading.events.payment_entry_balance_snapshot import (
	_is_customer_receipt,
	_sales_invoice_allocations,
)


class AttributeDict(dict):
	def __getattr__(self, key):
		return self.get(key)


class PaymentEntryStub(AttributeDict):
	def set(self, fieldname, value):
		self[fieldname] = value

	def append(self, fieldname, value):
		self[fieldname].append(AttributeDict(value))


class TestPaymentEntryBalanceSnapshot(unittest.TestCase):
	def test_only_customer_receipts_are_eligible(self):
		doc = AttributeDict({
			"payment_type": "Receive",
			"party_type": "Customer",
			"party": "CUST-0001",
			"company": "World Shading",
		})
		self.assertTrue(_is_customer_receipt(doc))
		doc.payment_type = "Pay"
		self.assertFalse(_is_customer_receipt(doc))

	def test_sales_invoice_allocations_are_grouped(self):
		doc = AttributeDict({"references": [
			AttributeDict({
				"reference_doctype": "Sales Invoice",
				"reference_name": "SINV-0001",
				"allocated_amount": 10,
			}),
			AttributeDict({
				"reference_doctype": "Sales Invoice",
				"reference_name": "SINV-0001",
				"allocated_amount": 5,
			}),
			AttributeDict({
				"reference_doctype": "Sales Order",
				"reference_name": "SO-0001",
				"allocated_amount": 99,
			}),
		]})
		self.assertEqual(_sales_invoice_allocations(doc, 3), {"SINV-0001": 15.0})

	@patch("worldshading.events.payment_entry_balance_snapshot.frappe.get_all")
	@patch("worldshading.events.payment_entry_balance_snapshot.frappe.get_precision")
	def test_snapshot_omits_fully_paid_invoice(self, get_precision, get_all):
		from worldshading.events.payment_entry_balance_snapshot import (
			set_invoice_balance_snapshot,
		)

		get_precision.return_value = 3
		get_all.return_value = [
			AttributeDict({
				"name": "SINV-0001", "posting_date": "2026-09-01",
				"currency": "BHD", "grand_total": 53,
				"rounded_total": 0, "outstanding_amount": 53,
			}),
			AttributeDict({
				"name": "SINV-0002", "posting_date": "2026-09-02",
				"currency": "BHD", "grand_total": 20,
				"rounded_total": 0, "outstanding_amount": 20,
			}),
		]
		doc = PaymentEntryStub({
			"payment_type": "Receive", "party_type": "Customer",
			"party": "CUST-0001", "company": "World Shading",
			"references": [AttributeDict({
				"reference_doctype": "Sales Invoice",
				"reference_name": "SINV-0001", "allocated_amount": 18,
			}), AttributeDict({
				"reference_doctype": "Sales Invoice",
				"reference_name": "SINV-0002", "allocated_amount": 20,
			})],
		})

		set_invoice_balance_snapshot(doc)

		self.assertEqual(len(doc.invoice_balance_snapshot), 1)
		self.assertEqual(doc.invoice_balance_snapshot[0].invoice_number, "SINV-0001")
		self.assertEqual(doc.invoice_balance_snapshot[0].this_payment, 18.0)
		self.assertEqual(doc.invoice_balance_snapshot[0].remaining_amount, 35.0)


if __name__ == "__main__":
	unittest.main()
