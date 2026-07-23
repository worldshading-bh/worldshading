import frappe
from frappe.utils import nowdate, getdate


def auto_activate_scheduled_payments():

    today = getdate(nowdate())
    processed = 0
    max_process = 50

    pes = frappe.get_all(
        "Payment Entry",
        filters={
            "workflow_state": "Scheduled",
            "posting_date": ["<=", today],
            "docstatus": 0
        },
        fields=["name", "posting_date"],
        limit_page_length=200
    )

    for pe in pes:

        if processed >= max_process:
            break

        try:

            doc = frappe.get_doc("Payment Entry", pe.name)

            doc.workflow_state = "Pending Payment - Maker"
            doc.save(ignore_permissions=True)

            doc.add_comment(
                "Workflow",
                f"⏰ Auto-activated payment (posting date reached: {doc.posting_date})"
            )

            frappe.db.commit()
            processed += 1

        except Exception as ex:

            frappe.log_error(
                f"Payment Entry: {pe.name}\nError: {str(ex)}",
                "Scheduled Payment Activation"
            )

    frappe.logger().info(
        f"[Payment Scheduler] Activated {processed} scheduled payments"
    )