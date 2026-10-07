# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import unittest

try:
	from unittest.mock import MagicMock, patch
except ImportError:
	from mock import MagicMock, patch

import frappe

from worldshading.api import business_pricing


class TestSecretPricingTransactionLockdown(unittest.TestCase):
	def setUp(self):
		frappe.local.db = MagicMock()
		frappe.local.flags = frappe._dict({
			"mute_messages": True,
			"rollback_on_exception": False
		})

	def tearDown(self):
		frappe.local.db = None
		frappe.local.flags = None

	def _quotation(self, price_list="B2B Price - Test"):
		return frappe._dict({
			"doctype": "Quotation",
			"selling_price_list": price_list,
			"quotation_to": "Customer",
			"party_name": "CM0001"
		})

	@patch.object(business_pricing, "_is_protected_price_list", return_value=False)
	def test_regular_price_list_is_not_restricted(self, is_protected):
		business_pricing.validate_verified_business_price_list(
			self._quotation(price_list="Standard Selling")
		)

	@patch.object(
		business_pricing,
		"_is_valid_linked_sales_invoice_return",
		return_value=True
	)
	@patch.object(business_pricing, "_is_protected_price_list", return_value=True)
	@patch.object(business_pricing.frappe, "get_roles", return_value=["Sales User"])
	def test_linked_sales_invoice_return_remains_allowed(
		self, get_roles, is_protected, is_return
	):
		doc = frappe._dict({
			"doctype": "Sales Invoice",
			"selling_price_list": "B2B Price - Test",
			"customer": "CM0001",
			"is_return": 1,
			"return_against": "ACC-SINV-0001"
		})

		business_pricing.validate_verified_business_price_list(doc)
		get_roles.assert_not_called()

	@patch.object(business_pricing, "_is_protected_price_list", return_value=True)
	@patch.object(business_pricing, "_validate_secret_price_permission")
	@patch.object(business_pricing.frappe, "get_doc")
	def test_remove_secret_price_list_clears_only_protected_assignment(
		self, get_doc, validate_permission, is_protected
	):
		customer_doc = MagicMock()
		customer_doc.name = "CM0001"
		customer_doc.default_price_list = "B2B Price - Test"
		customer_doc.flags = frappe._dict()
		get_doc.return_value = customer_doc

		result = business_pricing.remove_secret_price_list("CM0001")

		validate_permission.assert_called_once_with(customer_doc)
		customer_doc.check_permission.assert_called_once_with("write")
		is_protected.assert_called_once_with("B2B Price - Test")
		self.assertIsNone(customer_doc.default_price_list)
		self.assertTrue(customer_doc.flags.secret_price_list_assignment)
		customer_doc.save.assert_called_once_with()
		self.assertEqual(result["removed_price_list"], "B2B Price - Test")

	@patch.object(business_pricing, "_is_protected_price_list", return_value=False)
	@patch.object(business_pricing, "_validate_secret_price_permission")
	@patch.object(business_pricing.frappe, "get_doc")
	def test_remove_secret_price_list_rejects_ordinary_default(
		self, get_doc, validate_permission, is_protected
	):
		customer_doc = MagicMock()
		customer_doc.default_price_list = "Standard Selling"
		get_doc.return_value = customer_doc

		with self.assertRaises(frappe.ValidationError) as context:
			business_pricing.remove_secret_price_list("CM0001")

		self.assertIn("does not have a protected", str(context.exception))
		validate_permission.assert_called_once_with(customer_doc)
		customer_doc.save.assert_not_called()


