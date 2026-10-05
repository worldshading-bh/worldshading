from __future__ import unicode_literals

import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import frappe
from lxml import html


class TestPricingUpdateNotifications(unittest.TestCase):

	def setUp(self):
		from worldshading.api import pricing_update_notifications
		self.notifications = pricing_update_notifications
		frappe.local.session = frappe._dict(user="pricing@example.com")
		self.stack = ExitStack()
		self.addCleanup(self.stack.close)
		self.documents = []
		self.stack.enter_context(patch.object(frappe, "new_doc", side_effect=self.new_note))
		self.stack.enter_context(patch.object(pricing_update_notifications, "nowdate", return_value="2026-10-04"))
		self.stack.enter_context(patch.object(pricing_update_notifications, "now", return_value="2026-10-04 15:30:00"))

	def new_note(self, doctype):
		self.assertEqual(doctype, "Note")
		doc = MagicMock()
		doc.name = "NOTE-{0}".format(len(self.documents) + 1)
		self.documents.append(doc)
		return doc

	def price(self, **values):
		row = dict(item_code="A", item_name="Fabric", price_list="Regular", uom="Roll",
			currency="BHD", old_rate=10, new_rate=12, workflow_state="Active")
		row.update(values)
		return row

	def test_one_note_contains_all_changes_and_three_day_repeat_settings(self):
		result = self.notifications.create_pricing_update_note("item_price", "REP-1", [
			self.price(), self.price(price_list="B2B", old_rate=None, new_rate=11),
			self.price(item_code="B", workflow_state="Pending Final Price Approval")])
		self.assertEqual(result, "NOTE-1")
		self.assertEqual(len(self.documents), 1)
		note = self.documents[0]
		self.assertEqual((note.public, note.notify_on_login, note.notify_on_every_login), (1, 1, 1))
		self.assertEqual(str(note.expire_notification_on), "2026-10-07")
		for text in ["Regular Price", "B2B Price", "12.000", "11.000", "Item Name", "Roll"]:
			self.assertIn(text, note.content)
		for text in ["10.000", "Currency", "Previous", "Approval", "REP-1", "pricing@example.com",
			"Pending Final Price Approval", "Amounts are net", "Updated by"]:
			self.assertNotIn(text, note.content)
		note.insert.assert_called_once_with()

	def test_prices_merge_by_item_and_missing_changes_are_explicit(self):
		content = self.notifications.render_item_price_changes([
			self.price(price_list="B2B", new_rate=11, price_kind="B2B"),
			self.price(price_kind="Regular"), self.price(item_code="B", price_kind="Regular")])
		document = html.fromstring(content)
		self.assertEqual(document.xpath('//th/text()'), ["Item", "Item Name", "UOM", "Regular Price", "B2B Price"])
		self.assertEqual([row.xpath('./td/text()') for row in document.xpath('//tbody/tr')], [
			["A", "Fabric", "Roll", "12.000", "11.000"],
			["B", "Fabric", "Roll", "12.000", "Not changed"]])

	def test_single_price_list_has_only_one_price_column(self):
		document = html.fromstring(self.notifications.render_item_price_changes([self.price()]))
		self.assertEqual(document.xpath('//th/text()'), ["Item", "Item Name", "UOM", "Regular Price"])

	def test_different_uoms_are_not_merged(self):
		document = html.fromstring(self.notifications.render_item_price_changes([
			self.price(), self.price(uom="Nos", price_list="B2B", new_rate=1)]))
		self.assertEqual(len(document.xpath('//tbody/tr')), 2)

	def test_empty_changes_create_no_note(self):
		self.assertIsNone(self.notifications.create_pricing_update_note("item_price", "REP-1", []))
		self.assertEqual(self.documents, [])

	def test_repeated_operations_have_distinct_titles(self):
		for unused in range(2):
			self.notifications.create_pricing_update_note("item_price", "REP-1", [self.price()])
		self.assertNotEqual(self.documents[0].title, self.documents[1].title)

	def test_content_escapes_names_and_excludes_cost_fields(self):
		self.notifications.create_pricing_update_note("item_price", "<REP>", [
			self.price(item_name='<script>alert("x")</script>', base_cost="SECRET-COST")])
		content = self.documents[0].content
		self.assertNotIn("<script>", content)
		self.assertIn("&lt;script&gt;", content)
		self.assertNotIn("<REP>", content)
		self.assertNotIn("SECRET-COST", content)

	def test_rule_note_shows_final_discount_quantity_and_status(self):
		self.notifications.create_pricing_update_note("pricing_rule", "REP-1", [{
			"rule_name": "PSA - Fabric - Tier 1", "item_codes": ["A", "B"],
			"minimum_qty": 5, "maximum_qty": None, "discount_percentage": 7.5,
			"disabled": 0, "mixed_conditions": 1}])
		note = self.documents[0]
		self.assertTrue(note.title.startswith("Pricing Rules Updated"))
		for text in ["PSA - Fabric - Tier 1", "A, B", "7.500%", "No maximum", "Enabled", "Yes"]:
			self.assertIn(text, note.content)

	def test_note_insert_failure_propagates(self):
		doc = self.new_note("Note")
		doc.insert.side_effect = frappe.PermissionError("Cannot create Note")
		with patch.object(frappe, "new_doc", return_value=doc):
			with self.assertRaises(frappe.PermissionError):
				self.notifications.create_pricing_update_note("item_price", "REP-1", [self.price()])
