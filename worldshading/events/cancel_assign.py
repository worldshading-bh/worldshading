
# import frappe

# def assign_to_gm_on_cancel(doc, method):
#     target_user = "hussainaljad@worldshading.com"
#     current_user = frappe.session.user or "Administrator"

#     # Skip if GM is the one who cancelled
#     if current_user == target_user:
#         return

#     # Close existing open ToDos for this document
#     existing_todos = frappe.get_all("ToDo", filters={
#         "reference_type": doc.doctype,
#         "reference_name": doc.name,
#         "status": "Open"
#     }, fields=["name"])

#     for todo in existing_todos:
#         td = frappe.get_doc("ToDo", todo.name)
#         td.status = "Closed"
#         td.save(ignore_permissions=True)

#     # Create new ToDo for the GM
#     frappe.get_doc({
#         "doctype": "ToDo",
#         "owner": target_user,
#         "assigned_by": current_user,
#         "reference_type": doc.doctype,
#         "reference_name": doc.name,
#         "description": f"🛑 Cancelled - {doc.doctype} : {doc.name} by {current_user}",
#         "status": "Open",
#         "priority": "Medium",
#     }).insert(ignore_permissions=True)


import frappe

def assign_to_gm_on_cancel(doc, method):
    settings = frappe.get_single("Cancel ToDo Settings")

    # 🔁 Exit if global toggle is off
    if not settings.enable_todo_cancel:
        return

    # 📦 Build a map from the child table
    assign_map = {d.target_doctype: d.assign_to for d in settings.doctypes}
    
    # ❌ Exit if this doctype is not listed
    if doc.doctype not in assign_map:
        return

    target_user = assign_map[doc.doctype]
    current_user = frappe.session.user or "Administrator"

    # ⛔ Skip if target user is the one who cancelled
    if current_user == target_user:
        return

    # ✅ Close existing open ToDos
    existing_todos = frappe.get_all("ToDo", filters={
        "reference_type": doc.doctype,
        "reference_name": doc.name,
        "status": "Open"
    }, fields=["name"])

    for todo in existing_todos:
        td = frappe.get_doc("ToDo", todo.name)
        td.status = "Closed"
        td.save(ignore_permissions=True)

    # ➕ Create new ToDo
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
