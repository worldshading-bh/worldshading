from copy import deepcopy
import unittest
from unittest.mock import patch

import frappe
from worldshading.api.full_return_rounding import get_original_return_rounding


class TestFullReturnRounding(unittest.TestCase):
	def setUp(self):
		self.source = frappe._dict(
			name="SOURCE", docstatus=1, is_return=0, company="WS", customer="CUSTOMER",
			currency="BHD", party_account_currency="BHD", conversion_rate=1,
			grand_total=76.190, base_grand_total=76.190, net_total=69.264,
			base_net_total=69.264, total_taxes_and_charges=6.926,
			base_total_taxes_and_charges=6.926, rounded_total=76.200,
			base_rounded_total=76.200, rounding_adjustment=0.010,
			base_rounding_adjustment=0.010,
		)
		self.source["items"] = [frappe._dict(name="ROW", item_code="ITEM", uom="Each",
			conversion_factor=1, qty=8, stock_qty=8, rate=8.658,
			net_amount=69.264, base_net_amount=69.264)]
		self.source.taxes = [frappe._dict(account_head="VAT", charge_type="On Net Total",
			rate=10, tax_amount_after_discount_amount=6.926,
			base_tax_amount_after_discount_amount=6.926)]
		self.doc = deepcopy(self.source)
		self.doc.update(doctype="Sales Invoice", name="RETURN", docstatus=0,
			is_return=1, is_pos=0, return_against="SOURCE", payments=[])
		for field in ("grand_total", "base_grand_total", "net_total", "base_net_total",
			"total_taxes_and_charges", "base_total_taxes_and_charges"):
			self.doc[field] *= -1
		self.doc["items"][0].sales_invoice_item = "ROW"
		for field in ("qty", "stock_qty", "net_amount", "base_net_amount"):
			self.doc["items"][0][field] *= -1
		for field in ("tax_amount_after_discount_amount", "base_tax_amount_after_discount_amount"):
			self.doc.taxes[0][field] *= -1

	def result(self, other_returns=False):
		with patch.object(frappe, "get_doc", return_value=self.source), \
			patch.object(frappe.db, "exists", return_value=other_returns):
			return get_original_return_rounding(self.doc)

	def test_full_credit_return_reverses_original_rounding(self):
		before = deepcopy(self.doc)
		result = self.result()
		self.assertEqual(result["rounded_total"], -76.200)
		self.assertEqual(result["rounding_adjustment"], -0.010)
		self.assertEqual(result["base_rounded_total"], -76.200)
		self.assertEqual(self.doc, before)

	def test_partial_items_or_changed_tax_are_not_eligible(self):
		self.doc["items"][0].qty = -4
		self.assertIsNone(self.result())
		self.doc["items"][0].qty = -8
		self.doc.taxes[0].account_head = "OTHER VAT"
		self.assertIsNone(self.result())

	def test_other_submitted_return_blocks_reversal(self):
		self.assertIsNone(self.result(other_returns=True))

	def test_pos_payments_and_changed_currency_are_not_eligible(self):
		for field, value in (("is_pos", 1), ("payments", [frappe._dict(amount=0)]),
			("currency", "USD"), ("conversion_rate", 0.376),
			("paid_amount", -1), ("write_off_amount", 0.1), ("docstatus", 2)):
			old = self.doc.get(field)
			self.doc[field] = value
			self.assertIsNone(self.result())
			self.doc[field] = old

	def test_amended_return_ignores_cancelled_predecessor(self):
		self.doc.amended_from = "CANCELLED-RETURN"
		with patch.object(frappe, "get_doc", return_value=self.source), \
			patch.object(frappe.db, "exists", return_value=False) as exists:
			self.assertIsNotNone(get_original_return_rounding(self.doc))
			self.assertEqual(exists.call_args[0][1]["docstatus"], 1)

	def test_missing_item_link_and_duplicate_item_link_are_rejected(self):
		self.doc["items"][0].sales_invoice_item = None
		self.assertIsNone(self.result())
		self.doc["items"][0].sales_invoice_item = "ROW"
		self.doc["items"].append(deepcopy(self.doc["items"][0]))
		self.assertIsNone(self.result())

	def test_selected_rounding_is_applied_before_outstanding_calculation(self):
		from worldshading.api import dynamic_rounding
		from worldshading.api.test.test_dynamic_rounding import FakeSalesDocument
		doc = FakeSalesDocument("Sales Invoice")
		doc.is_return = True
		doc.return_against = "SOURCE"
		doc.grand_total = doc.base_grand_total = -76.190
		expected = self.result()
		observed = []
		with patch.object(frappe, "get_single", return_value={"enable_dynamic_rounding": 1}), \
			patch.object(dynamic_rounding, "get_original_return_rounding", return_value=expected), \
			patch.object(dynamic_rounding, "_recalculate_sales_invoice_outstanding",
				side_effect=lambda d: observed.append(d.rounded_total)):
			self.assertTrue(dynamic_rounding.apply_dynamic_rounding(doc))
		self.assertEqual(observed, [-76.200])
		self.assertEqual(doc.rounding_adjustment, -0.010)
		self.assertFalse(doc.payment_schedule_updated)
