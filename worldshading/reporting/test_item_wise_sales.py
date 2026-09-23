from __future__ import unicode_literals

import unittest
from decimal import Decimal
from unittest.mock import patch

from worldshading.reporting import item_wise_sales as report
from worldshading.reporting.item_wise_sales import (
	allocate_parent_pool,
	get_item_sales_aggregates,
	get_transaction_rows,
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

	def test_return_normalizes_positive_packed_quantity_to_parent_sign(self):
		rows = allocate_parent_pool(
			[self.parent("-20", qty="-1")], [self.packed("A", "20", qty="2")]
		)
		self.assertEqual(rows[0]["stock_qty"], Decimal("-2"))
		self.assertEqual(rows[0]["net_amount"], Decimal("-20.000"))
		self.assertEqual(rows[0]["net_rate"], Decimal("10.000"))

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


class TestSalesReader(unittest.TestCase):
	def test_sales_basis_filter_accepts_user_facing_item_labels(self):
		self.assertEqual(
			report.validate_filters(self.filters(sales_basis="Direct Items"))["sales_basis"],
			"Direct"
		)
		self.assertEqual(
			report.validate_filters(self.filters(sales_basis="Packed Items"))["sales_basis"],
			"Packed"
		)

	def filters(self, **overrides):
		values = {
			"company": "WS", "from_date": "2026-01-01", "to_date": "2026-12-31",
			"item_code": "A", "item_name": "Roll", "item_group": "Products",
			"brand": "Brand A", "customer": "CUST-1", "warehouse": "Main - WS",
			"project": "PROJ-1", "sales_basis": "All", "include_returns": 1
		}
		values.update(overrides)
		return values

	def test_reader_applies_invoice_and_optional_filters_in_sql(self):
		queries = []

		def fake_sql(query, values=None, as_dict=False):
			queries.append(query)
			return []

		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.side_effect = fake_sql
			get_transaction_rows(self.filters())

		self.assertEqual(len(queries), 2)
		direct_query = queries[0].lower()
		packed_query = queries[1].lower()
		for query in queries:
			lowered = query.lower()
			self.assertIn("si.docstatus = 1", lowered)
			self.assertIn("si.company = %(company)s", lowered)
			self.assertIn("si.posting_date between %(from_date)s and %(to_date)s", lowered)
			self.assertIn("si.customer = %(customer)s", lowered)
			self.assertIn("si.project = %(project)s", lowered)
		self.assertIn("sii.item_code = %(item_code)s", direct_query)
		self.assertIn("pi.item_code = %(item_code)s", packed_query)
		self.assertIn("item.item_name like %(item_name)s", direct_query)
		self.assertIn("item.item_group = %(item_group)s", packed_query)
		self.assertIn("item.brand = %(brand)s", packed_query)
		self.assertIn("sii.warehouse = %(warehouse)s", direct_query)
		self.assertIn("pi.warehouse = %(warehouse)s", packed_query)
		self.assertNotIn("pi.creation", packed_query)

	def test_reader_fetches_whole_packed_pool_then_filters_selected_child(self):
		packed_rows = [
			{"invoice": "SINV-1", "item_code": "A", "parent_item": "BUNDLE", "qty": 1,
			 "amount": 60, "rate": 60, "posting_date": "2026-09-01", "parent_base_net_amount": 80,
			 "parent_stock_qty": 1, "parent_row_count": 1},
			{"invoice": "SINV-1", "item_code": "B", "parent_item": "BUNDLE", "qty": 1,
			 "amount": 40, "rate": 40, "posting_date": "2026-09-01", "parent_base_net_amount": 80,
			 "parent_stock_qty": 1, "parent_row_count": 1},
		]

		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.side_effect = [[], packed_rows]
			rows = get_transaction_rows(self.filters(
				item_name=None, item_group=None, brand=None, customer=None,
				warehouse=None, project=None
			))

		self.assertEqual([row["item_code"] for row in rows], ["A"])
		self.assertEqual(rows[0]["net_amount"], Decimal("48.000"))

	def test_sales_basis_and_warehouse_are_output_filters(self):
		packed_rows = [{
			"invoice": "SINV-1", "item_code": "A", "parent_item": "BUNDLE", "qty": 1,
			"amount": 20, "rate": 20, "warehouse": "Main - WS", "posting_date": "2026-09-01",
			"parent_base_net_amount": 20, "parent_stock_qty": 1, "parent_row_count": 1
		}]
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.side_effect = [[], packed_rows]
			rows = get_transaction_rows(self.filters(
				item_code=None, item_name=None, item_group=None, brand=None,
				customer=None, project=None, sales_basis="Packed"
			))
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["sales_basis"], "Packed")

	def test_combined_item_qualifies_for_direct_and_packed_basis(self):
		direct_rows = [{
			"invoice": "SINV-1", "name": "SII-A", "item_code": "A",
			"stock_qty": 2, "qty": 2, "base_net_amount": 40,
			"posting_date": "2026-09-01", "warehouse": "Main - WS"
		}]
		packed_rows = [{
			"invoice": "SINV-1", "item_code": "A", "parent_item": "BUNDLE", "qty": 1,
			"amount": 20, "rate": 20, "warehouse": "Main - WS", "posting_date": "2026-09-01",
			"parent_base_net_amount": 20, "parent_stock_qty": 1, "parent_row_count": 1
		}]
		for sales_basis in ("Direct", "Packed"):
			with patch.object(report, "frappe") as frappe_mock:
				frappe_mock.db.sql.side_effect = [direct_rows, packed_rows]
				rows = get_transaction_rows(self.filters(
					item_code=None, item_name=None, item_group=None, brand=None,
					customer=None, project=None, sales_basis=sales_basis
				))
			self.assertEqual(len(rows), 1)
			self.assertEqual(rows[0]["sales_basis"], "Direct + Packed")

	def test_aggregate_counts_invoice_once_for_combined_item(self):
		rows = [
			{"invoice": "SINV-1", "item_code": "A", "posting_date": "2026-09-01",
			 "stock_qty": Decimal("6"), "net_amount": Decimal("120"), "net_rate": Decimal("20"),
			 "sales_basis": "Direct + Packed", "warnings": []},
			{"invoice": "SINV-2", "item_code": "A", "posting_date": "2026-09-03",
			 "stock_qty": Decimal("-1"), "net_amount": Decimal("-20"), "net_rate": Decimal("20"),
			 "sales_basis": "Direct", "warnings": []},
		]
		with patch.object(report, "get_transaction_rows", return_value=rows):
			result = get_item_sales_aggregates(self.filters(item_code=None), ["A"])["A"]
		self.assertEqual(result["sales_qty"], Decimal("5"))
		self.assertEqual(result["sales_value"], Decimal("100.000"))
		self.assertEqual(result["weighted_average_sold_rate"], Decimal("20.000"))
		self.assertEqual(result["invoice_count"], 2)
		self.assertEqual(result["last_sale_date"], "2026-09-03")
		self.assertEqual(result["last_sold_rate"], Decimal("20.000"))

	def test_reader_preserves_aggregated_parent_ambiguity_warning(self):
		packed_rows = [{
			"invoice": "SINV-1", "item_code": "A", "parent_item": "BUNDLE", "qty": 1,
			"amount": 10, "rate": 10, "posting_date": "2026-09-01",
			"parent_base_net_amount": 20, "parent_stock_qty": 2, "parent_row_count": 2
		}]
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.side_effect = [[], packed_rows]
			rows = get_transaction_rows(self.filters(
				item_code=None, item_name=None, item_group=None, brand=None,
				customer=None, warehouse=None, project=None
			))
		self.assertTrue(all("ambiguous_parent_rows" in row["warnings"] for row in rows))

	def test_item_group_filter_does_not_emit_unrelated_packed_sibling(self):
		packed_rows = [
			{"invoice": "SINV-1", "item_code": "A", "item_group": "Selected", "parent_item": "BUNDLE",
			 "qty": 1, "amount": 10, "rate": 10, "posting_date": "2026-09-01",
			 "parent_base_net_amount": 20, "parent_stock_qty": 1, "parent_row_count": 1},
			{"invoice": "SINV-1", "item_code": "B", "item_group": "Other", "parent_item": "BUNDLE",
			 "qty": 1, "amount": 10, "rate": 10, "posting_date": "2026-09-01",
			 "parent_base_net_amount": 20, "parent_stock_qty": 1, "parent_row_count": 1}
		]
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.side_effect = [[], packed_rows]
			rows = get_transaction_rows(self.filters(
				item_code=None, item_name=None, item_group="Selected", brand=None,
				customer=None, warehouse=None, project=None
			))
		self.assertEqual([row["item_code"] for row in rows], ["A"])

	def test_warehouse_filter_keeps_requested_contribution_separate(self):
		direct_rows = [
			{"invoice": "SINV-1", "name": "SII-1", "item_code": "A", "stock_qty": 1,
			 "base_net_amount": 10, "posting_date": "2026-09-01", "warehouse": "Main - WS"},
			{"invoice": "SINV-1", "name": "SII-2", "item_code": "A", "stock_qty": 2,
			 "base_net_amount": 20, "posting_date": "2026-09-01", "warehouse": "Other - WS"}
		]
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.side_effect = [direct_rows, []]
			rows = get_transaction_rows(self.filters(
				item_code=None, item_name=None, item_group=None, brand=None,
				customer=None, warehouse="Main - WS", project=None
			))
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["stock_qty"], Decimal("1"))
		self.assertEqual(rows[0]["net_amount"], Decimal("10.000"))

	def test_aggregate_warns_when_returns_exceed_sales(self):
		rows = [{
			"invoice": "SINV-1", "item_code": "A", "posting_date": "2026-09-01",
			"stock_qty": Decimal("-2"), "net_amount": Decimal("-20"),
			"net_rate": Decimal("10"), "warnings": []
		}]
		with patch.object(report, "get_transaction_rows", return_value=rows):
			result = get_item_sales_aggregates(self.filters(item_code=None), ["A"])["A"]
		self.assertIsNone(result["weighted_average_sold_rate"])
		self.assertIn("Sales returns equal or exceed sales", result["warnings"])


if __name__ == "__main__":
	unittest.main()
