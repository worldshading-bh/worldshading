import frappe
from frappe.utils import today, add_days, getdate

def assign_overdue_sales_orders():
    """Assign ToDos for overdue Sales Orders (after 2025-09-01, with 1-day tolerance).
       - Normal overdue (no invoice) → assign to Sales Employee (or SO owner)
       - If overdue >= 7 days:
            • If delivery_later = 1 → assign to Inventory Controller (Mr. Alboori)
            • Else → escalate to Accounts (Mr. Manu)
    """

    cutoff_date = getdate(add_days(today(), -2))  # overdue tolerance: day before yesterday
    start_date = getdate("2025-10-01")            # ignore older SOs

    print(f"🔎 Checking Sales Orders with {start_date} <= delivery_date <= {cutoff_date}")

    so_list = frappe.get_all(
        "Sales Order",
        filters={
            "docstatus": 1,
            "status": ["!=", "Closed"],
            "per_delivered": ["<", 100],
            "delivery_date": ["between", [start_date, cutoff_date]]
        },
        fields=["name", "owner", "pb_sales_employee", "delivery_date", "per_billed", "delivery_later"]
    )

    print(f"👉 Found {len(so_list)} overdue Sales Orders in range")

    escalated = 0
    normal = 0
    skipped = 0

    for so in so_list:
        so_date = getdate(so.delivery_date)  # ✅ ensure date object

        # Escalation: if overdue 7+ days
        if so_date <= getdate(add_days(today(), -7)):
            if so.delivery_later:   # ✅ check the correct field
                assignee = "inventory.controller@worldshading.com"
                description = (f"🚨 Escalated to Inventory Controller: Sales Order {so.name} "
                               f"is overdue more than 7 days and still pending delivery (delivery_later=1).")
                print(f"⚠️ Escalation: SO {so.name} → Assigned to Inventory Controller ({assignee})")
            else:
                assignee = "manu@worldshading.com"
                description = (f"🚨 Escalated to Accounts: Sales Order {so.name} "
                               f"is overdue more than 7 days (delivery_later=0).")
                print(f"⚠️ Escalation: SO {so.name} → Assigned to Accounts ({assignee})")
            escalated += 1

        else:
            # Skip salesman assignment if invoiced
            if so.per_billed and so.per_billed > 0:
                print(f"⏩ Skipping SO {so.name}, already invoiced ({so.per_billed}%).")
                skipped += 1
                continue

            # Normal overdue → assign to Salesman
            assignee = None
            if so.pb_sales_employee:
                user_id = frappe.db.get_value("Employee", so.pb_sales_employee, "user_id")
                if user_id:
                    assignee = user_id
            if not assignee:
                assignee = so.owner

            description = (f"⚠️ Sales Order {so.name} is overdue "
                           f"(delivery date {so.delivery_date}). Please re-evaluate.")
            print(f"➡️ Processing SO {so.name} | Delivery Date: {so.delivery_date} | Assigned to: {assignee}")
            normal += 1

        # Close existing open ToDos for this SO
        todos = frappe.get_all(
            "ToDo",
            filters={"reference_type": "Sales Order", "reference_name": so.name, "status": "Open"},
            fields=["name"]
        )
        for t in todos:
            frappe.db.set_value("ToDo", t.name, "status", "Closed")
            print(f"🛑 Closed old ToDo {t.name} for SO {so.name}")

        # Create new ToDo
        todo = frappe.get_doc({
            "doctype": "ToDo",
            "owner": assignee,
            "assigned_by": "Administrator",
            "allocated_to": assignee,
            "reference_type": "Sales Order",
            "reference_name": so.name,
            "description": description,
            "status": "Open",
            "priority": "High"
        })
        todo.insert(ignore_permissions=True)
        frappe.db.commit()

        print(f"✅ Assigned SO {so.name} to {assignee}")

    print(f"🎯 Completed: {len(so_list)} SOs processed → {normal} normal, {escalated} escalated, {skipped} skipped (already invoiced)")
