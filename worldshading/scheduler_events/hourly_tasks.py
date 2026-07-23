import frappe
from datetime import timedelta

def assign_unpaid_invoices():

    # --------------------------------------------------
    # Get Settings
    # --------------------------------------------------
    settings = frappe.get_single("WS Settings")

    if not settings.enable_unpaid_invoice_assign:
        return

    # Get users from settings
    user_list = [d.user for d in settings.users_to_assign if d.user]

    if not user_list:
        return

    # --------------------------------------------------
    # Time window (SAFE)
    # --------------------------------------------------
    now = frappe.utils.now_datetime()

    from_time = now - timedelta(hours=24)
    to_time = now - timedelta(hours=24)

    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "outstanding_amount": (">", 0),
            "grand_total": (">", 0),
            "creation": ("between", [from_time, to_time])
        },
        fields=["name"]
    )

    if not invoices:
        return

    # --------------------------------------------------
    # Process each invoice
    # --------------------------------------------------
    for inv in invoices:

        # Check if already assigned by system
        existing = frappe.get_all(
            "ToDo",
            filters={
                "reference_type": "Sales Invoice",
                "reference_name": inv.name,
                "assigned_by": "Administrator",
                "status": "Open"
            },
            limit=1
        )

        if existing:
            continue

        # Assign to configured users
        for user in user_list:
            frappe.get_doc({
                "doctype": "ToDo",
                "owner": user,
                "assigned_by": "Administrator",
                "description": "Unpaid Sales Invoice (24h): " + inv.name,
                "reference_type": "Sales Invoice",
                "reference_name": inv.name,
                "status": "Open",
                "priority": "Medium"
            }).insert(ignore_permissions=True)