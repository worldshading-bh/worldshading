# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import json
import os
import unittest
from unittest.mock import MagicMock, patch

import frappe

from worldshading.worldshading.doctype.pricing_group import pricing_group


class TestPricingGroup(unittest.TestCase):
	def setUp(self):
		frappe.local.db = MagicMock()
		frappe.local.flags = frappe._dict()
		frappe.local.message_log = []
		frappe.local.response = frappe._dict()
		definition_path = os.path.join(os.path.dirname(__file__), "pricing_group.json")
		with open(definition_path) as definition_file:
			self.definition = json.load(definition_file)

	def _field(self, fieldname):
		return next(
			field for field in self.definition["fields"]
			if field.get("fieldname") == fieldname
		)

	def test_pricing_group_is_a_normal_named_master(self):
		self.assertEqual(
			self.definition.get("autoname"), "field:pricing_group_name"
		)
		self.assertFalse(self.definition.get("is_tree", 0))
		self.assertEqual(self.definition.get("title_field"), "pricing_group_name")

		name_field = self._field("pricing_group_name")
		self.assertEqual(name_field.get("reqd"), 1)
		self.assertEqual(name_field.get("unique"), 1)
		self.assertEqual(name_field.get("in_list_view"), 1)
		self.assertEqual(name_field.get("in_standard_filter"), 1)

		disabled_field = self._field("disabled")
		self.assertEqual(disabled_field.get("default"), "0")
		self.assertEqual(disabled_field.get("in_list_view"), 1)
		self.assertEqual(disabled_field.get("in_standard_filter"), 1)

	def test_pricing_group_permissions_match_approved_roles(self):
		permissions = {
			row["role"]: row for row in self.definition.get("permissions", [])
		}
		self.assertEqual(
			set(permissions),
			set(["System Manager", "Accounts Manager", "Sales Manager", "Stock Manager"])
		)
		for role in ("System Manager", "Accounts Manager"):
			self.assertEqual(permissions[role].get("read"), 1)
			self.assertEqual(permissions[role].get("create"), 1)
			self.assertEqual(permissions[role].get("write"), 1)
		self.assertEqual(permissions["System Manager"].get("delete"), 1)
		for role in ("Sales Manager", "Stock Manager"):
			self.assertEqual(permissions[role].get("read"), 1)
			self.assertFalse(permissions[role].get("write", 0))

	def test_pricing_group_has_required_configuration_and_items_fields(self):
		for fieldname, options in (
			("company", "Company"),
			("item_group", "Item Group"),
			("pricing_strategy", "Pricing Strategy Template")
		):
			field = self._field(fieldname)
			self.assertEqual(field.get("fieldtype"), "Link")
			self.assertEqual(field.get("options"), options)
			self.assertEqual(field.get("reqd"), 1)
		items_field = self._field("included_items_html")
		self.assertEqual(items_field.get("fieldtype"), "HTML")
		self.assertEqual(items_field.get("read_only"), 1)

	def test_valid_configuration_accepts_matching_enabled_strategy(self):
		doc = frappe._dict({
			"name": "Colours", "company": "WS", "item_group": "PVC",
			"pricing_strategy": "PVC Strategy", "disabled": 0
		})
		with patch.object(pricing_group.frappe.db, "get_value", return_value=frappe._dict({
			"company": "WS", "enabled": 1
		})):
			with patch.object(pricing_group.frappe, "get_all", return_value=[]):
				pricing_group.validate_pricing_group_configuration(doc)

	def test_configuration_rejects_disabled_or_wrong_company_strategy(self):
		doc = frappe._dict({
			"name": "Colours", "company": "WS", "item_group": "PVC",
			"pricing_strategy": "PVC Strategy", "disabled": 0
		})
		for strategy, message in (
			(frappe._dict({"company": "WS", "enabled": 0}), "not enabled"),
			(frappe._dict({"company": "Other", "enabled": 1}), "Company")
		):
			with patch.object(pricing_group.frappe.db, "get_value", return_value=strategy):
				with self.assertRaisesRegex(frappe.ValidationError, message):
					pricing_group.validate_pricing_group_configuration(doc)

	def test_configuration_rejects_existing_item_group_mismatch(self):
		doc = frappe._dict({
			"name": "Colours", "company": "WS", "item_group": "PVC",
			"pricing_strategy": "PVC Strategy", "disabled": 0
		})
		with patch.object(pricing_group.frappe.db, "get_value", return_value=frappe._dict({
			"company": "WS", "enabled": 1
		})):
			with patch.object(pricing_group.frappe, "get_all", return_value=[
				frappe._dict({"name": "ITEM-001"}), frappe._dict({"name": "ITEM-002"})
			]):
				with self.assertRaisesRegex(frappe.ValidationError, "ITEM-001.*2 Item"):
					pricing_group.validate_pricing_group_configuration(doc)

	def test_configuration_reader_checks_permission_and_completeness(self):
		with patch.object(pricing_group.frappe, "has_permission", return_value=False):
			with self.assertRaises(frappe.PermissionError):
				pricing_group.get_pricing_group_configuration("Colours")
		with patch.object(pricing_group.frappe, "has_permission", return_value=True):
			with patch.object(pricing_group.frappe.db, "get_value", return_value=frappe._dict({
				"name": "Colours", "company": "", "item_group": "PVC",
				"pricing_strategy": "PVC Strategy", "disabled": 0
			})):
				with self.assertRaisesRegex(frappe.ValidationError, "incomplete"):
					pricing_group.get_pricing_group_configuration("Colours")

	def test_item_without_pricing_group_needs_no_validation(self):
		with patch.object(pricing_group, "get_pricing_group_configuration") as reader:
			pricing_group.validate_item_pricing_group(frappe._dict({
				"name": "ITEM-001", "item_group": "PVC", "pricing_group": ""
			}))
		reader.assert_not_called()

	def test_item_accepts_matching_pricing_group(self):
		with patch.object(pricing_group, "get_pricing_group_configuration", return_value={
			"name": "Colours", "company": "WS", "item_group": "PVC",
			"pricing_strategy": "PVC Strategy", "disabled": 0
		}):
			pricing_group.validate_item_pricing_group(frappe._dict({
				"name": "ITEM-001", "item_group": "PVC", "pricing_group": "Colours"
			}))

	def test_item_rejects_mismatched_item_group(self):
		with patch.object(pricing_group, "get_pricing_group_configuration", return_value={
			"name": "Colours", "company": "WS", "item_group": "PVC",
			"pricing_strategy": "PVC Strategy", "disabled": 0
		}):
			with self.assertRaisesRegex(frappe.ValidationError, "ITEM-001.*Colours.*PVC"):
				pricing_group.validate_item_pricing_group(frappe._dict({
					"name": "ITEM-001", "item_group": "Shade Net", "pricing_group": "Colours"
				}))

	def test_item_rejects_disabled_incomplete_or_missing_pricing_group(self):
		item = frappe._dict({
			"name": "ITEM-001", "item_group": "PVC", "pricing_group": "Colours"
		})
		cases = [
			(frappe._dict({
				"name": "Colours", "company": "WS", "item_group": "PVC",
				"pricing_strategy": "PVC Strategy", "disabled": 1
			}), "disabled"),
			(frappe._dict({
				"name": "Colours", "company": "", "item_group": "PVC",
				"pricing_strategy": "PVC Strategy", "disabled": 0
			}), "incomplete"),
			(None, "does not exist")
		]
		for group_values, message in cases:
			with patch.object(pricing_group.frappe, "has_permission", return_value=True):
				with patch.object(pricing_group.frappe.db, "get_value", return_value=group_values):
					with self.assertRaisesRegex(frappe.ValidationError, message):
						pricing_group.validate_item_pricing_group(item)

	def test_item_validate_hook_preserves_legacy_validator_first(self):
		hooks_path = os.path.abspath(os.path.join(
			os.path.dirname(__file__), "..", "..", "..", "hooks.py"
		))
		with open(hooks_path) as hooks_file:
			hooks_source = hooks_file.read()
		legacy = '"worldshading.api.legacy_groups.validate_active_group_assignment"'
		pricing = ('"worldshading.worldshading.doctype.pricing_group.'
			'pricing_group.validate_item_pricing_group"')
		self.assertIn(legacy, hooks_source)
		self.assertIn(pricing, hooks_source)
		self.assertLess(hooks_source.index(legacy), hooks_source.index(pricing))

	def test_item_reader_checks_pricing_group_and_item_permissions(self):
		with patch.object(pricing_group.frappe, "has_permission", return_value=False):
			with self.assertRaises(frappe.PermissionError):
				pricing_group.get_pricing_group_items("Colours")
		with patch.object(pricing_group.frappe, "has_permission", side_effect=[True, False]):
			with self.assertRaises(frappe.PermissionError):
				pricing_group.get_pricing_group_items("Colours")

	def test_item_reader_returns_all_members_in_item_code_order(self):
		rows = [
			frappe._dict({
				"name": "ITEM-001", "item_name": "Blue <Roll>", "item_group": "PVC",
				"brand": "Rakaz", "stock_uom": "Roll", "disabled": 0
			}),
			frappe._dict({
				"name": "ITEM-002", "item_name": "Red Roll", "item_group": "PVC",
				"brand": "Rakaz", "stock_uom": "Roll", "disabled": 1
			})
		]
		with patch.object(pricing_group.frappe, "has_permission", side_effect=[True, True]):
			with patch.object(pricing_group.frappe, "get_all", return_value=rows) as get_all:
				result = pricing_group.get_pricing_group_items("Colours")
		self.assertEqual(result[0]["item_code"], "ITEM-001")
		self.assertEqual(result[1]["disabled"], 1)
		call = get_all.call_args[1]
		self.assertEqual(call["filters"], {"pricing_group": "Colours"})
		self.assertEqual(call["order_by"], "name asc")
		self.assertEqual(call["limit_page_length"], 0)
		self.assertNotIn("disabled", call["filters"])


if __name__ == "__main__":
	unittest.main()
