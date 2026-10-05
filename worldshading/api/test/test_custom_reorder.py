# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from worldshading import custom_reorder


class MemoryRequest(object):
    """Capture request contents without accessing a site or saving documents."""

    def __init__(self):
        self.flags = frappe._dict()
        self.from_items = []
        self.items = []
        self.name = "TEST-MR"
        self.docstatus = 0

    def update(self, values):
        self.__dict__.update(values)

    def append(self, field, values):
        getattr(self, field).append(frappe._dict(values))

    def insert(self):
        return self

    def submit(self):
        self.docstatus = 1


class TestProductionReorderSource(unittest.TestCase):
    def run_reorder(self, request_type, warehouse, source, stock):
        rule = frappe._dict({
            "from_item": [frappe._dict(item_code="RAW", qty=1, uom="Roll")],
            "to_item": [frappe._dict(item_code="FINISHED", qty=25, uom="Meter")]
        })

        def get_value(doctype, name, field):
            if doctype == "Warehouse" and field == "production_source_warehouse":
                self.assertEqual(name, warehouse)
                return source
            if doctype == "Bin" and field == "actual_qty":
                return stock.get((name["item_code"], name["warehouse"]), 0)
            if doctype == "Stock Settings" and field == "reorder_email_notify":
                return 0
            raise AssertionError("Unexpected database read")

        def get_doc(doctype, name):
            if doctype == "Repack Production Rule" and name == "TEST-RULE":
                return rule
            if doctype == "Item" and name == "FINISHED":
                return frappe._dict(item_name="Finished", description="Finished",
                                    item_group="Products", brand=None)
            raise AssertionError("Unexpected document read")

        def get_all(doctype, filters):
            self.assertEqual(doctype, "Repack Production Rule")
            self.assertEqual(filters, {"type": request_type})
            return [frappe._dict(name="TEST-RULE")]

        def new_doc(doctype):
            self.assertEqual(doctype, "Material Request")
            return MemoryRequest()

        def fail_on_error(traceback):
            raise AssertionError(traceback)

        fake_frappe = SimpleNamespace(
            _dict=frappe._dict, db=SimpleNamespace(get_value=get_value),
            get_all=get_all, get_doc=get_doc, new_doc=new_doc,
            local=SimpleNamespace(message_log=[]),
            get_traceback=frappe.get_traceback, log_error=fail_on_error)
        with patch.object(custom_reorder, "frappe", fake_frappe), \
                patch.object(custom_reorder, "nowdate", return_value="2026-10-03"), \
                patch.object(custom_reorder, "get_item_details", return_value={}), \
                redirect_stdout(io.StringIO()):
            return custom_reorder.create_material_request({request_type: {
                "Test Company": [{"item_code": "FINISHED", "warehouse": warehouse,
                                  "reorder_qty": 50}]
            }})

    def test_production_uses_configured_source_and_preserves_batches(self):
        for warehouse in ("Production - Ras Zuwayed - WS", "Renamed Production - WS"):
            with self.subTest(warehouse=warehouse):
                requests = self.run_reorder("Production", warehouse, "Raw Store",
                                            {("RAW", "Raw Store"): 10})
                self.assertEqual(len(requests), 2)
                for request in requests:
                    self.assertEqual(request.from_items[0].warehouse, "Raw Store")
                    self.assertEqual(request.from_items[0].qty, 1)
                    self.assertEqual(request.items[0].warehouse, warehouse)
                    self.assertEqual(request.items[0].qty, 25)
                    self.assertEqual(request.docstatus, 1)

    def test_production_without_source_skips_even_when_stock_exists(self):
        for source in (None, ""):
            with self.subTest(source=source):
                requests = self.run_reorder("Production", "Production Store", source,
                                            {("RAW", "Production Store"): 10})
                self.assertEqual(requests, [])

    def test_production_does_not_fall_back_to_old_hardcoded_mapping(self):
        requests = self.run_reorder("Production", "Production Salmabad - WS", None,
                                    {("RAW", "Salmabad Showroom - WS"): 10})
        self.assertEqual(requests, [])

    def test_production_still_skips_unavailable_source_stock(self):
        for qty in (0, -1):
            with self.subTest(qty=qty):
                requests = self.run_reorder("Production", "Production Store", "Raw Store",
                                            {("RAW", "Raw Store"): qty,
                                             ("RAW", "Production Store"): 10})
                self.assertEqual(requests, [])

    def test_repack_keeps_same_warehouse_and_combined_quantity(self):
        requests = self.run_reorder("Repack", "Showroom", "Other Store",
                                    {("RAW", "Showroom"): 10})
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].from_items[0].warehouse, "Showroom")
        self.assertEqual(requests[0].from_items[0].qty, 2)
        self.assertEqual(requests[0].items[0].warehouse, "Showroom")
        self.assertEqual(requests[0].items[0].qty, 50)
        self.assertEqual(requests[0].docstatus, 1)


if __name__ == "__main__":
    unittest.main()
