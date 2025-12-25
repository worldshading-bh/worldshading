# -*- coding: utf-8 -*- 
# not using now, consolidated wuth the quotation followup


import frappe
from frappe.utils import nowdate

# change assignees as needed
ASSIGNEES = [
    "hussainaljad@worldshading.com",
    "Shakeel.worldshading@gmail.com",
]

def _make_todos_for(quotation_name, owners):
    """Create ToDos for given quotation & owners (skip duplicates)."""
    for user_email in owners:
        # skip if there's already an open ToDo for this user & quotation
        dup = frappe.get_all(
            "ToDo",
            filters={
                "reference_type": "Quotation",
                "reference_name": quotation_name,
                "owner": user_email,
                "status": "Open",
                "assigned_by": "Administrator",
            },
            limit=1,
        )
        if dup:
            print(f"⚠️ Skipped: ToDo already exists for {user_email} on Quotation {quotation_name}")
            continue

        quotation = frappe.get_doc("Quotation", quotation_name)

        todo = frappe.get_doc({
            "doctype": "ToDo",
            "owner": user_email,
            "assigned_by": "Administrator",
            "reference_type": "Quotation",
            "reference_name": quotation_name,
            "description": f"Quotation expired: {quotation.name} for {quotation.customer_name}. Please follow up.",
            "status": "Open",
            "priority": "Medium",
        })
        todo.insert(ignore_permissions=True)




def run(limit=50):
    """Scheduled job: find quotations that expired today and create ToDos once."""
    today = nowdate()
    yesterday = frappe.utils.add_days(today, -1)


    expired = frappe.get_all(
        "Quotation",
        filters={
            "docstatus": 1,
            "valid_till": yesterday,
            "status": ["not in", ["Ordered", "Cancelled"]],
        },
        fields=["name"],
        limit=limit,
    )

    quotation_names = [d.name for d in expired]

    if not quotation_names:

        return



    for q in quotation_names:
        _make_todos_for(q, ASSIGNEES)


