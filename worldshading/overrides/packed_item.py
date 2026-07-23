import frappe
from frappe.utils import flt
from erpnext.stock.doctype.packed_item.packed_item import (
    update_packing_list_item, get_product_bundle_items, cleanup_packing_list
)

def make_packing_list(doc):
    """Create packing list with optional custom project logic based on Product Bundle settings."""
    # frappe.msgprint("🔁 Creating Packing List...worldshading override...")

    if doc.doctype == "Delivery Note":
        doc.set("packed_items", [])
        return

    if doc.get("_action") == "update_after_submit":
        return

    parent_items = []
    processed_items = set()  # To track processed item_codes for custom logic

    for d in doc.get("items"):
        # 🔍 Check if Product Bundle exists and is enabled
        bundle = frappe.db.get_value("Product Bundle", {"new_item_code": d.item_code}, ["name", "disabled", "custom_project_logic"], as_dict=True)
        if not bundle or bundle.disabled:
            continue

        if bundle.custom_project_logic:
            # ✅ Custom Logic: Add only 1 set of packed items (fixed qty)
            if d.item_code in processed_items:
                continue  # Skip duplicate parent
            for i in get_product_bundle_items(d.item_code):
                update_packing_list_item(doc, i.item_code, flt(i.qty), d, i.description)
            processed_items.add(d.item_code)
        else:
            # 🔁 Default Logic: Multiply by parent qty (like standard ERPNext)
            for i in get_product_bundle_items(d.item_code):
                update_packing_list_item(doc, i.item_code, flt(i.qty) * flt(d.stock_qty), d, i.description)

        parent_items.append([d.item_code, d.name])

    # 🧹 Clean up old packed items no longer linked
    cleanup_packing_list(doc, parent_items)


# Proposed version for review only.
# This keeps one packed item set per repeated custom parent item code,
# but multiplies packed item qty by the number of parent item occurrences.
#
# def make_packing_list(doc):
#     """Create packing list with optional custom project logic based on Product Bundle settings."""

#     if doc.doctype == "Delivery Note":
#         doc.set("packed_items", [])
#         return

#     if doc.get("_action") == "update_after_submit":
#         return

#     parent_items = []
#     processed_items = set()
#     custom_parent_counts = {}

#     for d in doc.get("items"):
#         bundle = frappe.db.get_value(
#             "Product Bundle",
#             {"new_item_code": d.item_code},
#             ["name", "disabled", "custom_project_logic"],
#             as_dict=True
#         )

#         if not bundle or bundle.disabled or not bundle.custom_project_logic:
#             continue

#         custom_parent_counts[d.item_code] = custom_parent_counts.get(d.item_code, 0) + 1

#     for d in doc.get("items"):
#         bundle = frappe.db.get_value(
#             "Product Bundle",
#             {"new_item_code": d.item_code},
#             ["name", "disabled", "custom_project_logic"],
#             as_dict=True
#         )

#         if not bundle or bundle.disabled:
#             continue

#         if bundle.custom_project_logic:
#             if d.item_code in processed_items:
#                 continue

#             occurrence_count = custom_parent_counts.get(d.item_code, 1)

#             for i in get_product_bundle_items(d.item_code):
#                 update_packing_list_item(
#                     doc,
#                     i.item_code,
#                     flt(i.qty) * flt(occurrence_count),
#                     d,
#                     i.description
#                 )

#             processed_items.add(d.item_code)
#         else:
#             for i in get_product_bundle_items(d.item_code):
#                 update_packing_list_item(doc, i.item_code, flt(i.qty) * flt(d.stock_qty), d, i.description)

#         parent_items.append([d.item_code, d.name])

#     cleanup_packing_list(doc, parent_items)
