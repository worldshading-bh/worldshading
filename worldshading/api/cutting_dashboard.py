# -*- coding: utf-8 -*-
"""Read-only data API for the workshop Cutting Dashboard."""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime
from frappe.core.doctype.user_permission.user_permission import get_user_permissions


PENDING_CUTTING_STATE = "Pending Cutting"
ALLOWED_ROLES = (
    "System Manager",
    "Workshop (workflow)",
    "Manufacturing Manager",
    "Manufacturing User",
    "Sales Manager",
    "Sales User",
    "Accounts Manager",
    "Accounts User",
    "Cashier",
)


@frappe.whitelist()
def get_cutting_dashboard():
    """Return Pending Cutting invoices and their display-safe item details.

    This endpoint is deliberately read-only. Warehouse filtering comes from
    the logged-in user's Warehouse User Permissions.
    """
    _require_access()
    permitted_warehouses = _get_permitted_warehouses()
    cutting_item_codes = _get_cutting_item_codes()
    invoices = _get_pending_invoices()
    invoice_names = [row.name for row in invoices]

    visible_items_by_invoice = {}
    cutting_items_by_invoice = {}
    if invoice_names:
        items = frappe.get_all(
            "Sales Invoice Item",
            filters={"parent": ["in", invoice_names]},
            fields=[
                "name", "parent", "idx", "item_code", "item_name", "qty", "uom",
                "stock_uom", "warehouse",
            ],
            order_by="parent asc, idx asc",
            limit_page_length=0,
        )

        invoice_warehouse = dict((row.name, row.set_warehouse) for row in invoices)
        for item in items:
            item.warehouse = item.warehouse or invoice_warehouse.get(item.parent)
            if permitted_warehouses is not None and item.warehouse not in permitted_warehouses:
                continue
            item.qty = flt(item.qty)
            visible_items_by_invoice.setdefault(item.parent, []).append(item)
            if item.item_code in cutting_item_codes:
                cutting_items_by_invoice.setdefault(item.parent, []).append(item)

    jobs = []
    unconfigured_jobs = []
    for invoice in invoices:
        visible_items = visible_items_by_invoice.get(invoice.name, [])
        if not visible_items:
            continue
        invoice_items = cutting_items_by_invoice.get(invoice.name, [])

        if not invoice_items:
            unconfigured_jobs.append({
                "name": invoice.name,
                "delivery_date": invoice.delivery_date,
                "pending_since": invoice.modified,
            })
            continue

        jobs.append({
            "name": invoice.name,
            "delivery_date": invoice.delivery_date,
            "pending_since": invoice.modified,
            "items": invoice_items,
            "item_count": len(invoice_items),
        })

    jobs.sort(key=lambda row: (
        str(row.get("delivery_date") or "9999-12-31"),
        str(row.get("pending_since") or "9999-12-31 23:59:59"),
        row.get("name") or "",
    ))
    unconfigured_jobs.sort(key=lambda row: (
        str(row.get("delivery_date") or "9999-12-31"),
        str(row.get("pending_since") or "9999-12-31 23:59:59"),
        row.get("name") or "",
    ))

    return {
        "jobs": jobs,
        "unconfigured_jobs": unconfigured_jobs,
        "total_jobs": len(jobs),
        "total_invoices": len(jobs) + len(unconfigured_jobs),
        "total_items": sum([job["item_count"] for job in jobs]),
        "unconfigured_count": len(unconfigured_jobs),
        "warehouse_names": sorted(list(permitted_warehouses or [])),
        "server_time": now_datetime(),
        "refresh_seconds": 30,
    }


def _get_pending_invoices():
    fields = [
        "name", "delivery_date", "modified", "set_warehouse", "workflow_state_",
    ]
    return frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": ["<", 2],
            "is_return": 0,
            "workflow_state_": PENDING_CUTTING_STATE,
        },
        fields=fields,
        order_by="modified asc",
        limit_page_length=0,
    )


def _get_cutting_item_codes():
    """Return item codes configured by a rule or explicitly enabled on Item."""
    target_items = frappe.get_all(
        "Target Item",
        filters={
            "parenttype": "Repack Production Rule",
            "parentfield": "to_item",
        },
        fields=["item_code"],
        limit_page_length=0,
    )
    cutting_item_codes = set([
        row.item_code for row in target_items if row.item_code
    ])

    enabled_items = frappe.get_all(
        "Item",
        filters={"show_in_cutting_dashboard": 1},
        fields=["name"],
        limit_page_length=0,
    )
    cutting_item_codes.update([
        row.name for row in enabled_items if row.name
    ])
    return cutting_item_codes


def _get_permitted_warehouses():
    """Return allowed warehouses, or None when the user has no restriction."""
    if frappe.session.user == "Administrator":
        return None
    permissions = get_user_permissions(frappe.session.user).get("Warehouse", [])
    warehouses = set([
        permission.get("doc") for permission in permissions
        if permission.get("doc") and permission.get("applicable_for") in (None, "Sales Invoice")
    ])
    return warehouses if warehouses else None


def _require_access():
    if frappe.session.user == "Guest":
        frappe.throw(_("Please sign in to view the Cutting Dashboard."), frappe.PermissionError)
    if frappe.session.user == "Administrator":
        return
    roles = frappe.get_roles(frappe.session.user)
    if not any(role in roles for role in ALLOWED_ROLES):
        frappe.throw(_("You do not have access to the Cutting Dashboard."), frappe.PermissionError)
