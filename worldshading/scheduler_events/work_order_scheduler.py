# -*- coding: utf-8 -*-
# Push reminders for the Workshop PWA.
#
# Mirrors scheduler_events/service_visit_scheduler.send_service_visit_reminders:
# every 5 minutes, find submitted Work Orders in "Ready to Start" whose planned
# start is within the next 30 minutes, and push a reminder to each assigned team
# member who has an enabled push subscription. Uses the shared "PWA Notification
# Log" DocType to dedupe so a user is reminded at most once per work order/time.
#
# ERPNext v12 / Frappe v12 compatible.

import frappe
from frappe.utils import now_datetime, add_to_date, get_datetime
from worldshading.api.driver_visit import send_push_to_user

WORK_ORDER_REMINDER_TYPE = "30 Minute Reminder"
WORK_ORDER_REMINDER_STATE = "Ready to Start"


def send_work_order_reminders():
    now_dt = get_datetime(now_datetime())
    window_end = add_to_date(now_dt, minutes=30)
    processed = 0
    max_process = 100

    work_orders = frappe.get_all(
        "Work Order",
        filters={
            "docstatus": 1,
            "workflow_state": WORK_ORDER_REMINDER_STATE,
            "planned_start_date": ["between", [now_dt, window_end]],
        },
        fields=["name", "item_name", "production_item", "production_team", "planned_start_date"],
        limit_page_length=300,
    )

    if not work_orders:
        return

    for wo in work_orders:
        reminder_on = get_datetime(wo.get("planned_start_date"))

        if not reminder_on or reminder_on < now_dt or reminder_on > window_end:
            continue

        for user in _get_work_order_users(wo):
            if _has_reminder_log(wo.name, user, reminder_on):
                continue

            if not _has_enabled_push_subscription(user):
                continue

            result = send_push_to_user(
                user,
                "Work order starts in 30 minutes",
                _reminder_message(wo),
                "/workshop",
                "work-order-{0}-{1}".format(wo.name, WORK_ORDER_REMINDER_TYPE),
            )

            status = "Sent" if result.get("sent") else "Failed"
            _create_reminder_log(wo.name, user, reminder_on, status)
            processed += 1

            if processed >= max_process:
                break

        if processed >= max_process:
            break

    frappe.logger().info(
        "[Work Order Reminder] Total reminders processed: {0}".format(processed)
    )


def _get_work_order_users(wo):
    """Assigned users: the Work Order's own production_team_users rows plus the
    members of its Work Team (both use the Work Team User child)."""
    users = set()

    rows = frappe.get_all(
        "Work Team User",
        filters={"parenttype": "Work Order", "parent": wo.name},
        fields=["user"],
        limit_page_length=200,
    )
    for row in rows:
        if row.get("user"):
            users.add(row.user)

    if wo.get("production_team"):
        team_rows = frappe.get_all(
            "Work Team User",
            filters={"parenttype": "Work Team", "parent": wo.get("production_team")},
            fields=["user"],
            limit_page_length=200,
        )
        for row in team_rows:
            if row.get("user"):
                users.add(row.user)

    return users


def _reminder_message(wo):
    parts = [
        wo.get("item_name") or wo.get("production_item") or wo.name,
        wo.name,
    ]
    return " - ".join([part for part in parts if part])


def _has_enabled_push_subscription(user):
    return frappe.db.exists(
        "PWA Push Subscription",
        {"user": user, "enabled": 1},
    )


def _has_reminder_log(work_order, user, reminder_on):
    return frappe.db.exists(
        "PWA Notification Log",
        {
            "reference_doctype": "Work Order",
            "reference_name": work_order,
            "user": user,
            "reminder_type": WORK_ORDER_REMINDER_TYPE,
            "reminder_on": reminder_on,
        },
    )


def _create_reminder_log(work_order, user, reminder_on, status):
    doc = frappe.new_doc("PWA Notification Log")
    doc.reference_doctype = "Work Order"
    doc.reference_name = work_order
    doc.user = user
    doc.reminder_type = WORK_ORDER_REMINDER_TYPE
    doc.reminder_on = reminder_on
    doc.sent_on = now_datetime()
    doc.status = status
    doc.insert(ignore_permissions=True)
