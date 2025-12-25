import frappe
from frappe.utils import nowdate, getdate, add_months

def auto_transition_jv():
    """Daily scheduler for Journal Entries:
       - Moves Awaiting Maturity states based on transition_date
       - Moves Security Cheques older than 6 months → Review Security Cheque
    """

    state_map = {
        "Awaiting Maturity": "Pending Cheque Deposit",
        "Awaiting Maturity - 2nd": "Pending Cheque 2nd Deposit",
        "Awaiting Maturity - 3rd": "Pending Cheque 3rd Deposit",
        "Legal Action Initiated": "Pending Case Follow-Up" 
    }

    today = getdate(nowdate())
    moved = 0

    # --- 1️⃣ Handle Awaiting Maturity transitions ---
    for current_state, next_state in state_map.items():
        entries = frappe.get_all(
            "Journal Entry",
            filters={
                "workflow_state": current_state,
                "docstatus": ["in", ["0", "1"]]  # ← fixed here
            },
            fields=["name", "transition_date"]
        )


        for e in entries:
            if not e.transition_date:
                continue
            if getdate(e.transition_date) <= today:
                try:
                    doc = frappe.get_doc("Journal Entry", e.name)
                    doc.workflow_state = next_state
                    doc.save(ignore_permissions=True)
                    doc.add_comment(
                        "Workflow",
                        f"🕓 Auto-moved from '{current_state}' → '{next_state}' (Transition Date {e.transition_date})"
                    )
                    frappe.db.commit()
                    moved += 1
                except Exception as ex:
                    frappe.log_error(f"Journal Entry: {e.name}\nError: {str(ex)}", "Journal Entry Auto Transition")

    # --- 2️⃣ Handle Security Cheque → Review Security Cheque (after 6 months) ---
    six_months_passed = 0
    sec_entries = frappe.get_all(
        "Journal Entry",
        filters={
            "workflow_state": "Security Cheque",
            "docstatus": ["in", ["0", "1"]]  # ← fixed here too
        },
        fields=["name", "transition_date"]
    )


    for e in sec_entries:
        if not e.transition_date:
            continue
        # Check if 6 months passed since transition_date
        review_date = add_months(getdate(e.transition_date), 6)
        if getdate(today) >= review_date:
            try:
                doc = frappe.get_doc("Journal Entry", e.name)
                doc.workflow_state = "Review Security Cheque"
                doc.save(ignore_permissions=True)
                doc.add_comment(
                    "Workflow",
                    f"🔄 Auto-moved from 'Security Cheque' → 'Review Security Cheque' "
                    f"(6 months after {e.transition_date})"
                )
                frappe.db.commit()
                six_months_passed += 1
            except Exception as ex:
                frappe.log_error(f"Security Cheque: {e.name}\nError: {str(ex)}", "Security Cheque Auto Review")

    # Log summary
    frappe.logger().info(
        f"[JournalEntry Scheduler] Maturity transitions: {moved}, "
        f"Security Cheques moved to Review: {six_months_passed}"
    )
