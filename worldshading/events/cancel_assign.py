# Add todo to GM on cancel
import frappe

def assign_to_gm_on_cancel(doc, method):
    target_user = "hussainaljad@worldshading.com"

    # Close existing open ToDos for this document
    existing_todos = frappe.get_all("ToDo", filters={
        "reference_type": doc.doctype,
        "reference_name": doc.name,
        "status": "Open"
    }, fields=["name"])

    for todo in existing_todos:
        td = frappe.get_doc("ToDo", todo.name)
        td.status = "Closed"
        td.save(ignore_permissions=True)
    # Create new ToDo for the GM
    frappe.get_doc({
        "doctype": "ToDo",
        "owner": target_user,
        "assigned_by": frappe.session.user if frappe.session.user else "Administrator",
        "reference_type": doc.doctype,
        "reference_name": doc.name,
        "description": f"🛑 Cancelled - {doc.doctype} : {doc.name} by {frappe.session.user}",
        "status": "Open",
        "priority": "Medium",
    }).insert(ignore_permissions=True)

