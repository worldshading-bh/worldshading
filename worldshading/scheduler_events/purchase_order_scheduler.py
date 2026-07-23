import frappe
from frappe.utils import nowdate, getdate, add_days

def auto_update_purchase_order():

    today = getdate(nowdate())
    processed = 0
    max_process = 20   # Safety limit

    pos = frappe.get_all(
        "Purchase Order",
        filters={
            "workflow_state": ["in", ["In Production", "Shipped"]],
            "docstatus": ["in", ["0", "1"]]
        },
        fields=["name", "workflow_state", "schedule_date", "eta_date"],
        limit_page_length=200
    )

    for po in pos:

        # Stop if max limit reached
        if processed >= max_process:
            break

        try:
            doc = frappe.get_doc("Purchase Order", po.name)

            # -------------------------
            # CASE 1
            # In Production → Ready To Ship
            # -------------------------

            if doc.workflow_state == "In Production":

                if not doc.schedule_date:
                    continue

                days_left = (getdate(doc.schedule_date) - today).days

                if days_left <= 3:

                    doc.workflow_state = "Ready To Ship"
                    doc.save(ignore_permissions=True)

                    doc.add_comment(
                        "Workflow",
                        f"⏳ Auto-moved from 'In Production' → 'Ready To Ship' "
                        f"(ETD in {days_left} days: {doc.schedule_date})"
                    )

                    frappe.db.commit()
                    processed += 1
                    continue

            # -------------------------
            # CASE 2 & 3
            # Shipped logic
            # -------------------------

            if doc.workflow_state == "Shipped":

                if not doc.schedule_date or not doc.eta_date:
                    continue

                etd = getdate(doc.schedule_date)
                eta = getdate(doc.eta_date)

                voyage_days = (eta - etd).days

                midpoint = add_days(etd, int(voyage_days / 2))
                pre_arrival_date = add_days(eta, -7)

                # CASE 3: Pre-Arrival
                if today >= pre_arrival_date:

                    doc.workflow_state = "Pre-Arrival"
                    doc.save(ignore_permissions=True)

                    doc.add_comment(
                        "Workflow",
                        f"⏳ Auto-moved from 'Shipped' → 'Pre-Arrival' "
                        f"(ETA in {(eta - today).days} days: {eta})"
                    )

                    frappe.db.commit()
                    processed += 1
                    continue

                # CASE 2: Shipment Follow-Up
                if midpoint <= today < pre_arrival_date:

                    doc.workflow_state = "Shipment Follow-Up"
                    doc.save(ignore_permissions=True)

                    doc.add_comment(
                        "Workflow",
                        f"📦 Auto-moved from 'Shipped' → 'Shipment Follow-Up' "
                        f"(Mid-voyage check between ETD {etd} and ETA {eta})"
                    )

                    frappe.db.commit()
                    processed += 1
                    continue

        except Exception as ex:

            frappe.log_error(
                f"Purchase Order: {po.name}\nError: {str(ex)}",
                "PO Auto Update"
            )

    frappe.logger().info(f"[PO Automation] Total transitions processed: {processed}")



# ================================================================
# PURCHASE ORDER LOGISTICS AUTO WORKFLOW SCHEDULER
# ERPNext v12 | Custom App: worldshading
# ---------------------------------------------------------------
# PURPOSE
# Automatically moves Purchase Orders through logistics workflow
# stages based on ETD and ETA dates.
#
# This scheduler runs daily and handles production progress,
# mid-voyage shipment monitoring, and pre-arrival preparation.
#
# ---------------------------------------------------------------
# CASE 1 — Production Completion Monitoring
#
# Workflow:
#     In Production → Ready To Ship
#
# Condition:
#     schedule_date (ETD) is within 3 days or already passed
#
# Logic:
#     days_left = ETD - today
#     if days_left <= 3
#
# Purpose:
#     Production should be completed and shipment preparation
#     should begin.
#
# ---------------------------------------------------------------
# CASE 2 — Shipment Mid-Voyage Follow-Up
#
# Workflow:
#     Shipped → Shipment Follow-Up
#
# Condition:
#     Current date has reached the midpoint between ETD and ETA
#     but Pre-Arrival stage is not yet reached.
#
# Logic:
#     midpoint = ETD + (ETA - ETD) / 2
#     pre_arrival_date = ETA - 7 days
#
#     if midpoint <= today < pre_arrival_date
#
# Purpose:
#     Forces logistics team to check shipment progress and
#     update ETD / ETA if vessel schedule changed.
#
# ---------------------------------------------------------------
# CASE 3 — Pre-Arrival Preparation
#
# Workflow:
#     Shipped → Pre-Arrival
#
# Condition:
#     ETA is within 7 days.
#
# Logic:
#     if today >= ETA - 7 days
#
# Purpose:
#     Start customs preparation:
#     - Upload Arrival Notice
#     - Hand documents to broker
#     - Prepare clearance documents
#
# ---------------------------------------------------------------
# SAFETY FEATURES
#
# ✔ Maximum 50 POs processed per run (scheduler safety limit)
# ✔ Skips POs missing ETD / ETA dates
# ✔ Adds workflow timeline comment for audit tracking
# ✔ Error logging prevents scheduler failure
#
# Example timeline:
#
# ETD: Jan 1
# ETA: Mar 1
#
# Jan 30  → Shipment Follow-Up
# Feb 22  → Pre-Arrival
#
# ================================================================