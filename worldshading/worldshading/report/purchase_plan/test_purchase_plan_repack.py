# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import unittest

import frappe

from worldshading.worldshading.report.purchase_plan import purchase_plan


class TestPurchasePlanRepackAlternatives(unittest.TestCase):
	def setUp(self):
		self.original_get_all = purchase_plan.frappe.get_all

	def tearDown(self):
		purchase_plan.frappe.get_all = self.original_get_all

	def test_oldest_rule_is_used_and_alternative_is_exposed(self):
		def fake_get_all(doctype, filters=None, fields=None,
				order_by=None, limit_page_length=None):
			if doctype == 'Repack Production Rule':
				self.assertEqual(order_by, 'creation asc, name asc')
				return [
					frappe._dict({
						'name': 'Repack-KM3004',
						'creation': '2025-05-11 10:00:00'
					}),
					frappe._dict({
						'name': 'Repack-KM3004-1',
						'creation': '2026-10-17 10:00:00'
					})
				]
			if doctype == 'Source Item':
				return [
					frappe._dict({
						'parent': 'Repack-KM3004',
						'item_code': 'K3004',
						'qty': 1
					}),
					frappe._dict({
						'parent': 'Repack-KM3004-1',
						'item_code': 'HA2004',
						'qty': 2
					})
				]
			if doctype == 'Target Item':
				return [
					frappe._dict({
						'parent': 'Repack-KM3004',
						'item_code': 'KM3004',
						'qty': 50
					}),
					frappe._dict({
						'parent': 'Repack-KM3004-1',
						'item_code': 'KM3004',
						'qty': 50
					})
				]
			raise AssertionError('Unexpected DocType: {0}'.format(doctype))

		purchase_plan.frappe.get_all = fake_get_all

		context = purchase_plan.get_repack_context(['KM3004'])

		self.assertEqual(context['purchase_item_codes'], ['K3004'])
		self.assertEqual(context['target_to_sources']['KM3004'], [{
			'item_code': 'K3004',
			'ratio': 0.02,
			'rule': 'Repack-KM3004'
		}])
		self.assertEqual(
			[rule['name'] for rule in context['repack_rules']],
			['Repack-KM3004']
		)
		alternative_detail = context['repack_alternatives_by_source']['K3004']
		self.assertIn('KM3004', alternative_detail)
		self.assertIn('Repack-KM3004', alternative_detail)
		self.assertIn('K3004', alternative_detail)
		self.assertIn('Repack-KM3004-1', alternative_detail)
		self.assertIn('HA2004', alternative_detail)


if __name__ == '__main__':
	unittest.main()
