# Add todo to GM on cancel
# Add todo to GM on cancel
import frappe

def assign_to_gm_on_cancel(doc, method):
    target_user = "hussainaljad@worldshading.com"
    current_user = frappe.session.user or "Administrator"

    # Skip if GM is the one who cancelled
    if current_user == target_user:
        return

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
        "assigned_by": current_user,
        "reference_type": doc.doctype,
        "reference_name": doc.name,
        "description": f"🛑 Cancelled - {doc.doctype} : {doc.name} by {current_user}",
        "status": "Open",
        "priority": "Medium",
    }).insert(ignore_permissions=True)


