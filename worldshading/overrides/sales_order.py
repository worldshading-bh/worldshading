from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.utils import flt
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list as core_make_packing_list

def validate(doc, method):
    update_current_stock(doc)
    custom_after_save(doc, method)  # <-- manually call it here
    calculate_packed_item_pricing(doc)

def custom_after_save(doc, method):
    if doc.is_new():
        if any(item.prevdoc_docname for item in doc.items):
            pull_packed_items_from_quotation(doc)
        else:
            core_make_packing_list(doc)
    else:
        for item in doc.items:
            if not any(d.parent_item == item.item_code for d in doc.get("packed_items", [])):
                #core_make_packing_list(doc)
                break


def pull_packed_items_from_quotation(doc):
    # 🧹 Clear existing packed items before adding
    doc.set("packed_items", [])

    processed_parents = set()  # ✅ Keep track of parent items already handled

    for item in doc.items:
        if not item.prevdoc_docname:
            continue

        # ✅ Avoid duplicate pulls for the same parent item
        if item.item_code in processed_parents:
            continue  

        quotation = frappe.get_doc("Quotation", item.prevdoc_docname)

        # ✅ Add only those packed items from Quotation which match the parent item
        for packed_item in quotation.get("packed_items", []):
            if packed_item.parent_item == item.item_code:  # 🔑 match only for this parent
                doc.append("packed_items", {
                    "parent_item": packed_item.parent_item,
                    "item_code": packed_item.item_code,
                    "item_name": packed_item.item_name,
                    "qty": packed_item.qty,
                    "description": packed_item.description,
                    "uom": packed_item.uom or "Nos",
                    "rate": packed_item.rate or 0,
                    "amount": packed_item.amount or 0
                })

        processed_parents.add(item.item_code)  # ✅ mark this parent as done

    # ✅ Re-index rows
    for i, row in enumerate(doc.packed_items, start=1):
        row.idx = i


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



