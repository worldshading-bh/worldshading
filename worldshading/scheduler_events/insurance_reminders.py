import frappe
from frappe.utils import today, add_days

def create_insurance_todos():

    # --------------------------------------------------
    # Get Settings
    # --------------------------------------------------
    settings = frappe.get_single("WS Settings")

    if not settings.enable_vehicle_insurance_reminder:
        return

    # --------------------------------------------------
    # Get users from settings
    # --------------------------------------------------
    valid_users = frappe.get_all("User", filters={"enabled": 1}, fields=["name"])
    valid_users = [u["name"] for u in valid_users]

    user_list = [
        d.user for d in settings.users_to_assign_vir
        if d.user in valid_users and d.user not in ("Administrator", "Guest")
    ]

    if not user_list:
        frappe.log_error(
            "No valid users found in WS Settings (Vehicle Insurance Reminder).",
            "Insurance ToDo Script"
        )
        return

    # --------------------------------------------------
    # Find vehicles whose insurance is expiring
    # --------------------------------------------------
    vehicles = frappe.get_all(
        "Vehicle",
        filters={
            "end_date": ["between", [today(), add_days(today(), 10)]]
        },
        fields=["name", "end_date"]
    )

    if not vehicles:
        return

    for vehicle in vehicles:
        for user in user_list:

            # --------------------------------------------------
            # Duplication check (UNCHANGED)
            # --------------------------------------------------
            existing = frappe.get_all(
                "ToDo",
                filters={
                    "reference_type": "Vehicle",
                    "reference_name": vehicle.name,
                    "status": "Open",
                    "owner": user,
                    "description": ["like", "%Insurance Expiry%"]
                }
            )

            if not existing:
                # --------------------------------------------------
                # Create ToDo (UNCHANGED)
                # --------------------------------------------------
                frappe.get_doc({
                    "doctype": "ToDo",
                    "owner": user,
                    "assigned_by": "Administrator",
                    "description": f"""<b>Vehicle Insurance Expiry Reminder:</b> 
                        <a href="/desk#Form/Vehicle/{vehicle.name}">{vehicle.name}</a> 
                        insurance ends on <b>{vehicle.end_date}</b>.""",
                    "reference_type": "Vehicle",
                    "reference_name": vehicle.name,
                    "date": vehicle.end_date,
                    "priority": "High"
                }).insert(ignore_permissions=True)

    frappe.db.commit()