from __future__ import unicode_literals

import unittest
from decimal import Decimal

from worldshading.reporting.item_wise_sales import (
	allocate_parent_pool,
	normalize_transaction_rows,
)


class TestPackedRevenueAllocation(unittest.TestCase):
	def parent(self, amount="100", item_code="BUNDLE", name="SII-1", qty="1"):
		return {
			"invoice": "SINV-1", "name": name, "item_code": item_code,
			"stock_qty": qty, "qty": qty, "base_net_amount": amount,
			"posting_date": "2026-09-01", "stock_uom": "Nos"
		}

	def packed(self, item_code, amount, qty="1", rate=None, parent_item="BUNDLE"):
		return {
			"invoice": "SINV-1", "item_code": item_code,
			"parent_item": parent_item, "qty": qty,
			"amount": amount, "rate": rate if rate is not None else amount,
			"posting_date": "2026-09-01", "uom": "Nos"
		}

	def test_preserves_declared_packed_values_and_parent_residual(self):
		rows = allocate_parent_pool(
			[self.parent("100")],
			[self.packed("A", "60"), self.packed("B", "30")]
		)
		self.assertEqual(
			[(row["item_code"], row["net_amount"]) for row in rows],
			[("A", Decimal("60.000")), ("B", Decimal("30.000")),
			 ("BUNDLE", Decimal("10.000"))]
		)
		self.assertEqual(sum(row["net_amount"] for row in rows), Decimal("100.000"))

	def test_scales_packed_values_to_discounted_parent(self):
		rows = allocate_parent_pool(
			[self.parent("80")],
			[self.packed("A", "60"), self.packed("B", "40")]
		)
		self.assertEqual(
			[(row["item_code"], row["net_amount"]) for row in rows],
			[("A", Decimal("48.000")), ("B", Decimal("32.000"))]
		)
		self.assertEqual(sum(row["net_amount"] for row in rows), Decimal("80.000"))

	def test_return_uses_parent_sign(self):
		rows = allocate_parent_pool(
			[self.parent("-80", qty="-1")],
			[self.packed("A", "60", qty="-1"), self.packed("B", "40", qty="-1")]
		)
		self.assertEqual([row["net_amount"] for row in rows], [Decimal("-48.000"), Decimal("-32.000")])
		self.assertEqual([row["stock_qty"] for row in rows], [Decimal("-1"), Decimal("-1")])

	def test_duplicate_parent_rows_warn_and_reconcile_as_one_pool(self):
		rows = allocate_parent_pool(
			[self.parent("70", name="SII-1"), self.parent("30", name="SII-2")],
			[self.packed("A", "40"), self.packed("B", "30")]
		)
		self.assertEqual(sum(row["net_amount"] for row in rows), Decimal("100.000"))
		self.assertTrue(all("ambiguous_parent_rows" in row["warnings"] for row in rows))

	def test_missing_amount_uses_rate_times_quantity(self):
		rows = allocate_parent_pool(
			[self.parent("20")],
			[self.packed("A", None, qty="2", rate="5")]
		)
		self.assertEqual(rows[0]["net_amount"], Decimal("10.000"))
		self.assertIn("packed_amount_from_rate", rows[0]["warnings"])

	def test_missing_money_uses_quantity_weight(self):
		rows = allocate_parent_pool(
			[self.parent("20")],
			[self.packed("A", None, qty="1", rate=None), self.packed("B", None, qty="3", rate=None)]
		)
		self.assertEqual([row["net_amount"] for row in rows[:2]], [Decimal("5.000"), Decimal("15.000")])
		self.assertTrue(all("packed_value_from_quantity" in row["warnings"] for row in rows[:2]))

	def test_zero_quantity_with_value_warns(self):
		rows = allocate_parent_pool([self.parent("10")], [self.packed("A", "10", qty="0")])
		self.assertEqual(rows[0]["net_amount"], Decimal("10.000"))
		self.assertIn("zero_qty_nonzero_value", rows[0]["warnings"])

	def test_rounding_remainder_is_applied_to_final_component(self):
		rows = allocate_parent_pool(
			[self.parent("10")],
			[self.packed("A", "4"), self.packed("B", "4"), self.packed("C", "4")]
		)
		self.assertEqual([row["net_amount"] for row in rows], [Decimal("3.333"), Decimal("3.333"), Decimal("3.334")])

	def test_unmatched_packed_group_has_quantity_but_no_revenue(self):
		rows = allocate_parent_pool([], [self.packed("A", "20", qty="2")])
		self.assertEqual(rows[0]["net_amount"], Decimal("0.000"))
		self.assertEqual(rows[0]["stock_qty"], Decimal("2"))
		self.assertIn("missing_parent_item", rows[0]["warnings"])

	def test_normalize_combines_same_item_direct_and_packed_once(self):
		direct = [self.parent("50", item_code="A", name="SII-A", qty="2"), self.parent("80")]
		packed = [self.packed("A", "80", qty="4")]
		rows = normalize_transaction_rows(direct, packed)
		item_a = [row for row in rows if row["item_code"] == "A"][0]
		self.assertEqual(item_a["sales_basis"], "Direct + Packed")
		self.assertEqual(item_a["direct_qty"], Decimal("2"))
		self.assertEqual(item_a["packed_qty"], Decimal("4"))
		self.assertEqual(item_a["stock_qty"], Decimal("6"))
		self.assertEqual(item_a["net_amount"], Decimal("130.000"))

	def test_direct_only_row_is_preserved(self):
		rows = normalize_transaction_rows([self.parent("25", item_code="A", qty="2")], [])
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["sales_basis"], "Direct")
		self.assertEqual(rows[0]["net_rate"], Decimal("12.500"))


if __name__ == "__main__":
	unittest.main()
