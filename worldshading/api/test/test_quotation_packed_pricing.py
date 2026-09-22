from __future__ import unicode_literals

import unittest

import frappe
try:
    from unittest.mock import MagicMock, patch
except ImportError:
    from mock import MagicMock, patch

from worldshading.api import quotation_packed_pricing


class TestQuotationPackedPricing(unittest.TestCase):
    def _quotation(self, items=None, packed_items=None):
        doc = frappe._dict({
            "doctype": "Quotation",
            "selling_price_list": "B2B Price",
            "auto_parent_price_calculation": 1,
            "items": items or [],
            "packed_items": packed_items or [],
            "total_selling_price": 0
        })
        doc.calculate_taxes_and_totals = MagicMock()
        return doc

    @patch.object(quotation_packed_pricing.frappe, "get_all", return_value=[{"name": "W0000"}])
    @patch.object(quotation_packed_pricing, "_get_item_price")
    def test_bundle_parent_uses_packed_total_and_margin(self, get_item_price, get_all):
        parent = frappe._dict({
            "item_code": "W0000", "qty": 5,
            "price_list_rate": 0.25, "rate": 0.25, "amount": 1.25
        })
        packed = frappe._dict({
            "parent_item": "W0000", "item_code": "WS0001",
            "qty": 5, "uom": "Each", "rate": 0, "amount": 0
        })
        doc = self._quotation([parent], [packed])
        get_item_price.side_effect = lambda item_code, price_list, uom=None: (
            1 if item_code == "WS0001" else 0.25
        )

        quotation_packed_pricing.apply_quotation_packed_pricing(
            doc, show_messages=False
        )

        self.assertEqual(packed.rate, 1)
        self.assertEqual(packed.amount, 5)
        self.assertEqual(doc.total_selling_price, 5)
        self.assertEqual(parent.rate, 1.25)
        self.assertEqual(parent.amount, 6.25)
        self.assertEqual(parent.margin_type, "Amount")
        self.assertEqual(parent.margin_rate_or_amount, 1)
        self.assertEqual(parent.rate_with_margin, 1.25)
        self.assertEqual(parent.discount_percentage, 0)
        self.assertEqual(parent.discount_amount, 0)
        doc.calculate_taxes_and_totals.assert_called_once_with()

    @patch.object(
        quotation_packed_pricing,
        "_get_item_price",
        side_effect=frappe.ValidationError("Missing Item Price")
    )
    def test_missing_packed_item_price_stops_save(self, get_item_price):
        packed = frappe._dict({
            "parent_item": "W0000", "item_code": "WS0001",
            "qty": 1, "uom": "Each"
        })
        doc = self._quotation([], [packed])

        with self.assertRaises(frappe.ValidationError):
            quotation_packed_pricing.apply_quotation_packed_pricing(
                doc, show_messages=False
            )

    @patch.object(quotation_packed_pricing, "_get_item_price", return_value=2)
    def test_parent_calculation_can_be_disabled(self, get_item_price):
        parent = frappe._dict({
            "item_code": "W0000", "qty": 1,
            "price_list_rate": 0.25, "rate": 9, "amount": 9
        })
        packed = frappe._dict({
            "parent_item": "W0000", "item_code": "WS0001",
            "qty": 3, "uom": "Each"
        })
        doc = self._quotation([parent], [packed])
        doc.auto_parent_price_calculation = 0

        quotation_packed_pricing.apply_quotation_packed_pricing(
            doc, show_messages=False
        )

        self.assertEqual(packed.amount, 6)
        self.assertEqual(doc.total_selling_price, 6)
        self.assertEqual(parent.rate, 9)
        self.assertEqual(parent.amount, 9)

    def test_warranty_is_fifteen_percent_of_other_items(self):
        normal = frappe._dict({
            "item_code": "KSA0001", "qty": 2, "rate": 50, "amount": 100
        })
        warranty = frappe._dict({
            "item_code": "QC7026", "qty": 1,
            "price_list_rate": 10, "rate": 10, "amount": 10
        })
        doc = self._quotation([normal, warranty], [])
        doc.auto_parent_price_calculation = 0

        quotation_packed_pricing.apply_quotation_packed_pricing(
            doc, show_messages=False
        )

        self.assertEqual(warranty.qty, 1)
        self.assertEqual(warranty.rate, 15)
        self.assertEqual(warranty.amount, 15)
        self.assertEqual(warranty.margin_type, "Amount")
        self.assertEqual(warranty.margin_rate_or_amount, 5)
        self.assertEqual(warranty.rate_with_margin, 15)
        self.assertEqual(warranty.discount_percentage, 0)
        self.assertEqual(warranty.discount_amount, 0)
        doc.calculate_taxes_and_totals.assert_called_once_with()

    @patch.object(quotation_packed_pricing.frappe, "get_all", return_value=[{"name": "W0000"}])
    @patch.object(quotation_packed_pricing, "_get_item_price")
    def test_repeated_calculation_is_stable(self, get_item_price, get_all):
        parent = frappe._dict({
            "item_code": "W0000", "qty": 5,
            "price_list_rate": 0.25, "rate": 0.25, "amount": 1.25
        })
        packed = frappe._dict({
            "parent_item": "W0000", "item_code": "WS0001",
            "qty": 25, "uom": "Each", "rate": 0, "amount": 0
        })
        warranty = frappe._dict({
            "item_code": "QC7026", "qty": 1,
            "price_list_rate": 1, "rate": 1, "amount": 1
        })
        doc = self._quotation([parent, warranty], [packed])
        get_item_price.side_effect = lambda item_code, price_list, uom=None: (
            1 if item_code == "WS0001" else 0.25
        )

        quotation_packed_pricing.apply_quotation_packed_pricing(
            doc, show_messages=False
        )
        first_values = (
            parent.rate,
            parent.amount,
            warranty.rate,
            warranty.amount,
            doc.total_selling_price
        )

        quotation_packed_pricing.apply_quotation_packed_pricing(
            doc, show_messages=False
        )
        second_values = (
            parent.rate,
            parent.amount,
            warranty.rate,
            warranty.amount,
            doc.total_selling_price
        )

        self.assertEqual(first_values, (5.25, 26.25, 3.938, 3.938, 25))
        self.assertEqual(second_values, first_values)
        self.assertEqual(doc.calculate_taxes_and_totals.call_count, 2)

    def test_item_price_prefers_selected_price_list(self):
        with patch.object(quotation_packed_pricing.frappe, "db") as database:
            database.get_value.return_value = 8

            rate = quotation_packed_pricing._get_item_price(
                "K3001", "B2B Price", "Roll"
            )

        self.assertEqual(rate, 8)
        database.get_single_value.assert_not_called()

    def test_item_price_falls_back_to_regular_selling_price_list(self):
        with patch.object(quotation_packed_pricing.frappe, "db") as database:
            database.get_single_value.return_value = "Regular Price"
            database.get_value.side_effect = [None, None, 59.091]

            rate = quotation_packed_pricing._get_item_price(
                "K3001", "B2B Price", "Roll"
            )

        self.assertEqual(rate, 59.091)
        fallback_filters = database.get_value.call_args_list[2][0][1]
        self.assertEqual(fallback_filters["price_list"], "Regular Price")
        self.assertEqual(fallback_filters["uom"], "Roll")

    def test_item_price_error_lists_selected_and_fallback_price_lists(self):
        with patch.object(quotation_packed_pricing.frappe, "db") as database, \
                patch.object(
                    quotation_packed_pricing.frappe,
                    "throw",
                    side_effect=frappe.ValidationError
                ) as throw:
            database.get_single_value.return_value = "Regular Price"
            database.get_value.return_value = None

            with self.assertRaises(frappe.ValidationError):
                quotation_packed_pricing._get_item_price(
                    "K3001", "B2B Price", "Roll"
                )

        message = throw.call_args[0][0]
        self.assertIn("B2B Price", message)
        self.assertIn("Regular Price (fallback)", message)


if __name__ == "__main__":
    unittest.main()
