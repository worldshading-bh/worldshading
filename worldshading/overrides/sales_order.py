from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.utils import flt
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list as core_make_packing_list

def validate(doc, method):
    frappe.msgprint("🔁 Validating Sales Order...worldshading override")
    update_current_stock(doc)
    custom_after_save(doc, method)  # <-- manually call it here
    calculate_packed_item_pricing(doc)

def custom_after_save(doc, method):
    if doc.is_new():
        if any(item.prevdoc_docname for item in doc.items):
            frappe.msgprint("📦 First Save with Quotation → Pulling packed items from Quotation")
            pull_packed_items_from_quotation(doc)
        else:
            frappe.msgprint("📦 First Save without Quotation → Pulling from Product Bundle")
            core_make_packing_list(doc)
    else:
        for item in doc.items:
            if not any(d.parent_item == item.item_code for d in doc.get("packed_items", [])):
                frappe.msgprint(f"📦 Later Save → New item {item.item_code} detected → Pulling from Product Bundle")
                core_make_packing_list(doc)
                break


def pull_packed_items_from_quotation(doc):
    doc.set("packed_items", [])
    for item in doc.items:
        if item.prevdoc_docname:
            quotation = frappe.get_doc("Quotation", item.prevdoc_docname)
            for packed_item in quotation.get("packed_items", []):
                doc.append("packed_items", {
                    "parent_item": item.item_code,
                    "item_code": packed_item.item_code,
                    "item_name": packed_item.item_name,
                    "qty": packed_item.qty,
                    "description": packed_item.description,
                    "uom": packed_item.uom or "Nos",
                    "rate": packed_item.rate or 0,
                    "amount": packed_item.amount or 0
                })
    for i, row in enumerate(doc.packed_items, start=1):
        row.idx = i
    frappe.msgprint("🔁 Packed items added from Quotation.")

def update_current_stock(doc):
    if doc.get("packed_items"):
        for d in doc.packed_items:
            bin = frappe.db.sql("""
                SELECT actual_qty, projected_qty FROM `tabBin`
                WHERE item_code = %s AND warehouse = %s
            """, (d.item_code, d.warehouse), as_dict=True)
            d.actual_qty = flt(bin[0]["actual_qty"]) if bin else 0
            d.projected_qty = flt(bin[0]["projected_qty"]) if bin else 0

            if not d.parent_item:
                match = next((item.item_code for item in doc.items if item.item_code == d.item_code), None)
                d.parent_item = match or doc.items[0].item_code


def calculate_packed_item_pricing(doc):
    price_list = doc.selling_price_list
    total = 0

    for row in doc.get("packed_items") or []:
        if not row.item_code or not row.qty:
            continue

        # Use existing rate if present; otherwise, fetch it
        if row.rate:
            rate = flt(row.rate)
        else:
            rate = frappe.db.get_value("Item Price", {
                "item_code": row.item_code,
                "price_list": price_list,
                "selling": 1
            }, "price_list_rate") or 0
            row.rate = flt(rate)

        # Always update amount
        row.amount = flt(rate) * flt(row.qty)
        total += row.amount

    # 🔢 Set total_selling_price at document level
    doc.total_selling_price = total



