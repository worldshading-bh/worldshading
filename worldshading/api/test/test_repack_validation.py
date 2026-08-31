# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import unittest

from worldshading.api import repack_validation
from worldshading.api.repack_validation import (
	_build_mismatch_message, _get_rule_stock_entry_type, find_matching_rule,
	find_matching_rules)


ROLL = ("ROLL-001", "Roll")
FABRIC = ("FABRIC-001", "Meter")
ROLL_2 = ("ROLL-002", "Roll")
FABRIC_2 = ("FABRIC-002", "Meter")


def repack_rule(source_qty=1, target_qty=25):
	return {
		"name": "RP-001",
		"sources": {ROLL: source_qty},
		"targets": {FABRIC: target_qty}
	}


class TestRepackRuleMatching(unittest.TestCase):
	def setUp(self):
		self.original_get_link_to_form = repack_validation.frappe.utils.get_link_to_form
		repack_validation.frappe.utils.get_link_to_form = self.get_link_to_form

	def tearDown(self):
		repack_validation.frappe.utils.get_link_to_form = self.original_get_link_to_form

	@staticmethod
	def get_link_to_form(doctype, name, label=None):
		return '<a href="#Form/{0}/{1}">{2}</a>'.format(doctype, name, label or name)

	def test_exact_rule_batch_is_allowed(self):
		matched = find_matching_rule({ROLL: 1}, {FABRIC: 25}, [repack_rule()])
		self.assertEqual(matched, "RP-001")

	def test_whole_number_multiple_is_allowed(self):
		matched = find_matching_rule({ROLL: 3}, {FABRIC: 75}, [repack_rule()])
		self.assertEqual(matched, "RP-001")

	def test_incorrect_target_quantity_is_rejected(self):
		matched = find_matching_rule({ROLL: 1}, {FABRIC: 1}, [repack_rule()])
		self.assertIsNone(matched)

	def test_fraction_of_a_rule_batch_is_rejected(self):
		matched = find_matching_rule({ROLL: 0.5}, {FABRIC: 12.5}, [repack_rule()])
		self.assertIsNone(matched)

	def test_incorrect_source_quantity_is_rejected(self):
		matched = find_matching_rule({ROLL: 2}, {FABRIC: 25}, [repack_rule()])
		self.assertIsNone(matched)

	def test_extra_item_is_rejected(self):
		extra_source = ("PACKING-001", "Nos")
		matched = find_matching_rule(
			{ROLL: 1, extra_source: 1}, {FABRIC: 25}, [repack_rule()])
		self.assertIsNone(matched)

	def test_uom_must_match_the_rule(self):
		matched = find_matching_rule(
			{ROLL: 1}, {("FABRIC-001", "Nos"): 25}, [repack_rule()])
		self.assertIsNone(matched)

	def test_stock_entry_type_drives_rule_type(self):
		self.assertEqual(
			_get_rule_stock_entry_type({
				"purpose": "Repack",
				"stock_entry_type": "Production"
			}),
			"Production"
		)

	def test_erpnext_purpose_repack_does_not_trigger_without_custom_type(self):
		self.assertIsNone(_get_rule_stock_entry_type({
			"purpose": "Repack",
			"stock_entry_type": "Manufacture"
		}))

	def test_message_explains_wrong_target_quantity_on_separate_lines(self):
		message = _build_mismatch_message(
			{ROLL: 1}, {FABRIC: 20}, [repack_rule(target_qty=50)])
		self.assertIn("Target quantity for FABRIC-001 is 20.0 Meter; it must be 50.0 Meter.", message)
		self.assertIn("<br>", message)
		self.assertIn("<b>Applicable rule:</b>", message)
		self.assertIn("<b>Required quantities:</b>", message)
		self.assertIn("<b>Problem:</b>", message)
		self.assertNotIn("<b>Issue:</b>", message)
		self.assertNotIn("Entered quantities", message)

	def test_message_links_to_the_existing_rule(self):
		message = _build_mismatch_message(
			{ROLL: 1}, {FABRIC: 20}, [repack_rule(target_qty=50)])
		self.assertIn('href="#Form/Repack Production Rule/RP-001"', message)
		self.assertIn(">RP-001</a>", message)

	def test_two_different_repacks_in_one_stock_entry_are_allowed(self):
		rules = [
			repack_rule(),
			{
				"name": "RP-002",
				"sources": {ROLL_2: 1},
				"targets": {FABRIC_2: 10}
			}
		]
		matched = find_matching_rules(
			{ROLL: 1, ROLL_2: 2},
			{FABRIC: 25, FABRIC_2: 20},
			rules
		)
		self.assertEqual(matched, ["RP-001", "RP-002"])

	def test_one_incorrect_repack_rejects_the_combined_stock_entry(self):
		rules = [
			repack_rule(),
			{
				"name": "RP-002",
				"sources": {ROLL_2: 1},
				"targets": {FABRIC_2: 10}
			}
		]
		matched = find_matching_rules(
			{ROLL: 1, ROLL_2: 2},
			{FABRIC: 25, FABRIC_2: 19},
			rules
		)
		self.assertEqual(matched, [])

	def test_two_repacks_can_share_the_same_source_item(self):
		rules = [
			repack_rule(),
			{
				"name": "RP-002",
				"sources": {ROLL: 1},
				"targets": {FABRIC_2: 10}
			}
		]
		matched = find_matching_rules(
			{ROLL: 2},
			{FABRIC: 25, FABRIC_2: 10},
			rules
		)
		self.assertEqual(matched, ["RP-001", "RP-002"])

	def test_duplicate_target_rules_are_treated_as_alternatives(self):
		matched = find_matching_rules(
			{("KSA0011", "Roll"): 1},
			{("WK0011", "Meter"): 225},
			[
				{
					"name": "Repack-WK0011",
					"sources": {("KSA0011", "Roll"): 1},
					"targets": {("WK0011", "Meter"): 225}
				},
				{
					"name": "Production-WK0011",
					"sources": {("K0011", "Roll"): 1},
					"targets": {("WK0011", "Meter"): 225}
				}
			]
		)
		self.assertEqual(matched, ["Repack-WK0011"])

	def test_multi_repack_message_reports_each_wrong_target_quantity(self):
		rules = [
			repack_rule(target_qty=50),
			{
				"name": "RP-002",
				"sources": {ROLL_2: 1},
				"targets": {FABRIC_2: 25}
			}
		]
		message = _build_mismatch_message(
			{ROLL: 1, ROLL_2: 1},
			{FABRIC: 40, FABRIC_2: 20},
			rules
		)
		self.assertIn(
			"Target quantity for FABRIC-001 is 40.0 Meter; it must be 50.0 Meter.",
			message)
		self.assertIn(
			"Target quantity for FABRIC-002 is 20.0 Meter; it must be 25.0 Meter.",
			message)
		self.assertNotIn("item or UOM does not match", message)


if __name__ == "__main__":
	unittest.main()
