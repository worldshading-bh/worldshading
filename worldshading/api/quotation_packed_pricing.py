from __future__ import unicode_literals

import frappe
from frappe.utils import flt


WARRANTY_ITEM = "QC7026"
WARRANTY_PERCENT = 0.15


def apply_quotation_packed_pricing(doc, method=None, show_messages=True):
    """Prepared replacement for the packed-pricing Server Script.

    This function is intentionally not connected to hooks yet.
    """
    if doc.get("doctype") != "Quotation":
        return

    messages = []
    packed_totals = _set_packed_item_prices(doc)

    if doc.get("auto_parent_price_calculation"):
        messages.extend(_set_custom_bundle_parent_prices(doc, packed_totals))

    _set_warranty_price(doc, messages)
    doc.calculate_taxes_and_totals()

    if show_messages and messages:
        frappe.msgprint(
            "<br><br>".join(messages),
            title="Price Calculation Summary"
        )


def _set_packed_item_prices(doc):
    price_cache = {}
    packed_totals = {}
    overall_total = 0

    for row in doc.get("packed_items") or []:
        if not row.get("item_code") or not row.get("parent_item"):
            continue

        cache_key = (row.item_code, row.get("uom"))
        if cache_key not in price_cache:
            price_cache[cache_key] = _get_item_price(
                row.item_code,
                doc.get("selling_price_list"),
                row.get("uom")
            )

        rate = price_cache[cache_key]
        qty = flt(row.get("qty"))
        amount = flt(rate * qty, 3)
        row.rate = rate
        row.amount = amount

        packed_totals[row.parent_item] = (
            packed_totals.get(row.parent_item, 0) + amount
        )
        overall_total += amount

    doc.total_selling_price = flt(overall_total, 3)
    return packed_totals


def _set_custom_bundle_parent_prices(doc, packed_totals):
    grouped_items = {}
    bundle_cache = {}
    parent_price_cache = {}
    messages = []

    for row in doc.get("items") or []:
        if not row.get("item_code") or not flt(row.get("qty")):
            continue

        item_code = row.item_code
        if item_code not in bundle_cache:
            bundle_cache[item_code] = bool(frappe.get_all(
                "Product Bundle",
                filters={
                    "new_item_code": item_code,
                    "disabled": 0,
                    "custom_project_logic": 1
                },
                limit=1
            ))

        if not bundle_cache[item_code]:
            continue

        grouped_items.setdefault(
            item_code,
            {"rows": [], "total_qty": 0}
        )
        grouped_items[item_code]["rows"].append(row)
        grouped_items[item_code]["total_qty"] += flt(row.qty)

    for item_code, data in grouped_items.items():
        total_qty = flt(data["total_qty"])
        if not total_qty:
            continue

        if item_code not in parent_price_cache:
            parent_price_cache[item_code] = _get_item_price(
                item_code,
                doc.get("selling_price_list"),
                None
            )

        parent_price = parent_price_cache[item_code]
        parent_total = parent_price * total_qty
        packed_total = flt(packed_totals.get(item_code))
        unit_rate = flt((packed_total + parent_total) / total_qty, 3)

        for row in data["rows"]:
            _apply_service_rate(row, unit_rate)

        messages.append(
            "Item <b>{0}</b>:<br>"
            "Packed Items Total = <b>{1}</b><br>"
            "Parent Price x Total Qty = <b>{2} x {3} = {4}</b><br>"
            "Unit Price = ({1} + {4}) / {3} = <b>{5}</b>".format(
                item_code,
                flt(packed_total, 3),
                flt(parent_price, 3),
                total_qty,
                flt(parent_total, 3),
                unit_rate
            )
        )

    return messages


def _apply_service_rate(row, unit_rate):
    """Represent a calculated service rate as margin, not negative discount."""
    price_list_rate = flt(row.get("price_list_rate"))
    margin_amount = unit_rate - price_list_rate

    if price_list_rate and margin_amount:
        row.margin_type = "Amount"
        row.margin_rate_or_amount = margin_amount
        row.rate_with_margin = unit_rate
    else:
        row.margin_type = None
        row.margin_rate_or_amount = 0
        row.rate_with_margin = 0

    row.discount_percentage = 0
    row.discount_amount = 0
    row.rate = unit_rate
    row.amount = flt(unit_rate * flt(row.get("qty")), 3)


def _set_warranty_price(doc, messages):
    total_amount = 0
    warranty_row = None

    for row in doc.get("items") or []:
        if not row.get("item_code"):
            continue
        if row.item_code == WARRANTY_ITEM:
            warranty_row = row
            continue
        total_amount += flt(row.get("amount"))

    if not warranty_row or total_amount <= 0:
        return

    warranty_amount = flt(total_amount * WARRANTY_PERCENT, 3)
    warranty_row.qty = 1
    _apply_service_rate(warranty_row, warranty_amount)

    messages.append(
        "<b>Warranty Updated</b><br>"
        "Warranty calculated as <b>15%</b> of total items value.<br><br>"
        "<b>Total Base Amount:</b> {0}<br>"
        "<b>Warranty Amount:</b> {1}".format(
            flt(total_amount, 3),
            warranty_amount
        )
    )


def _get_item_price(item_code, price_list, uom=None):
    rate = _find_item_price(item_code, price_list, uom)
    if rate is not None:
        return flt(rate)

    regular_price_list = frappe.db.get_single_value(
        "Selling Settings",
        "selling_price_list"
    )
    if regular_price_list and regular_price_list != price_list:
        rate = _find_item_price(item_code, regular_price_list, uom)
        if rate is not None:
            return flt(rate)

    attempted_price_lists = price_list
    if regular_price_list and regular_price_list != price_list:
        attempted_price_lists = "{0}, {1} (fallback)".format(
            price_list,
            regular_price_list
        )

    frappe.throw(
        "No Item Price found for <b>{0}</b><br>"
        "UOM: {1}<br>"
        "Price List: {2}".format(
            item_code,
            uom or "-",
            attempted_price_lists
        )
    )


def _find_item_price(item_code, price_list, uom=None):
    filters = {
        "item_code": item_code,
        "price_list": price_list,
        "selling": 1
    }
    if uom:
        filters["uom"] = uom

    rate = frappe.db.get_value("Item Price", filters, "price_list_rate")
    if rate is None and uom:
        filters.pop("uom")
        rate = frappe.db.get_value("Item Price", filters, "price_list_rate")

    return rate
