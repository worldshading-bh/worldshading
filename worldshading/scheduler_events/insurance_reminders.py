import frappe
from frappe.utils import today, add_days

def create_insurance_todos():
    print("🔔 [Insurance ToDo Scheduler] Starting task...")

    # Step 1: Get all valid enabled users with role "Senior Accountant"
    role_users = frappe.get_all("Has Role", filters={"role": "Senior Accountant"}, fields=["parent"])
    valid_users = frappe.get_all("User", filters={"enabled": 1}, fields=["name"])
    valid_users = [u["name"] for u in valid_users]

    user_list = [
        user["parent"]
        for user in role_users
        if user["parent"] in valid_users and user["parent"] not in ("Administrator", "Guest")
    ]

    if not user_list:
        msg = "❌ No users found with role: Senior Accountant"
        frappe.log_error(msg, "Insurance ToDo Script")
        print(msg)
        return

    print(f"👤 Found {len(user_list)} users with role 'Senior Accountant': {user_list}")

    # Step 2: Find vehicles whose insurance is expiring in next 10 days
    vehicles = frappe.get_all("Vehicle", 
        filters={
            "end_date": ["between", [today(), add_days(today(), 10)]]
        },
        fields=["name", "end_date"]
    )

    if not vehicles:
        print("ℹ️ No vehicles found with insurance ending in the next 10 days.")
        return

    print(f"🚗 Found {len(vehicles)} vehicles with upcoming insurance expiry.")

    created_count = 0

    for vehicle in vehicles:
        for user in user_list:
            # Check if a similar ToDo already exists for this user and vehicle
            existing = frappe.get_all("ToDo", filters={
                "reference_type": "Vehicle",
                "reference_name": vehicle.name,
                "status": "Open",
                "owner": user,
                "description": ["like", "%Insurance Expiry%"]
            })

            if not existing:
                # Create a new ToDo
                todo = frappe.get_doc({
                    "doctype": "ToDo",
                    "owner": user,  # Allocated To
                    "assigned_by": "Administrator",  # Assigned By fixed
                    "description": f"""<b>Vehicle Insurance Expiry Reminder:</b> 
                        <a href="/desk#Form/Vehicle/{vehicle.name}">{vehicle.name}</a> 
                        insurance ends on <b>{vehicle.end_date}</b>.""",
                    "reference_type": "Vehicle",
                    "reference_name": vehicle.name,
                    "date": vehicle.end_date,
                    "priority": "High"
                })
                todo.insert(ignore_permissions=True)
                print(f"✅ Created ToDo for user '{user}' - Vehicle: {vehicle.name}")
                created_count += 1
            else:
                print(f"⚠️ Skipped duplicate ToDo for user '{user}' - Vehicle: {vehicle.name}")

    if created_count:
        print(f"🎯 Done. Created {created_count} new ToDos.")
    else:
        print("✔️ Script finished. No new ToDos needed today.")

    frappe.db.commit()



