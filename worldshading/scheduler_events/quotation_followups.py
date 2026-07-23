import frappe
from frappe.utils import now_datetime, getdate, add_days

def auto_update_followups():
    """Daily job (cron) to auto-transition Quotations through follow-up states and handle expiry sync."""
    now = now_datetime()

    # Rules for Waiting states
    rules = {
        "Waiting 24h": {"hours": 24, "next": "Follow-up 1"},
        "Waiting 48h": {"hours": 48, "next": "Follow-up 2"},
        "Waiting 72h": {"hours": 72, "next": "Follow-up 3"},
    }

    tolerance = 6  # hours → allow early transition up to 6h

    # --- Handle Waiting 24/48/72 ---
    quotations_processed = 0
    for state, cfg in rules.items():
        quotations = frappe.get_all(
            "Quotation",
            filters={"workflow_state": state, "docstatus": 1},
            fields=["name", "transition_date", "status"]
        )

        for q in quotations:
            if q.status == "Expired" or not q.transition_date:
                continue

            elapsed = (now - q.transition_date).total_seconds() / 3600.0
            threshold = cfg["hours"] - tolerance

            if elapsed >= threshold:
                qtn_doc = frappe.get_doc("Quotation", q.name)
                qtn_doc.workflow_state = cfg["next"]
                qtn_doc.save(ignore_permissions=True)
                frappe.db.commit()
                quotations_processed += 1

    frappe.logger().info(f"[Followups] Waiting → Follow-up processed: {quotations_processed}")

    # --- Handle Scheduled → Follow-up 1 / Scheduled - Visitor → Pending Call - Visitor ---
    scheduled_processed = 0
    scheduled_rules = {
        "Scheduled": "Follow-up 1",
        "Scheduled - Visitor": "Pending Call - Visitor"
    }
    scheduled_qtns = frappe.get_all(
        "Quotation",
        filters={"workflow_state": ["in", list(scheduled_rules.keys())], "docstatus": 1},
        fields=["name", "workflow_state", "transition_date", "valid_till", "status"]
    )

    for q in scheduled_qtns:
        if not q.transition_date:
            continue

        required_valid_till = add_days(getdate(q.transition_date), 10)
        if not q.valid_till or getdate(q.valid_till) < required_valid_till:
            frappe.db.set_value("Quotation", q.name, {
                "valid_till": required_valid_till,
                "status": "Open" if q.status == "Expired" else q.status
            })
        #check today is >= transition date, used date field instead of datetime
        if getdate(now) >= getdate(q.transition_date):
            qtn_doc = frappe.get_doc("Quotation", q.name)
            qtn_doc.workflow_state = scheduled_rules.get(q.workflow_state)
            qtn_doc.save(ignore_permissions=True)
            frappe.db.commit()
            scheduled_processed += 1

    frappe.logger().info(f"[Followups] Scheduled transitions processed: {scheduled_processed}")

    # --- Sync Expired Quotations ---
    expiry_assignees = _get_quotation_expiry_assignees()

    if not expiry_assignees:
        frappe.logger().info("[Followups] Expired quotation assign skipped: no assignees configured.")
        return

    expired_processed = 0
    expired_qtns = frappe.get_all(
        "Quotation",
        filters={"docstatus": 1, "status": "Expired"},
        fields=["name", "workflow_state", "customer_name"]
    )

    for q in expired_qtns:
        if q.workflow_state != "Expired":
            frappe.db.set_value("Quotation", q.name, "workflow_state", "Expired")

            # Close existing open todos
            todos = frappe.get_all(
                "ToDo",
                filters={"reference_type": "Quotation", "reference_name": q.name, "status": "Open"},
                fields=["name"]
            )
            for t in todos:
                frappe.db.set_value("ToDo", t.name, "status", "Closed")

            # Create new todos
            for user in expiry_assignees:
                todo = frappe.get_doc({
                    "doctype": "ToDo",
                    "owner": user,
                    "assigned_by": "Administrator",
                    "allocated_to": user,
                    "reference_type": "Quotation",
                    "reference_name": q.name,
                    "description": f"Quotation expired: {q.name} for {q.customer_name}. Please follow up.",
                    "status": "Open",
                    "priority": "High"
                })
                todo.insert(ignore_permissions=True)

            frappe.db.commit()
            expired_processed += 1

    frappe.logger().info(f"[Followups] Expired sync processed: {expired_processed}")


def _get_quotation_expiry_assignees():
    settings = frappe.get_single("WS Settings")

    if not settings.get("enable_quotation_expiry_assign"):
        return []

    valid_users = frappe.get_all("User", filters={"enabled": 1}, fields=["name"])
    valid_users = [u["name"] for u in valid_users]

    user_list = [
        d.user for d in settings.get("users_to_assign_qer") or []
        if d.user in valid_users and d.user not in ("Administrator", "Guest")
    ]

    if not user_list:
        frappe.log_error(
            "No valid users found in WS Settings (Quotation Expiry Reminder).",
            "Quotation Expiry ToDo Script"
        )

    return user_list
