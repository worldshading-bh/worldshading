# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import unittest

try:
	from unittest.mock import patch
except ImportError:
	from mock import patch

import frappe

from worldshading.api import quotation_discount_details


class QuotationStub(frappe._dict):
	def set(self, fieldname, value):
		self[fieldname] = value

	def append(self, fieldname, values):
		row = frappe._dict(values)
		self.setdefault(fieldname, []).append(row)
		return row


class TestQuotationDiscountDetails(unittest.TestCase):
	def _quotation(self, items):
		return QuotationStub({
			"doctype": "Quotation",
			"selling_price_list": "B2B Price",
			"items": items,
			"discount_calculation_details": []
		})

	@patch.object(quotation_discount_details.frappe, "get_all")
	def test_mixed_rule_shows_special_and_combined_quantity_discounts(self, get_all):
		get_all.return_value = [{
			"name": "PVC Mixed Qty",
			"price_or_product_discount": "Price",
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": 6.558,
			"discount_amount": 0,
			"rate": 0,
			"mixed_conditions": 1,
			"is_cumulative": 0,
			"apply_on": "Item Code",
			"applicable_for": "",
			"min_qty": 40,
			"max_qty": 1000,
			"min_amt": 0,
			"max_amt": 0
		}]
		doc = self._quotation([
			frappe._dict({
				"item_code": "KSA0001", "qty": 70, "uom": "Roll",
				"regular_price_list_rate": 59.091,
				"price_list_rate": 55.455, "rate": 51.818,
				"discount_percentage": 6.558,
				"pricing_rules": '["PVC Mixed Qty"]'
			}),
			frappe._dict({
				"item_code": "KSA0005", "qty": 1, "uom": "Roll",
				"regular_price_list_rate": 59.091,
				"price_list_rate": 55.455, "rate": 51.818,
				"discount_percentage": 6.558,
				"pricing_rules": '["PVC Mixed Qty"]'
			})
		])

		quotation_discount_details.set_discount_calculation_details(doc)

		self.assertEqual(len(doc.discount_calculation_details), 2)
		first = doc.discount_calculation_details[0]
		self.assertEqual(first.item_code, "KSA0001")
		self.assertEqual(first.qty, 70)
		self.assertEqual(first.special_price_list_discount, 6.153)
		self.assertEqual(first.pricing_rule_discount, 6.558)
		self.assertEqual(
			first.explanation,
			'Price List "B2B Price" reduced the regular unit price by 6.153%. '
			'Pricing Rule "PVC Mixed Qty" then applied a 6.558% discount to '
			'the reduced price because the combined quantity of KSA0001 and '
			'KSA0005 was 71 Rolls, falling within the 40–1,000 Roll tier. '
			'The combined effective discount is 12.308%.'
		)

	@patch.object(quotation_discount_details.frappe, "get_all")
	def test_item_quantity_rule_uses_item_quantity(self, get_all):
		get_all.return_value = [{
			"name": "2% Qty Discount",
			"price_or_product_discount": "Price",
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": 2,
			"discount_amount": 0,
			"rate": 0,
			"mixed_conditions": 0,
			"is_cumulative": 0,
			"apply_on": "Item Code",
			"applicable_for": "",
			"min_qty": 10,
			"max_qty": 0,
			"min_amt": 0,
			"max_amt": 0
		}]
		doc = self._quotation([frappe._dict({
			"item_code": "K3001", "qty": 20, "uom": "Roll",
			"regular_price_list_rate": 91.818,
			"price_list_rate": 91.818, "rate": 89.982,
			"discount_percentage": 2,
			"pricing_rules": '["2% Qty Discount"]'
		})])

		quotation_discount_details.set_discount_calculation_details(doc)

		row = doc.discount_calculation_details[0]
		self.assertEqual(row.special_price_list_discount, 0)
		self.assertEqual(row.pricing_rule_discount, 2)
		self.assertEqual(
			row.explanation,
			'Pricing Rule "2% Qty Discount" applied a 2% discount because the '
			'ordered quantity was 20 Rolls, meeting the minimum tier of 10 '
			'Rolls or more.'
		)

	@patch.object(quotation_discount_details.frappe, "get_all", return_value=[])
	def test_undiscounted_item_is_not_added(self, get_all):
		doc = self._quotation([frappe._dict({
			"item_code": "FULL-PRICE", "qty": 1, "uom": "Each",
			"regular_price_list_rate": 10,
			"price_list_rate": 10, "rate": 10,
			"discount_percentage": 0, "pricing_rules": None
		})])

		quotation_discount_details.set_discount_calculation_details(doc)

		self.assertEqual(doc.discount_calculation_details, [])

	@patch.object(quotation_discount_details.frappe, "get_all", return_value=[])
	def test_special_price_without_pricing_rule_is_explained(self, get_all):
		doc = self._quotation([frappe._dict({
			"item_code": "SPECIAL", "qty": 5, "uom": "Each",
			"regular_price_list_rate": 100,
			"price_list_rate": 90, "rate": 90,
			"discount_percentage": 0, "pricing_rules": None
		})])

		quotation_discount_details.set_discount_calculation_details(doc)

		row = doc.discount_calculation_details[0]
		self.assertEqual(row.special_price_list_discount, 10)
		self.assertEqual(row.pricing_rule_discount, 0)
		self.assertEqual(
			row.explanation,
			'Price List "B2B Price" reduced the regular unit price by 10%.'
		)


if __name__ == "__main__":
	unittest.main()
