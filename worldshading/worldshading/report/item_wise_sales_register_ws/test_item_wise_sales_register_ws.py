from __future__ import unicode_literals

import json
import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from worldshading.worldshading.report.item_wise_sales_register_ws import (
	item_wise_sales_register_ws as report,
)


class TestItemWiseSalesRegisterWS(unittest.TestCase):
	def filters(self, detailed=0):
		return {
			"company": "WS", "from_date": "2026-01-01", "to_date": "2026-12-31",
			"include_returns": 1, "sales_basis": "All",
			"show_detailed_report": detailed
		}

	def transaction(self, **overrides):
		row = {
			"posting_date": "2026-09-01", "invoice": "SINV-1", "item_code": "A",
			"item_name": "Roll A", "item_group": "Rolls", "brand": "Brand A",
			"stock_uom": "Nos", "stock_qty": Decimal("2"),
			"direct_qty": Decimal("0"), "packed_qty": Decimal("2"),
			"net_rate": Decimal("40"), "net_amount": Decimal("80"),
			"direct_net_amount": Decimal("0"), "packed_net_amount": Decimal("80"),
			"sales_basis": "Packed", "parent_item": "BUNDLE",
			"currency": "USD", "warnings": []
		}
		row.update(overrides)
		return row

	def test_compact_columns_are_ordered_and_detail_columns_are_hidden(self):
		fieldnames = [column["fieldname"] for column in report.get_columns(self.filters())]
		self.assertEqual(fieldnames, [
			"item_code", "item_name", "posting_date", "invoice", "item_group", "brand",
			"sales_basis", "stock_uom", "stock_qty", "net_rate", "net_amount",
			"tax", "total", "current_stock_qty", "default_supplier", "supplier_name",
		])
		self.assertNotIn("customer", fieldnames)
		self.assertNotIn("reconciliation_warning", fieldnames)

	def test_detailed_columns_include_reconciliation_and_document_fields(self):
		fieldnames = [column["fieldname"] for column in report.get_columns(self.filters(1))]
		for fieldname in (
			"customer", "customer_name", "customer_group", "territory", "project",
			"sales_order", "delivery_note", "parent_item", "warehouse",
			"income_account", "cost_center", "mode_of_payment", "currency",
			"qty", "uom", "conversion_factor", "discount_percentage",
			"discount_amount", "tax_accounts", "sales_person", "employee",
			"direct_qty", "packed_qty", "direct_net_amount", "packed_net_amount",
			"invoice_count", "last_sold_date"
		):
			self.assertIn(fieldname, fieldnames)

	def test_execute_enriches_row_and_calculates_tax_total(self):
		captured = {}

		def read_rows(filters):
			captured.update(filters)
			return [self.transaction()]

		with patch.object(report, "get_transaction_contributions", side_effect=read_rows), \
				patch.object(report, "get_item_context", return_value={
					"A": {"current_stock_qty": Decimal("12"), "default_supplier": "SUP-1",
						  "supplier_name": "Supplier One", "item_name": "Roll A",
						  "item_group": "Rolls", "brand": "Brand A", "stock_uom": "Nos",
						  "company_currency": "BHD"}
				}), \
				patch.object(report, "get_tax_context", return_value={
					("SINV-1", "BUNDLE"): {"amount": Decimal("8"), "accounts": "VAT 10%"}
				}), \
				patch.object(report, "get_detail_context", return_value={}):
			columns, rows, message, chart = report.execute(self.filters())

		self.assertEqual(captured["company"], "WS")
		self.assertEqual(rows[0]["tax"], Decimal("8.000"))
		self.assertEqual(rows[0]["total"], Decimal("88.000"))
		self.assertEqual(rows[0]["current_stock_qty"], Decimal("12"))
		self.assertEqual(rows[0]["default_supplier"], "SUP-1")
		self.assertEqual(rows[0]["currency"], "BHD")
		self.assertEqual(rows[0]["invoice_currency"], "USD")
		self.assertIsNone(message)
		self.assertIsNone(chart)

	def test_tax_is_shared_once_between_packed_and_parent_residual(self):
		rows = [
			self.transaction(net_amount=Decimal("80"), packed_net_amount=Decimal("80")),
			self.transaction(item_code="BUNDLE", parent_item=None, sales_basis="Direct",
				net_amount=Decimal("20"), direct_net_amount=Decimal("20"),
				packed_net_amount=Decimal("0"), direct_qty=Decimal("1"), packed_qty=Decimal("0"))
		]
		report.apply_tax_values(rows, {
			("SINV-1", "BUNDLE"): {"amount": Decimal("10"), "accounts": "VAT"}
		})
		self.assertEqual([row["tax"] for row in rows], [Decimal("8.000"), Decimal("2.000")])
		self.assertEqual(sum(row["tax"] for row in rows), Decimal("10.000"))

	def test_tax_allocation_indexes_rows_instead_of_rescanning_every_invoice(self):
		class CountingRow(dict):
			reads = 0

			def get(self, key, default=None):
				if key == "invoice":
					CountingRow.reads += 1
				return dict.get(self, key, default)

		rows = []
		tax_context = {}
		for index in range(200):
			invoice = "SINV-{0}".format(index)
			item_code = "ITEM-{0}".format(index)
			rows.append(CountingRow(self.transaction(
				invoice=invoice, item_code=item_code, parent_item=None,
				sales_basis="Direct", net_amount=Decimal("10"),
				direct_net_amount=Decimal("10"), packed_net_amount=Decimal("0"),
				direct_qty=Decimal("1"), packed_qty=Decimal("0")
			)))
			tax_context[(invoice, item_code)] = {
				"amount": Decimal("1"), "accounts": "VAT"
			}

		report.apply_tax_values(rows, tax_context)

		self.assertLess(CountingRow.reads, 1000)
		self.assertEqual(sum(row["tax"] for row in rows), Decimal("200.000"))

	def test_execute_keeps_reconciliation_warnings_internal(self):
		with patch.object(report, "get_transaction_contributions", return_value=[
			self.transaction(warnings=["ambiguous_parent_rows", "zero_qty_nonzero_value"])
		]), patch.object(report, "get_item_context", return_value={}), \
				patch.object(report, "get_tax_context", return_value={}), \
				patch.object(report, "get_detail_context", return_value={}):
			unused_columns, rows, message, unused_chart = report.execute(self.filters(1))
		self.assertIsNone(message)
		self.assertIn("ambiguous_parent_rows", rows[0]["reconciliation_warning"])

	def test_item_context_query_limits_stock_and_supplier_to_company(self):
		queries = []

		def fake_sql(query, values=None, as_dict=False):
			queries.append(query.lower())
			return []

		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.db.sql.side_effect = fake_sql
			report.get_item_context(["A"], "WS", None)
		combined = "\n".join(queries)
		self.assertIn("warehouse.company = %(company)s", combined)
		self.assertIn("item_default.company = %(company)s", combined)
		self.assertIn("sum(bin.actual_qty)", combined)

	def test_metadata_enables_prepared_report(self):
		path = os.path.join(os.path.dirname(__file__), "item_wise_sales_register_ws.json")
		with open(path) as source:
			metadata = json.load(source)
		self.assertEqual(metadata["prepared_report"], 1)
		self.assertEqual(metadata["disable_prepared_report"], 0)
		self.assertEqual(metadata["ref_doctype"], "Sales Invoice")
		self.assertEqual(metadata["module"], "Worldshading")
		self.assertEqual(metadata["add_total_row"], 1)

	def test_javascript_uses_core_filter_spacing_and_fixed_purchase_plan_highlight(self):
		path = os.path.join(os.path.dirname(__file__), "item_wise_sales_register_ws.js")
		with open(path) as source:
			script = source.read()
		self.assertNotIn("Row Highlight Color", script)
		self.assertNotIn("localStorage", script)
		self.assertIn("background:#fff3cd !important", script)
		self.assertNotIn("iwsr-ws-filter-control{height", script)
		self.assertNotIn("margin:0!important", script)
		self.assertIn("iwsr-ws-sticky-header-cell", script)
		self.assertIn("translateX(\" + scroll_left + \"px)", script)
		self.assertIn("scroll.iwsr_ws_sticky_columns", script)
		self.assertIn(".iwsr-ws-table .dt-cell--col-0{position:sticky;left:0", script)
		self.assertIn(".dt-scrollable__no-data", script)
		self.assertIn("datatable.bodyRenderer.renderFooter()", script)
		self.assertIn("iwsr_ws_last_scroll_left", script)
		self.assertIn("iwsr_ws_refresh_sticky_columns", script)
		self.assertIn('options: "All\\nDirect Items\\nPacked Items"', script)

	def test_prepared_filter_reader_accepts_owned_completed_report(self):
		prepared = type("Prepared", (object,), {
			"report_name": "Item-wise Sales Register WS",
			"status": "Completed", "owner": "user@example.com"
		})()
		with patch.object(report, "frappe") as frappe_mock:
			frappe_mock.session.user = "user@example.com"
			frappe_mock.db.get_value.side_effect = [prepared, '{"company":"WS"}']
			frappe_mock.parse_json.side_effect = json.loads
			result = report.get_prepared_report_filters("REP-00001")
		self.assertEqual(result, {"company": "WS"})


if __name__ == "__main__":
	unittest.main()
