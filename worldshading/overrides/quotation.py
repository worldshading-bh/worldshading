from __future__ import unicode_literals

import frappe


def cleanup_abandoned_packed_items(doc, method=None):
    """Remove packed items whose parent item row no longer exists."""
    if not doc.get("packed_items"):
        return

    parent_items = set()
    parent_item_rows = {}

    for item in doc.get("items") or []:
        if item.item_code and item.name:
            parent_items.add((item.item_code, item.name))
            parent_item_rows.setdefault(item.item_code, item.name)

    cleaned_packed_items = []
    removed_parent_items = []

    for packed_item in doc.get("packed_items") or []:
        parent_key = (
            packed_item.parent_item,
            packed_item.parent_detail_docname
        )

        if parent_key not in parent_items:
            parent_detail_docname = parent_item_rows.get(packed_item.parent_item)

            if parent_detail_docname:
                packed_item.parent_detail_docname = parent_detail_docname
                parent_key = (packed_item.parent_item, parent_detail_docname)

        if parent_key in parent_items:
            row = packed_item.as_dict()
            for fieldname in ("name", "parent", "parentfield", "parenttype", "idx"):
                row.pop(fieldname, None)
            cleaned_packed_items.append(row)
        else:
            removed_parent_items.append(packed_item.parent_item)

    if len(cleaned_packed_items) != len(doc.get("packed_items") or []):
        doc.set("packed_items", [])

        for idx, row in enumerate(cleaned_packed_items, start=1):
            packed_item = doc.append("packed_items", row)
            packed_item.idx = idx

        frappe.msgprint(
            "Removed packed items for {0}".format(
                ", ".join(sorted(set(removed_parent_items)))
            )
        )
