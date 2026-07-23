
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

    # 📦 Build multi-user map (FIXED)
    assign_map = {}
    for d in settings.doctypes:
        assign_map.setdefault(d.target_doctype, []).append(d.assign_to)

    # ❌ Exit if this doctype is not listed
    if doc.doctype not in assign_map:
        return

    target_users = assign_map[doc.doctype]
    current_user = frappe.session.user or "Administrator"

    # ✅ Close existing open ToDos (using db.set_value)
    existing_todos = frappe.get_all("ToDo", filters={
        "reference_type": doc.doctype,
        "reference_name": doc.name,
        "status": "Open"
    }, fields=["name"])

    for todo in existing_todos:
        frappe.db.set_value("ToDo", todo.name, "status", "Closed")

    # ➕ Create new ToDos for all users
    for target_user in target_users:
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