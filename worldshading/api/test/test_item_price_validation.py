import unittest
from unittest.mock import Mock, patch

import frappe


class TestItemPriceValidation(unittest.TestCase):

    @patch("worldshading.api.item_price_validation.get_link_to_form",
        new=lambda doctype, name: name)
    def validate(self, values=None, existing=None, is_new=True):
        from worldshading.api.item_price_validation import validate_new_item_price
        doc = frappe._dict(item_code="ITEM-1", price_list="Regular Price",
            uom="Each", valid_from="2026-10-21", valid_upto="2026-12-31")
        doc.update(values or {})
        doc.is_new = Mock(return_value=is_new)
        with patch.object(frappe, "get_all", return_value=existing or []) as query:
            with patch.object(frappe, "throw", side_effect=frappe.ValidationError) as throw:
                if existing and is_new:
                    with self.assertRaises(frappe.ValidationError):
                        validate_new_item_price(doc)
                    self.assertIn("PRICE-1", throw.call_args[0][0])
                else:
                    validate_new_item_price(doc)
                    throw.assert_not_called()
        return query

    def test_duplicate_check_ignores_both_dates(self):
        query = self.validate(existing=[frappe._dict(name="PRICE-1")])
        self.assertEqual(query.call_args[1]["filters"], {
            "item_code": "ITEM-1", "price_list": "Regular Price", "uom": "Each"})

    def test_distinct_price_is_allowed(self):
        self.validate()

    def test_existing_price_updates_are_not_checked(self):
        query = self.validate(existing=[frappe._dict(name="PRICE-1")], is_new=False)
        query.assert_not_called()

    def test_preserves_optional_matching_fields(self):
        values = {"uom": "Box", "packing_unit": 5, "customer": "CUSTOMER-1",
            "supplier": "SUPPLIER-1"}
        query = self.validate(values)
        for field, value in values.items():
            self.assertEqual(query.call_args[1]["filters"][field], value)

    def test_blank_fields_remain_unrestricted_like_native_check(self):
        query = self.validate({"uom": "", "packing_unit": 0,
            "customer": None, "supplier": ""})
        self.assertEqual(query.call_args[1]["filters"], {
            "item_code": "ITEM-1", "price_list": "Regular Price"})

    def test_hook_is_registered_for_validation(self):
        from worldshading import hooks
        self.assertEqual(hooks.doc_events["Item Price"]["validate"],
            "worldshading.api.item_price_validation.validate_new_item_price")
