from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import get_link_to_form


def validate_new_item_price(doc, method=None):
    if not doc.is_new():
        return

    filters = {"item_code": doc.item_code, "price_list": doc.price_list}
    # Preserve the native optional-field matching, but disregard validity dates.
    for field in ("uom", "packing_unit", "customer", "supplier"):
        if doc.get(field):
            filters[field] = doc.get(field)

    matches = frappe.get_all("Item Price", filters=filters,
        fields=["name"], limit_page_length=1)
    if matches:
        frappe.throw(_(
            "Item Price {0} already exists for this combination. "
            "Different validity dates do not allow a duplicate. "
            "Update the existing Item Price instead."
        ).format(get_link_to_form("Item Price", matches[0].name)))
