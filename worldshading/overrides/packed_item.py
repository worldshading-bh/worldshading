import frappe
from frappe.utils import flt
from erpnext.stock.doctype.packed_item.packed_item import update_packing_list_item, get_product_bundle_items, cleanup_packing_list

def make_packing_list(doc):
    """make packing list for Product Bundle item"""

    if doc.get("_action") and doc._action == "update_after_submit":
        return

    parent_items = []
    for d in doc.get("items"):
        # ✅ Skip disabled Product Bundles
        bundle = frappe.db.get_value("Product Bundle", {"new_item_code": d.item_code}, ["name", "disabled"], as_dict=True)
        if not bundle or bundle.disabled:
            continue

        for i in get_product_bundle_items(d.item_code):
            update_packing_list_item(doc, i.item_code, flt(i.qty) * flt(d.stock_qty), d, i.description)

        if [d.item_code, d.name] not in parent_items:
            parent_items.append([d.item_code, d.name])

    cleanup_packing_list(doc, parent_items)