class TestQuotationPricingTotals(unittest.TestCase):
	def _quotation(self, price_list, items):
		doc = frappe._dict({
			"doctype": "Quotation",
			"selling_price_list": price_list,
			"items": items
		})
		doc.precision = lambda fieldname: 3
		return doc

	def test_regular_price_list_totals_include_item_discount(self):
		doc = self._quotation("Standard Selling", [
			frappe._dict({
				"qty": 5,
				"price_list_rate": 59.091,
				"discount_amount": 1.182,
				"regular_price_list_rate": 0,
				"applied_price_list": None
			}),
			frappe._dict({
				"qty": 2,
				"price_list_rate": 10,
				"discount_amount": 0,
				"regular_price_list_rate": 0,
				"applied_price_list": None
			})
		])

		business_pricing.set_quotation_pricing_totals(doc, False)

		self.assertEqual(doc.regular_price_list_subtotal, 315.455)
		self.assertEqual(doc.special_price_savings, 0)
		self.assertEqual(doc.price_list_subtotal, 315.455)
		self.assertEqual(doc.total_item_discount, 5.91)
		self.assertEqual(doc.get("items")[0].total_discount_amount, 5.91)

	def test_protected_price_totals_separate_savings_and_item_discount(self):
		doc = self._quotation("B2B Price - Test", [
			frappe._dict({
				"qty": 2,
				"price_list_rate": 100,
				"discount_amount": 5,
				"regular_price_list_rate": 120,
				"applied_price_list": "B2B Price - Test"
			})
		])

		business_pricing.set_quotation_pricing_totals(doc, True)

		self.assertEqual(doc.regular_price_list_subtotal, 240)
		self.assertEqual(doc.special_price_savings, 40)
		self.assertEqual(doc.price_list_subtotal, 200)
		self.assertEqual(doc.total_item_discount, 50)
		self.assertEqual(doc.get("items")[0].total_discount_amount, 50)

	def test_regular_fallback_has_no_special_savings(self):
		doc = self._quotation("B2B Price - Test", [
			frappe._dict({
				"qty": 3,
				"price_list_rate": 25,
				"discount_amount": 0,
				"regular_price_list_rate": 25,
				"applied_price_list": "Standard Selling"
			})
		])

		business_pricing.set_quotation_pricing_totals(doc, True)

		self.assertEqual(doc.regular_price_list_subtotal, 75)
		self.assertEqual(doc.special_price_savings, 0)
		self.assertEqual(doc.price_list_subtotal, 75)
		self.assertEqual(doc.total_item_discount, 0)

	def test_missing_regular_comparison_uses_protected_rate_as_baseline(self):
		doc = self._quotation("B2B Price - Test", [
			frappe._dict({
				"qty": 4,
				"price_list_rate": 12,
				"discount_amount": 2,
				"regular_price_list_rate": 0,
				"applied_price_list": "B2B Price - Test"
			})
		])

		business_pricing.set_quotation_pricing_totals(doc, True)

		self.assertEqual(doc.regular_price_list_subtotal, 48)
		self.assertEqual(doc.special_price_savings, 0)
		self.assertEqual(doc.price_list_subtotal, 48)
		self.assertEqual(doc.total_item_discount, 8)

	def test_unsupported_transaction_is_not_modified(self):
		doc = frappe._dict({
			"doctype": "Purchase Order",
			"items": []
		})

		business_pricing.set_quotation_pricing_totals(doc, False)

		self.assertIsNone(doc.get("price_list_subtotal"))

	def test_sales_order_sets_only_relevant_parent_totals(self):
		stock_item = frappe._dict({
			"qty": 10,
			"price_list_rate": 55,
			"regular_price_list_rate": 59.091,
			"rate": 53.9,
			"amount": 539,
			"applied_price_list": "B2B Price"
		})
		stock_item.precision = lambda fieldname: 3
		service_item = frappe._dict({
			"qty": 5,
			"price_list_rate": 0.25,
			"regular_price_list_rate": 0,
			"rate": 7.25,
			"amount": 36.25,
			"applied_price_list": None
		})
		service_item.precision = lambda fieldname: 3
		doc = frappe._dict({
			"doctype": "Sales Order",
			"selling_price_list": "B2B Price",
			"items": [stock_item, service_item]
		})
		doc.precision = lambda fieldname: 3

		business_pricing.set_quotation_total_discount_percentages(
			doc,
			set([id(service_item)])
		)
		business_pricing.set_quotation_pricing_totals(
			doc,
			True,
			set([id(service_item)])
		)

		self.assertEqual(stock_item.total_discount_percentage, 8.785)
		self.assertEqual(stock_item.total_discount_amount, 51.91)
		self.assertEqual(service_item.total_discount_percentage, 0)
		self.assertEqual(service_item.total_discount_amount, 0)
		self.assertEqual(doc.regular_price_list_subtotal, 627.16)
		self.assertEqual(doc.total_item_discount, 51.91)
		self.assertIsNone(doc.get("special_price_savings"))
		self.assertIsNone(doc.get("price_list_subtotal"))

	@patch.object(business_pricing, "_is_protected_price_list", return_value=False)
	def test_regular_transaction_snapshots_selected_price_list_rate(self, is_protected):
		doc = self._quotation("Standard Selling", [
			frappe._dict({
				"qty": 10,
				"price_list_rate": 8,
				"discount_amount": 0.16,
				"regular_price_list_rate": 0,
				"applied_price_list": "Old Protected List"
			})
		])
		doc.get("items")[0].precision = lambda fieldname: 3

		with patch.object(business_pricing.frappe, "db") as database:
			database.get_value.return_value = 1
			business_pricing.set_regular_price_list_rates(doc)

		self.assertEqual(doc.get("items")[0].regular_price_list_rate, 8)
		self.assertIsNone(doc.get("items")[0].applied_price_list)
		self.assertEqual(doc.regular_price_list_subtotal, 80)
		self.assertEqual(doc.price_list_subtotal, 80)
		self.assertEqual(doc.total_item_discount, 1.6)

	def test_total_discount_percentage_uses_regular_comparison_rate(self):
		item = frappe._dict({
			"regular_price_list_rate": 59.091,
			"price_list_rate": 55,
			"rate": 53.9
		})
		item.precision = lambda fieldname: 3
		doc = self._quotation("B2B Price", [item])

		business_pricing.set_quotation_total_discount_percentages(doc)

		self.assertEqual(item.total_discount_percentage, 8.785)

	def test_regular_total_discount_matches_standard_item_discount(self):
		item = frappe._dict({
			"regular_price_list_rate": 8,
			"price_list_rate": 8,
			"rate": 7.84
		})
		item.precision = lambda fieldname: 3
		doc = self._quotation("Standard Selling", [item])

		business_pricing.set_quotation_total_discount_percentages(doc)

		self.assertEqual(item.total_discount_percentage, 2)

	def test_total_discount_uses_price_list_rate_when_regular_rate_is_missing(self):
		item = frappe._dict({
			"regular_price_list_rate": 0,
			"price_list_rate": 20,
			"rate": 18
		})
		item.precision = lambda fieldname: 3
		doc = self._quotation("B2B Price", [item])

		business_pricing.set_quotation_total_discount_percentages(doc)

		self.assertEqual(item.total_discount_percentage, 10)

	def test_total_discount_does_not_show_negative_savings(self):
		item = frappe._dict({
			"regular_price_list_rate": 10,
			"price_list_rate": 10,
			"rate": 12
		})
		item.precision = lambda fieldname: 3
		doc = self._quotation("Standard Selling", [item])

		business_pricing.set_quotation_total_discount_percentages(doc)

		self.assertEqual(item.total_discount_percentage, 0)
		self.assertEqual(item.total_discount_amount, 0)

	@patch.object(business_pricing, "_is_protected_price_list", return_value=False)
	def test_regular_service_item_keeps_list_rate_out_of_comparison(self, is_protected):
		item = frappe._dict({
			"item_code": "SERVICE-ITEM",
			"qty": 2,
			"price_list_rate": 500,
			"regular_price_list_rate": 0,
			"discount_percentage": 25,
			"discount_amount": 0.25,
			"rate": 125,
			"amount": 250,
			"applied_price_list": "Old Protected List"
		})
		item.precision = lambda fieldname: 3
		doc = self._quotation("Standard Selling", [item])

		with patch.object(business_pricing.frappe, "db") as database:
			database.get_value.return_value = 0
			business_pricing.set_regular_price_list_rates(doc)

		self.assertEqual(item.price_list_rate, 500)
		self.assertEqual(item.regular_price_list_rate, 0)
		self.assertEqual(item.discount_percentage, 0)
		self.assertEqual(item.discount_amount, 0)
		self.assertEqual(item.total_discount_percentage, 0)
		self.assertEqual(item.total_discount_amount, 0)
		self.assertIsNone(item.applied_price_list)
		self.assertEqual(doc.regular_price_list_subtotal, 250)
		self.assertEqual(doc.special_price_savings, 0)
		self.assertEqual(doc.price_list_subtotal, 250)
		self.assertEqual(doc.total_item_discount, 0)

	def test_stock_item_is_not_normalized_as_service_pricing(self):
		item = frappe._dict({
			"item_code": "STOCK-ITEM",
			"price_list_rate": 55,
			"regular_price_list_rate": 59.091,
			"discount_percentage": 2,
			"discount_amount": 1.1,
			"rate": 53.9,
			"applied_price_list": "B2B Price"
		})
		doc = self._quotation("B2B Price", [item])

		with patch.object(business_pricing.frappe, "get_all", return_value=[]):
			service_item_ids = business_pricing.normalize_quotation_service_item_pricing(doc)

		self.assertEqual(service_item_ids, set())
		self.assertEqual(item.price_list_rate, 55)
		self.assertEqual(item.regular_price_list_rate, 59.091)
		self.assertEqual(item.discount_percentage, 2)
		self.assertEqual(item.discount_amount, 1.1)
		self.assertEqual(item.rate, 53.9)
		self.assertEqual(item.applied_price_list, "B2B Price")

	def test_non_stock_item_without_custom_project_logic_uses_normal_pricing(self):
		item = frappe._dict({
			"item_code": "HA0001",
			"price_list_rate": 0,
			"regular_price_list_rate": 0,
			"discount_percentage": 0,
			"discount_amount": 0,
			"rate": 0,
			"applied_price_list": None
		})
		doc = self._quotation("B2B Price", [item])

		with patch.object(
			business_pricing.frappe, "get_all", return_value=[]
		), patch.object(business_pricing.frappe, "db") as database:
			database.get_value.return_value = 0
			service_item_ids = business_pricing.normalize_quotation_service_item_pricing(doc)

		self.assertEqual(service_item_ids, set())

	def test_custom_project_bundle_is_normalized_as_dynamic_pricing(self):
		item = frappe._dict({
			"item_code": "W0000",
			"price_list_rate": 1,
			"regular_price_list_rate": 59.091,
			"discount_percentage": 10,
			"discount_amount": 0.1,
			"rate": 125,
			"applied_price_list": "B2B Price"
		})
		doc = self._quotation("B2B Price", [item])

		with patch.object(
			business_pricing.frappe,
			"get_all",
			return_value=[frappe._dict({"new_item_code": "W0000"})]
		):
			service_item_ids = business_pricing.normalize_quotation_service_item_pricing(doc)

		self.assertEqual(service_item_ids, set([id(item)]))
		self.assertEqual(item.regular_price_list_rate, 0)
		self.assertEqual(item.discount_percentage, 0)
		self.assertEqual(item.discount_amount, 0)
		self.assertIsNone(item.applied_price_list)

	@patch.object(business_pricing, "_get_applicable_item_price")
	@patch.object(
		business_pricing,
		"_is_valid_linked_sales_invoice_return",
		return_value=False
	)
	@patch.object(
		business_pricing,
		"_is_protected_price_list",
		side_effect=lambda price_list: price_list == "B2B Price"
	)
	@patch.object(business_pricing, "get_company_currency", return_value="BHD")
	def test_protected_service_item_skips_price_lookup_and_fallback(
		self, company_currency, is_protected, is_return, get_item_price
	):
		item = frappe._dict({
			"item_code": "SERVICE-ITEM",
			"qty": 2,
			"price_list_rate": 1,
			"regular_price_list_rate": 0,
			"discount_percentage": 10,
			"discount_amount": 0.1,
			"rate": 125,
			"amount": 250,
			"applied_price_list": None
		})
		item.precision = lambda fieldname: 3
		doc = self._quotation("B2B Price", [item])
		doc.company = "World Shading"
		doc.transaction_date = "2026-09-19"
		doc.conversion_rate = 1
		doc.calculate_taxes_and_totals = MagicMock()

		with patch.object(
			business_pricing.frappe,
			"get_all",
			return_value=[frappe._dict({"new_item_code": "SERVICE-ITEM"})]
		), patch.object(business_pricing.frappe, "db") as database:
			database.get_single_value.return_value = "Standard Selling"
			database.get_value.side_effect = lambda doctype, name, fields, **kwargs: (
				0 if doctype == "Item" else frappe._dict({
					"price_not_uom_dependent": 0,
					"enabled": 1,
					"selling": 1,
					"currency": "BHD"
				})
			)
			business_pricing.set_regular_price_list_rates(doc)

		get_item_price.assert_not_called()
		doc.calculate_taxes_and_totals.assert_not_called()
		self.assertEqual(item.price_list_rate, 1)
		self.assertEqual(item.regular_price_list_rate, 0)
		self.assertEqual(item.rate, 125)
		self.assertEqual(item.amount, 250)
		self.assertEqual(item.discount_percentage, 0)
		self.assertEqual(item.discount_amount, 0)
		self.assertEqual(item.total_discount_percentage, 0)
		self.assertIsNone(item.applied_price_list)


if __name__ == "__main__":
	unittest.main()
