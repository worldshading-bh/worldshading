# worldshading/events/material_request_event.py

import frappe

def make_stock_qty_zero(doc, method):
    if hasattr(doc, "from_items"):
        for d in doc.from_items:
            d.stock_qty = 0
