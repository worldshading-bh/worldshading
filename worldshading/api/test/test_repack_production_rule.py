# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import unittest

from worldshading.api import repack_production_rule
from worldshading.api.repack_production_rule import (
	_get_next_rule_name, _get_rule_name_base)


class FakeDB(object):
	def __init__(self, count, existing_names=None):
		self._count = count
		self._existing_names = set(existing_names or [])

	def count(self, doctype, filters):
		return self._count

	def exists(self, doctype, name):
		return name in self._existing_names


class TestRepackProductionRuleNaming(unittest.TestCase):
	def setUp(self):
		self.original_db = repack_production_rule.frappe.db

	def tearDown(self):
		repack_production_rule.frappe.db = self.original_db

	def test_rule_name_base_uses_type_and_final_item_code(self):
		self.assertEqual(
			_get_rule_name_base("Production", "WK0011"),
			"Production-WK0011"
		)

	def test_first_rule_starts_with_small_suffix(self):
		repack_production_rule.frappe.db = FakeDB(0)
		self.assertEqual(
			_get_next_rule_name("Production-WK0011", "Production", "WK0011"),
			"Production-WK0011-1"
		)

	def test_existing_unsuffixed_rule_does_not_force_large_series_number(self):
		repack_production_rule.frappe.db = FakeDB(2, [
			"Repack-DCAL7019",
			"Repack-DCAL7019-390708"
		])
		self.assertEqual(
			_get_next_rule_name("Repack-DCAL7019", "Repack", "DCAL7019"),
			"Repack-DCAL7019-2"
		)

	def test_existing_small_suffix_is_skipped(self):
		repack_production_rule.frappe.db = FakeDB(2, [
			"Production-WK0011",
			"Production-WK0011-1"
		])
		self.assertEqual(
			_get_next_rule_name("Production-WK0011", "Production", "WK0011"),
			"Production-WK0011-2"
		)


if __name__ == "__main__":
	unittest.main()
